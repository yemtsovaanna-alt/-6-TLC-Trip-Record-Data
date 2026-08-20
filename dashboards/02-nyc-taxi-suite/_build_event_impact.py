"""Measure taxi trip lift around NYC mass events (NFL/NBA/MLB/marathon/US Open).

Reads events/nyc_events.csv + events/venues.csv, aggregates FHVHV pickups/dropoffs
in venue zones, compares event windows to same-DOW/hour baselines.

Outputs Postgres tables + events/event_impact_summary.csv for Grafana dash 06.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
EVENTS_CSV = ROOT / "events" / "nyc_events.csv"
VENUES_CSV = ROOT / "events" / "venues.csv"
PARQUET = "TLC_Trip_Data_clean/fhvhv/*.parquet"
YEARS = list(range(2019, 2026))

# Event window offsets (hours from start_hour)
PRE_H = (-2, 0)       # arrivals: dropoffs to venue
EVENT_H = (0, 3)      # during
POST_H = (3, 5)       # departures: pickups from venue


def load_venue_zones() -> dict[str, set[int]]:
    vdf = pd.read_csv(VENUES_CSV)
    out = {}
    for _, r in vdf.iterrows():
        zones = {int(r.primary_zone)}
        if pd.notna(r.buffer_zones) and str(r.buffer_zones).strip():
            zones |= {int(z) for z in str(r.buffer_zones).split(",")}
        out[r.venue_id] = zones
    return out


def ensure_events() -> pd.DataFrame:
    if not EVENTS_CSV.exists():
        import _fetch_nyc_events
        _fetch_nyc_events.main()
    ev = pd.read_csv(EVENTS_CSV, parse_dates=["date"])
    ev["date"] = pd.to_datetime(ev["date"]).dt.date
    return ev


def build_zone_hourly(con: duckdb.DuckDBPyConnection, all_zones: set[int]) -> pd.DataFrame:
    zone_list = ",".join(str(z) for z in sorted(all_zones))
    print(f"  aggregating zone x hour for {len(all_zones)} venue zones...")
    q = f"""
    WITH pu AS (
      SELECT CAST(pickup_datetime AS DATE) AS d,
             hour(pickup_datetime) AS hr,
             dayofweek(pickup_datetime) AS dow,
             PULocationID AS zone,
             count(*) AS n
      FROM read_parquet('{PARQUET}', union_by_name=True)
      WHERE year(pickup_datetime) BETWEEN 2019 AND 2025
        AND PULocationID IN ({zone_list})
      GROUP BY 1, 2, 3, 4
    ),
    dropoffs AS (
      SELECT CAST(pickup_datetime AS DATE) AS d,
             hour(pickup_datetime) AS hr,
             dayofweek(pickup_datetime) AS dow,
             DOLocationID AS zone,
             count(*) AS n
      FROM read_parquet('{PARQUET}', union_by_name=True)
      WHERE year(pickup_datetime) BETWEEN 2019 AND 2025
        AND DOLocationID IN ({zone_list})
      GROUP BY 1, 2, 3, 4
    )
    SELECT coalesce(p.d, dropoffs.d) AS d,
           coalesce(p.hr, dropoffs.hr) AS hr,
           coalesce(p.dow, dropoffs.dow) AS dow,
           coalesce(p.zone, dropoffs.zone) AS zone,
           coalesce(p.n, 0) AS pu_trips,
           coalesce(dropoffs.n, 0) AS do_trips
    FROM pu p
    FULL OUTER JOIN dropoffs ON p.d = dropoffs.d AND p.hr = dropoffs.hr
        AND p.dow = dropoffs.dow AND p.zone = dropoffs.zone
    """
    return con.execute(q).fetchdf()


def window_trips(day_df: pd.DataFrame, zones: set[int], start_h: int, pre: tuple[int, int]) -> tuple[int, int]:
    """Sum PU/DO in [start+pre[0], start+pre[1]) across venue zones."""
    h0, h1 = start_h + pre[0], start_h + pre[1]
    hours = list(range(h0, h1))
    sub = day_df[(day_df["zone"].isin(zones)) & (day_df["hr"].isin(hours))]
    return int(sub["pu_trips"].sum()), int(sub["do_trips"].sum())


def baseline_trips(full: pd.DataFrame, zones: set[int], dow: int, start_h: int,
                   pre: tuple[int, int], exclude_dates: set) -> tuple[float, float]:
    h0, h1 = start_h + pre[0], start_h + pre[1]
    hours = list(range(h0, h1))
    sub = full[
        (full["dow"] == dow) & (full["zone"].isin(zones)) & (full["hr"].isin(hours))
        & (~full["d"].isin(exclude_dates))
    ]
    if sub.empty:
        return 1.0, 1.0
    by_day = sub.groupby("d").agg(pu=("pu_trips", "sum"), do=("do_trips", "sum"))
    return max(by_day["pu"].mean(), 1.0), max(by_day["do"].mean(), 1.0)


def analyze_events(ev: pd.DataFrame, venue_zones: dict[str, set[int]], hourly: pd.DataFrame) -> pd.DataFrame:
    hourly = hourly.copy()
    hourly["d"] = pd.to_datetime(hourly["d"]).dt.date
    event_dates = set(ev["date"])

    rows = []
    for _, e in ev.iterrows():
        vid = e["venue_id"]
        if vid not in venue_zones:
            continue
        zones = venue_zones[vid]
        d = e["date"]
        sh = int(e["start_hour"])
        day_df = hourly[hourly["d"] == d]
        if day_df.empty:
            continue
        dow = int(day_df["dow"].iloc[0])
        excl = {x for x in event_dates if x != d}

        b_pre_pu, b_pre_do = baseline_trips(hourly, zones, dow, sh, PRE_H, excl)
        b_evt_pu, b_evt_do = baseline_trips(hourly, zones, dow, sh, EVENT_H, excl)
        b_post_pu, b_post_do = baseline_trips(hourly, zones, dow, sh, POST_H, excl)

        pre_pu, pre_do = window_trips(day_df, zones, sh, PRE_H)
        evt_pu, evt_do = window_trips(day_df, zones, sh, EVENT_H)
        post_pu, post_do = window_trips(day_df, zones, sh, POST_H)

        rows.append({
            "date": d, "venue_id": vid, "event_type": e["event_type"], "title": e["title"],
            "start_hour": sh,
            "pre_pu_lift_pct": round(100 * (pre_pu / b_pre_pu - 1), 1),
            "pre_do_lift_pct": round(100 * (pre_do / b_pre_do - 1), 1),
            "event_pu_lift_pct": round(100 * (evt_pu / b_evt_pu - 1), 1),
            "event_do_lift_pct": round(100 * (evt_do / b_evt_do - 1), 1),
            "post_pu_lift_pct": round(100 * (post_pu / b_post_pu - 1), 1),
            "post_do_lift_pct": round(100 * (post_do / b_post_do - 1), 1),
            "post_pu_trips": post_pu, "post_do_trips": post_do,
        })
    return pd.DataFrame(rows)


def aggregate_by_type(impact: pd.DataFrame) -> pd.DataFrame:
    agg = impact.groupby("event_type").agg(
        n_events=("date", "count"),
        avg_pre_do_lift=("pre_do_lift_pct", "mean"),
        avg_post_pu_lift=("post_pu_lift_pct", "mean"),
        avg_event_pu_lift=("event_pu_lift_pct", "mean"),
        median_post_pu_lift=("post_pu_lift_pct", "median"),
    ).reset_index()
    for c in agg.columns[2:]:
        agg[c] = agg[c].round(1)
    return agg


def load_postgres(con: duckdb.DuckDBPyConnection, impact: pd.DataFrame, by_type: pd.DataFrame,
                  ev: pd.DataFrame):
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")

    con.register("impact_df", impact)
    con.execute("CREATE OR REPLACE TABLE pg.event_impact AS SELECT * FROM impact_df")

    con.register("type_df", by_type)
    con.execute("CREATE OR REPLACE TABLE pg.event_impact_by_type AS SELECT * FROM type_df")

    # Grafana annotations
    ann = ev.copy()
    ann["event_time"] = pd.to_datetime(ann["date"]) + pd.to_timedelta(ann["start_hour"], unit="h")
    ann = ann[["event_time", "title", "tags"]]
    con.register("ann_df", ann)
    con.execute("CREATE OR REPLACE TABLE pg.dashboard_events AS SELECT * FROM ann_df")
    print(f"  postgres: event_impact={len(impact)}, dashboard_events={len(ann)}")


def main():
    t0 = time.time()
    venue_zones = load_venue_zones()
    ev = ensure_events()
    all_zones = set().union(*venue_zones.values())

    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    hourly = build_zone_hourly(con, all_zones)
    print(f"  zone x hour rows: {len(hourly)} [{time.time()-t0:.1f}s]")

    impact = analyze_events(ev, venue_zones, hourly)
    by_type = aggregate_by_type(impact)
    impact.to_csv(ROOT / "events" / "event_impact_summary.csv", index=False)
    by_type.to_csv(ROOT / "events" / "event_impact_by_type.csv", index=False)

    with open(ROOT / "events" / "event_impact_by_type.json", "w", encoding="utf-8") as f:
        json.dump(by_type.to_dict(orient="records"), f, ensure_ascii=False, indent=2)

    print("\n=== Lift by event type (post-event pickups, median) ===")
    print(by_type.to_string(index=False))

    load_postgres(con, impact, by_type, ev)
    print(f"done [{time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()

"""Event-day timelapse: hourly pickups in venue zones on event days.

Merges `event_timelapse` block into _map_v2_data.json (map zooms client-side).
Uses FHVHV 2024 + nyc_events.csv (run _fetch_nyc_events.py first).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from _map_metric_colors import METRIC_COLOR_LO, METRIC_STOPS_5

ROOT = Path(__file__).resolve().parent
YEAR = 2024
FHVHV = (
    f"read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_{YEAR}-*.parquet', "
    "union_by_name=True)"
)

LON_MIN, LON_MAX = -74.233535, -73.711025
LAT_MIN, LAT_MAX = 40.525491, 40.899528
LAT0 = (LAT_MIN + LAT_MAX) / 2
COS_LAT0 = math.cos(math.radians(LAT0))
PAD, VIEW_H = 40, 1000
SCALE = (VIEW_H - 2 * PAD) / (LAT_MAX - LAT_MIN)
VIEW_W = (LON_MAX - LON_MIN) * COS_LAT0 * SCALE + 2 * PAD

TRIP_STOPS = METRIC_STOPS_5
NO_TRIP_COLOR = METRIC_COLOR_LO

HOUR_LABELS = [
    "00:00", "01:00", "02:00", "03:00", "04:00", "05:00",
    "06:00", "07:00", "08:00", "09:00", "10:00",
    "11:00", "12:00", "13:00", "14:00", "15:00",
    "16:00", "17:00", "18:00", "19:00", "20:00",
    "21:00", "22:00", "23:00",
]


def project(lon: float, lat: float) -> tuple[float, float]:
    x = PAD + (lon - LON_MIN) * COS_LAT0 * SCALE
    y = PAD + (LAT_MAX - lat) * SCALE
    return round(x, 1), round(y, 1)


def interpolate_color(value, lo, hi, stops):
    if value is None or hi <= lo or value <= 0:
        return NO_TRIP_COLOR
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    seg = t * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    local_t = seg - i
    c0, c1 = stops[i], stops[i + 1]
    rgb = tuple(round(c0[k] + (c1[k] - c0[k]) * local_t) for k in range(3))
    return "#%02x%02x%02x" % rgb


def load_venues() -> pd.DataFrame:
    return pd.read_csv(ROOT / "events" / "venues.csv")


def load_events() -> pd.DataFrame:
    ev = pd.read_csv(ROOT / "events" / "nyc_events.csv", parse_dates=["date"])
    ev["date"] = pd.to_datetime(ev["date"]).dt.date
    return ev[ev["date"].map(lambda d: d.year) == YEAR]


def venue_zone_map(vdf: pd.DataFrame) -> dict[str, set[int]]:
    out = {}
    for _, r in vdf.iterrows():
        zones = {int(r.primary_zone)}
        if pd.notna(r.buffer_zones) and str(r.buffer_zones).strip():
            zones |= {int(z) for z in str(r.buffer_zones).split(",")}
        out[r.venue_id] = zones
    return out


def zoom_preset(lon: float, lat: float, k: float = 5.5) -> dict:
    cx, cy = project(lon, lat)
    vw, vh = VIEW_W / k, VIEW_H / k
    return {
        "k": k,
        "x": round(max(0, min(VIEW_W - vw, cx - vw / 2)), 1),
        "y": round(max(0, min(VIEW_H - vh, cy - vh / 2)), 1),
    }


def build_hourly(con: duckdb.DuckDBPyConnection, all_zones: set[int]) -> pd.DataFrame:
    zlist = ",".join(str(z) for z in sorted(all_zones))
    return con.execute(f"""
        SELECT CAST(pickup_datetime AS DATE) AS d,
               hour(pickup_datetime) AS hr,
               dayofweek(pickup_datetime) AS dow,
               PULocationID AS zone,
               count(*) AS trips
        FROM {FHVHV}
        WHERE PULocationID IN ({zlist})
        GROUP BY 1, 2, 3, 4
    """).fetchdf()


def frames_for_venue(hourly: pd.DataFrame, zones: set[int], event_dates: set) -> tuple[list[dict], list[float]]:
    sub = hourly[hourly["zone"].isin(zones)].copy()
    if sub.empty or not event_dates:
        return [], []
    sub["d"] = pd.to_datetime(sub["d"]).dt.date
    sub["is_event"] = sub["d"].isin(event_dates)

    evt = sub[sub["is_event"]].groupby(["hr", "zone"])["trips"].mean().reset_index(name="evt")
    base = sub[~sub["is_event"]].groupby(["hr", "zone", "dow"])["trips"].mean().reset_index(name="base")
    event_dows = set(sub.loc[sub["is_event"], "dow"].unique())
    base = base[base["dow"].isin(event_dows)]
    base = base.groupby(["hr", "zone"])["base"].mean().reset_index()
    merged = evt.merge(base, on=["hr", "zone"], how="outer").fillna(0)
    merged["lift"] = merged.apply(
        lambda r: (r.evt / r.base) if r.base > 0 else (r.evt if r.evt > 0 else 0), axis=1)

    trip_vals = merged.loc[merged["evt"] > 0, "evt"].values
    if len(trip_vals) == 0:
        return [], []
    lo_t = float(np.quantile(trip_vals, 0.08))
    hi_t = float(np.quantile(trip_vals, 0.92))
    if hi_t <= lo_t:
        hi_t = lo_t + 1

    out = []
    for h in range(24):
        fills, lifts, trips = {}, {}, {}
        hr_rows = merged[merged["hr"] == h]
        for _, row in hr_rows.iterrows():
            z = str(int(row["zone"]))
            lift = float(row["lift"]) if row["base"] > 0 else 0.0
            t = float(row["evt"])
            lifts[z] = round(lift, 2)
            trips[z] = round(t, 1)
            fills[z] = interpolate_color(t if t > 0 else None, lo_t, hi_t, TRIP_STOPS)
        out.append({
            "hour": h,
            "label": HOUR_LABELS[h],
            "fills": fills,
            "trips": trips,
            "lift": lifts,
        })
    return out, [round(lo_t, 1), round(hi_t, 1)]


def main():
    t0 = time.time()
    vdf = load_venues()
    ev = load_events()
    vzones = venue_zone_map(vdf)
    all_zones = set().union(*vzones.values())

    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar;")
    print("scanning 2024 hourly pickups near venues...")
    hourly = build_hourly(con, all_zones)
    print(f"  rows: {len(hourly):,}")

    venues_out = {}
    for _, v in vdf.iterrows():
        vid = v.venue_id
        zones = vzones[vid]
        dates = set(ev.loc[ev.venue_id == vid, "date"])
        if len(dates) < 3:
            print(f"  skip {vid}: only {len(dates)} event days in {YEAR}")
            continue
        frames, domain = frames_for_venue(hourly, zones, dates)
        if not frames:
            continue
        venues_out[vid] = {
            "name": v["name"],
            "zones": sorted(zones),
            "n_event_days": len(dates),
            "domain": domain,
            "frames": frames,
        }
        print(f"  {vid}: {len(dates)} event days, {len(zones)} zones, trips/hr {domain}")

    if not venues_out:
        raise SystemExit("no venue timelapse built — check events CSV and parquet")

    path = ROOT / "_map_v2_data.json"
    data = json.load(open(path, encoding="utf-8"))
    data["event_timelapse"] = {
        "year": YEAR,
        "metric": "avg_pickups_per_hour_event_days",
        "venues": venues_out,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"merged event_timelapse ({len(venues_out)} venues) into {path} [{time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()

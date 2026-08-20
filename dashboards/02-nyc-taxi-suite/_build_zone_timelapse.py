"""Build 24-frame trip heatmap timelapse data for the zone map.

Averages FHVHV 2024 pickups by zone × hour, separately for weekdays and
weekends. Writes a `timelapse` block into _map_v2_data.json (run after
_build_map_v2_data.py, before _build_map_v2_artifact.py).
"""
import json
import time

import duckdb
import numpy as np

from _map_metric_colors import METRIC_COLOR_LO, METRIC_STOPS_5

YEAR = 2024
FHVHV = (
    f"read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_{YEAR}-*.parquet', "
    "union_by_name=True)"
)

TIMELAPSE_STOPS = METRIC_STOPS_5
NO_TRIP_COLOR = METRIC_COLOR_LO

HOUR_LABELS = [
    "00:00 — ночь", "01:00", "02:00", "03:00", "04:00", "05:00",
    "06:00 — рассвет", "07:00 — утро", "08:00", "09:00", "10:00",
    "11:00 — день", "12:00", "13:00", "14:00", "15:00",
    "16:00 — вечер", "17:00", "18:00", "19:00", "20:00",
    "21:00 — ночь", "22:00", "23:00",
]


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


def build_profile(con, weekend: bool) -> list[dict]:
    dow_filter = "dow IN (0, 6)" if weekend else "dow NOT IN (0, 6)"
    df = con.execute(f"""
        SELECT zone, hr,
               round(avg(daily_trips)::numeric, 1) AS avg_trips
        FROM (
            SELECT PULocationID AS zone,
                   hour(pickup_datetime) AS hr,
                   dayofweek(pickup_datetime) AS dow,
                   CAST(pickup_datetime AS DATE) AS d,
                   count(*) AS daily_trips
            FROM {FHVHV}
            WHERE PULocationID IS NOT NULL
            GROUP BY 1, 2, 3, 4
        ) t
        WHERE {dow_filter}
        GROUP BY zone, hr
        ORDER BY hr, zone
    """).fetchdf()
    return df


def frames_from_df(df, lo, hi) -> list[dict]:
    by_hour = {h: {} for h in range(24)}
    trips_by_hour = {h: {} for h in range(24)}
    for _, row in df.iterrows():
        z, hr, trips = int(row["zone"]), int(row["hr"]), float(row["avg_trips"])
        by_hour[hr][str(z)] = interpolate_color(trips, lo, hi, TIMELAPSE_STOPS)
        trips_by_hour[hr][str(z)] = round(trips, 1)

    out = []
    for h in range(24):
        out.append({
            "hour": h,
            "label": HOUR_LABELS[h],
            "fills": by_hour[h],
            "trips": trips_by_hour[h],
        })
    return out


def main():
    t0 = time.time()
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar;")

    print("scanning weekday hourly pickups...")
    wd = build_profile(con, weekend=False)
    print(f"  weekday rows: {len(wd):,}")

    print("scanning weekend hourly pickups...")
    we = build_profile(con, weekend=True)
    print(f"  weekend rows: {len(we):,}")

    all_vals = np.concatenate([
        wd["avg_trips"].values,
        we["avg_trips"].values,
    ])
    all_vals = all_vals[all_vals > 0]
    lo, hi = float(np.quantile(all_vals, 0.05)), float(np.quantile(all_vals, 0.95))
    print(f"  color domain (p5-p95): {lo:.1f} – {hi:.1f} trips/hr (zone-day avg)")

    timelapse = {
        "year": YEAR,
        "source": "FHVHV pickups",
        "domain": [round(lo, 1), round(hi, 1)],
        "hour_labels": HOUR_LABELS,
        "weekday": frames_from_df(wd, lo, hi),
        "weekend": frames_from_df(we, lo, hi),
    }

    path = "_map_v2_data.json"
    data = json.load(open(path, encoding="utf-8"))
    data["timelapse"] = timelapse
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"merged timelapse into {path} [{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()

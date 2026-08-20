"""Cluster the 263 taxi zones by the SHAPE of their hourly pickup demand
profile (weekday vs weekend, normalized to %-of-daily-trips-per-hour) —
not by borough, but by how each zone actually behaves through the day.
"""
import json

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

YEAR = 2024


def build_hourly_profiles():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = f"""
    SELECT PULocationID AS zone, dayofweek(pickup_datetime) AS dow, hour(pickup_datetime) AS hr,
      count(*) trips
    FROM read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_{YEAR}-*.parquet', union_by_name=True)
    GROUP BY 1, 2, 3
    """
    df = con.execute(q).fetchdf()
    print(f"raw hourly rows: {len(df)}")

    df["is_weekend"] = df["dow"].isin([0, 6])  # duckdb dayofweek: 0=Sun, 6=Sat
    agg = df.groupby(["zone", "is_weekend", "hr"], as_index=False)["trips"].sum()

    # normalize: within each (zone, weekday/weekend), % of that zone's trips per hour
    agg["total"] = agg.groupby(["zone", "is_weekend"])["trips"].transform("sum")
    agg["pct"] = agg["trips"] / agg["total"]

    zones = sorted(agg["zone"].unique())
    features = []
    for z in zones:
        row = []
        for is_we in [False, True]:
            sub = agg[(agg.zone == z) & (agg.is_weekend == is_we)].set_index("hr")["pct"]
            row.extend([sub.get(h, 0.0) for h in range(24)])
        features.append(row)
    X = np.array(features)
    return zones, X, agg


def main():
    zones, X, agg = build_hourly_profiles()
    print(f"feature matrix: {X.shape} ({len(zones)} zones x 48 hourly-pct features)")

    # pick k via silhouette across a small range
    best_k, best_score = None, -1
    scores = {}
    for k in range(3, 10):
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
        s = silhouette_score(X, km.labels_)
        scores[k] = s
        if s > best_score:
            best_k, best_score = k, s
    print("silhouette by k:", {k: round(v, 4) for k, v in scores.items()})
    print(f"chosen k={best_k} (silhouette={best_score:.4f})")

    km = KMeans(n_clusters=best_k, n_init=20, random_state=42).fit(X)
    labels = km.labels_

    zone_borough = duckdb.connect()
    zone_borough.execute("LOAD spatial;")
    zb = zone_borough.execute(
        "SELECT LocationID, zone, borough FROM ST_Read('taxi_zones/taxi_zones.shp')"
    ).fetchdf().set_index("LocationID")

    result = {"k": best_k, "silhouette": best_score, "silhouette_by_k": scores, "clusters": {}}
    for c in range(best_k):
        idx = [i for i, l in enumerate(labels) if l == c]
        member_zones = [zones[i] for i in idx]
        centroid = X[idx].mean(axis=0)
        borough_counts = {}
        zone_names = []
        for z in member_zones:
            if z in zb.index:
                b = zb.loc[z, "borough"]
                zn = zb.loc[z, "zone"]
                borough_counts[b] = borough_counts.get(b, 0) + 1
                zone_names.append({"id": int(z), "name": zn, "borough": b})
        result["clusters"][c] = {
            "n_zones": len(member_zones),
            "borough_counts": borough_counts,
            "weekday_profile": centroid[:24].tolist(),
            "weekend_profile": centroid[24:].tolist(),
            "zones": zone_names,
        }
        print(f"\ncluster {c}: {len(member_zones)} zones, boroughs={borough_counts}")
        print(f"  sample zones: {[z['name'] for z in zone_names[:6]]}")

    zone_to_cluster = {int(zones[i]): int(labels[i]) for i in range(len(zones))}
    result["zone_to_cluster"] = zone_to_cluster

    with open("_zone_clusters.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nsaved _zone_clusters.json")


if __name__ == "__main__":
    main()

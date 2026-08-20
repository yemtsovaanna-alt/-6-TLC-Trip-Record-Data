"""Build aggregated summary tables from the analyses in this session and load
them into the local Postgres (nyc_taxi db) via DuckDB's postgres extension,
for a local Grafana dashboard.
"""
import json
import math
import time

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

t0 = time.time()
con = duckdb.connect()
con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
con.execute("INSTALL postgres; LOAD postgres;")
con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")
print(f"attached postgres [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 1. daily_citywide — full time series for the main charts
# ---------------------------------------------------------------------------
print("building daily_citywide...")
con.execute("""
    CREATE OR REPLACE TABLE mem_daily_citywide AS
    SELECT CAST(pickup_datetime AS DATE) AS date, count(*) AS trips,
        sum(base_passenger_fare)/sum(trip_miles) AS fare_per_mile
    FROM read_parquet('TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
    GROUP BY 1
""")
weather = con.execute("SELECT * FROM read_csv('taxi_weather_analysis/weather_daily_2019_2026.csv')").fetchdf()
mta = con.execute("SELECT * FROM read_csv('taxi_weather_analysis/mta_daily_ridership.csv')").fetchdf()
daily = con.execute("SELECT * FROM mem_daily_citywide ORDER BY date").fetchdf()
daily["date"] = pd.to_datetime(daily["date"])
weather["date"] = pd.to_datetime(weather["date"])
mta["date"] = pd.to_datetime(mta["date"])
daily = daily.merge(weather, on="date", how="left").merge(
    mta[["date", "Subway", "CRZ Entries"]].rename(
        columns={"Subway": "subway_ridership", "CRZ Entries": "crz_entries"}), on="date", how="left")
con.register("daily_citywide_df", daily)
con.execute("CREATE OR REPLACE TABLE pg.daily_citywide AS SELECT * FROM daily_citywide_df")
print(f"  daily_citywide: {len(daily)} rows [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 2. daily_by_borough
# ---------------------------------------------------------------------------
print("building daily_by_borough...")
con.execute("""
    CREATE OR REPLACE TABLE mem_daily_zone AS
    SELECT CAST(pickup_datetime AS DATE) AS date, PULocationID AS zone,
        count(*) AS trips, sum(base_passenger_fare) AS sum_fare, sum(trip_miles) AS sum_miles
    FROM read_parquet('TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
    GROUP BY 1, 2
""")
con.execute("LOAD spatial;")
zones = con.execute("""
    SELECT LocationID, zone AS zone_name, borough,
        ST_X(ST_Transform(ST_Centroid(geom), 'EPSG:2263', 'EPSG:4326')) AS lat,
        ST_Y(ST_Transform(ST_Centroid(geom), 'EPSG:2263', 'EPSG:4326')) AS lon
    FROM ST_Read('taxi_zones/taxi_zones.shp')
""").fetchdf()
con.register("zones_df", zones)
con.execute("""
    CREATE OR REPLACE TABLE mem_daily_borough AS
    SELECT z.date, z.borough, sum(z.trips) AS trips,
        sum(z.sum_fare)/sum(z.sum_miles) AS fare_per_mile
    FROM (SELECT d.*, zd.borough FROM mem_daily_zone d JOIN zones_df zd ON zd.LocationID = d.zone) z
    WHERE z.borough != 'EWR'
    GROUP BY 1, 2
""")
con.execute("CREATE OR REPLACE TABLE pg.daily_by_borough AS SELECT * FROM mem_daily_borough ORDER BY date, borough")
n = con.execute("SELECT count(*) FROM pg.daily_by_borough").fetchone()[0]
print(f"  daily_by_borough: {n} rows [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 3. product_metrics_yearly (hardcoded from the earlier product-metrics run)
# ---------------------------------------------------------------------------
print("building product_metrics_yearly...")
product_metrics = pd.DataFrame([
    {"year": 2019, "avg_daily_trips": 998451, "med_wait_sec": 246, "med_hourly_pay": 44.53, "med_pay_per_trip": 10.19, "med_fare_per_mile": 4.11, "avg_trips_per_active_zone_hour": 114.62},
    {"year": 2020, "avg_daily_trips": 492164, "med_wait_sec": 237, "med_hourly_pay": 47.83, "med_pay_per_trip": 10.91, "med_fare_per_mile": 4.60, "avg_trips_per_active_zone_hour": 64.61},
    {"year": 2021, "avg_daily_trips": 570466, "med_wait_sec": 296, "med_hourly_pay": 53.87, "med_pay_per_trip": 13.90, "med_fare_per_mile": 5.48, "avg_trips_per_active_zone_hour": 78.67},
    {"year": 2022, "avg_daily_trips": 698930, "med_wait_sec": 271, "med_hourly_pay": 53.59, "med_pay_per_trip": 14.35, "med_fare_per_mile": 5.68, "avg_trips_per_active_zone_hour": 95.80},
    {"year": 2023, "avg_daily_trips": 749959, "med_wait_sec": 244, "med_hourly_pay": 53.77, "med_pay_per_trip": 14.54, "med_fare_per_mile": 5.93, "avg_trips_per_active_zone_hour": 104.76},
    {"year": 2024, "avg_daily_trips": 773747, "med_wait_sec": 239, "med_hourly_pay": 55.00, "med_pay_per_trip": 15.09, "med_fare_per_mile": 6.28, "avg_trips_per_active_zone_hour": 107.53},
    {"year": 2025, "avg_daily_trips": 801936, "med_wait_sec": 243, "med_hourly_pay": 56.34, "med_pay_per_trip": 15.54, "med_fare_per_mile": 6.41, "avg_trips_per_active_zone_hour": 109.62},
    {"year": 2026, "avg_daily_trips": 798574, "med_wait_sec": 264, "med_hourly_pay": 57.61, "med_pay_per_trip": 15.70, "med_fare_per_mile": 6.72, "avg_trips_per_active_zone_hour": 114.86},
])
con.register("pm_df", product_metrics)
con.execute("CREATE OR REPLACE TABLE pg.product_metrics_yearly AS SELECT * FROM pm_df")
print(f"  product_metrics_yearly: {len(product_metrics)} rows")

# ---------------------------------------------------------------------------
# 4. weather_effect_by_borough (hardcoded DoWhy results)
# ---------------------------------------------------------------------------
weather_effect = pd.DataFrame([
    {"borough": "Manhattan", "pct_per_10mm_rain": 2.11, "p_value": 0.0000968, "n_days": 2609},
    {"borough": "Brooklyn", "pct_per_10mm_rain": 1.44, "p_value": 0.0000333, "n_days": 2609},
    {"borough": "Citywide", "pct_per_10mm_rain": 1.44, "p_value": 0.0001740, "n_days": 2609},
    {"borough": "Queens", "pct_per_10mm_rain": 0.89, "p_value": 0.0172233, "n_days": 2609},
    {"borough": "Bronx", "pct_per_10mm_rain": 0.485, "p_value": 0.0461292, "n_days": 2609},
    {"borough": "Staten Island", "pct_per_10mm_rain": 0.232, "p_value": 0.4619966, "n_days": 2609},
])
con.register("we_df", weather_effect)
con.execute("CREATE OR REPLACE TABLE pg.weather_effect_by_borough AS SELECT * FROM we_df")
print(f"  weather_effect_by_borough: {len(weather_effect)} rows")

# ---------------------------------------------------------------------------
# 5. rain_effect_by_subway_tier
# ---------------------------------------------------------------------------
subway_tier = pd.DataFrame([
    {"tier": "near (<=354m)", "pct_per_10mm_rain": 1.771, "p_value": 0.0000114, "n_zones": 88},
    {"tier": "mid (354-893m)", "pct_per_10mm_rain": 1.563, "p_value": 0.0000042, "n_zones": 87},
    {"tier": "far (>893m)", "pct_per_10mm_rain": 0.332, "p_value": 0.1805, "n_zones": 87},
])
con.register("st_df", subway_tier)
con.execute("CREATE OR REPLACE TABLE pg.rain_effect_by_subway_tier AS SELECT * FROM st_df")
print(f"  rain_effect_by_subway_tier: {len(subway_tier)} rows")

# ---------------------------------------------------------------------------
# 6. forecast_results
# ---------------------------------------------------------------------------
forecast = pd.DataFrame([
    {"model": "Naive (=yesterday)", "mae": 62175, "rmse": 81473, "mape_pct": 9.83},
    {"model": "Trailing 7-day mean", "mae": 63672, "rmse": 82051, "mape_pct": 9.98},
    {"model": "Seasonal naive (=last week)", "mae": 42559, "rmse": 68846, "mape_pct": 6.88},
    {"model": "Linear regression", "mae": 26142, "rmse": 46572, "mape_pct": 4.41},
    {"model": "Gradient boosting", "mae": 24801, "rmse": 44279, "mape_pct": 4.12},
])
con.register("fc_df", forecast)
con.execute("CREATE OR REPLACE TABLE pg.forecast_results AS SELECT * FROM fc_df")
print(f"  forecast_results: {len(forecast)} rows")

# ---------------------------------------------------------------------------
# 7. price_elasticity
# ---------------------------------------------------------------------------
elasticity = pd.DataFrame([
    {"method": "Naive OLS (biased)", "estimate": 0.472, "p_value": 0.0000118, "note": "wrong sign due to price/demand simultaneity"},
    {"method": "IV (congestion pricing DiD)", "estimate": -2.998, "p_value": None, "note": "Wald estimator, Manhattan vs Queens"},
])
con.register("el_df", elasticity)
con.execute("CREATE OR REPLACE TABLE pg.price_elasticity AS SELECT * FROM el_df")
print(f"  price_elasticity: {len(elasticity)} rows")

# ---------------------------------------------------------------------------
# 8. congestion_pricing_yoy
# ---------------------------------------------------------------------------
cpyoy = pd.DataFrame([
    {"borough": "Manhattan", "trips_2024": 260696, "trips_2025": 249848, "yoy_pct": -4.16, "fare_2024": 5.75, "fare_2025": 6.09, "fare_yoy_pct": 5.81},
    {"borough": "Queens", "trips_2024": 136449, "trips_2025": 143034, "yoy_pct": 4.83, "fare_2024": 4.38, "fare_2025": 4.50, "fare_yoy_pct": 2.69},
    {"borough": "Brooklyn", "trips_2024": 175304, "trips_2025": 179129, "yoy_pct": 2.18, "fare_2024": 5.26, "fare_2025": 5.44, "fare_yoy_pct": 3.42},
    {"borough": "Bronx", "trips_2024": 81764, "trips_2025": 85923, "yoy_pct": 5.09, "fare_2024": 4.47, "fare_2025": 4.58, "fare_yoy_pct": 2.40},
])
con.register("cp_df", cpyoy)
con.execute("CREATE OR REPLACE TABLE pg.congestion_pricing_yoy AS SELECT * FROM cp_df")
print(f"  congestion_pricing_yoy: {len(cpyoy)} rows")

# ---------------------------------------------------------------------------
# 9. subway_access — zone-level distance to nearest station + volume
# ---------------------------------------------------------------------------
print("building subway_access...")
stations = json.load(open("subway_stations.json", encoding="utf-8"))
station_coords = [(lat, lon) for lat, lon, name in stations.values()]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


zones["dist_to_subway_m"] = zones.apply(
    lambda r: min(haversine(r.lat, r.lon, slat, slon) for slat, slon in station_coords), axis=1)

vol = con.execute("""
    SELECT PULocationID AS zone, count(*) AS annual_trips,
        avg(trip_miles) AS avg_trip_miles,
        sum(base_passenger_fare)/sum(trip_miles) AS fare_per_mile
    FROM read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet', union_by_name=True)
    GROUP BY 1
""").fetchdf()
subway_access = zones.merge(vol, left_on="LocationID", right_on="zone", how="inner")
subway_access = subway_access[subway_access.borough != "EWR"][
    ["LocationID", "zone_name", "borough", "lat", "lon", "dist_to_subway_m",
     "annual_trips", "avg_trip_miles", "fare_per_mile"]]
con.register("sa_df", subway_access)
con.execute("CREATE OR REPLACE TABLE pg.subway_access AS SELECT * FROM sa_df")
print(f"  subway_access: {len(subway_access)} rows [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 10. zone_clusters — re-run k-means (k=4, same as before)
# ---------------------------------------------------------------------------
print("building zone_clusters...")
hourly = con.execute("""
    SELECT PULocationID AS zone, dayofweek(pickup_datetime) AS dow, hour(pickup_datetime) AS hr,
        count(*) AS trips
    FROM read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet', union_by_name=True)
    GROUP BY 1, 2, 3
""").fetchdf()
hourly["is_weekend"] = hourly["dow"].isin([0, 6])
agg = hourly.groupby(["zone", "is_weekend", "hr"], as_index=False)["trips"].sum()
agg["total"] = agg.groupby(["zone", "is_weekend"])["trips"].transform("sum")
agg["pct"] = agg["trips"] / agg["total"]

zone_ids = sorted(agg["zone"].unique())
features = []
for z in zone_ids:
    row = []
    for is_we in [False, True]:
        sub = agg[(agg.zone == z) & (agg.is_weekend == is_we)].set_index("hr")["pct"]
        row.extend([sub.get(h, 0.0) for h in range(24)])
    features.append(row)
X = np.array(features)
km = KMeans(n_clusters=4, n_init=20, random_state=42).fit(X)
labels = km.labels_

cluster_names = {0: "Утренний коммьютер", 1: "Вечернее ядро", 2: "Досуговый вечер", 3: "Аэропорт (outlier)"}
zc = pd.DataFrame({"zone": zone_ids, "cluster": labels})
zc["cluster_label"] = zc["cluster"].map(cluster_names)
zc = zc.merge(zones[["LocationID", "zone_name", "borough"]], left_on="zone", right_on="LocationID", how="left")
zc = zc[["zone", "zone_name", "borough", "cluster", "cluster_label"]]
con.register("zc_df", zc)
con.execute("CREATE OR REPLACE TABLE pg.zone_clusters AS SELECT * FROM zc_df")
print(f"  zone_clusters: {len(zc)} rows [{time.time()-t0:.1f}s]")

print(f"\nALL DONE in {time.time()-t0:.1f}s")
print("\nTables in postgres:")
print(con.execute("SELECT * FROM pg.pg_tables WHERE schemaname='public'").fetchdf() if False else "")
for t in ["daily_citywide", "daily_by_borough", "product_metrics_yearly", "weather_effect_by_borough",
          "rain_effect_by_subway_tier", "forecast_results", "price_elasticity",
          "congestion_pricing_yoy", "subway_access", "zone_clusters"]:
    n = con.execute(f"SELECT count(*) FROM pg.{t}").fetchone()[0]
    print(f"  {t}: {n} rows")

# Wait heatmaps (zone_wait_time / zone_wait_by_period / wait_by_hour_dow) are
# built by _build_zone_wait_tables.py. One-click: python _run_wait_heatmaps.py
# (or double-click run_wait_heatmaps.bat) — also rebuilds the map + Grafana JSON.

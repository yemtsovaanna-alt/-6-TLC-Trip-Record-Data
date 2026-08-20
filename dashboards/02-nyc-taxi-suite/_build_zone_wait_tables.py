"""Build wait-time summary tables for the zone map + Grafana heatmaps.

Wait definition (same as _compute_product_metrics.py):
  wait_sec = pickup_datetime - request_datetime, FHVHV only, 0 < wait < 3600.
  (Yellow/green/fhv have no request timestamp — wait is FHVHV-only.)

Snapshot year: 2024 (matches airport panel copy on dashboard 3).

Writes to Postgres nyc_taxi:
  - zone_wait_time              (zone-level overall)
  - zone_wait_by_period         (zone × morning/day/evening/night/all)
  - zone_wait_by_aggregator     (zone × Uber/Lyft/Via/Juno)
  - zone_wait_by_period_agg     (zone × period × aggregator + 'all')
  - wait_by_hour_dow            (citywide hour × DOW)
  - wait_by_hour_dow_aggregator (hour × DOW × aggregator)

Run before _build_map_v2_data.py (or via _run_wait_heatmaps.py).
"""
import time

import duckdb

YEAR = 2024
MIN_WAIT_N = 50

FHVHV = (
    f"read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_{YEAR}-*.parquet', "
    "union_by_name=True)"
)

AGG_MAP = (
    "CASE hvfhs_license_num "
    "WHEN 'HV0002' THEN 'Juno' WHEN 'HV0003' THEN 'Uber' "
    "WHEN 'HV0004' THEN 'Via' WHEN 'HV0005' THEN 'Lyft' "
    "ELSE hvfhs_license_num END"
)

PERIOD_CASE = """
CASE
  WHEN hour(request_datetime) BETWEEN 7 AND 10 THEN 'morning'
  WHEN hour(request_datetime) BETWEEN 11 AND 15 THEN 'day'
  WHEN hour(request_datetime) BETWEEN 16 AND 18 THEN 'evening'
  ELSE 'night'
END
"""

t0 = time.time()
con = duckdb.connect()
con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
con.execute("INSTALL postgres; LOAD postgres;")
con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")
print(f"attached postgres [{time.time()-t0:.1f}s]")

print(f"scanning FHVHV {YEAR} wait times...")
con.execute(f"""
CREATE OR REPLACE TEMP TABLE wait_trips AS
SELECT
  PULocationID AS zone,
  {AGG_MAP} AS aggregator,
  hour(request_datetime) AS hr,
  (dayofweek(request_datetime) + 6) % 7 AS dow,
  {PERIOD_CASE} AS period,
  date_diff('second', request_datetime, pickup_datetime) AS wait_sec
FROM {FHVHV}
WHERE request_datetime IS NOT NULL
  AND pickup_datetime > request_datetime
  AND date_diff('second', request_datetime, pickup_datetime) < 3600
  AND PULocationID IS NOT NULL
  AND hvfhs_license_num IN ('HV0002','HV0003','HV0004','HV0005')
""")
n = con.execute("SELECT count(*) FROM wait_trips").fetchone()[0]
print(f"  wait_trips: {n:,} rows [{time.time()-t0:.1f}s]")

print("building zone_wait_time...")
con.execute("""
CREATE OR REPLACE TABLE pg.zone_wait_time AS
SELECT zone,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY zone
ORDER BY zone
""")
print(f"  zone_wait_time: {con.execute('SELECT count(*) FROM pg.zone_wait_time').fetchone()[0]} [{time.time()-t0:.1f}s]")

print("building zone_wait_by_period...")
con.execute("""
CREATE OR REPLACE TABLE pg.zone_wait_by_period AS
SELECT zone, period,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY zone, period
UNION ALL
SELECT zone, 'all' AS period,
  round(median(wait_sec), 0), round(avg(wait_sec), 1), count(*)::BIGINT
FROM wait_trips
GROUP BY zone
ORDER BY zone, period
""")
print(f"  zone_wait_by_period: {con.execute('SELECT count(*) FROM pg.zone_wait_by_period').fetchone()[0]} [{time.time()-t0:.1f}s]")

print("building zone_wait_by_aggregator...")
con.execute("""
CREATE OR REPLACE TABLE pg.zone_wait_by_aggregator AS
SELECT zone, aggregator,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY zone, aggregator
ORDER BY zone, aggregator
""")
print(f"  zone_wait_by_aggregator: {con.execute('SELECT count(*) FROM pg.zone_wait_by_aggregator').fetchone()[0]} [{time.time()-t0:.1f}s]")

print("building zone_wait_by_period_agg...")
con.execute("""
CREATE OR REPLACE TABLE pg.zone_wait_by_period_agg AS
SELECT zone, period, aggregator,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY zone, period, aggregator
UNION ALL
SELECT zone, 'all' AS period, aggregator,
  round(median(wait_sec), 0), round(avg(wait_sec), 1), count(*)::BIGINT
FROM wait_trips
GROUP BY zone, aggregator
UNION ALL
SELECT zone, period, 'all' AS aggregator,
  round(median(wait_sec), 0), round(avg(wait_sec), 1), count(*)::BIGINT
FROM wait_trips
GROUP BY zone, period
UNION ALL
SELECT zone, 'all' AS period, 'all' AS aggregator,
  round(median(wait_sec), 0), round(avg(wait_sec), 1), count(*)::BIGINT
FROM wait_trips
GROUP BY zone
ORDER BY zone, period, aggregator
""")
print(f"  zone_wait_by_period_agg: {con.execute('SELECT count(*) FROM pg.zone_wait_by_period_agg').fetchone()[0]} [{time.time()-t0:.1f}s]")

print("building wait_by_hour_dow...")
con.execute("""
CREATE OR REPLACE TABLE pg.wait_by_hour_dow AS
SELECT hr AS hour, dow,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY hr, dow
ORDER BY dow, hr
""")
print(f"  wait_by_hour_dow: {con.execute('SELECT count(*) FROM pg.wait_by_hour_dow').fetchone()[0]} [{time.time()-t0:.1f}s]")

print("building wait_by_hour_dow_aggregator...")
con.execute("""
CREATE OR REPLACE TABLE pg.wait_by_hour_dow_aggregator AS
SELECT hr AS hour, dow, aggregator,
  round(median(wait_sec), 0) AS med_wait_sec,
  round(avg(wait_sec), 1) AS avg_wait_sec,
  count(*)::BIGINT AS n_trips
FROM wait_trips
GROUP BY hr, dow, aggregator
ORDER BY aggregator, dow, hr
""")
print(f"  wait_by_hour_dow_aggregator: {con.execute('SELECT count(*) FROM pg.wait_by_hour_dow_aggregator').fetchone()[0]} [{time.time()-t0:.1f}s]")

peek = con.execute("""
  SELECT aggregator, round(median(med_wait_sec),0) AS city_med, sum(n_trips) AS trips
  FROM pg.zone_wait_by_aggregator GROUP BY 1 ORDER BY trips DESC
""").fetchdf()
print("\nby aggregator:")
print(peek.to_string(index=False))
print(f"\nALL DONE in {time.time()-t0:.1f}s (min_n for map gray-out: {MIN_WAIT_N})")

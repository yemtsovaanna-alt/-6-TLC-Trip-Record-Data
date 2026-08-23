"""Compute 6 product metrics (1 North Star + 3 Guardrail + 2 Proxy) from the
cleaned TLC archive, with year-over-year trend, to ground the product-metrics
write-up in real numbers rather than a purely theoretical framework.
"""
import json
import time

import duckdb

con = duckdb.connect()
con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")

FHVHV = "read_parquet('TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)"
YELLOW = "read_parquet('TLC_Trip_Data_clean/yellow/*.parquet', union_by_name=True)"
GREEN = "read_parquet('TLC_Trip_Data_clean/green/*.parquet', union_by_name=True)"
FHV = "read_parquet('TLC_Trip_Data_clean/fhv/*.parquet', union_by_name=True)"

import os

results = {}
if os.path.exists("_product_metrics.json"):
    results = json.load(open("_product_metrics.json", encoding="utf-8"))
t0 = time.time()


def run(key, label, sql):
    if key in results:
        print(f"skip {label} (cached)")
        return
    print(label)
    results[key] = con.execute(sql).fetchdf().to_dict(orient="records")
    with open("_product_metrics.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  done in {time.time()-t0:.1f}s (saved)")


# 1. NSM — daily completed trips (all 4 types), by year
run("nsm_daily_trips_by_year", "1/5 NSM: daily completed trips by year...", f"""
WITH d AS (
  SELECT year(tpep_pickup_datetime) y, CAST(tpep_pickup_datetime AS DATE) d FROM {YELLOW}
  UNION ALL SELECT year(lpep_pickup_datetime), CAST(lpep_pickup_datetime AS DATE) FROM {GREEN}
  UNION ALL SELECT year(pickup_datetime), CAST(pickup_datetime AS DATE) FROM {FHVHV}
  UNION ALL SELECT year(pickup_datetime), CAST(pickup_datetime AS DATE) FROM {FHV}
)
SELECT y, count(*) trips, count(DISTINCT d) n_days, count(*)*1.0/count(DISTINCT d) avg_daily
FROM d WHERE y BETWEEN 2019 AND 2026 GROUP BY 1 ORDER BY 1
""")

# 2+3 combined — rider wait time AND driver hourly pay in one pass over fhvhv.
# approx_quantile (t-digest) instead of exact median/quantile_cont — exact quantiles
# over 1.6B grouped rows blew the 8GB memory budget (needs to materialize every value).
run("guardrail_wait_and_pay_by_year", "2/5 Guardrail: wait time + driver pay by year (combined pass)...", f"""
SELECT year(pickup_datetime) y,
  approx_quantile(CASE WHEN request_datetime IS NOT NULL AND pickup_datetime > request_datetime
               AND date_diff('second', request_datetime, pickup_datetime) < 3600
          THEN date_diff('second', request_datetime, pickup_datetime) END, 0.5) med_wait_sec,
  approx_quantile(CASE WHEN request_datetime IS NOT NULL AND pickup_datetime > request_datetime
               AND date_diff('second', request_datetime, pickup_datetime) < 3600
          THEN date_diff('second', request_datetime, pickup_datetime) END, 0.9) p90_wait_sec,
  approx_quantile(CASE WHEN trip_time > 60 THEN driver_pay / (trip_time/3600.0) END, 0.5) med_hourly_pay,
  approx_quantile(CASE WHEN trip_time > 60 THEN driver_pay END, 0.5) med_pay_per_trip
FROM {FHVHV}
GROUP BY 1 ORDER BY 1
""")

# 4. Guardrail — unmet shared-ride request rate
run("guardrail_shared_match_by_year", "3/5 Guardrail: unmet shared-ride requests by year...", f"""
SELECT year(pickup_datetime) y,
  sum(CASE WHEN shared_request_flag='Y' THEN 1 ELSE 0 END) requested,
  sum(CASE WHEN shared_request_flag='Y' AND shared_match_flag='Y' THEN 1 ELSE 0 END) n_matched
FROM {FHVHV}
GROUP BY 1 ORDER BY 1
""")

# 5. Proxy — fare per mile (surge/imbalance signal)
run("proxy_fare_per_mile_by_year", "4/5 Proxy: fare per mile by year...", f"""
SELECT year(pickup_datetime) y,
  approx_quantile(base_passenger_fare / trip_miles, 0.5) med_fare_per_mile
FROM {FHVHV}
WHERE trip_miles > 0.1
GROUP BY 1 ORDER BY 1
""")

# 6. Proxy — marketplace liquidity: trips per active-zone-hour
run("proxy_liquidity_by_year", "5/5 Proxy: trips per active pickup-zone-hour by year...", f"""
WITH hourly AS (
  SELECT year(pickup_datetime) y, date_trunc('hour', pickup_datetime) h, PULocationID
  FROM {FHVHV}
),
per_hour AS (
  SELECT y, h, count(*) trips, count(DISTINCT PULocationID) active_zones
  FROM hourly GROUP BY 1,2
)
SELECT y, avg(trips*1.0/active_zones) avg_trips_per_active_zone_hour, avg(active_zones) avg_active_zones
FROM per_hour GROUP BY 1 ORDER BY 1
""")

print(f"all done, total {time.time()-t0:.1f}s")

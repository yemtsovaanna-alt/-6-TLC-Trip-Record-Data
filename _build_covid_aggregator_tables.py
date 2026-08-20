"""Build additional Postgres tables: monthly trips by taxi type (COVID curve),
aggregator (Uber/Lyft/Via/Juno) market share over time and by borough, and
per-zone dominant taxi type / dominant aggregator.
"""
import time

import duckdb
import pandas as pd

t0 = time.time()
con = duckdb.connect()
con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
con.execute("INSTALL postgres; LOAD postgres;")
con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")

AGG_MAP = "CASE hvfhs_license_num WHEN 'HV0002' THEN 'Juno' WHEN 'HV0003' THEN 'Uber' " \
          "WHEN 'HV0004' THEN 'Via' WHEN 'HV0005' THEN 'Lyft' ELSE hvfhs_license_num END"

# reuse the zone -> borough/name mapping already sitting in postgres (subway_access)
zones = con.execute('SELECT "LocationID" AS zone, zone_name, borough FROM pg.subway_access').fetchdf()
print(f"zones loaded from pg.subway_access: {len(zones)} [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 1. monthly_by_type — COVID crash/recovery curve, all 4 types, full archive
# ---------------------------------------------------------------------------
print("building monthly_by_type...")
q = """
SELECT date_trunc('month', tpep_pickup_datetime)::date AS month, 'yellow' AS taxi_type, count(*) AS trips
FROM read_parquet('TLC_Trip_Data_clean/yellow/*.parquet', union_by_name=True) GROUP BY 1
UNION ALL
SELECT date_trunc('month', lpep_pickup_datetime)::date, 'green', count(*)
FROM read_parquet('TLC_Trip_Data_clean/green/*.parquet', union_by_name=True) GROUP BY 1
UNION ALL
SELECT date_trunc('month', pickup_datetime)::date, 'fhvhv', count(*)
FROM read_parquet('TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True) GROUP BY 1
UNION ALL
SELECT date_trunc('month', pickup_datetime)::date, 'fhv', count(*)
FROM read_parquet('TLC_Trip_Data_clean/fhv/*.parquet', union_by_name=True) GROUP BY 1
"""
monthly_by_type = con.execute(q).fetchdf()
con.register("mbt_df", monthly_by_type)
con.execute("CREATE OR REPLACE TABLE pg.monthly_by_type AS SELECT * FROM mbt_df ORDER BY month, taxi_type")
print(f"  monthly_by_type: {len(monthly_by_type)} rows [{time.time()-t0:.1f}s]")

# also a normalized-to-Jan-2019=100 index per type, useful for "who fell/recovered more"
mbt = monthly_by_type.copy()
mbt["month"] = pd.to_datetime(mbt["month"])
base = mbt[(mbt.month.dt.year == 2019) & (mbt.month.dt.month == 1)].set_index("taxi_type")["trips"]
mbt["index_jan2019_100"] = mbt.apply(lambda r: 100.0 * r.trips / base.get(r.taxi_type, r.trips), axis=1)
con.register("mbt_idx_df", mbt)
con.execute("CREATE OR REPLACE TABLE pg.monthly_by_type_indexed AS SELECT * FROM mbt_idx_df ORDER BY month, taxi_type")
print(f"  monthly_by_type_indexed: {len(mbt)} rows")

# ---------------------------------------------------------------------------
# 2. aggregator_monthly — Uber/Lyft/Via/Juno market share over time
# ---------------------------------------------------------------------------
print("building aggregator_monthly...")
q = f"""
SELECT date_trunc('month', pickup_datetime)::date AS month, {AGG_MAP} AS aggregator, count(*) AS trips
FROM read_parquet('TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
GROUP BY 1, 2
"""
agg_monthly = con.execute(q).fetchdf()
agg_monthly["month"] = pd.to_datetime(agg_monthly["month"])
agg_monthly["month_total"] = agg_monthly.groupby("month")["trips"].transform("sum")
agg_monthly["share_pct"] = 100 * agg_monthly["trips"] / agg_monthly["month_total"]
con.register("am_df", agg_monthly)
con.execute("CREATE OR REPLACE TABLE pg.aggregator_monthly AS SELECT * FROM am_df ORDER BY month, aggregator")
print(f"  aggregator_monthly: {len(agg_monthly)} rows [{time.time()-t0:.1f}s]")

# Jan-2019=100 index per aggregator (COVID recovery heatmap)
agg_idx = agg_monthly.copy()
base_agg = agg_idx[agg_idx.month == pd.Timestamp("2019-01-01")].set_index("aggregator")["trips"]
agg_idx["index_jan2019_100"] = agg_idx.apply(
    lambda r: 100.0 * r.trips / base_agg.get(r.aggregator, r.trips), axis=1)
con.register("am_idx_df", agg_idx)
con.execute("CREATE OR REPLACE TABLE pg.aggregator_monthly_indexed AS SELECT * FROM am_idx_df ORDER BY month, aggregator")
print(f"  aggregator_monthly_indexed: {len(agg_idx)} rows")

yr_agg = agg_idx.copy()
yr_agg["year"] = yr_agg["month"].dt.year
yearly_agg = yr_agg.groupby(["year", "aggregator"], as_index=False).agg(trips=("trips", "sum"))
base_yr_agg = yearly_agg[yearly_agg.year == 2019].set_index("aggregator")["trips"]
yearly_agg["index_jan2019_100"] = yearly_agg.apply(
    lambda r: 100.0 * r.trips / base_yr_agg.get(r.aggregator, r.trips), axis=1)
con.register("yearly_agg_df", yearly_agg)
con.execute("CREATE OR REPLACE TABLE pg.yearly_aggregator_indexed AS SELECT * FROM yearly_agg_df ORDER BY year, aggregator")
print(f"  yearly_aggregator_indexed: {len(yearly_agg)} rows")

# ---------------------------------------------------------------------------
# 2b. monthly_by_borough + recovery index (borough + metro row)
#     Built from daily_by_borough / daily_citywide already in Postgres.
# ---------------------------------------------------------------------------
print("building monthly_by_borough...")
con.execute("""
CREATE OR REPLACE TABLE pg.monthly_by_borough AS
SELECT date_trunc('month', date)::DATE AS month, borough, sum(trips)::BIGINT AS trips
FROM pg.daily_by_borough
GROUP BY 1, 2
ORDER BY 1, 2
""")
print(f"  monthly_by_borough: {con.execute('SELECT count(*) FROM pg.monthly_by_borough').fetchone()[0]} rows")

print("building monthly_subway...")
con.execute("""
CREATE OR REPLACE TABLE pg.monthly_subway AS
SELECT date_trunc('month', date)::DATE AS month, avg(subway_ridership)::BIGINT AS ridership
FROM pg.daily_citywide
WHERE subway_ridership IS NOT NULL
GROUP BY 1
ORDER BY 1
""")
print(f"  monthly_subway: {con.execute('SELECT count(*) FROM pg.monthly_subway').fetchone()[0]} rows")

mbb = con.execute("SELECT * FROM pg.monthly_by_borough ORDER BY month, borough").fetchdf()
mbb["month"] = pd.to_datetime(mbb["month"])
base_b = mbb[(mbb.month.dt.year == 2019) & (mbb.month.dt.month == 1)].set_index("borough")["trips"]
mbb["index_jan2019_100"] = mbb.apply(lambda r: 100.0 * r.trips / base_b.get(r.borough, r.trips), axis=1)
mbb["series"] = mbb["borough"]

ms = con.execute("SELECT * FROM pg.monthly_subway ORDER BY month").fetchdf()
ms["month"] = pd.to_datetime(ms["month"])
pre_crash_subway = con.execute("""
    SELECT avg(subway_ridership)::DOUBLE FROM pg.daily_citywide
    WHERE date BETWEEN '2020-03-01' AND '2020-03-11'
""").fetchone()[0]
ms["trips"] = ms["ridership"]
ms["index_jan2019_100"] = 100.0 * ms["ridership"] / pre_crash_subway
ms["series"] = "Метро NYC"
ms["borough"] = "Метро NYC"
print(f"  metro baseline (pre-COVID daily avg 2020-03-01..11): {pre_crash_subway:,.0f}")

recovery = pd.concat([
    mbb[["month", "series", "trips", "index_jan2019_100"]],
    ms[["month", "series", "trips", "index_jan2019_100"]],
], ignore_index=True)
con.register("recovery_df", recovery)
con.execute("CREATE OR REPLACE TABLE pg.monthly_recovery_indexed AS SELECT * FROM recovery_df ORDER BY month, series")
print(f"  monthly_recovery_indexed: {len(recovery)} rows [{time.time()-t0:.1f}s]")

# yearly rollup for year × series heatmap
print("building yearly_recovery_indexed...")
yr = recovery.copy()
yr["year"] = yr["month"].dt.year
yearly = yr.groupby(["year", "series"], as_index=False).agg(
    index_jan2019_100=("index_jan2019_100", "mean"),
    trips=("trips", "sum"),
)
con.register("yearly_df", yearly)
con.execute("CREATE OR REPLACE TABLE pg.yearly_recovery_indexed AS SELECT * FROM yearly_df ORDER BY year, series")
print(f"  yearly_recovery_indexed: {len(yearly)} rows")

# ---------------------------------------------------------------------------
# 3. aggregator_by_borough_2024
# ---------------------------------------------------------------------------
print("building aggregator_by_borough_2024...")
q = f"""
SELECT PULocationID AS zone, {AGG_MAP} AS aggregator, count(*) AS trips
FROM read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet', union_by_name=True)
GROUP BY 1, 2
"""
agg_zone = con.execute(q).fetchdf()
agg_zone = agg_zone.merge(zones, on="zone", how="left")
agg_borough = agg_zone.groupby(["borough", "aggregator"], as_index=False)["trips"].sum()
agg_borough["borough_total"] = agg_borough.groupby("borough")["trips"].transform("sum")
agg_borough["share_pct"] = 100 * agg_borough["trips"] / agg_borough["borough_total"]
con.register("ab_df", agg_borough)
con.execute("CREATE OR REPLACE TABLE pg.aggregator_by_borough_2024 AS SELECT * FROM ab_df ORDER BY borough, aggregator")
print(f"  aggregator_by_borough_2024: {len(agg_borough)} rows [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 4. zone_dominant_type — per zone, which of yellow/green/fhv/fhvhv dominates (2024)
# ---------------------------------------------------------------------------
print("building zone_dominant_type...")
type_frames = {}
for t, col, path in [
    ("yellow", "PULocationID", "TLC_Trip_Data_clean/yellow/yellow_tripdata_2024-*.parquet"),
    ("green", "PULocationID", "TLC_Trip_Data_clean/green/green_tripdata_2024-*.parquet"),
    ("fhvhv", "PULocationID", "TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet"),
    ("fhv", "PUlocationID", "TLC_Trip_Data_clean/fhv/fhv_tripdata_2024-*.parquet"),
]:
    d = con.execute(f"SELECT {col} AS zone, count(*) AS trips FROM read_parquet('{path}', union_by_name=True) GROUP BY 1").fetchdf()
    type_frames[t] = d.set_index("zone")["trips"]
    print(f"  {t}: {d.trips.sum():,} trips [{time.time()-t0:.1f}s]")

wide = pd.DataFrame(type_frames).fillna(0)
wide["total"] = wide.sum(axis=1)
wide["dominant_type"] = wide[["yellow", "green", "fhvhv", "fhv"]].idxmax(axis=1)
wide["dominant_share_pct"] = 100 * wide[["yellow", "green", "fhvhv", "fhv"]].max(axis=1) / wide["total"]
wide = wide.reset_index().rename(columns={"index": "zone"})
wide = wide.merge(zones, on="zone", how="left")
wide = wide[wide.total > 0]
con.register("zdt_df", wide)
con.execute("CREATE OR REPLACE TABLE pg.zone_dominant_type AS SELECT * FROM zdt_df ORDER BY total DESC")
print(f"  zone_dominant_type: {len(wide)} rows [{time.time()-t0:.1f}s]")

# ---------------------------------------------------------------------------
# 5. zone_dominant_aggregator — per zone, within fhvhv, which aggregator dominates (2024)
# ---------------------------------------------------------------------------
print("building zone_dominant_aggregator...")
q = f"""
SELECT PULocationID AS zone, {AGG_MAP} AS aggregator, count(*) AS trips
FROM read_parquet('TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet', union_by_name=True)
GROUP BY 1, 2
"""
agg_zone2 = con.execute(q).fetchdf()
pivot = agg_zone2.pivot_table(index="zone", columns="aggregator", values="trips", fill_value=0)
pivot["total"] = pivot.sum(axis=1)
agg_cols = [c for c in pivot.columns if c != "total"]
pivot["dominant_aggregator"] = pivot[agg_cols].idxmax(axis=1)
pivot["dominant_share_pct"] = 100 * pivot[agg_cols].max(axis=1) / pivot["total"]
pivot = pivot.reset_index()
pivot = pivot.merge(zones, on="zone", how="left")
con.register("zda_df", pivot)
con.execute("CREATE OR REPLACE TABLE pg.zone_dominant_aggregator AS SELECT * FROM zda_df ORDER BY total DESC")
print(f"  zone_dominant_aggregator: {len(pivot)} rows [{time.time()-t0:.1f}s]")

print(f"\nALL DONE in {time.time()-t0:.1f}s")
for t in ["monthly_by_type", "monthly_by_type_indexed", "aggregator_monthly", "aggregator_monthly_indexed",
          "monthly_by_borough", "monthly_subway", "monthly_recovery_indexed", "yearly_recovery_indexed",
          "yearly_aggregator_indexed",
          "aggregator_by_borough_2024", "zone_dominant_type", "zone_dominant_aggregator"]:
    n = con.execute(f"SELECT count(*) FROM pg.{t}").fetchone()[0]
    print(f"  {t}: {n} rows")

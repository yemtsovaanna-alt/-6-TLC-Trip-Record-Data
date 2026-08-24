"""NYC congestion pricing (Congestion Relief Zone, launched 2025-01-05) —
before/after + difference-in-differences check on Manhattan taxi trips.

Design: compare Manhattan trip volume Jan-Jun 2025 (post-policy) to
Jan-Jun 2024 (same months prior year, controls for seasonality) — then do the
same year-over-year comparison for a borough outside the toll zone (Queens)
as a control group. If Manhattan's YoY change is more negative than Queens',
that gap is a difference-in-differences estimate of the policy's effect, net
of the general year-over-year demand trend already seen in the product
metrics work (recovery from COVID, unrelated to congestion pricing).

Also reports the CRZ Entries series itself (vehicle entries into the zone)
as a direct compliance/volume readout.
"""
import duckdb
import pandas as pd

ZONE_CSV = "_zone_borough_cp.csv"


def get_zone_borough():
    con = duckdb.connect()
    con.execute("LOAD spatial;")
    z = con.execute("SELECT LocationID, borough FROM ST_Read('../taxi_zones/taxi_zones.shp')").fetchdf()
    z.to_csv(ZONE_CSV, index=False)
    return z


def daily_trips_by_zone():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = """
    SELECT CAST(pickup_datetime AS DATE) AS date, PULocationID,
      count(*) trips, sum(base_passenger_fare) sum_fare, sum(trip_miles) sum_miles
    FROM read_parquet(['../TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet',
                        '../TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2025-*.parquet'],
                       union_by_name=True)
    WHERE pickup_datetime >= TIMESTAMP '2024-01-01' AND pickup_datetime < TIMESTAMP '2025-07-01'
    GROUP BY 1, 2
    """
    return con.execute(q).fetchdf()


def main():
    zones = get_zone_borough()
    dz = daily_trips_by_zone()
    print(f"daily-by-zone rows: {len(dz)}")

    dz = dz.merge(zones, left_on="PULocationID", right_on="LocationID", how="left")
    dz["date"] = pd.to_datetime(dz["date"])

    by_borough = dz.groupby(["date", "borough"], as_index=False).agg(
        trips=("trips", "sum"), sum_fare=("sum_fare", "sum"), sum_miles=("sum_miles", "sum"))
    by_borough["fare_per_mile"] = by_borough.sum_fare / by_borough.sum_miles

    def jan_jun_avg(borough, year):
        sub = by_borough[(by_borough.borough == borough) &
                          (by_borough.date >= f"{year}-01-01") & (by_borough.date < f"{year}-07-01")]
        return sub.trips.mean(), sub.fare_per_mile.mean(), len(sub)

    print("\n=== Year-over-year Jan-Jun avg daily trips ===")
    results = {}
    for b in ["Manhattan", "Queens", "Brooklyn", "Bronx"]:
        t24, f24, n24 = jan_jun_avg(b, 2024)
        t25, f25, n25 = jan_jun_avg(b, 2025)
        yoy = 100 * (t25 / t24 - 1)
        fare_yoy = 100 * (f25 / f24 - 1)
        results[b] = {"2024": t24, "2025": t25, "yoy_pct": yoy, "fare_2024": f24, "fare_2025": f25, "fare_yoy_pct": fare_yoy}
        print(f"  {b:12s}  2024={t24:9.0f}/day  2025={t25:9.0f}/day  YoY={yoy:+.2f}%   "
              f"fare/mi 2024=${f24:.2f} 2025=${f25:.2f} YoY={fare_yoy:+.2f}%")

    did = results["Manhattan"]["yoy_pct"] - results["Queens"]["yoy_pct"]
    print(f"\n=== Diff-in-diff (Manhattan YoY - Queens YoY, control for city-wide trend) ===")
    print(f"  {did:+.2f} percentage points")

    # CRZ entries trend
    mta = pd.read_csv("mta_daily_ridership.csv", parse_dates=["date"])
    crz = mta[mta["CRZ Entries"].notna()][["date", "CRZ Entries"]].dropna()
    crz["month"] = crz.date.dt.to_period("M")
    monthly_crz = crz.groupby("month")["CRZ Entries"].mean()
    print("\n=== CRZ vehicle entries, monthly average ===")
    print(monthly_crz.to_string())

    pd.DataFrame(results).T.to_csv("_congestion_pricing_results.csv")
    monthly_crz.to_csv("_crz_monthly.csv")
    print("\nsaved _congestion_pricing_results.csv, _crz_monthly.csv")


if __name__ == "__main__":
    main()

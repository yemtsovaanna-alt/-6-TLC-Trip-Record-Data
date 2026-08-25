"""How does subway accessibility (distance from zone centroid to nearest
station) relate to taxi usage?

Part A: cross-sectional — zone-level annual taxi volume / trip length / fare
vs subway distance (log-log correlation + borough-controlled regression).

Part B: effect modification — does the RAIN -> taxi-demand effect (already
estimated citywide via DoWhy) differ between zones near a subway station and
zones far from one? Splits zones into terciles by distance, aggregates daily
trips within each tier, re-runs the same regression as
causal_full_analysis.py separately per tier.
"""
import warnings

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore")


def part_a_cross_sectional():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = """
    SELECT PULocationID AS zone, count(*) trips,
      avg(trip_miles) avg_trip_miles,
      sum(base_passenger_fare)/sum(trip_miles) fare_per_mile
    FROM read_parquet('../TLC_Trip_Data_clean/fhvhv/fhvhv_tripdata_2024-*.parquet', union_by_name=True)
    GROUP BY 1
    """
    vol = con.execute(q).fetchdf()

    dist = pd.read_csv("../_zone_subway_distance.csv")
    df = vol.merge(dist, left_on="zone", right_on="LocationID", how="inner")
    df = df[df.borough != "EWR"]
    df["log_trips"] = np.log(df.trips)
    df["log_dist"] = np.log(df.dist_to_subway_m + 1)

    r = np.corrcoef(df.log_dist, df.log_trips)[0, 1]
    print(f"Part A: correlation log(dist to subway) vs log(annual trips): r={r:+.3f}")

    m = smf.ols("log_trips ~ log_dist + C(borough)", data=df).fit(cov_type="HC3")
    print(f"  with borough controls: coef(log_dist)={m.params['log_dist']:+.4f}, "
          f"p={m.pvalues['log_dist']:.4g}")
    print(f"  interpretation: 1% farther from subway -> {m.params['log_dist']:+.3f}% "
          f"change in zone's annual taxi trips (holding borough fixed)")

    m2 = smf.ols("fare_per_mile ~ log_dist + C(borough)", data=df).fit(cov_type="HC3")
    print(f"  fare_per_mile ~ log_dist: coef={m2.params['log_dist']:+.4f}, p={m2.pvalues['log_dist']:.4g}")

    m3 = smf.ols("avg_trip_miles ~ log_dist + C(borough)", data=df).fit(cov_type="HC3")
    print(f"  avg_trip_miles ~ log_dist: coef={m3.params['log_dist']:+.4f}, p={m3.pvalues['log_dist']:.4g}")

    df.to_csv("_subway_access_crosssection.csv", index=False)
    return df


def part_b_effect_modification():
    dist = pd.read_csv("../_zone_subway_distance.csv")
    dist = dist[dist.borough != "EWR"].copy()
    q1, q2 = dist.dist_to_subway_m.quantile([1/3, 2/3])
    dist["tier"] = pd.cut(dist.dist_to_subway_m, [-1, q1, q2, np.inf],
                           labels=["near", "mid", "far"])
    print(f"\nPart B: tiers by distance to subway — near <= {q1:.0f}m, "
          f"mid <= {q2:.0f}m, far > {q2:.0f}m")
    print(dist.groupby("tier", observed=True).size())

    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = """
    SELECT CAST(pickup_datetime AS DATE) AS date, PULocationID AS zone, count(*) trips
    FROM read_parquet('../TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
    GROUP BY 1, 2
    """
    daily_zone = con.execute(q).fetchdf()
    print(f"daily-by-zone rows: {len(daily_zone)}")

    daily_zone = daily_zone.merge(dist[["LocationID", "tier"]], left_on="zone",
                                    right_on="LocationID", how="inner")
    daily_zone["date"] = pd.to_datetime(daily_zone["date"])

    weather = pd.read_csv("weather_daily_2019_2026.csv", parse_dates=["date"])

    results = {}
    for tier in ["near", "mid", "far"]:
        sub = daily_zone[daily_zone.tier == tier].groupby("date", as_index=False)["trips"].sum()
        sub = sub.merge(weather, on="date", how="left").dropna(subset=["prcp_mm", "tmax_c"])
        sub["weekday"] = sub.date.dt.weekday.astype(str)
        sub["month"] = sub.date.dt.month.astype(str)
        sub["year"] = sub.date.dt.year.astype(str)
        sub["log_trips"] = np.log(sub.trips)
        m = smf.ols("log_trips ~ prcp_mm + tmax_c + awnd_ms + snow_mm + C(weekday) + C(month) + C(year)",
                     data=sub).fit(cov_type="HC3")
        coef = m.params["prcp_mm"]
        p = m.pvalues["prcp_mm"]
        pct = (np.exp(coef * 10) - 1) * 100
        results[tier] = {"coef": coef, "p": p, "pct_per_10mm": pct, "n": len(sub)}
        print(f"  {tier:5s}: rain effect = {pct:+.3f}% trips per 10mm (p={p:.4g}, n={len(sub)})")

    return results


def main():
    df_a = part_a_cross_sectional()
    results_b = part_b_effect_modification()

    import json
    with open("_subway_access_results.json", "w", encoding="utf-8") as f:
        json.dump({"effect_modification": results_b}, f, indent=2, default=str)
    print("\nsaved _subway_access_crosssection.csv, _subway_access_results.json")


if __name__ == "__main__":
    main()

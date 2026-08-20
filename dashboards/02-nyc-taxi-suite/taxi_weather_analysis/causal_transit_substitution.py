"""Does the rain -> taxi-demand effect run (partly) through subway substitution?

Tests, citywide daily (2020-03-01 .. 2026-06-30, the overlap of MTA ridership
data and the cleaned fhvhv archive):
  1. Does rain reduce subway ridership? (subway_ridership ~ prcp_mm + controls)
  2. Baseline: rain -> taxi trips effect (no subway control) — matches
     causal_full_analysis.py's citywide backdoor estimate as a cross-check.
  3. Rain -> taxi trips effect WITH subway ridership as an added control — if
     the prcp coefficient shrinks a lot vs (2), part of the rain effect on taxi
     demand is explained by riders leaving the subway, not a rain effect on
     taxi demand in its own right.

Caveat: MTA ridership here is citywide-only (no borough breakdown), so this
test can't be run per-borough like the main DoWhy analysis.
"""
import warnings

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore")


def build_dataset():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    taxi = con.execute("""
        SELECT CAST(pickup_datetime AS DATE) AS date, count(*) fhvhv_trips
        FROM read_parquet('../TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
        GROUP BY 1 ORDER BY 1
    """).fetchdf()
    taxi["date"] = pd.to_datetime(taxi["date"])

    weather = pd.read_csv("weather_daily_2019_2026.csv", parse_dates=["date"])
    mta = pd.read_csv("mta_daily_ridership.csv", parse_dates=["date"])
    mta = mta.rename(columns={"Subway": "subway_ridership"})[["date", "subway_ridership"]]

    df = taxi.merge(weather, on="date").merge(mta, on="date")
    df = df.dropna(subset=["prcp_mm", "tmax_c", "awnd_ms", "subway_ridership"]).reset_index(drop=True)
    df["weekday"] = df["date"].dt.weekday.astype(str)
    df["month"] = df["date"].dt.month.astype(str)
    df["year"] = df["date"].dt.year.astype(str)
    df["log_trips"] = np.log(df["fhvhv_trips"])
    df["log_subway"] = np.log(df["subway_ridership"])
    return df


def main():
    df = build_dataset()
    print(f"dataset: {len(df)} days, {df.date.min().date()}..{df.date.max().date()}")

    controls = "tmax_c + awnd_ms + snow_mm + C(weekday) + C(month) + C(year)"

    print("\n=== 1) rain -> subway ridership ===")
    m1 = smf.ols(f"log_subway ~ prcp_mm + {controls}", data=df).fit(cov_type="HC3")
    print(f"  prcp_mm coef = {m1.params['prcp_mm']:+.6f}  p = {m1.pvalues['prcp_mm']:.4g}  "
          f"({(np.exp(m1.params['prcp_mm']*10)-1)*100:+.3f}% subway riders per 10mm rain)")

    print("\n=== 2) rain -> taxi trips, WITHOUT subway control (baseline) ===")
    m2 = smf.ols(f"log_trips ~ prcp_mm + {controls}", data=df).fit(cov_type="HC3")
    print(f"  prcp_mm coef = {m2.params['prcp_mm']:+.6f}  p = {m2.pvalues['prcp_mm']:.4g}  "
          f"({(np.exp(m2.params['prcp_mm']*10)-1)*100:+.3f}% trips per 10mm rain)")

    print("\n=== 3) rain -> taxi trips, WITH subway control ===")
    m3 = smf.ols(f"log_trips ~ prcp_mm + log_subway + {controls}", data=df).fit(cov_type="HC3")
    print(f"  prcp_mm coef = {m3.params['prcp_mm']:+.6f}  p = {m3.pvalues['prcp_mm']:.4g}  "
          f"({(np.exp(m3.params['prcp_mm']*10)-1)*100:+.3f}% trips per 10mm rain)")
    print(f"  log_subway coef = {m3.params['log_subway']:+.4f}  p = {m3.pvalues['log_subway']:.4g}")

    shrink = 100 * (1 - m3.params["prcp_mm"] / m2.params["prcp_mm"])
    print(f"\n=== Decomposition ===")
    print(f"  baseline (no subway control): {m2.params['prcp_mm']:+.6f}")
    print(f"  with subway control:          {m3.params['prcp_mm']:+.6f}")
    print(f"  coefficient shrinkage: {shrink:.1f}% "
          f"(share of rain->taxi effect potentially 'explained away' by subway ridership)")

    df.to_csv("_transit_substitution_data.csv", index=False)
    with open("_transit_substitution_results.txt", "w", encoding="utf-8") as f:
        f.write(f"n_days={len(df)}\n")
        f.write(f"rain_to_subway_coef={m1.params['prcp_mm']}\np={m1.pvalues['prcp_mm']}\n")
        f.write(f"rain_to_taxi_baseline_coef={m2.params['prcp_mm']}\np={m2.pvalues['prcp_mm']}\n")
        f.write(f"rain_to_taxi_with_subway_coef={m3.params['prcp_mm']}\np={m3.pvalues['prcp_mm']}\n")
        f.write(f"subway_coef_in_taxi_model={m3.params['log_subway']}\np={m3.pvalues['log_subway']}\n")
        f.write(f"shrinkage_pct={shrink}\n")
    print("\nsaved _transit_substitution_data.csv, _transit_substitution_results.txt")


if __name__ == "__main__":
    main()

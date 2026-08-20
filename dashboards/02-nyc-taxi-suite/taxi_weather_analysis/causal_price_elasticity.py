"""Price elasticity of demand for taxi trips: naive (biased) vs IV-style
(via congestion pricing as an exogenous price shock).

Naive: OLS of log(trips) on log(fare_per_mile) + calendar controls, citywide
daily. Price and quantity are jointly determined (surge pricing reacts to
demand), so this estimate is contaminated by simultaneity/reverse-causality
bias — a demand spike raises both price AND quantity together, which pushes
the naive coefficient toward positive/zero, understating how negative the
true price elasticity is.

IV-style (Wald estimator): congestion pricing (CRZ toll, launched 2025-01-05)
is a policy-driven price shock uncorrelated with underlying demand shocks.
Using Manhattan vs Queens diff-in-diff (Jan-Jun 2025 vs Jan-Jun 2024) on BOTH
quantity and price, elasticity = DiD(log quantity) / DiD(log price) — a
reduced-form ratio, valid under the assumption the policy affects quantity
only through price (exclusion restriction — see caveats in the writeup).
"""
import warnings

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore")


def naive_ols():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = """
    SELECT CAST(pickup_datetime AS DATE) AS date, count(*) trips,
      sum(base_passenger_fare) sum_fare, sum(trip_miles) sum_miles
    FROM read_parquet('../TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
    GROUP BY 1 ORDER BY 1
    """
    df = con.execute(q).fetchdf()
    df["fare_per_mile"] = df.sum_fare / df.sum_miles
    df["date"] = pd.to_datetime(df["date"])
    df["log_trips"] = np.log(df.trips)
    df["log_fpm"] = np.log(df.fare_per_mile)
    df["weekday"] = df.date.dt.weekday.astype(str)
    df["month"] = df.date.dt.month.astype(str)
    df["year"] = df.date.dt.year.astype(str)

    m = smf.ols("log_trips ~ log_fpm + C(weekday) + C(month) + C(year)", data=df).fit(cov_type="HC3")
    coef = m.params["log_fpm"]
    p = m.pvalues["log_fpm"]
    print(f"Naive OLS elasticity (log trips ~ log fare_per_mile + calendar): "
          f"{coef:+.3f}  (p={p:.4g}, n={len(df)})")
    print("  interpretation: a 1% rise in fare/mile is associated with a "
          f"{coef:+.3f}% change in trips — biased toward 0/positive by simultaneity.")
    return coef, p, len(df)


def main():
    naive_coef, naive_p, n = naive_ols()

    # Wald/IV elasticity from the congestion-pricing diff-in-diff (numbers from
    # causal_congestion_pricing.py's latest run, printed to console there).
    print("\nSee causal_congestion_pricing.py output for the Manhattan/Queens "
          "diff-in-diff on quantity and price — combine manually below:")
    print("  IV elasticity = DiD(log quantity) / DiD(log price)")

    with open("_elasticity_naive.txt", "w", encoding="utf-8") as f:
        f.write(f"naive_coef={naive_coef}\np={naive_p}\nn={n}\n")
    print("\nsaved _elasticity_naive.txt")


if __name__ == "__main__":
    main()

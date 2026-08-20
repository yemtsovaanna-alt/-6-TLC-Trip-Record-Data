"""Did aggregators (Uber/Lyft/Via/Juno, i.e. fhvhv) cannibalize yellow + green
("medallion") taxi trips?

Design: zone x year panel, NYC taxi zones (LocationID) x years 2019-2025 (2026
excluded — archive only covers Jan-Jun 2026, a partial year would mechanically
show fewer trips than a full year and bias any year-level comparison).

Naive cross-sectional/time correlation is hopeless here: aggregator volume and
overall market conditions (COVID crash/recovery, secular ride-hail adoption)
move together across the WHOLE city at the SAME time, so a simple
aggregator_trips vs medallion_trips regression mostly picks up "everything
crashed together in 2020" rather than substitution.

Two-way fixed effects fixes this: zone dummies absorb every time-invariant
thing about a zone (observed or not — borough, subway access, land use,
airport status, ...), year dummies absorb every citywide-common shock in a
given year (COVID, secular trend, congestion pricing, weather-in-aggregate).
What's left is the "within" question DoWhy is asked to estimate: in years
when a GIVEN zone's aggregator penetration rose MORE than that zone's own
average trend (net of the citywide year effect), did that SAME zone's
medallion trip count fall more than its own trend? That's a real empirical
question, not a definitional one, because outcome is an absolute trip COUNT
(log), not a share of the same total the treatment is a share of.
"""
import json
import os
import sys
import warnings

# console codepage (cp1251) can't encode some unicode arrows DoWhy prints in
# estimand summaries — force utf-8 stdout instead of crashing mid-run
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import networkx as nx

# same dowhy/networkx 3.6 compat shim as causal_full_analysis.py
if not hasattr(nx.algorithms, "d_separated"):
    nx.algorithms.d_separated = nx.is_d_separator

import duckdb
import numpy as np
import pandas as pd
from dowhy import CausalModel
from dowhy.causal_estimator import CausalEstimate
from dowhy.causal_estimators.regression_estimator import RegressionEstimator

warnings.filterwarnings("ignore")


def _patched_estimate_effect(self, data_df=None, need_conditional_estimates=None):
    """same pandas-compat patch as causal_full_analysis.py (Series.__getitem__
    positional fallback removed in modern pandas; dowhy 0.8 relies on it)."""
    if data_df is None:
        data_df = self._data
    if need_conditional_estimates is None:
        need_conditional_estimates = self.need_conditional_estimates
    if not self.model:
        _, self.model = self._build_model()
    effect_estimate = self._do(self._treatment_value, data_df) - self._do(self._control_value, data_df)
    conditional_effect_estimates = None
    if need_conditional_estimates:
        conditional_effect_estimates = self._estimate_conditional_effects(
            self._estimate_effect_fn, effect_modifier_names=self._effect_modifier_names)
    intercept_parameter = self.model.params.iloc[0]
    return CausalEstimate(
        estimate=effect_estimate, control_value=self._control_value,
        treatment_value=self._treatment_value, conditional_estimates=conditional_effect_estimates,
        target_estimand=self._target_estimand, realized_estimand_expr=self.symbolic_estimator,
        intercept=intercept_parameter,
    )


RegressionEstimator._estimate_effect = _patched_estimate_effect

YEARS = list(range(2019, 2026))  # 2019..2025, full years only


def build_panel():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")

    print("aggregating trip counts by zone x year, 4 taxi types (2019-2025)...")
    sources = [
        ("yellow", "PULocationID", "tpep_pickup_datetime", "../TLC_Trip_Data_clean/yellow/*.parquet"),
        ("green", "PULocationID", "lpep_pickup_datetime", "../TLC_Trip_Data_clean/green/*.parquet"),
        ("fhvhv", "PULocationID", "pickup_datetime", "../TLC_Trip_Data_clean/fhvhv/*.parquet"),
        ("fhv", "PUlocationID", "pickup_datetime", "../TLC_Trip_Data_clean/fhv/*.parquet"),
    ]
    frames = []
    for name, loc_col, date_col, glob in sources:
        q = f"""
            SELECT {loc_col} AS zone, extract(year FROM {date_col})::int AS year, count(*) AS trips
            FROM read_parquet('{glob}', union_by_name=True)
            WHERE extract(year FROM {date_col}) BETWEEN 2019 AND 2025
            GROUP BY 1, 2
        """
        d = con.execute(q).fetchdf()
        d["taxi_type"] = name
        frames.append(d)
        print(f"  {name}: {d.trips.sum():,} trips, {len(d)} zone-year cells")

    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot_table(index=["zone", "year"], columns="taxi_type", values="trips", fill_value=0).reset_index()
    for c in ["yellow", "green", "fhv", "fhvhv"]:
        if c not in wide.columns:
            wide[c] = 0

    wide["medallion_trips"] = wide["yellow"] + wide["green"]
    wide["total_trips"] = wide["yellow"] + wide["green"] + wide["fhv"] + wide["fhvhv"]
    wide["aggregator_share"] = wide["fhvhv"] / wide["total_trips"].replace(0, np.nan)
    wide = wide[wide["total_trips"] > 0].copy()
    wide["log_medallion_trips"] = np.log(wide["medallion_trips"].clip(lower=1))
    wide["log_aggregator_trips"] = np.log(wide["fhvhv"].clip(lower=1))

    boroughs = pd.read_csv("_zone_borough_cp.csv")
    wide = wide.merge(boroughs, left_on="zone", right_on="LocationID", how="left").drop(columns=["LocationID"])
    wide["zone"] = wide["zone"].astype(int)
    wide["year"] = wide["year"].astype(int)

    print(f"panel: {len(wide)} zone-year rows, {wide.zone.nunique()} zones, years {sorted(wide.year.unique())}")
    return wide


def run_naive(df):
    """No fixed effects at all — just the raw relationship, for contrast."""
    import statsmodels.formula.api as smf
    m = smf.ols("log_medallion_trips ~ aggregator_share", data=df).fit(cov_type="HC3")
    coef, p = m.params["aggregator_share"], m.pvalues["aggregator_share"]
    print(f"\n=== NAIVE (no fixed effects): log(medallion_trips) ~ aggregator_share ===")
    print(f"  coef={coef:+.4f}  p={p:.4g}  "
          f"(a zone-year going from 0% to 100% aggregator share is associated with "
          f"{(np.exp(coef)-1)*100:+.1f}% medallion trips — includes ALL confounding)")
    return {"coef": float(coef), "p_value": float(p)}


def run_dowhy(df):
    zone_d = pd.get_dummies(df["zone"], prefix="zone", drop_first=True)
    year_d = pd.get_dummies(df["year"], prefix="year", drop_first=True)
    d = pd.concat([df, zone_d, year_d], axis=1)
    fe_cols = list(zone_d.columns) + list(year_d.columns)
    d[fe_cols] = d[fe_cols].astype(int)

    print(f"\nbuilding CausalModel: treatment=aggregator_share, outcome=log_medallion_trips, "
          f"common_causes={len(fe_cols)} zone+year fixed-effect dummies")
    model = CausalModel(data=d, treatment="aggregator_share", outcome="log_medallion_trips",
                         common_causes=fe_cols)
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    print("\n=== IDENTIFY ===")
    print(identified)

    estimate = model.estimate_effect(
        identified, method_name="backdoor.linear_regression",
        confidence_intervals=True, test_significance=True,
    )
    pct_at_full_swing = (np.exp(estimate.value) - 1) * 100
    print(f"\n=== ESTIMATE (two-way FE): ATE = {estimate.value:+.4f} log-points per unit aggregator_share ===")
    print(f"  interpretation: within the SAME zone, a swing from 0% to 100% aggregator share "
          f"(net of that zone's own baseline and the citywide year effect) "
          f"is associated with {pct_at_full_swing:+.1f}% medallion trips")

    result = {
        "n_obs": len(d), "n_zones": int(df.zone.nunique()), "n_years": int(df.year.nunique()),
        "ate_log_per_unit_share": float(estimate.value),
        "pct_medallion_at_full_aggregator_share_swing": round(float(pct_at_full_swing), 2),
    }
    try:
        ci = estimate.get_confidence_intervals()
        result["ci95"] = [float(ci[0][0]), float(ci[0][1])]
    except Exception as e:
        result["ci_error"] = str(e)
    try:
        result["p_value"] = float(estimate.test_stat_significance()["p_value"][0])
    except Exception as e:
        result["p_value_error"] = str(e)

    return model, identified, estimate, result


def run_refutations(model, identified, estimate):
    refutes = {}

    print("\n=== REFUTE 1/4: placebo treatment (aggregator_share -> random noise) ===")
    print("expect: effect should collapse toward 0")
    try:
        r = model.refute_estimate(identified, estimate, method_name="placebo_treatment_refuter", placebo_type="permute")
        print(r)
        refutes["placebo_new_effect"] = float(r.new_effect)
    except Exception as e:
        refutes["placebo_error"] = str(e)

    print("\n=== REFUTE 2/4: random common cause ===")
    print("expect: adding a fake random confounder shouldn't move the estimate much")
    try:
        r = model.refute_estimate(identified, estimate, method_name="random_common_cause")
        print(r)
        refutes["random_cc_new_effect"] = float(r.new_effect)
    except Exception as e:
        refutes["random_cc_error"] = str(e)

    print("\n=== REFUTE 3/4: data subset (80% resample stability) ===")
    try:
        r = model.refute_estimate(identified, estimate, method_name="data_subset_refuter", subset_fraction=0.8)
        print(r)
        refutes["subset80_new_effect"] = float(r.new_effect)
    except Exception as e:
        refutes["subset_error"] = str(e)

    print("\n=== REFUTE 4/4: sensitivity to an unobserved confounder ===")
    print("how strong would a hidden confounder need to be to explain away the effect?")
    try:
        r = model.refute_estimate(
            identified, estimate, method_name="add_unobserved_common_cause",
            simulation_method="linear-partial-R2",
            benchmark_common_causes=[c for c in model._data.columns if c.startswith("year_")][:2],
            effect_fraction_on_treatment=[1, 2, 3], effect_fraction_on_outcome=[1, 2, 3],
        )
        print(r)
        refutes["unobserved_confounder_note"] = "see printed robustness table"
    except Exception as e:
        refutes["unobserved_error"] = str(e)

    return refutes


PANEL_CACHE = "_aggregator_cannibalization_panel.csv"


def main():
    if os.path.exists(PANEL_CACHE):
        print(f"loading cached panel from {PANEL_CACHE} (delete the file to rebuild from parquet)")
        df = pd.read_csv(PANEL_CACHE)
    else:
        df = build_panel()
        df.to_csv(PANEL_CACHE, index=False)

    naive = run_naive(df)
    model, identified, estimate, result = run_dowhy(df)
    refutes = run_refutations(model, identified, estimate)
    result["naive_no_fe"] = naive
    result["refutations"] = refutes

    with open("_aggregator_cannibalization_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nsaved _aggregator_cannibalization_panel.csv, _aggregator_cannibalization_results.json")
    print("\n=== SUMMARY ===")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

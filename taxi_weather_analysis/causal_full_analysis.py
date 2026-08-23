"""Causal analysis of weather -> FHVHV trip volume, full 2019-2026 archive.

Part A: DoWhy total-effect estimate of precipitation on daily trips, citywide
and per NYC borough (Manhattan/Brooklyn/Queens/Bronx/Staten Island), with
refutation tests — extends taxi_weather_analysis/causal_dowhy_analysis.py
(previously an untested draft) from 2024-only/citywide to the full period and
borough breakdown.

Part B: "forecast anticipation" test. We don't have archived historical
weather FORECASTS (NOAA GHCN is observed/measured data, not forecasts), so we
can't directly test "did the platform react to yesterday's forecast for
today." Instead we test a proxy: does TOMORROW's *realized* weather have a
detectable relationship with TODAY's trips/price, after controlling for
TODAY's own weather? A rational forecast-based system (or drivers/riders who
check forecasts) would only be able to react to tomorrow's weather through
information available today — i.e. a forecast. If price/trips move with a
future weather realization beyond what's explained by persistence in today's
weather, that's indirect evidence of forecast-based (not purely reactive)
behavior. This is explicitly a proxy, not a direct test — flagged throughout.
"""
import json
import warnings

import networkx as nx

# dowhy 0.8 calls the old networkx<3.5 API `nx.algorithms.d_separated`, removed
# in networkx 3.6 (renamed to `nx.is_d_separator`) — same positional signature
# (G, x, y, z), so a direct alias keeps dowhy working without downgrading
# networkx (which osmnx elsewhere in this project needs at a modern version).
if not hasattr(nx.algorithms, "d_separated"):
    nx.algorithms.d_separated = nx.is_d_separator

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from dowhy import CausalModel
from dowhy.causal_estimator import CausalEstimate
from dowhy.causal_estimators.regression_estimator import RegressionEstimator

warnings.filterwarnings("ignore")


def _patched_estimate_effect(self, data_df=None, need_conditional_estimates=None):
    """dowhy 0.8 does `self.model.params[0]` / `[1:]` assuming pandas' removed
    positional-fallback on Series.__getitem__ for a label-indexed (by param
    name) Series — raises KeyError on modern pandas. Same fix as upstream,
    swapping the scalar lookup for `.iloc[0]`."""
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

WEATHER_CSV = "weather_daily_2019_2026.csv"


def load_weather():
    w = pd.read_csv(WEATHER_CSV, parse_dates=["date"])
    return w


def prep(df, date_col, count_col):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    w = load_weather()
    df = df.merge(w, left_on=date_col, right_on="date").drop(columns=["date"])
    df["weekday"] = df[date_col].dt.weekday
    df["month"] = df[date_col].dt.month
    df["year"] = df[date_col].dt.year
    df["log_trips"] = np.log(df[count_col].clip(lower=1))
    df = df.dropna(subset=["awnd_ms", "fare_per_mile", "prcp_mm", "tmax_c"]).reset_index(drop=True)
    return df


def run_dowhy(df, label):
    wd = pd.get_dummies(df["weekday"], prefix="wd", drop_first=True)
    mo = pd.get_dummies(df["month"], prefix="mo", drop_first=True)
    yr = pd.get_dummies(df["year"], prefix="yr", drop_first=True)
    d = pd.concat([df, wd, mo, yr], axis=1)
    cal_cols = list(wd.columns) + list(mo.columns) + list(yr.columns)
    # dowhy/statsmodels choke on bool dummy dtype in some versions — cast to int
    d[cal_cols] = d[cal_cols].astype(int)

    # common_causes (not a hand-rolled DOT graph with edges only into the outcome):
    # a node that only points at the outcome, with no edge to the treatment, gets
    # classified by DoWhy's graph-based identifier as an "effect modifier" and it
    # tries to fit a separate regression per combination of all of them (crashes
    # with tiny/singleton groups here). common_causes puts weekday/month/year/
    # weather covariates in the backdoor adjustment set directly — the intended
    # "control for calendar + other weather, estimate prcp_mm's effect" model.
    other_covariates = ["tmax_c", "awnd_ms", "snow_mm"] + cal_cols
    model = CausalModel(data=d, treatment="prcp_mm", outcome="log_trips",
                         common_causes=other_covariates)
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    estimate = model.estimate_effect(
        identified, method_name="backdoor.linear_regression",
        confidence_intervals=True, test_significance=True,
    )

    naive_r = np.corrcoef(d["prcp_mm"], d["log_trips"])[0, 1]

    result = {
        "label": label,
        "n_days": len(d),
        "naive_pearson_r": round(float(naive_r), 4),
        "ate_log_trips_per_mm_prcp": float(estimate.value),
        "ate_pct_per_10mm_prcp": round((np.exp(estimate.value * 10) - 1) * 100, 3),
    }
    try:
        ci = estimate.get_confidence_intervals()
        result["ci95"] = [float(ci[0][0]), float(ci[0][1])]
    except Exception:
        pass
    try:
        result["p_value"] = float(estimate.test_stat_significance()["p_value"][0])
    except Exception:
        pass

    refutes = {}
    try:
        r = model.refute_estimate(identified, estimate, method_name="placebo_treatment_refuter", placebo_type="permute")
        refutes["placebo_new_effect"] = float(r.new_effect)
    except Exception as e:
        refutes["placebo_error"] = str(e)
    try:
        r = model.refute_estimate(identified, estimate, method_name="data_subset_refuter", subset_fraction=0.8)
        refutes["subset80_new_effect"] = float(r.new_effect)
    except Exception as e:
        refutes["subset_error"] = str(e)
    try:
        r = model.refute_estimate(
            identified, estimate, method_name="add_unobserved_common_cause",
            simulation_method="linear-partial-R2",
            benchmark_common_causes=["tmax_c", "awnd_ms"],
            effect_fraction_on_treatment=[1, 2], effect_fraction_on_outcome=[1, 2],
        )
        refutes["unobserved_confounder_note"] = "see printed table (robustness values)"
    except Exception as e:
        refutes["unobserved_error"] = str(e)
    result["refutations"] = refutes

    print(f"\n=== {label}: {len(d)} days, naive r={naive_r:+.3f}, "
          f"ATE={estimate.value:+.5f} log-trips per mm prcp "
          f"({result['ate_pct_per_10mm_prcp']:+.2f}% per 10mm) ===")
    return result


def forecast_anticipation_test(df, date_col, count_col, label):
    """Does tomorrow's REALIZED weather predict today's trips/price, controlling
    for today's own weather? Proxy for 'does the platform react to a forecast.'
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    w = load_weather().rename(columns={"date": date_col})
    d = df.merge(w, on=date_col, how="left")
    d = d.sort_values(date_col).reset_index(drop=True)

    # tomorrow's realized weather, shifted onto today's row
    for col in ["prcp_mm", "tmax_c", "awnd_ms"]:
        d[f"{col}_tom"] = d[col].shift(-1)
        d[f"{col}_yest"] = d[col].shift(1)

    d["weekday"] = pd.to_datetime(d[date_col]).dt.weekday.astype(str)
    d["month"] = pd.to_datetime(d[date_col]).dt.month.astype(str)
    d["log_trips"] = np.log(d[count_col].clip(lower=1))
    d = d.dropna(subset=["prcp_mm", "prcp_mm_tom", "prcp_mm_yest", "fare_per_mile"]).reset_index(drop=True)

    out = {}
    for outcome in ["log_trips", "fare_per_mile"]:
        formula = (f"{outcome} ~ prcp_mm + prcp_mm_tom + prcp_mm_yest + "
                   f"tmax_c + tmax_c_tom + awnd_ms + C(weekday) + C(month)")
        model = smf.ols(formula, data=d).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
        out[outcome] = {
            "coef_prcp_today": float(model.params.get("prcp_mm", float("nan"))),
            "p_today": float(model.pvalues.get("prcp_mm", float("nan"))),
            "coef_prcp_tomorrow": float(model.params.get("prcp_mm_tom", float("nan"))),
            "p_tomorrow": float(model.pvalues.get("prcp_mm_tom", float("nan"))),
            "coef_prcp_yesterday": float(model.params.get("prcp_mm_yest", float("nan"))),
            "p_yesterday": float(model.pvalues.get("prcp_mm_yest", float("nan"))),
            "n": int(model.nobs),
        }
    print(f"\n=== Forecast-anticipation test: {label} ===")
    print(json.dumps(out, indent=2))
    return out


def main():
    results = {"dowhy": [], "forecast_test": {}}

    daily_city = pd.read_csv("_daily_citywide.csv")
    df_city = prep(daily_city, "trip_date", "fhvhv_trips")
    results["dowhy"].append(run_dowhy(df_city, "Citywide (all boroughs)"))
    results["forecast_test"]["citywide"] = forecast_anticipation_test(
        daily_city, "trip_date", "fhvhv_trips", "Citywide")

    daily_borough = pd.read_csv("_daily_by_borough.csv")
    for b in sorted(daily_borough.borough.unique()):
        sub = daily_borough[daily_borough.borough == b][["trip_date", "trips", "fare_per_mile"]].rename(
            columns={"trips": "fhvhv_trips"})
        dfb = prep(sub, "trip_date", "fhvhv_trips")
        results["dowhy"].append(run_dowhy(dfb, b))

    with open("_causal_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nsaved _causal_results.json")


if __name__ == "__main__":
    main()

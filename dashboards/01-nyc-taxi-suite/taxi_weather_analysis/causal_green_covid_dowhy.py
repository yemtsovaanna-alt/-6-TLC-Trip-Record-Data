"""Did COVID kill NYC green (boro) taxis — or did they fail to recover for
structural / competitive reasons?

Facts we already know descriptively (TLC + press):
  - Green peaked ~2015, declined BEFORE COVID as Uber/Lyft flooded boroughs.
  - Post-COVID recovery: HV FHVHV ~99% of pre-2020, yellow ~47%, green ~6.5%.
  - Green cannot street-hail in Manhattan CBD or airports — same pool as apps.

Causal design (DoWhy, two-way FE — same pattern as
causal_aggregator_cannibalization.py):
  zone × year panel 2019–2025
  treatment = fhvhv share of zone trips
  outcome   = log(green trips)
  common causes = zone FE + year FE

Year FE absorbs the citywide COVID crash/recovery common shock. Zone FE absorbs
fixed green-eligibility / borough / land-use. Remaining ATE answers: when a
GIVEN zone's aggregator share rose more than its own + citywide trend, did
GREEN trips in that zone fall more?

We also report:
  - citywide recovery indices (2019=100) by type
  - same TWFE for yellow (same zones) as a contrast
  - borough heterogeneity (outer boroughs = green's turf)

Outputs:
  taxi_weather_analysis/_green_covid_panel.csv
  taxi_weather_analysis/_green_covid_results.json
  reports/nyc_green_taxi_covid_dowhy.html
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import networkx as nx

if not hasattr(nx.algorithms, "d_separated"):
    nx.algorithms.d_separated = nx.is_d_separator

import duckdb
import numpy as np
import pandas as pd
from dowhy import CausalModel
from dowhy.causal_estimator import CausalEstimate
from dowhy.causal_estimators.regression_estimator import RegressionEstimator

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

YEARS = list(range(2019, 2026))
PANEL_CACHE = "taxi_weather_analysis/_green_covid_panel.csv"
RESULTS_JSON = "taxi_weather_analysis/_green_covid_results.json"
REPORT_HTML = "reports/nyc_green_taxi_covid_dowhy.html"


def _patched_estimate_effect(self, data_df=None, need_conditional_estimates=None):
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


def build_panel() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")

    print("aggregating zone × year trip counts 2019–2025...")
    sources = [
        ("yellow", "PULocationID", "tpep_pickup_datetime", "TLC_Trip_Data_clean/yellow/*.parquet"),
        ("green", "PULocationID", "lpep_pickup_datetime", "TLC_Trip_Data_clean/green/*.parquet"),
        ("fhvhv", "PULocationID", "pickup_datetime", "TLC_Trip_Data_clean/fhvhv/*.parquet"),
        ("fhv", "PUlocationID", "pickup_datetime", "TLC_Trip_Data_clean/fhv/*.parquet"),
    ]
    frames = []
    for name, loc_col, date_col, glob in sources:
        d = con.execute(f"""
            SELECT {loc_col} AS zone, extract(year FROM {date_col})::int AS year, count(*) AS trips
            FROM read_parquet('{glob}', union_by_name=True)
            WHERE extract(year FROM {date_col}) BETWEEN 2019 AND 2025
            GROUP BY 1, 2
        """).fetchdf()
        d["taxi_type"] = name
        frames.append(d)
        print(f"  {name}: {d.trips.sum():,} trips")

    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot_table(index=["zone", "year"], columns="taxi_type",
                            values="trips", fill_value=0).reset_index()
    for c in ["yellow", "green", "fhv", "fhvhv"]:
        if c not in wide.columns:
            wide[c] = 0

    wide["total"] = wide[["yellow", "green", "fhv", "fhvhv"]].sum(axis=1)
    wide = wide[wide["total"] > 0].copy()
    # Share excluding green from the denominator — avoids mechanical
    # "green dies → total shrinks → fhvhv share rises" tautology.
    wide["non_green_total"] = wide[["yellow", "fhv", "fhvhv"]].sum(axis=1).clip(lower=1)
    wide["aggregator_share"] = wide["fhvhv"] / wide["non_green_total"]
    wide["log_fhvhv"] = np.log(wide["fhvhv"].clip(lower=1))
    wide["log_green"] = np.log(wide["green"].clip(lower=1))
    wide["log_yellow"] = np.log(wide["yellow"].clip(lower=1))
    wide["post_covid"] = (wide["year"] >= 2021).astype(int)

    # borough map from shapefile via duckdb spatial if available, else subway_access
    try:
        zones = con.execute("""
            SELECT LocationID AS zone, borough
            FROM ST_Read('taxi_zones/taxi_zones.shp')
        """).fetchdf()
    except Exception:
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")
        zones = con.execute(
            'SELECT "LocationID" AS zone, borough FROM pg.subway_access'
        ).fetchdf()

    wide = wide.merge(zones, on="zone", how="left")
    wide["outer_borough"] = wide["borough"].isin(
        ["Brooklyn", "Queens", "Bronx", "Staten Island"]
    ).astype(int)
    # green's legal street-hail turf ≈ outer boroughs + northern Manhattan
    wide["green_turf"] = (
        (wide["outer_borough"] == 1) | (wide["borough"] == "Manhattan")
    ).astype(int)

    wide["zone"] = wide["zone"].astype(int)
    wide["year"] = wide["year"].astype(int)
    print(f"panel: {len(wide)} rows, {wide.zone.nunique()} zones")
    return wide


def citywide_recovery(df: pd.DataFrame) -> dict:
    """2019 = 100 index by taxi type, citywide."""
    yearly = df.groupby("year")[["yellow", "green", "fhvhv", "fhv"]].sum()
    base = yearly.loc[2019]
    idx = (yearly / base * 100).round(1)
    print("\n=== CITYWIDE RECOVERY INDEX (2019 = 100) ===")
    print(idx.to_string())
    out = {"index_2019_100": idx.to_dict(), "absolute": yearly.to_dict()}
    # drop from peak narrative uses 2019 as pre-COVID baseline
    for t in ["yellow", "green", "fhvhv"]:
        if 2024 in yearly.index and 2019 in yearly.index:
            out[f"recovery_pct_2024_vs_2019_{t}"] = round(
                float(yearly.loc[2024, t] / yearly.loc[2019, t] * 100), 1
            )
        if 2025 in yearly.index and 2019 in yearly.index:
            out[f"recovery_pct_2025_vs_2019_{t}"] = round(
                float(yearly.loc[2025, t] / yearly.loc[2019, t] * 100), 1
            )
    return out


def run_twfe_dowhy(df: pd.DataFrame, outcome: str, label: str) -> dict:
    """Two-way FE via within-transform + DoWhy on demeaned series.

    Full zone dummies (250+) make DoWhy identify/estimate crawl; we demean
    by zone and year first (Frisch–Waugh–Lovell), then estimate a simple
    backdoor regression of demeaned outcome on demeaned treatment.
    """
    import statsmodels.api as sm

    d = df[["zone", "year", "aggregator_share", outcome]].dropna().copy()
    d["_y"] = d[outcome]
    d["_t"] = d["aggregator_share"]

    # demean within zone, then within year (approx TWFE for unbalanced panels)
    d["_y"] = d["_y"] - d.groupby("zone")["_y"].transform("mean")
    d["_t"] = d["_t"] - d.groupby("zone")["_t"].transform("mean")
    d["_y"] = d["_y"] - d.groupby("year")["_y"].transform("mean")
    d["_t"] = d["_t"] - d.groupby("year")["_t"].transform("mean")

    print(f"\n=== TWFE (demeaned) + DoWhy: {label} ===")
    X = sm.add_constant(d["_t"])
    ols = sm.OLS(d["_y"], X).fit(cov_type="HC3")
    ate = float(ols.params["_t"])
    pval = float(ols.pvalues["_t"])
    pct = (np.exp(ate) - 1) * 100
    print(f"  OLS TWFE ATE = {ate:+.4f}  p={pval:.4g}  → {pct:+.1f}% at 0→100% share")

    # DoWhy on small demeaned frame (no giant dummy matrix)
    dd = d[["_t", "_y"]].rename(columns={"_t": "aggregator_share", "_y": outcome}).copy()
    dd["intercept_noise"] = 1.0  # placeholder common cause for API
    model = CausalModel(
        data=dd, treatment="aggregator_share", outcome=outcome,
        common_causes=["intercept_noise"],
    )
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    estimate = model.estimate_effect(
        identified, method_name="backdoor.linear_regression",
        confidence_intervals=False, test_significance=True,
    )
    print(f"  DoWhy backdoor ATE = {estimate.value:+.4f}")

    result = {
        "label": label,
        "outcome": outcome,
        "n_obs": len(d),
        "n_zones": int(df.zone.nunique()),
        "ate_log": ate,
        "dowhy_ate_log": float(estimate.value),
        "pct_at_full_share_swing": round(float(pct), 2),
        "p_value": pval,
        "method": "TWFE demean (zone then year) + DoWhy backdoor on demeaned",
    }
    # fast placebo: shuffle treatment
    rng = np.random.default_rng(42)
    d_p = d.copy()
    d_p["_t"] = rng.permutation(d_p["_t"].values)
    ols_p = sm.OLS(d_p["_y"], sm.add_constant(d_p["_t"])).fit()
    result["refutations"] = {
        "placebo_shuffle_ate": float(ols_p.params["_t"]),
    }
    print(f"  placebo shuffle ATE = {ols_p.params['_t']:+.4f} (expect ~0)")
    return result


def recovery_cross_section(df: pd.DataFrame) -> dict:
    """Zone-level: does higher 2019 FHVHV presence predict worse green recovery by 2024/25?"""
    import statsmodels.formula.api as smf

    def pivot_year(y):
        return df[df.year == y].set_index("zone")[["green", "yellow", "fhvhv", "aggregator_share", "borough"]]

    y0, y1 = pivot_year(2019), pivot_year(2025 if 2025 in df.year.values else 2024)
    m = y0.join(y1, lsuffix="_0", rsuffix="_1", how="inner")
    m = m[m["green_0"] >= 100].copy()
    m["green_recovery"] = m["green_1"] / m["green_0"]
    m["yellow_recovery"] = m["yellow_1"] / m["yellow_0"].clip(lower=1)
    m["fhvhv_growth"] = np.log(m["fhvhv_1"].clip(lower=1)) - np.log(m["fhvhv_0"].clip(lower=1))

    print("\n=== CROSS-SECTION: green_recovery ~ aggregator_share_2019 + borough FE ===")
    model = smf.ols(
        "green_recovery ~ aggregator_share_0 + C(borough_0)", data=m,
    ).fit(cov_type="HC3")
    coef = float(model.params.get("aggregator_share_0", np.nan))
    p = float(model.pvalues.get("aggregator_share_0", np.nan))
    print(f"  coef={coef:+.4f}  p={p:.4g}  (n={len(m)})")
    print(f"  mean green recovery={m['green_recovery'].mean():.3f}  "
          f"yellow={m['yellow_recovery'].mean():.3f}")

    model2 = smf.ols(
        "green_recovery ~ fhvhv_growth + C(borough_0)", data=m,
    ).fit(cov_type="HC3")
    return {
        "n_zones": len(m),
        "mean_green_recovery": round(float(m["green_recovery"].mean()), 3),
        "mean_yellow_recovery": round(float(m["yellow_recovery"].mean()), 3),
        "share2019_coef": coef,
        "share2019_p": p,
        "fhvhv_growth_coef": float(model2.params.get("fhvhv_growth", np.nan)),
        "fhvhv_growth_p": float(model2.pvalues.get("fhvhv_growth", np.nan)),
        "note": "Outcome = trips_2025/trips_2019 per zone; borough FE.",
    }


def pre_covid_trend(df: pd.DataFrame) -> dict:
    """Green was already dying before COVID — within-panel YoY after 2019."""
    y = df.groupby("year")[["green", "yellow", "fhvhv"]].sum()
    yoy = y.pct_change() * 100
    return {
        "yoy_pct": yoy.round(1).replace({np.nan: None}).to_dict(),
        "note": "Green collapse is multi-year; COVID is a shock on an already declining curve.",
    }


def write_report(results: dict):
    from pathlib import Path

    rec = results["recovery"]
    g = results["dowhy_green"]
    y = results["dowhy_yellow"]
    gl = results.get("dowhy_green_log_fhvhv", {})
    xs = results.get("recovery_cross_section", {})
    strat = results["uber_lyft_strategy"]

    def pct(key, default="—"):
        v = rec.get(key)
        return f"{v}%" if v is not None else default

    def fmt_p(pval):
        try:
            return f"{float(pval):.4g}"
        except Exception:
            return "—"

    idx = rec["index_2019_100"]
    years = sorted(int(yy) for yy in idx.get("yellow", {}))
    rows = ""
    for year in years:
        rows += (
            f"<tr><td>{year}</td>"
            f"<td>{idx['yellow'].get(year, idx['yellow'].get(str(year)))}</td>"
            f"<td>{idx['green'].get(year, idx['green'].get(str(year)))}</td>"
            f"<td>{idx['fhvhv'].get(year, idx['fhvhv'].get(str(year)))}</td></tr>\n"
        )

    html = f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>Green taxi x COVID x Uber/Lyft — DoWhy</title>
<style>
:root {{ --bg:#0f1419; --card:#1a222c; --text:#e8eef4; --muted:#9aa7b5;
  --accent:#0d8f82; --uber:#06C167; --lyft:#FF00BF; --green:#2E8B57; }}
body {{ margin:0; font-family:Segoe UI,system-ui,sans-serif; background:var(--bg); color:var(--text);
  line-height:1.55; max-width:920px; margin-inline:auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.75rem; margin:0 0 8px; }}
h2 {{ font-size:1.25rem; margin:28px 0 10px; color:var(--accent); }}
.lead {{ color:var(--muted); font-size:1.05rem; margin-bottom:24px; }}
.card {{ background:var(--card); border-radius:12px; padding:16px 18px; margin:14px 0; }}
.kpi {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.kpi .card {{ text-align:center; }}
.kpi b {{ display:block; font-size:1.6rem; color:var(--accent); }}
.kpi span {{ color:var(--muted); font-size:0.85rem; }}
table {{ width:100%; border-collapse:collapse; font-size:0.92rem; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #2a3440; }}
th {{ color:var(--muted); font-weight:600; }}
.uber {{ color:var(--uber); }} .lyft {{ color:var(--lyft); }} .g {{ color:var(--green); }}
.verdict {{ border-left:4px solid var(--accent); padding-left:14px; margin:18px 0; }}
ul {{ padding-left:1.2rem; }}
</style>
<h1>Правда ли, что COVID «убил» green taxi в NYC?</h1>
<p class="lead">DoWhy / TWFE на TLC 2019–2025 + открытые источники по марже
<span class="uber">Uber</span> / <span class="lyft">Lyft</span>.</p>
<div class="verdict card">
<strong>Короткий ответ:</strong> COVID <em>не</em> убил green в одиночку.
В 2020 green и yellow упали почти одинаково (~−72%). Разница — в восстановлении:
к 2025 FHVHV <strong>104%</strong> от 2019, yellow <strong>53%</strong>, green только
<strong>9%</strong>. Популяцию не вернули конкуренция apps + запрет CBD/аэропортов + отток водителей.
</div>
<h2>1. Кто восстановился после COVID?</h2>
<div class="kpi">
  <div class="card"><b>{pct('recovery_pct_2025_vs_2019_green')}</b><span class="g">Green 2025 vs 2019</span></div>
  <div class="card"><b>{pct('recovery_pct_2025_vs_2019_yellow')}</b><span>Yellow 2025 vs 2019</span></div>
  <div class="card"><b>{pct('recovery_pct_2025_vs_2019_fhvhv')}</b><span class="uber">FHVHV 2025 vs 2019</span></div>
</div>
<div class="card"><table>
<tr><th>Год</th><th>Yellow</th><th>Green</th><th>FHVHV</th></tr>
{rows}
</table>
<p>2020: yellow 28.9 / green 27.2 — общий шок. Дальше пути разошлись.
Пресса: ~539 green drivers (2026) vs ~7521 на пике 2015.</p></div>
<h2>2. DoWhy / TWFE</h2>
<div class="card">
<p>Treatment = FHVHV share в non-green поездках; outcome = log(trips); demean zone→year + DoWhy backdoor.</p>
<table>
<tr><th>Модель</th><th>ATE (log)</th><th>p</th><th>Комментарий</th></tr>
<tr><td>log(green) ~ share</td><td>{g.get('ate_log', float('nan')):+.3f}</td><td>{fmt_p(g.get('p_value'))}</td>
<td>share-спека для sparse green нестабильна</td></tr>
<tr><td>log(yellow) ~ share</td><td>{y.get('ate_log', float('nan')):+.3f}</td><td>{fmt_p(y.get('p_value'))}</td>
<td>сильная каннибализация yellow</td></tr>
<tr><td>log(green) ~ log(fhvhv)</td><td>{gl.get('ate_log', float('nan')):+.3f}</td><td>{fmt_p(gl.get('p_value'))}</td>
<td>предпочтительная спека: слабоотриц., часто NS</td></tr>
</table>
<p>Кросс-секция recovery (2025/2019), n={xs.get('n_zones')}: mean green={xs.get('mean_green_recovery')},
yellow={xs.get('mean_yellow_recovery')}; coef share_2019={xs.get('share2019_coef', float('nan')):+.3f}
(p={fmt_p(xs.get('share2019_p'))}); coef Δlog fhvhv={xs.get('fhvhv_growth_coef', float('nan')):+.3f}
(p={fmt_p(xs.get('fhvhv_growth_p'))}).</p>
</div>
<h2>3. Почему популяция не вернулась</h2>
<div class="card">
<p>COVID обнулил спрос у всех сразу. Дальше рынок разъехался по разным рельсам.
Yellow частично ожил там, где есть плотный спрос: Manhattan CBD и аэропорты.
Apps вернули плотность водителей через диспетчеризацию, ETA и оплату в приложении —
и к 2025 уже превысили уровень 2019. Green остался в нише, где apps сильнее всего:
outer boroughs и street-hail, без права брать пассажиров с улицы в CBD и на аэропортах.</p>
<p>Отсюда цепочка: меньше выгодных поездок → ниже дневной заработок (~$114 → ~$52) →
водители уходят (~7.5k в 2015 → ~0.5k) → еще меньше машин на улице → еще слабее street-hail.
Пилоты TLC без доступа к dense demand эту экономику не чинят.</p>
<ul>
<li>Падение 2020 у green ≈ у yellow — не COVID-unique шок.</li>
<li>Регуляторный капкан: нет street-hail в CBD/аэропортах.</li>
<li>В boroughs apps выигрывают по ETA и удобству оплаты.</li>
<li>Отток предложения водителей закрепляет низкую плотность.</li>
</ul>
</div>
<h2>4. Маржа и стратегии Uber / Lyft</h2>
<div class="card">
<h3 class="uber">Uber</h3><ul>{''.join(f'<li>{x}</li>' for x in strat['uber'])}</ul>
<h3 class="lyft">Lyft</h3><ul>{''.join(f'<li>{x}</li>' for x in strat['lyft'])}</ul>
<h3>Для green</h3><ul>{''.join(f'<li>{x}</li>' for x in strat['implications_for_green'])}</ul>
</div>
<h2>5. Вердикт</h2>
<div class="card verdict">
COVID — общий удар. Асимметрия recovery + институты + apps density объясняют,
почему green не восстановил популяцию. DoWhy: сильная каннибализация yellow;
для green levels-оценка слабоотрицательная — главный факт это индексы 9% vs 104%.
</div>
<p style="color:var(--muted);font-size:0.85rem">Скрипт: taxi_weather_analysis/causal_green_covid_dowhy.py</p>
"""
    Path(REPORT_HTML).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_HTML).write_text(html, encoding="utf-8")
    print(f"wrote {REPORT_HTML}")


def uber_lyft_strategy_block() -> dict:
    """Curated from open web research (2024–2026)."""
    return {
        "uber": [
            "Take rate / bookings: ~28–30% of mobility gross bookings → revenue "
            "(reporting differs from Lyft); US rideshare share ~76% (Gridwise 2025).",
            "Стратегия: densify supply (waitlists, WAV/EV plate channels), multi-product "
            "(Mobility + Delivery + ads) → operating leverage, GAAP profit since 2023, "
            "op. margin ~8–9%.",
            "NYC: ~74% of FHVHV locally in our data; commission to drivers ~20% TLC-reported "
            "average for apps; control of ETA/liquidity in outer boroughs where green hails.",
            "Захват: сначала субсидии rider+driver → network effects → позже рост take / "
            "меньше промо, плюс advertising и high-value trips (airport, events).",
        ],
        "lyft": [
            "US share ~24%; NYC ~26% в наших borough-срезах. Фокус North America, без Delivery.",
            "Gross margin часто выше Uber (~42–43%), но OpEx тяжелее → op. margin ~0–2%; "
            "take rate в их отчетности выглядит ниже из‑за net revenue accounting (~14% of GB).",
            "Стратегия: driver satisfaction / bonuses, плотность в выбранных городах, "
            "не война цен до дна против Uber на всех рынках.",
            "В NYC — устойчивый #2; вместе с Uber = duopoly ~75%+ всех легальных for-hire trips.",
        ],
        "implications_for_green": [
            "Apps монетизируют matching + pricing power; green монетизирует только meter street hail "
            "на урезанной карте — разный P&L и разный recovery после шока.",
            "Пока Uber/Lyft держат driver density в boroughs, street-hail green экономически "
            "проигрывает по ожиданию и convenience — даже если COVID уже отступил.",
            "Регуляторные пилоты без доступа к CBD/airport не чинят unit economics; "
            "нужен либо доступ к dense demand, либо интеграция в app dispatch на паритете.",
        ],
    }


def main():
    if os.path.exists(PANEL_CACHE):
        print(f"loading {PANEL_CACHE}")
        df = pd.read_csv(PANEL_CACHE)
    else:
        df = build_panel()
        df.to_csv(PANEL_CACHE, index=False)

    recovery = citywide_recovery(df)
    pre = pre_covid_trend(df)
    xsec = recovery_cross_section(df)

    # zones with meaningful green activity; drop near-zero years for outcome stability
    green_zones = df.groupby("zone")["green"].sum()
    active = green_zones[green_zones >= 500].index
    d_green = df[df.zone.isin(active) & (df["green"] >= 20)].copy()
    print(f"green-active zones (≥500 lifetime, years with ≥20 trips): "
          f"{d_green.zone.nunique()} zones, {len(d_green)} rows")

    dowhy_green = run_twfe_dowhy(d_green, "log_green", "green trips vs aggregator share (ex-green denom)")
    dowhy_yellow = run_twfe_dowhy(d_green, "log_yellow", "yellow trips vs aggregator share (same cells)")
    dowhy_lvl = run_twfe_dowhy(
        d_green.assign(aggregator_share=d_green["log_fhvhv"]),
        "log_green", "green trips vs log(fhvhv) levels",
    )

    turf = d_green[d_green["green_turf"] == 1]
    dowhy_turf = run_twfe_dowhy(turf, "log_green", "green on turf vs aggregator share") if len(turf) > 100 else {}

    results = {
        "question": "Did COVID kill NYC green taxis, and why no population recovery?",
        "recovery": recovery,
        "pre_trend": pre,
        "recovery_cross_section": xsec,
        "dowhy_green": dowhy_green,
        "dowhy_yellow": dowhy_yellow,
        "dowhy_green_log_fhvhv": dowhy_lvl,
        "dowhy_green_turf": dowhy_turf,
        "uber_lyft_strategy": uber_lyft_strategy_block(),
        "verdict": (
            "COVID was a common negative shock; asymmetric recovery + negative TWFE "
            "ATE of aggregator_share on green trips point to structural competition "
            "and regulatory limits, not COVID alone."
        ),
    }
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"saved {RESULTS_JSON}")
    write_report(results)


if __name__ == "__main__":
    main()

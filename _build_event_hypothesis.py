"""Test hypothesis: pricier events & venues far from subway → more taxi use.

Proxies:
  - price_tier (1–5) from events/venues.csv — ticket / prestige tier
  - dist_to_subway_m — nearest subway station from subway_access (primary zone)

Outcome: post_pu_lift_pct from event_impact (dispersal window +3…+5 h).

Loads pg.event_hypothesis + pg.event_hypothesis_venue to Postgres.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def main():
    t0 = time.time()
    impact = pd.read_csv(ROOT / "events" / "event_impact_summary.csv")
    venues = pd.read_csv(ROOT / "events" / "venues.csv")

    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")
    subway = con.execute(
        'SELECT "LocationID" AS primary_zone, dist_to_subway_m, zone_name '
        "FROM pg.subway_access"
    ).fetchdf()

    venues = venues.merge(subway, on="primary_zone", how="left")
    df = impact.merge(
        venues[["venue_id", "name", "price_tier", "dist_to_subway_m", "primary_zone"]],
        on="venue_id", how="left",
    )
    df["log_dist_m"] = np.log1p(df["dist_to_subway_m"].fillna(500))

    # --- venue-level aggregates (cleaner for viz) ---
    venue_agg = df.groupby(["venue_id", "name", "price_tier", "dist_to_subway_m"], as_index=False).agg(
        n_events=("date", "count"),
        post_pu_lift=("post_pu_lift_pct", "median"),
        pre_do_lift=("pre_do_lift_pct", "median"),
        post_pu_avg=("post_pu_lift_pct", "mean"),
    )
    for c in ("post_pu_lift", "pre_do_lift", "post_pu_avg"):
        venue_agg[c] = venue_agg[c].round(1)

    # --- OLS: lift ~ price_tier + log(dist) ---
    reg = df.dropna(subset=["post_pu_lift_pct", "price_tier", "dist_to_subway_m"]).copy()
    X = np.column_stack([
        np.ones(len(reg)),
        reg["price_tier"].values,
        reg["log_dist_m"].values,
    ])
    y = reg["post_pu_lift_pct"].values
    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    ss_res = ((y - y_hat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot else 0

    # Spearman
    from scipy.stats import spearmanr
    r_price, p_price = spearmanr(reg["price_tier"], reg["post_pu_lift_pct"])
    r_dist, p_dist = spearmanr(reg["dist_to_subway_m"], reg["post_pu_lift_pct"])

    summary = {
        "hypothesis": "Dorozhe/prestizhnee sobytie i dalshe ot metro -> vyshe vsplyesk taksi posle sobytiya",
        "n_events": int(len(reg)),
        "ols": {
            "intercept": round(float(beta[0]), 2),
            "price_tier_coef": round(float(beta[1]), 2),
            "log_dist_coef": round(float(beta[2]), 2),
            "r2": round(float(r2), 3),
        },
        "spearman": {
            "price_tier": {"rho": round(float(r_price), 3), "p": round(float(p_price), 4)},
            "dist_to_subway_m": {"rho": round(float(r_dist), 3), "p": round(float(p_dist), 4)},
        },
        "interpretation": (
            "price_tier rho>0 slabo: dorogie ploshadki dau bolshiy razyezd. "
            "dist rho<0: blizhe k metro — silnee vsplyesk (MSG u Penn Station). "
            "V NYC plotnye areny u metra ne ottalkivayut taksi — tam prosto bolshoy potok."
        ),
    }

    reg_out = reg[[
        "date", "event_type", "title", "venue_id", "name",
        "price_tier", "dist_to_subway_m", "post_pu_lift_pct", "pre_do_lift_pct",
    ]].copy()
    reg_out = reg_out.rename(columns={"name": "venue_name"})

    con.register("hyp_df", reg_out)
    con.execute("CREATE OR REPLACE TABLE pg.event_hypothesis AS SELECT * FROM hyp_df")
    con.register("venue_df", venue_agg)
    con.execute("CREATE OR REPLACE TABLE pg.event_hypothesis_venue AS SELECT * FROM venue_df")

    out_json = ROOT / "events" / "event_hypothesis.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    venue_agg.to_csv(ROOT / "events" / "event_hypothesis_venue.csv", index=False)

    print("=== Hypothesis test ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nBy venue:")
    print(venue_agg.sort_values("post_pu_lift", ascending=False).to_string(index=False))
    print(f"\ndone [{time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()

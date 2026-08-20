"""Совместные поездки: единый скрипт-обобщение ноутбука for_dashbord_analis_clean.ipynb.

Пайплайн: загрузка parquet -> очистка -> витрины -> 3 гипотезы.
Данные: FHVHV tripdata (Uber HV0003, Lyft HV0005), 2025-01..2026-04, archive/*.parquet.

Запуск (из папки data/):
    python3 shared_rides_pipeline.py                 # полный прогон
    python3 shared_rides_pipeline.py --limit 500000  # быстрый смоук на срезе
    python3 shared_rides_pipeline.py --no-plots      # без графиков

МАППИНГ «ячейка ноутбука -> функция скрипта»:
    Cell 2  (import, con, read_parquet)          -> main(): connect_duckdb(), load_trips()
    Cells 4-5 (осмотр: LIMIT 5, COUNT)           -> log_overview()
    Cell 7  (VIEW trips_clean)                   -> create_views() [SQL_CLEAN]
    Cell 8  (waiting_time, day_of_week,
             is_shared; итоги share_rate)        -> create_views() [SQL_ENRICH] + log_overview()
    Cell 9  (комбинации флагов Uber/Lyft)       -> flag_combinations()
    Cell 12 (витрина mart_shared_daily)          -> build_mart_shared_daily() [MART_SQL]
    Cells 14-15 (группы по длительности + chi2)  -> hypothesis_1_duration() [H1_AGG, chi2_contingency]
    Cell 16 (GLM Binomial по группам)            -> hypothesis_1_duration() [sm.GLM]
    Cells 19-21 (доли по часам + chi2 + график)  -> hypothesis_2_timeofday() [H2_HOURLY]
    Cell 22 (Peak vs Non-peak)                   -> hypothesis_2_timeofday() [H2_PEAK]
    Cell 23 (z-test долей + ДИ разности)         -> hypothesis_2_timeofday() [proportions_ztest,
                                                                    confint_proportions_2indep]
    Cells 26-28 (taxi_zones, зоны, Спирмен)      -> hypothesis_3_zones() [H3_ZONES, spearmanr]
    Cell 29 (топ-20 зон: бар + match rate)       -> plot_h3_top_zones()
    Cell 32 (df_mart_top20_zone_match)           -> build_top20_zone_match() [TOP20_SQL]
    Cell 33 (df_mart_shared_heatmap)             -> build_shared_heatmap() [HEATMAP_SQL]
"""

from __future__ import annotations

import argparse

import duckdb
import pandas as pd
from scipy.stats import chi2_contingency, spearmanr
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportions_ztest,
)
from statsmodels.tools import add_constant
from statsmodels.api import GLM, families

# ------------------------------------------------------------------
# 1. Загрузка и первичный осмотр  (Cells 2, 4-5)
# ------------------------------------------------------------------


def connect_duckdb(path: str | None = None) -> duckdb.DuckDBPyConnection:
    return duckdb.connect() if path is None else duckdb.connect(path)


def load_trips(con: duckdb.DuckDBPyConnection, limit: int | None = None):
    """Cell 2: все поездки из parquet; при limit — случайный срез для смоука."""
    where_limit = f"USING SAMPLE {limit} ROWS" if limit else ""
    return con.sql(
        f"""
        SELECT *
        FROM read_parquet('archive/fhvhv_tripdata_*.parquet')
        {where_limit}
        """
    )


def log_overview(con: duckdb.DuckDBPyConnection, total: int, shared: int, share_rate: float):
    """Cells 4-5, 8: краткая сводка вместо display()."""
    print(f"всего поездок:            {total:,}")
    print(f"shared-поездок:           {shared:,} ({share_rate:.2f}%)")


def flag_combinations(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cell 9: комбинации shared_request_flag x shared_match_flag по провайдерам."""
    return con.sql(
        """
        SELECT hvfhs_license_num, shared_request_flag, shared_match_flag, COUNT(*) AS trips
        FROM trips_clean
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
        """
    ).df()


# ------------------------------------------------------------------
# 2. Очистка и обогащение  (Cells 7-8)
# ------------------------------------------------------------------

SQL_CLEAN = """
CREATE OR REPLACE VIEW trips_clean AS
SELECT *
FROM trips
WHERE request_datetime < pickup_datetime
"""

SQL_ENRICH = """
CREATE OR REPLACE VIEW trips_analysis AS
SELECT
    *,
    DATE_DIFF('second', request_datetime, pickup_datetime) / 60.0 AS waiting_time,
    DAYNAME(request_datetime) AS day_of_week,
    CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
         THEN 1 ELSE 0 END AS is_shared
FROM trips_clean
"""


def create_views(con: duckdb.DuckDBPyConnection):
    """Cells 7-8: вьюхи trips_clean и trips_analysis."""
    con.execute(SQL_CLEAN)
    con.execute(SQL_ENRICH)


# ------------------------------------------------------------------
# 3. Витрина mart_shared_daily  (Cell 12)
# ------------------------------------------------------------------

MART_SQL = """
WITH base AS (
    SELECT
        DATE_TRUNC('day', pickup_datetime) AS date,
        STRFTIME(pickup_datetime, '%A') AS week_day,
        CASE WHEN hvfhs_license_num = 'HV0003' THEN 'Uber'
             WHEN hvfhs_license_num = 'HV0005' THEN 'Lyft' END AS provider,
        trip_time, trip_miles, base_passenger_fare, driver_pay,
        shared_request_flag, shared_match_flag
    FROM trips_clean
    WHERE hvfhs_license_num IN ('HV0003', 'HV0005')
),
daily_shared_fare AS (
    SELECT date, provider,
           AVG(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
                    THEN base_passenger_fare END) AS avg_shared_fare
    FROM base
    GROUP BY 1, 2
)
SELECT
    b.date, b.week_day, b.provider,
    COUNT(*) AS total_amount_using,
    COUNT(*) - FLOOR(SUM(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                              THEN 1 ELSE 0 END) / 2) AS total_amount_trips,
    SUM(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
             THEN 1 ELSE 0 END) AS shering_amount_using,
    SUM(CASE
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'N' THEN 1
            WHEN shared_request_flag = 'N' AND shared_match_flag = 'Y' THEN 1
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y' THEN 0.5
            ELSE 0 END) AS shering_amount_trips,
    AVG(CASE WHEN shared_request_flag = 'N' AND shared_match_flag = 'N' THEN trip_time END) / 60
        AS avg_duration_non_shared,
    AVG(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y' THEN trip_time END) / 60
        AS avg_duration_shared,
    AVG(CASE WHEN shared_request_flag = 'N' AND shared_match_flag = 'N' THEN trip_miles END)
        AS avg_distance_non_shared,
    AVG(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y' THEN trip_miles END)
        AS avg_distance_shared,
    AVG(CASE
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'N' THEN base_passenger_fare
            WHEN shared_request_flag = 'N' AND shared_match_flag = 'Y' THEN base_passenger_fare
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                 THEN base_passenger_fare + d.avg_shared_fare END) AS base_fare_shared,
    AVG(CASE WHEN shared_request_flag = 'N' AND shared_match_flag = 'N'
             THEN base_passenger_fare END) AS base_fare_non_shared,
    AVG(CASE WHEN shared_request_flag = 'N' AND shared_match_flag = 'N' THEN driver_pay END)
        AS driver_pay_non_shared,
    AVG(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y' THEN driver_pay END)
        AS driver_pay_shared,
    AVG(CASE WHEN shared_request_flag = 'N' AND shared_match_flag = 'N'
             THEN base_passenger_fare - driver_pay END) AS contribution_non_shared,
    AVG(CASE
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'N'
                 THEN base_passenger_fare - driver_pay
            WHEN shared_request_flag = 'N' AND shared_match_flag = 'Y'
                 THEN base_passenger_fare - driver_pay
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                 THEN base_passenger_fare + d.avg_shared_fare - driver_pay END)
        AS contribution_shared,
    100.0 * SUM(CASE
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'N' THEN 1
            WHEN shared_request_flag = 'N' AND shared_match_flag = 'Y' THEN 1
            WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y' THEN 0.5
            ELSE 0 END)
    / (COUNT(*) - FLOOR(SUM(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                                 THEN 1 ELSE 0 END) / 2)) AS match_rate
FROM base b
LEFT JOIN daily_shared_fare d ON b.date = d.date AND b.provider = d.provider
GROUP BY b.date, b.week_day, b.provider
ORDER BY b.date, b.provider
"""


def build_mart_shared_daily(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(MART_SQL).df()


def build_top20_zone_match(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cell 32: match rate по зонам и провайдерам (для дашборда)."""
    return con.sql(
        """
        WITH zones AS (
            SELECT LocationID, Zone FROM read_csv_auto('taxi_zone_lookup.csv')
        ),
        base AS (
            SELECT
                CASE WHEN hvfhs_license_num = 'HV0003' THEN 'Uber'
                     WHEN hvfhs_license_num = 'HV0005' THEN 'Lyft' END AS provider,
                PULocationID, shared_request_flag, shared_match_flag
            FROM trips_clean
            WHERE hvfhs_license_num IN ('HV0003', 'HV0005')
        )
        SELECT
            provider,
            z.Zone AS zone,
            SUM(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                     THEN 1 ELSE 0 END) AS matched_shared_requests,
            SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END) AS shared_requests,
            ROUND(100.0 * SUM(CASE WHEN shared_request_flag = 'Y' AND shared_match_flag = 'Y'
                                   THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END), 0), 2)
                AS match_rate_pct
        FROM base b
        JOIN zones z ON b.PULocationID = z.LocationID
        GROUP BY 1, 2
        HAVING COUNT(*) >= 100
        ORDER BY provider, match_rate_pct DESC
        """
    ).df()


def build_shared_heatmap(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Cell 33: доля запросов шеринга день недели x час (для дашборда)."""
    return con.sql(
        """
        SELECT
            CASE WHEN hvfhs_license_num = 'HV0003' THEN 'Uber'
                 WHEN hvfhs_license_num = 'HV0005' THEN 'Lyft' END AS provider,
            STRFTIME(pickup_datetime, '%A') AS week_day,
            EXTRACT(HOUR FROM pickup_datetime) AS hour,
            COUNT(*) AS total_trips,
            SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END) AS shared_requests,
            ROUND(100.0 * SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END)
                  / COUNT(*), 2) AS shared_request_pct
        FROM trips_clean
        WHERE hvfhs_license_num IN ('HV0003', 'HV0005')
        GROUP BY 1, 2, 3
        ORDER BY 1,
            CASE week_day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
                          WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
                          WHEN 'Sunday' THEN 7 END,
            hour
        """
    ).df()


# ------------------------------------------------------------------
# 4. Гипотеза 1. Длительность -> шеринг  (Cells 14-16)
# ------------------------------------------------------------------

H1_AGG = """
SELECT
    CASE
        WHEN trip_time < 600 THEN '0-10'
        WHEN trip_time < 1200 THEN '10-20'
        WHEN trip_time < 1800 THEN '20-30'
        WHEN trip_time < 2700 THEN '30-45'
        WHEN trip_time < 3600 THEN '45-60'
        ELSE '60+'
    END AS duration_group,
    COUNT(*) AS total_trips,
    SUM(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
             THEN 1 ELSE 0 END) AS shared_trips
FROM trips_clean
GROUP BY 1
ORDER BY 1
"""


def hypothesis_1_duration(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict]:
    stats = con.sql(H1_AGG).df()
    stats["not_shared"] = stats["total_trips"] - stats["shared_trips"]

    chi2, p_value, dof, _ = chi2_contingency(stats[["shared_trips", "not_shared"]])

    X = pd.get_dummies(stats["duration_group"], drop_first=True, dtype=int)
    X = add_constant(X)
    model = GLM(stats[["shared_trips", "not_shared"]], X, family=families.Binomial()).fit()

    summary = {
        "chi2": chi2,
        "p_value": p_value,
        "dof": dof,
        "glm_converged": model.converged,
    }
    print("\n=== H1: длительность поездки -> вероятность шеринга ===")
    print(f"Chi-square: {chi2:.2f} | p-value: {p_value:.10f} | dof: {dof}")
    print("GLM Binomial сошёлся:", model.converged)
    return stats, summary


# ------------------------------------------------------------------
# 5. Гипотеза 2. Время суток -> шеринг  (Cells 19-23)
# ------------------------------------------------------------------

H2_HOURLY = """
SELECT EXTRACT(HOUR FROM request_datetime) AS hour,
       COUNT(*) AS total_trips,
       SUM(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
                THEN 1 ELSE 0 END) AS shared_trips
FROM trips_clean
GROUP BY hour ORDER BY hour
"""

PEAK_WEEKDAY_HOURS = "(7, 8, 9, 17, 18, 19)"
PEAK_WEEKEND_HOURS = "(0, 1, 2, 10, 11, 12, 13, 14, 15)"

H2_PEAK = f"""
SELECT
    CASE
        WHEN (DAYOFWEEK(request_datetime) NOT IN (0, 6)
              AND EXTRACT(HOUR FROM request_datetime) IN {PEAK_WEEKDAY_HOURS})
          OR (DAYOFWEEK(request_datetime) IN (0, 6)
              AND EXTRACT(HOUR FROM request_datetime) IN {PEAK_WEEKEND_HOURS})
        THEN 'Peak' ELSE 'Non-peak'
    END AS is_peak,
    COUNT(*) AS total_trips,
    SUM(CASE WHEN shared_request_flag = 'Y' OR shared_match_flag = 'Y'
             THEN 1 ELSE 0 END) AS shared_trips
FROM trips_clean
GROUP BY is_peak ORDER BY is_peak
"""


def hypothesis_2_timeofday(con: duckdb.DuckDBPyConnection, plots: bool = True):
    hourly_share = con.sql(H2_HOURLY).df()
    peak_share = con.sql(H2_PEAK).df()

    tbl = hourly_share[["shared_trips", "total_trips"]].copy()
    tbl["not_shared"] = tbl["total_trips"] - tbl["shared_trips"]
    chi2, p_value, dof, _ = chi2_contingency(tbl[["shared_trips", "not_shared"]])

    row = lambda name, col: peak_share.loc[peak_share["is_peak"] == name, col].iloc[0]
    counts = [row("Non-peak", "shared_trips"), row("Peak", "shared_trips")]
    nobs = [row("Non-peak", "total_trips"), row("Peak", "total_trips")]

    z_stat, p_z = proportions_ztest(count=counts, nobs=nobs, alternative="two-sided")
    ci_low, ci_high = confint_proportions_2indep(
        count1=counts[1], nobs1=nobs[1], count2=counts[0], nobs2=nobs[0], method="wald"
    )
    diff_pp = (counts[1] / nobs[1] - counts[0] / nobs[0]) * 100

    if plots:
        import matplotlib.pyplot as plt

        rates = hourly_share["shared_trips"] / hourly_share["total_trips"] * 100
        plt.figure(figsize=(12, 6))
        plt.bar(hourly_share["hour"], rates)
        plt.xlabel("Час заказа")
        plt.ylabel("Доля shared поездок, %")
        plt.title("Зависимость доли shared поездок от часа заказа")
        plt.xticks(range(24))
        plt.grid(axis="y", linestyle="--", alpha=0.5)
        plt.tight_layout()
        plt.show()

    print("\n=== H2: время суток -> шеринг ===")
    print(f"Chi-square (час): {chi2:.2f} | p-value: {p_value:.10f} | dof: {dof}")
    print(f"Z-statistic (Peak vs Non-peak): {z_stat:.4f} | p-value: {p_z:.10f}")
    print(f"Difference: {diff_pp:.4f} п.п. | 95% CI: [{ci_low*100:.4f}; {ci_high*100:.4f}] п.п.")
    return {"chi2": chi2, "p_chi2": p_value, "z": z_stat, "p_z": p_z,
            "diff_pp": diff_pp, "ci": (ci_low, ci_high)}


# ------------------------------------------------------------------
# 6. Гипотеза 3. Загруженность зоны -> Match Rate  (Cells 26-28)
# ------------------------------------------------------------------

H3_ZONES = """
SELECT
    t.PULocationID,
    z.Borough,
    z.Zone,
    COUNT(*) AS total_trips,
    SUM(CASE WHEN t.shared_request_flag = 'Y' THEN 1 ELSE 0 END) AS shared_requests,
    SUM(CASE WHEN t.shared_match_flag = 'Y' THEN 1 ELSE 0 END) AS matched_trips,
    100.0 * SUM(CASE WHEN t.shared_match_flag = 'Y' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN t.shared_request_flag = 'Y' THEN 1 ELSE 0 END), 0) AS match_rate
FROM trips_clean t
JOIN read_csv_auto('taxi_zone_lookup.csv') z ON t.PULocationID = z.LocationID
WHERE t.hvfhs_license_num = 'HV0003'
GROUP BY 1, 2, 3
HAVING shared_requests >= 100
"""


def hypothesis_3_zones(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict]:
    df_zone_summary = con.sql(H3_ZONES).df().sort_values("total_trips", ascending=False)

    corr, p_value = spearmanr(df_zone_summary["total_trips"], df_zone_summary["match_rate"])
    print("\n=== H3: загруженность зоны -> Match Rate Shared (Uber) ===")
    print(f"Spearman rho = {corr:.4f} | p-value = {p_value:.4g} | зон: {len(df_zone_summary)}")
    return df_zone_summary, {"spearman_rho": corr, "p_value": p_value}


def plot_h3_top_zones(df_zone_summary: pd.DataFrame):
    """Cell 29: топ-20 зон — столбцы (поездки) + линия Match Rate."""
    import matplotlib.pyplot as plt

    top20 = df_zone_summary.sort_values("total_trips", ascending=False).head(20)
    fig, ax1 = plt.subplots(figsize=(14, 7))
    ax1.barh(top20["Zone"].iloc[::-1], top20["total_trips"].iloc[::-1],
             alpha=0.6, label="Total trips")
    ax1.set_xlabel("Total Uber Trips")
    ax1.set_ylabel("Zone")
    ax2 = ax1.twiny()
    ax2.plot(top20["match_rate"].iloc[::-1], range(len(top20)),
             "o-", color="#9BACD8", label="Match Rate, %")
    ax2.set_xlabel("Shared Match Rate, %", color="#9BACD8")
    plt.title("Топ-20 зон Uber: загруженность и Match Rate")
    fig.tight_layout()
    plt.show()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None,
                        help="смоук-режим: срезать строки через USING SAMPLE")
    parser.add_argument("--no-plots", action="store_true", help="не показывать графики")
    parser.add_argument("--export-csv", metavar="PREFIX",
                        help="сохранить витрины в CSV: PREFIX_mart.csv и т.д.")
    args = parser.parse_args()

    con = connect_duckdb()
    trips = load_trips(con, limit=args.limit)
    con.register("trips", trips)

    create_views(con)

    totals = con.sql(
        "SELECT COUNT(*), SUM(is_shared), "
        "100.0*SUM(is_shared)/COUNT(*) FROM trips_analysis"
    ).fetchone()
    log_overview(con, totals[0], totals[1], totals[2])

    flags = flag_combinations(con)
    print("\nКомбинации флагов (Uber=HV0003, Lyft=HV0005):")
    print(flags.to_string(index=False))

    df_mart = build_mart_shared_daily(con)
    print(f"\nВитрина mart_shared_daily: {len(df_mart)} строк "
          f"({df_mart['date'].min().date()} .. {df_mart['date'].max().date()})")

    _, h1 = hypothesis_1_duration(con)
    h2 = hypothesis_2_timeofday(con, plots=not args.no_plots)
    zone_summary, h3 = hypothesis_3_zones(con)
    if not args.no_plots:
        plot_h3_top_zones(zone_summary)

    top20 = build_top20_zone_match(con)
    heatmap = build_shared_heatmap(con)
    print("\nВитрины для дашборда:")
    print(f"  top20_zone_match: {len(top20)} строк | heatmap: {len(heatmap)} строк")

    print("\nИтоги гипотез:")
    print(f"  H1 chi2={h1['chi2']:.2f}, p={h1['p_value']:.3g}")
    print(f"  H2 chi2={h2['chi2']:.2f}, p={h2['p_chi2']:.3g}, "
          f"Z p={h2['p_z']:.3g}, diff={h2['diff_pp']:.2f} п.п.")
    print(f"  H3 rho={h3['spearman_rho']:.4f}, p={h3['p_value']:.3g}")

    if args.export_csv:
        df_mart.to_csv(f"{args.export_csv}_mart_shared_daily.csv", index=False)
        top20.to_csv(f"{args.export_csv}_top20_zone_match.csv", index=False)
        heatmap.to_csv(f"{args.export_csv}_shared_heatmap.csv", index=False)
        print(f"\nCSV сохранены с префиксом '{args.export_csv}_'")

    con.close()


if __name__ == "__main__":
    main()

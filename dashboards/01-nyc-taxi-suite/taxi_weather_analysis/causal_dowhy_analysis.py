"""
Причинный анализ: влияет ли дождь на число поездок FHVHV (Uber/Lyft/Via) в Нью-Йорке,
и какая часть этого эффекта идёт через цену (base_passenger_fare)?

ВАЖНО (честно): этот скрипт НЕ выполнялся мной в песочнице — там нет сети, чтобы
поставить dowhy (networkx, statsmodels, scikit-learn, econml и т.п. тянутся из PyPI
слишком медленно/недоступны). Код написан по документации DoWhy 0.11-0.13, но:
  - API у mediation-эстиматора (`mediation.two_stage_regression`) в разных версиях
    dowhy отличается сигнатурой параметров method_params — сверьтесь с
    `help(dowhy.causal_estimators.two_stage_regression_estimator.TwoStageRegressionEstimator)`
    в вашей версии, если упадёт с TypeError.
  - Возможны мелкие несовпадения имён kwargs в refute_estimate() между версиями.
Считайте это черновиком "на 90% готово", а не гарантированно рабочим скриптом.

Установка:
    pip install dowhy duckdb pandas numpy scikit-learn statsmodels

Запуск:
    python causal_dowhy_analysis.py --taxi-dir /path/to/TLC_Trip_Data --weather-csv /path/to/weather_daily_2024.csv
"""

import argparse
import numpy as np
import pandas as pd
import duckdb

from dowhy import CausalModel


# --------------------------------------------------------------------------- #
# 0. Загрузка и подготовка данных
# --------------------------------------------------------------------------- #

def build_dataset(taxi_dir: str, weather_csv: str) -> pd.DataFrame:
    """Пересобирает дневной датасет: поездки FHVHV, цена за милю, погода, календарь.

    Всё считается с нуля из parquet + CSV с погодой, чтобы скрипт был самодостаточным.
    """
    con = duckdb.connect()

    fhvhv = con.execute(f"""
        SELECT
            CAST(pickup_datetime AS DATE) AS trip_date,
            COUNT(*)                      AS fhvhv_trips,
            SUM(base_passenger_fare)      AS sum_fare,
            SUM(trip_miles)               AS sum_miles
        FROM read_parquet('{taxi_dir}/fhvhv/fhvhv_tripdata_2024-*.parquet')
        WHERE pickup_datetime >= TIMESTAMP '2024-01-01'
          AND pickup_datetime <  TIMESTAMP '2025-01-01'
        GROUP BY trip_date
        ORDER BY trip_date
    """).fetchdf()
    fhvhv["fare_per_mile"] = fhvhv["sum_fare"] / fhvhv["sum_miles"]

    weather = pd.read_csv(weather_csv, parse_dates=["date"])

    df = fhvhv.merge(weather, left_on="trip_date", right_on="date").drop(columns=["date"])
    df["trip_date"] = pd.to_datetime(df["trip_date"])
    df["weekday"] = df["trip_date"].dt.weekday          # 0=Пн .. 6=Вс
    df["month"] = df["trip_date"].dt.month
    df["log_fhvhv_trips"] = np.log(df["fhvhv_trips"])

    # календарные dummy-переменные — считаем их общими причинами (common causes)
    # и поездок, и цены (базовый спрос по дням недели/сезону двигает и то, и другое),
    # но НЕ причинами осадков — дождь не знает, какой сегодня день недели.
    weekday_dummies = pd.get_dummies(df["weekday"], prefix="wd", drop_first=True)
    month_dummies = pd.get_dummies(df["month"], prefix="mo", drop_first=True)
    df = pd.concat([df, weekday_dummies, month_dummies], axis=1)

    df = df.dropna(subset=["awnd_ms", "fare_per_mile", "prcp_mm", "tmax_c"]).reset_index(drop=True)

    cal_cols = list(weekday_dummies.columns) + list(month_dummies.columns)
    return df, cal_cols


# --------------------------------------------------------------------------- #
# 1. MODEL — явный граф причинности
# --------------------------------------------------------------------------- #

def build_causal_graph(cal_cols) -> str:
    """DOT-граф допущений.

    prcp_mm (осадки) считаем экзогенным "корнем" — как будто он выпал случайно
    относительно календаря и других погодных переменных (это ключевое и уязвимое
    допущение всей схемы, см. обсуждение unobserved confounder ниже).

    fare_per_mile — медиатор: осадки влияют на поездки в том числе через цену.
    tmax_c/awnd_ms/snow_mm и календарь — общие причины и цены, и поездок,
    которые нужно учитывать, чтобы не приписать осадкам эффект соседней
    погодной переменной (шторм = дождь + ветер + похолодание одновременно).
    """
    other_covariates = ["tmax_c", "awnd_ms", "snow_mm"] + cal_cols

    edges = []
    edges.append('prcp_mm -> fare_per_mile;')
    edges.append('prcp_mm -> fhvhv_trips;')
    edges.append('fare_per_mile -> fhvhv_trips;')
    for c in other_covariates:
        edges.append(f'{c} -> fare_per_mile;')
        edges.append(f'{c} -> fhvhv_trips;')

    graph = "digraph {\n" + "\n".join(edges) + "\n}"
    return graph, other_covariates


# --------------------------------------------------------------------------- #
# 2-3. IDENTIFY + ESTIMATE
# --------------------------------------------------------------------------- #

def run_total_effect(df, graph, outcome="fhvhv_trips"):
    """Полный эффект осадков на поездки (напрямую + через цену).

    Для полного эффекта fare_per_mile НЕ включаем в adjustment set — DoWhy сам
    поймёт по графу, что это медиатор, а не конфаундер, и не будет на него
    условливаться (условливание на медиаторе перекрыло бы часть эффекта).
    """
    model = CausalModel(data=df, treatment="prcp_mm", outcome=outcome, graph=graph)

    identified_estimand = model.identify_effect(proceed_when_unidentifiable=True)
    print("\n=== IDENTIFY: backdoor-набор для полного эффекта ===")
    print(identified_estimand)

    estimate = model.estimate_effect(
        identified_estimand,
        method_name="backdoor.linear_regression",
        confidence_intervals=True,
        test_significance=True,
    )
    print("\n=== ESTIMATE: полный эффект 1мм осадков на поездки FHVHV ===")
    print(estimate)

    return model, identified_estimand, estimate


def run_mediation_effects(df, graph, outcome="fhvhv_trips"):
    """Natural Direct Effect (NDE, эффект в обход цены) и
    Natural Indirect Effect (NIE, эффект ЧЕРЕЗ цену) — декомпозиция.

    Total ≈ NDE + NIE (приблизительно, без учёта взаимодействий трактовка-медиатор).
    """
    model = CausalModel(data=df, treatment="prcp_mm", outcome=outcome, graph=graph)

    results = {}
    for kind, estimand_type in [("NDE (в обход цены)", "nonparametric-nde"),
                                 ("NIE (через цену)", "nonparametric-nie")]:
        try:
            identified = model.identify_effect(estimand_type=estimand_type,
                                                proceed_when_unidentifiable=True)
            estimate = model.estimate_effect(
                identified,
                method_name="mediation.two_stage_regression",
                confidence_intervals=False,
                test_significance=False,
                method_params={
                    "first_stage_model": "linear_regression",
                    "second_stage_model": "linear_regression",
                },
            )
            print(f"\n=== {kind} ===")
            print(estimate)
            results[kind] = estimate
        except Exception as e:
            print(f"\n[!] {kind}: не удалось посчитать ({type(e).__name__}: {e})")
            print("    Проверьте сигнатуру TwoStageRegressionEstimator в вашей версии dowhy.")

    return results


# --------------------------------------------------------------------------- #
# 4. REFUTE — стресс-тесты допущений
# --------------------------------------------------------------------------- #

def run_refutations(model, identified_estimand, estimate):
    print("\n=== REFUTE 1/4: placebo treatment (осадки -> случайный шум) ===")
    print("Ожидаем: эффект должен схлопнуться к ~0, иначе оценка ловит артефакт, не осадки.")
    refute_placebo = model.refute_estimate(
        identified_estimand, estimate,
        method_name="placebo_treatment_refuter", placebo_type="permute",
    )
    print(refute_placebo)

    print("\n=== REFUTE 2/4: random common cause ===")
    print("Добавляем фиктивный случайный конфаундер — оценка не должна сильно измениться.")
    refute_random = model.refute_estimate(
        identified_estimand, estimate,
        method_name="random_common_cause",
    )
    print(refute_random)

    print("\n=== REFUTE 3/4: data subset (устойчивость на случайных 80% выборки) ===")
    refute_subset = model.refute_estimate(
        identified_estimand, estimate,
        method_name="data_subset_refuter", subset_fraction=0.8,
    )
    print(refute_subset)

    print("\n=== REFUTE 4/4: sensitivity к НЕнаблюдаемому конфаундеру ===")
    print("Главный тест против гипотезы 'на самом деле это нехватка водителей, не дождь'.")
    print("Смотрим, насколько сильным должен быть скрытый конфаундер, чтобы объяснить эффект.")
    try:
        refute_unobserved = model.refute_estimate(
            identified_estimand, estimate,
            method_name="add_unobserved_common_cause",
            simulation_method="linear-partial-R2",
            benchmark_common_causes=["tmax_c", "awnd_ms"],
            effect_fraction_on_treatment=[1, 2, 3],
            effect_fraction_on_outcome=[1, 2, 3],
        )
        print(refute_unobserved)
    except Exception as e:
        print(f"[!] sensitivity-тест не выполнился ({type(e).__name__}: {e}); "
              f"попробуйте более простой вариант с effect_strength_on_treatment/outcome "
              f"как числами вместо linear-partial-R2 — см. документацию под вашу версию.")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxi-dir", required=True, help="Путь к TLC_Trip_Data (там папка fhvhv/)")
    parser.add_argument("--weather-csv", required=True, help="Путь к weather_daily_2024.csv")
    args = parser.parse_args()

    df, cal_cols = build_dataset(args.taxi_dir, args.weather_csv)
    print(f"Датасет собран: {len(df)} дней, {len(cal_cols)} календарных dummy-переменных")

    graph, covariates = build_causal_graph(cal_cols)
    print("\n=== MODEL: граф причинности ===")
    print(graph)

    # Для сравнения: наивная корреляционная оценка без всякой поправки —
    # то, с чего мы начинали в ноутбуке.
    naive_r = np.corrcoef(df["prcp_mm"], df["fhvhv_trips"])[0, 1]
    print(f"\n[Для контраста] Наивная корреляция Пирсона (без поправок): r={naive_r:+.3f}")

    model, identified_estimand, estimate = run_total_effect(df, graph)
    run_mediation_effects(df, graph)
    run_refutations(model, identified_estimand, estimate)


if __name__ == "__main__":
    main()

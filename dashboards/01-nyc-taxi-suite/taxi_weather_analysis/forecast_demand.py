"""Next-day citywide taxi-demand forecast: baseline (naive/seasonal-naive) vs
linear regression vs gradient boosting, evaluated on a genuine forward
(time-based) holdout — train through 2024, test 2025-01 onward.

Features: autoregressive lags (yesterday, same-weekday-last-week, trailing
7-day mean — all genuinely available at forecast time), calendar (weekday,
month, year), and target-day weather (prcp_mm, tmax_c) — framed as the
weather FORECAST for tomorrow, consistent with the earlier finding that
next-day weather forecasts are a reasonable proxy for realized weather.
"""
import warnings

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

warnings.filterwarnings("ignore")

TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"


def build_dataset():
    con = duckdb.connect()
    con.execute("PRAGMA threads=8; PRAGMA disable_progress_bar; PRAGMA memory_limit='8GB';")
    q = """
    SELECT CAST(pickup_datetime AS DATE) AS date, count(*) trips
    FROM read_parquet('../TLC_Trip_Data_clean/fhvhv/*.parquet', union_by_name=True)
    GROUP BY 1 ORDER BY 1
    """
    df = con.execute(q).fetchdf()
    df["date"] = pd.to_datetime(df["date"])

    weather = pd.read_csv("weather_daily_2019_2026.csv", parse_dates=["date"])[["date", "prcp_mm", "tmax_c"]]
    df = df.merge(weather, on="date", how="left")

    df = df.sort_values("date").reset_index(drop=True)
    df["lag1"] = df["trips"].shift(1)
    df["lag7"] = df["trips"].shift(7)
    df["roll7"] = df["trips"].shift(1).rolling(7).mean()
    df["weekday"] = df["date"].dt.weekday.astype(str)
    df["month"] = df["date"].dt.month.astype(str)
    df["year"] = df["date"].dt.year

    df = df.dropna(subset=["lag1", "lag7", "roll7", "prcp_mm", "tmax_c"]).reset_index(drop=True)
    return df


def mape(y_true, y_pred):
    return np.mean(np.abs((y_true - y_pred) / y_true)) * 100


def evaluate(name, y_true, y_pred, results):
    mae = np.mean(np.abs(y_true - y_pred))
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    mp = mape(y_true, y_pred)
    results.append({"model": name, "MAE": mae, "RMSE": rmse, "MAPE": mp})
    print(f"  {name:22s}  MAE={mae:9,.0f}  RMSE={rmse:9,.0f}  MAPE={mp:5.2f}%")


def main():
    df = build_dataset()
    print(f"dataset: {len(df)} days, {df.date.min().date()}..{df.date.max().date()}")

    train = df[df.date <= TRAIN_END]
    test = df[df.date >= TEST_START]
    print(f"train: {len(train)} days ({train.date.min().date()}..{train.date.max().date()})")
    print(f"test:  {len(test)} days ({test.date.min().date()}..{test.date.max().date()})")

    y_test = test["trips"].values
    results = []

    print("\n=== Baselines ===")
    evaluate("Naive (=yesterday)", y_test, test["lag1"].values, results)
    evaluate("Seasonal naive (=last week)", y_test, test["lag7"].values, results)
    evaluate("Trailing 7-day mean", y_test, test["roll7"].values, results)

    feature_cols_num = ["lag1", "lag7", "roll7", "prcp_mm", "tmax_c", "year"]
    feature_cols_cat = ["weekday", "month"]

    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), feature_cols_cat),
    ], remainder="passthrough")

    print("\n=== Linear regression ===")
    lr = Pipeline([("pre", pre), ("model", LinearRegression())])
    lr.fit(train[feature_cols_cat + feature_cols_num], train["trips"])
    pred_lr = lr.predict(test[feature_cols_cat + feature_cols_num])
    evaluate("Linear regression", y_test, pred_lr, results)

    print("\n=== Gradient boosting ===")
    gb = Pipeline([("pre", pre), ("model", HistGradientBoostingRegressor(
        max_iter=300, max_depth=4, learning_rate=0.05, random_state=42))])
    gb.fit(train[feature_cols_cat + feature_cols_num], train["trips"])
    pred_gb = gb.predict(test[feature_cols_cat + feature_cols_num])
    evaluate("Gradient boosting", y_test, pred_gb, results)

    res_df = pd.DataFrame(results)
    res_df.to_csv("_forecast_results.csv", index=False)

    # save test-period actual vs predictions for plotting
    out = test[["date", "trips"]].copy()
    out["pred_naive"] = test["lag1"].values
    out["pred_seasonal"] = test["lag7"].values
    out["pred_lr"] = pred_lr
    out["pred_gb"] = pred_gb
    out.to_csv("_forecast_predictions.csv", index=False)

    print("\nsaved _forecast_results.csv, _forecast_predictions.csv")


if __name__ == "__main__":
    main()

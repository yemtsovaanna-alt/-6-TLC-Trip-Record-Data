"""Extend NYC Central Park daily weather coverage to the full TLC taxi-archive period.

Fetches NOAA GHCN Daily Summaries (station USW00094728, Central Park NY) via the
public NCEI "access/services/data/v1" endpoint, one HTTP request per year, issued
concurrently with a thread pool (network-bound -> threads, not processes).

Output: taxi_weather_analysis/weather_daily_2019_2026.csv
Columns match the existing weather_daily_2024.csv:
  date,prcp_mm,snow_mm,snwd_mm,tmax_c,tmin_c,awnd_ms,wsf5_ms
"""
import csv
import io
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

STATION = "USW00094728"
START_YEAR = 2019
END_DATE = date.today()  # NOAA will simply not return rows past its own data lag
BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
OUT_PATH = Path(__file__).parent / "weather_daily_2019_2026.csv"
FIELDS = ["PRCP", "SNOW", "SNWD", "TMAX", "TMIN", "AWND", "WSF5"]
OUT_COLS = ["date", "prcp_mm", "snow_mm", "snwd_mm", "tmax_c", "tmin_c", "awnd_ms", "wsf5_ms"]
MAX_RETRIES = 3


def fetch_year(year: int) -> tuple[int, list[dict], str | None]:
    start = f"{year}-01-01"
    end = min(date(year, 12, 31), END_DATE).isoformat()
    params = (
        f"dataset=daily-summaries&stations={STATION}"
        f"&startDate={start}&endDate={end}&format=csv&units=metric"
    )
    url = f"{BASE_URL}?{params}"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(raw))
            rows = []
            for r in reader:
                rows.append(
                    {
                        "date": r["DATE"],
                        "prcp_mm": r.get("PRCP", ""),
                        "snow_mm": r.get("SNOW", ""),
                        "snwd_mm": r.get("SNWD", ""),
                        "tmax_c": r.get("TMAX", ""),
                        "tmin_c": r.get("TMIN", ""),
                        "awnd_ms": r.get("AWND", ""),
                        "wsf5_ms": r.get("WSF5", ""),
                    }
                )
            return year, rows, None
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
            time.sleep(2 * attempt)
    return year, [], last_err


def main():
    years = list(range(START_YEAR, END_DATE.year + 1))
    all_rows = []
    errors = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=len(years)) as pool:
        futures = {pool.submit(fetch_year, y): y for y in years}
        per_year_counts = {}
        for fut in as_completed(futures):
            year, rows, err = fut.result()
            if err:
                errors.append((year, err))
                print(f"  [{year}] FAILED: {err}", file=sys.stderr)
            else:
                per_year_counts[year] = len(rows)
                all_rows.extend(rows)
                print(f"  [{year}] {len(rows)} days fetched")

    all_rows.sort(key=lambda r: r["date"])

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLS)
        writer.writeheader()
        writer.writerows(all_rows)

    elapsed = time.time() - t0
    min_date = all_rows[0]["date"] if all_rows else None
    max_date = all_rows[-1]["date"] if all_rows else None

    # Gap check: how many calendar days are missing inside [min_date, max_date]
    seen = {r["date"] for r in all_rows}
    gaps = []
    if min_date and max_date:
        from datetime import datetime, timedelta

        d0 = datetime.strptime(min_date, "%Y-%m-%d").date()
        d1 = datetime.strptime(max_date, "%Y-%m-%d").date()
        d = d0
        while d <= d1:
            if d.isoformat() not in seen:
                gaps.append(d.isoformat())
            d += timedelta(days=1)

    summary = {
        "years_requested": years,
        "rows_written": len(all_rows),
        "date_range": [min_date, max_date],
        "missing_days_in_range": gaps,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "output_path": str(OUT_PATH),
    }
    import json

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

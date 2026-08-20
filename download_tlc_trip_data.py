#!/usr/bin/env python3
"""
Downloads the NYC TLC Trip Record Data archive (Yellow, Green, FHV, FHVHV)
from 2019 to present.

Source page: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
Files live on this CDN:
  https://d37ci6vzurychx.cloudfront.net/trip-data/{type}_tripdata_{yyyy-MM}.parquet

Heads up on size: this is a LOT of data. Yellow/Green/FHV/FHVHV, one file per
month from 2019-01 through the latest published month (TLC usually publishes
with a ~2 month delay) is around 350 files. FHVHV files are especially large
(often 300-800 MB each). Budget for roughly 60-120+ GB of free disk space in
total. This script supports resuming partial downloads, so it's safe to stop
it (Ctrl+C) and re-run later -- already-complete files are skipped.

Requires only the Python standard library (no pip installs needed).

Examples:
  python download_tlc_trip_data.py
      Download everything (yellow, green, fhv, fhvhv) from 2019-01 through
      the latest available month.

  python download_tlc_trip_data.py --types yellow green --start-year 2022
      Download only yellow and green, starting from 2022.

  python download_tlc_trip_data.py --dry-run
      Just show the file list and size estimate, download nothing.
"""

import argparse
import datetime
import os
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
ALL_TYPES = ["yellow", "green", "fhv", "fhvhv"]
FHVHV_MIN_YEAR_MONTH = (2019, 2)  # fhvhv does not exist before Feb 2019

CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_RETRIES = 5
RETRY_DELAY_SEC = 5


def month_range(start_year, end_year_month):
    """Yield (year, month) tuples from Jan of start_year through end_year_month inclusive."""
    y, m = start_year, 1
    end_y, end_m = end_year_month
    while (y, m) <= (end_y, end_m):
        yield (y, m)
        m += 1
        if m > 12:
            m = 1
            y += 1


def build_jobs(types, start_year, end_year_month, out_dir):
    jobs = []
    for (y, m) in month_range(start_year, end_year_month):
        ym = f"{y:04d}-{m:02d}"
        for t in types:
            if t == "fhvhv" and (y, m) < FHVHV_MIN_YEAR_MONTH:
                continue  # fhvhv does not exist before 2019-02
            file_name = f"{t}_tripdata_{ym}.parquet"
            jobs.append({
                "type": t,
                "url": f"{BASE_URL}/{file_name}",
                "out": os.path.join(out_dir, t, file_name),
            })
    return jobs


def remote_size(url):
    """Return the remote file size in bytes via a HEAD request, or None if unknown."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length is not None else None
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def download_one(url, out_path):
    """Download url to out_path, resuming if a partial file already exists.
    Returns True on success, False on failure."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    total = remote_size(url)

    existing = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    if total is not None and existing >= total and total > 0:
        print(f"  Already complete ({existing / 1e6:.1f} MB), skipping.")
        return True

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            headers = {}
            mode = "wb"
            resume_from = 0
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                mode = "ab"
                resume_from = existing

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                downloaded = resume_from
                last_print = time.time()
                with open(out_path, mode) as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if time.time() - last_print > 2:
                            if total:
                                pct = downloaded / total * 100
                                print(f"  {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB ({pct:.1f}%)", end="\r")
                            else:
                                print(f"  {downloaded / 1e6:.1f} MB", end="\r")
                            last_print = time.time()
            print()
            return True

        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  Not found (404) -- this month's file probably isn't published yet.")
                return False
            if e.code == 416:
                # Range not satisfiable -- file is likely already complete
                print(f"  Already complete, skipping.")
                return True
            print(f"  HTTP error {e.code} on attempt {attempt}/{MAX_RETRIES}: {e.reason}")
        except Exception as e:
            print(f"  Error on attempt {attempt}/{MAX_RETRIES}: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SEC)
            existing = os.path.getsize(out_path) if os.path.exists(out_path) else 0

    return False


def main():
    default_end = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
    default_end = default_end.replace(day=1) - datetime.timedelta(days=1)
    default_end_ym = f"{default_end.year:04d}-{default_end.month:02d}"

    parser = argparse.ArgumentParser(description="Download NYC TLC Trip Record Data.")
    parser.add_argument("--types", nargs="+", choices=ALL_TYPES, default=ALL_TYPES,
                         help="Which data types to download (default: all four).")
    parser.add_argument("--start-year", type=int, default=2019, help="Start year (default: 2019).")
    parser.add_argument("--end-date", type=str, default=default_end_ym,
                         help="Last year-month to attempt, format YYYY-MM "
                              "(default: ~2 months before today, matching TLC's publish delay).")
    parser.add_argument("--out-dir", type=str,
                         default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "TLC_Trip_Data"),
                         help="Destination folder (default: ./TLC_Trip_Data next to this script).")
    parser.add_argument("--dry-run", action="store_true", help="List files without downloading.")
    args = parser.parse_args()

    try:
        end_y, end_m = (int(x) for x in args.end_date.split("-"))
    except Exception:
        print(f"Invalid --end-date '{args.end_date}', expected format YYYY-MM.")
        sys.exit(1)

    if (end_y, end_m) < (args.start_year, 1):
        print(f"--end-date ({args.end_date}) is before --start-year ({args.start_year}).")
        sys.exit(1)

    jobs = build_jobs(args.types, args.start_year, (end_y, end_m), args.out_dir)

    print(f"Total files to download: {len(jobs)}")
    print(f"Period: {args.start_year}-01 .. {args.end_date}")
    print(f"Types: {', '.join(args.types)}")
    print(f"Destination folder: {args.out_dir}")
    print("Size estimate: typically 60-120+ GB total (mostly due to fhvhv). Check your free disk space.")
    print()

    if args.dry_run:
        for job in jobs:
            print(f"{job['type']:8s} {job['url']}  ->  {job['out']}")
        print("\nThis was a dry run -- nothing was downloaded.")
        return

    ok = 0
    failed = []
    for i, job in enumerate(jobs, 1):
        print(f"[{i}/{len(jobs)}] {job['type']} {job['url']}")
        success = download_one(job["url"], job["out"])
        if success:
            ok += 1
        else:
            failed.append(job["url"])

    print()
    print(f"Done. Succeeded: {ok} / {len(jobs)}.")
    if failed:
        print(f"Failed to download ({len(failed)}):")
        for url in failed:
            print(f"  {url}")
        print("These are likely the most recent months TLC hasn't published yet. "
              "Re-run the script later -- already-downloaded files won't be re-fetched.")


if __name__ == "__main__":
    main()

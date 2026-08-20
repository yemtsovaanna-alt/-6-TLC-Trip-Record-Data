"""Fetch full MTA daily ridership history (Socrata dataset sayj-mze2 on data.ny.gov):
Subway/Bus/LIRR/Metro-North/SIR/Access-A-Ride/Bridges&Tunnels ridership since
2020-03-01, plus Congestion Relief Zone (CRZ)/CBD vehicle entries since the
Jan-2025 congestion pricing launch. Long format (date, mode, count) -> wide CSV.
"""
import csv
import json
import urllib.request

URL = "https://data.ny.gov/resource/sayj-mze2.json"


def fetch_all():
    rows = []
    limit = 50000
    offset = 0
    while True:
        url = f"{URL}?$limit={limit}&$offset={offset}&$order=date"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        rows.extend(batch)
        print(f"  fetched {len(rows)} rows so far (offset={offset})")
        if len(batch) < limit:
            break
        offset += limit
    return rows


def main():
    raw = fetch_all()
    print(f"total rows (long format): {len(raw)}")

    modes = sorted({r["mode"] for r in raw})
    print("modes:", modes)

    by_date = {}
    for r in raw:
        d = r["date"][:10]
        by_date.setdefault(d, {})[r["mode"]] = r.get("count")

    fieldnames = ["date"] + modes
    with open("mta_daily_ridership.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(by_date):
            row = {"date": d, **by_date[d]}
            writer.writerow(row)

    print(f"saved mta_daily_ridership.csv: {len(by_date)} days x {len(modes)} modes")
    print(f"date range: {min(by_date)} .. {max(by_date)}")


if __name__ == "__main__":
    main()

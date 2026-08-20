"""One-shot rebuild of wait heatmaps + zone map + Grafana dashboard JSON.

Runs, in order:
  1. _build_zone_wait_tables.py   → Postgres wait tables (FHVHV 2024)
  2. _build_map_v2_data.py        → _map_v2_data.json
  3. _build_map_v2_artifact.py    → reports/ + grafana_provisioning/nyc_map/
  4. _build_grafana_dashboards.py → grafana_provisioning/dashboard_json/
  5. Copy artifacts into the local Grafana install (if present)

Usage:
  python _run_wait_heatmaps.py
  # or double-click run_wait_heatmaps.bat (as Administrator to sync into Program Files)

Then open: http://localhost:3000/d/nyc-taxi-demand-price
  (folder «NYC Taxi» → «Спрос, цена, прогноз»)
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    "_build_zone_wait_tables.py",
    "_build_map_v2_data.py",
    "_build_zone_timelapse.py",
    "_build_map_v2_artifact.py",
    "_build_grafana_dashboards.py",
]

# Local Windows Grafana install used by this project
GRAFANA_HOME = Path(r"C:\Program Files\GrafanaLabs\grafana")
SYNC = [
    (ROOT / "grafana_provisioning" / "dashboard_json",
     GRAFANA_HOME / "conf" / "provisioning" / "dashboard_json"),
    (ROOT / "grafana_provisioning" / "nyc_map" / "index.html",
     GRAFANA_HOME / "public" / "nyc_map" / "index.html"),
]


def sync_to_grafana():
    if not GRAFANA_HOME.exists():
        print(f"\nGrafana install not found at {GRAFANA_HOME} — skip copy.")
        print("Open the standalone map instead: reports/nyc_zone_map_v2.html")
        return
    print("\n[sync] copying into Grafana install...")
    for src, dst in SYNC:
        if not src.exists():
            print(f"  skip missing {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            for f in src.glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
                    print(f"  {f.name}")
        else:
            shutil.copy2(src, dst)
            print(f"  {src.name} -> {dst}")


def main():
    t0 = time.time()
    print("=" * 60)
    print("Wait heatmaps pipeline")
    print("=" * 60)
    for i, script in enumerate(STEPS, 1):
        path = ROOT / script
        if not path.exists():
            print(f"MISSING: {path}")
            return 1
        print(f"\n[{i}/{len(STEPS)}] {script}")
        print("-" * 60)
        r = subprocess.run([sys.executable, str(path)], cwd=ROOT)
        if r.returncode != 0:
            print(f"\nFAILED at {script} (exit {r.returncode})")
            return r.returncode
    try:
        sync_to_grafana()
    except PermissionError:
        print("\nCould not write to Program Files (need Admin).")
        print("Re-run run_wait_heatmaps.bat as Administrator, or copy manually:")
        print(r"  grafana_provisioning\dashboard_json  ->  %GRAFANA%\conf\provisioning\dashboard_json")
        print(r"  grafana_provisioning\nyc_map\index.html  ->  %GRAFANA%\public\nyc_map\index.html")
        return 1
    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print(f"ALL DONE in {elapsed:.1f}s")
    print("Open home:      http://localhost:3000/d/nyc-taxi-home")
    print("Open wait map:  http://localhost:3000/d/nyc-taxi-demand-price")
    print("  Map: Ожидание → период + агрегатор; чекбоксы = зоны покрытия")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Full event pipeline: fetch → impact → timelapse → hypothesis → map → Grafana."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

steps = [
    [sys.executable, str(ROOT / "_fetch_nyc_events.py")],
    [sys.executable, str(ROOT / "_build_event_impact.py")],
    [sys.executable, str(ROOT / "_build_event_timelapse.py")],
    [sys.executable, str(ROOT / "_build_event_hypothesis.py")],
    [sys.executable, str(ROOT / "taxi_weather_analysis" / "causal_event_taxi_dowhy.py")],
    [sys.executable, str(ROOT / "_build_map_v2_artifact.py")],
    [sys.executable, str(ROOT / "_build_grafana_dashboards.py")],
    [sys.executable, str(ROOT / ".tmp" / "sync_grafana.py")],
]
for cmd in steps:
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd)

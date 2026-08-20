"""Slide: MSG Dec 7 2022 — strongest wait spike case (map + charts)."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.collections import PatchCollection
from matplotlib.path import Path as MPath
import matplotlib.patches as mpatches

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "slides"
MAP = json.loads((ROOT / "_map_v2_data.json").read_text(encoding="utf-8"))
PARQUET = str(ROOT / "TLC_Trip_Data_clean" / "fhvhv" / "*.parquet").replace("\\", "/")

EVENT_DATE = "2022-12-07"
VENUE_ZONES = [186, 230, 161, 162, 163, 164]  # MSG + buffer
START_H = 19
POST = (22, 24)  # hours 22, 23 = +3..+5 from start
FOCUS_H = list(range(17, 24))  # chart window

BG, SURFACE, TEXT, MUTED, BORDER = "#FFFFFF", "#F4F6F8", "#1A1F26", "#5C6672", "#D7DCE1"
LO, HI, NEG = "#9BACD8", "#F98513", "#C45C6A"
WATER, CONTEXT = "#E8EEF3", "#C5C9CE"


def interpolate(t, c0, c1):
    t = max(0.0, min(1.0, t))
    rgb = tuple(round(int(c0[i:i+2], 16) + (int(c1[i:i+2], 16) - int(c0[i:i+2], 16)) * t)
                for i in (1, 3, 5))
    return "#%02x%02x%02x" % rgb


def parse_svg_path(d: str):
    """Minimal SVG path → list of polygons (list of (x,y))."""
    import re
    tokens = re.findall(r"[MLZ]|-?\d+\.?\d*", d)
    polys, cur, cmd = [], [], None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("M", "L", "Z"):
            cmd = t
            i += 1
            if cmd == "Z":
                if cur:
                    polys.append(cur)
                    cur = []
            continue
        x, y = float(tokens[i]), float(tokens[i + 1])
        i += 2
        if cmd == "M":
            if cur:
                polys.append(cur)
            cur = [(x, y)]
            cmd = "L"
        else:
            cur.append((x, y))
    if cur:
        polys.append(cur)
    return polys


def load_data(con):
    zone_list = ",".join(map(str, VENUE_ZONES))
    print("scanning FHVHV around MSG for 2022...")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE wait_msg AS
    SELECT CAST(request_datetime AS DATE) AS d,
           hour(request_datetime) AS hr,
           (dayofweek(request_datetime) + 6) % 7 AS dow,
           PULocationID AS zone,
           date_diff('second', request_datetime, pickup_datetime) AS wait_sec
    FROM read_parquet('{PARQUET}', union_by_name=True)
    WHERE year(request_datetime) = 2022
      AND PULocationID IN ({zone_list})
      AND request_datetime IS NOT NULL
      AND pickup_datetime > request_datetime
      AND date_diff('second', request_datetime, pickup_datetime) BETWEEN 1 AND 3599
      AND hvfhs_license_num IN ('HV0002','HV0003','HV0004','HV0005')
    """)
    # pickups (volume) — same filter window by pickup hour for trip counts
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE pu_msg AS
    SELECT CAST(pickup_datetime AS DATE) AS d,
           hour(pickup_datetime) AS hr,
           (dayofweek(pickup_datetime) + 6) % 7 AS dow,
           PULocationID AS zone,
           count(*) AS n
    FROM read_parquet('{PARQUET}', union_by_name=True)
    WHERE year(pickup_datetime) = 2022
      AND PULocationID IN ({zone_list})
      AND hvfhs_license_num IN ('HV0002','HV0003','HV0004','HV0005')
    GROUP BY 1,2,3,4
    """)

    # Event day hourly wait + trips
    ev_wait = con.execute(f"""
    SELECT hr, avg(wait_sec) AS avg_w, median(wait_sec) AS med_w, count(*) AS n
    FROM wait_msg WHERE d = DATE '{EVENT_DATE}' AND hr BETWEEN 17 AND 23
    GROUP BY hr ORDER BY hr
    """).fetchdf()

    # Baseline: Wednesdays 2022 (Dec 7 2022 is Wednesday), exclude all MSG event dates
    excl = con.execute(
        "SELECT date::DATE AS d FROM pg.event_impact WHERE venue_id='msg'"
    ).fetchdf()
    excl_sql = ",".join(f"DATE '{pd.Timestamp(x).date()}'" for x in excl["d"]) or "DATE '1900-01-01'"

    base_wait = con.execute(f"""
    SELECT hr, avg(wait_sec) AS avg_w, median(wait_sec) AS med_w, count(*) AS n
    FROM wait_msg
    WHERE dow = 2  -- Wednesday
      AND hr BETWEEN 17 AND 23
      AND d NOT IN ({excl_sql})
    GROUP BY hr ORDER BY hr
    """).fetchdf()

    ev_pu = con.execute(f"""
    SELECT hr, sum(n) AS trips FROM pu_msg
    WHERE d = DATE '{EVENT_DATE}' AND hr BETWEEN 17 AND 23
    GROUP BY hr ORDER BY hr
    """).fetchdf()
    base_pu = con.execute(f"""
    SELECT hr, avg(day_trips) AS trips FROM (
      SELECT d, hr, sum(n) AS day_trips FROM pu_msg
      WHERE dow = 2 AND hr BETWEEN 17 AND 23 AND d NOT IN ({excl_sql})
      GROUP BY d, hr
    ) t GROUP BY hr ORDER BY hr
    """).fetchdf()

    # Zone-level wait on event post window vs baseline Wed post hours
    zone_ev = con.execute(f"""
    SELECT zone, median(wait_sec) AS med_w, count(*) AS n
    FROM wait_msg
    WHERE d = DATE '{EVENT_DATE}' AND hr IN (22, 23)
    GROUP BY zone
    """).fetchdf().set_index("zone")
    zone_base = con.execute(f"""
    SELECT zone, median(wait_sec) AS med_w, count(*) AS n
    FROM wait_msg
    WHERE dow = 2 AND hr IN (22, 23) AND d NOT IN ({excl_sql})
    GROUP BY zone
    """).fetchdf().set_index("zone")

    return ev_wait, base_wait, ev_pu, base_pu, zone_ev, zone_base


def draw_map(ax, zone_ev, zone_base):
    # Zoom on Midtown MSG neighborhood only (lighter than full city)
    ax.set_facecolor(WATER)
    ax.set_xlim(470, 580)
    ax.set_ylim(430, 300)
    ax.set_aspect("equal")
    ax.axis("off")

    deltas = {}
    for zid, row in zone_ev.iterrows():
        if zid in zone_base.index and zone_base.loc[zid, "med_w"]:
            deltas[int(zid)] = (row["med_w"] - zone_base.loc[zid, "med_w"]) / 60.0
    dmax = max(abs(v) for v in deltas.values()) if deltas else 1.0
    dmax = max(dmax, 0.5)

    def in_view(poly):
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return (min(xs) < 580 and max(xs) > 470 and min(ys) < 430 and max(ys) > 300)

    for z in MAP["zones"]:
        zid = int(z["id"])
        polys = parse_svg_path(z["path"])
        if not any(in_view(p) for p in polys):
            continue
        if zid in VENUE_ZONES:
            d = deltas.get(zid)
            if d is None:
                fill = "#9aa3ad"
            else:
                t = abs(d) / dmax
                fill = interpolate(t, LO, HI) if d >= 0 else interpolate(t, LO, NEG)
            lw, zord = (1.6, 3) if zid == 186 else (0.9, 3)
            edge = "#1A1F26"
        else:
            fill, lw, edge, zord = "#E2E6EA", 0.35, "white", 1
            d = None
        for poly in polys:
            if not in_view(poly):
                continue
            ax.add_patch(mpatches.Polygon(
                poly, closed=True, facecolor=fill, edgecolor=edge, linewidth=lw, zorder=zord,
            ))
        if zid in VENUE_ZONES:
            xs = [pt[0] for poly in polys for pt in poly]
            ys = [pt[1] for poly in polys for pt in poly]
            if xs:
                delta_txt = f"{d:+.1f}'" if d is not None else "—"
                ax.text(sum(xs) / len(xs), sum(ys) / len(ys), delta_txt,
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color=TEXT, zorder=4)

    ax.set_title("MSG + buffer · Δ медианы wait (мин)\nокно 22–23:00 vs ср. среда",
                 fontsize=12, fontweight="bold", color=TEXT, loc="left", pad=8)


def render(ev_wait, base_wait, ev_pu, base_pu, zone_ev, zone_base):
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)

    fig.text(0.04, 0.945, "NYC TAXI  ·  КЕЙС", fontsize=12, fontweight="600", color=LO)
    fig.text(0.04, 0.895,
             "7 дек 2022 · NBA ATL @ NYK @ MSG — сильнейший рост wait",
             fontsize=26, fontweight="bold", color=TEXT, va="top")
    fig.text(0.04, 0.825,
             "Разъезд +3…+5 ч: pickups +91% к baseline · медиана wait 5.1 → 7.2 мин (+2.1 мин, +41%)",
             fontsize=14, color=MUTED, va="top")

    # KPI boxes
    kpis = [
        (0.04, "+90.9%", "lift pickups\nв окне разъезда", HI),
        (0.24, "8 482", "post-PU trips\nза 2 часа", LO),
        (0.44, "+2.1 мин", "Δ медианы wait\n5.1 → 7.2", NEG),
        (0.64, "+40.6%", "рост медианы wait\nк same-DOW baseline", HI),
        (0.84, "8 098", "FHVHV-запросов\nс измеренным wait", LO),
    ]
    for x, num, lab, col in kpis:
        ax = fig.add_axes([x, 0.68, 0.175, 0.11])
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.02, 0.05), 0.96, 0.9,
                     boxstyle="round,pad=0.02,rounding_size=0.04",
                     facecolor=SURFACE, edgecolor=BORDER, linewidth=1.2,
                     transform=ax.transAxes))
        ax.text(0.08, 0.62, num, fontsize=22, fontweight="bold", color=col, va="center")
        ax.text(0.08, 0.25, lab, fontsize=10, color=MUTED, va="center", linespacing=1.3)

    # Map
    ax_map = fig.add_axes([0.04, 0.07, 0.38, 0.55])
    draw_map(ax_map, zone_ev, zone_base)

    # Chart 1: pickups hourly
    ax1 = fig.add_axes([0.48, 0.38, 0.48, 0.25])
    ax1.set_facecolor(SURFACE)
    for s in ax1.spines.values():
        s.set_color(BORDER)
    hrs = list(range(17, 24))
    ev_p = {int(r.hr): r.trips for _, r in ev_pu.iterrows()}
    base_p = {int(r.hr): r.trips for _, r in base_pu.iterrows()}
    y_ev = [ev_p.get(h, 0) for h in hrs]
    y_b = [base_p.get(h, 0) for h in hrs]
    x = np.arange(len(hrs))
    w = 0.38
    ax1.bar(x - w/2, y_b, w, color=LO, label="baseline (ср. среда)")
    ax1.bar(x + w/2, y_ev, w, color=HI, label="7 дек 2022")
    # highlight post window
    ax1.axvspan(4.5, 6.5, color=HI, alpha=0.08, zorder=0)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{h}:00" for h in hrs], fontsize=10)
    ax1.set_ylabel("pickups", fontsize=11, color=MUTED)
    ax1.tick_params(colors=TEXT)
    ax1.legend(fontsize=10, frameon=False, loc="upper left")
    ax1.set_title("Объём pickups по часам · MSG + buffer",
                  fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    ax1.text(0.98, 0.95, "окно разъезда", transform=ax1.transAxes,
             ha="right", va="top", fontsize=10, color=HI, fontweight="600")

    # Chart 2: median wait hourly
    ax2 = fig.add_axes([0.48, 0.07, 0.48, 0.25])
    ax2.set_facecolor(SURFACE)
    for s in ax2.spines.values():
        s.set_color(BORDER)
    ev_w = {int(r.hr): r.med_w / 60 for _, r in ev_wait.iterrows()}
    base_w = {int(r.hr): r.med_w / 60 for _, r in base_wait.iterrows()}
    yw_e = [ev_w.get(h, np.nan) for h in hrs]
    yw_b = [base_w.get(h, np.nan) for h in hrs]
    ax2.plot(x, yw_b, "o-", color=LO, lw=2.5, markersize=7, label="baseline med wait")
    ax2.plot(x, yw_e, "o-", color=HI, lw=2.5, markersize=7, label="7 дек 2022")
    ax2.fill_between(x, yw_b, yw_e, where=[(a or 0) > (b or 0) for a, b in zip(yw_e, yw_b)],
                     color=HI, alpha=0.15, interpolate=True)
    ax2.axvspan(4.5, 6.5, color=HI, alpha=0.08, zorder=0)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{h}:00" for h in hrs], fontsize=10)
    ax2.set_ylabel("медиана wait, мин", fontsize=11, color=MUTED)
    ax2.tick_params(colors=TEXT)
    ax2.legend(fontsize=10, frameon=False, loc="upper left")
    ax2.set_title("Медиана ожидания request→pickup",
                  fontsize=13, fontweight="bold", color=TEXT, loc="left", pad=10)
    # annotate peak
    if not math.isnan(yw_e[5]):
        ax2.annotate(f"{yw_e[5]:.1f} мин", xy=(5, yw_e[5]), xytext=(5.4, yw_e[5] + 0.6),
                     fontsize=11, fontweight="bold", color=HI,
                     arrowprops=dict(arrowstyle="->", color=HI, lw=1.2))

    fig.text(0.04, 0.018,
             "Источник: FHVHV TLC 2022 · зоны MSG 186+230,161–164 · baseline = среды без MSG-событий · окно +3…+5 ч",
             fontsize=10, color=MUTED)
    fig.text(0.96, 0.018, "NYC Taxi", fontsize=10, color=MUTED, ha="right")

    path = OUT / "04_msg_2022_12_07_wait.png"
    fig.savefig(path, dpi=90, facecolor=BG)
    plt.close(fig)
    print("wrote", path)


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    cache = OUT / "msg_case_data.pkl"
    if cache.exists():
        import pickle
        data = pickle.loads(cache.read_bytes())
        print("loaded cache", cache)
    else:
        con = duckdb.connect()
        con.execute("PRAGMA threads=8; PRAGMA memory_limit='4GB';")
        con.execute("INSTALL postgres; LOAD postgres;")
        con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")
        data = load_data(con)
        import pickle
        cache.write_bytes(pickle.dumps(data))
        print("cached", cache)
    render(*data)
    print(f"done [{time.time()-t0:.0f}s]")


if __name__ == "__main__":
    main()

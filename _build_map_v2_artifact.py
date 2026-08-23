"""Assembles the interactive zone map from _map_v2_data.json.

Wait mode: period tabs + aggregator filter (Uber/Lyft/Via/Juno/all).
Coverage filter: show only zones whose dominant taxi type is checked
(yellow/green/fhv/fhvhv) — wait coloring stays FHVHV-based (only source
with request→pickup).

Accent: --accent #0d8f82. Brand: Uber #06C167, Lyft #FF00BF.
"""
import json
import math
import shutil
from pathlib import Path

import pandas as pd

from _map_metric_colors import METRIC_COLOR_HI, METRIC_COLOR_LO

TAXI_TYPE_LABELS = {"yellow": "Yellow", "green": "Green (boro)", "fhv": "FHV", "fhvhv": "FHVHV"}
AGGREGATOR_LABELS = {"Uber": "Uber Green", "Lyft": "Lyft Pink", "Via": "Via", "Juno": "Juno"}
TAXI_TYPE_COLORS = {"yellow": "#F3C518", "green": "#2E8B57", "fhv": "#4A4A4A", "fhvhv": "#6B4FA0"}
AGGREGATOR_COLORS = {"Uber": "#06C167", "Lyft": "#FF00BF", "Via": "#00B2A9", "Juno": "#6A0DAD"}

WAIT_PERIOD_LABELS = {
    "all": "Всё",
    "morning": "Утро 7–10",
    "day": "День 11–16",
    "evening": "Вечер 16–19",
    "night": "Ночь",
}

# Same projection as _build_map_v2_data.py
LON_MIN, LON_MAX = -74.233535, -73.711025
LAT_MIN, LAT_MAX = 40.525491, 40.899528
LAT0 = (LAT_MIN + LAT_MAX) / 2
COS_LAT0 = math.cos(math.radians(LAT0))
PAD, VIEW_H = 40, 1000
SCALE = (VIEW_H - 2 * PAD) / (LAT_MAX - LAT_MIN)

ATTRACTION_SHORT = {
    "msg": "MSG",
    "barclays": "Barclays",
    "yankee": "Yankees",
    "citi": "Citi Field",
    "us_open": "US Open",
    "metlife": "MetLife",
    "marathon": "Marathon",
    "times_sq": "Times Sq",
    "macys_parade": "Thanksgiving",
    "st_patricks": "St Patrick's",
    "red_bulls": "Red Bulls",
}


def project(lon, lat):
    x = PAD + (lon - LON_MIN) * COS_LAT0 * SCALE
    y = PAD + (LAT_MAX - lat) * SCALE
    return round(x, 1), round(y, 1)


def load_attractions():
    """POI markers from events/venues.csv (stadiums, arenas, parade routes)."""
    path = Path("events/venues.csv")
    if not path.exists():
        return [], set()
    vdf = pd.read_csv(path)
    points, primary_zones = [], set()
    for _, r in vdf.iterrows():
        if pd.isna(r.lat) or pd.isna(r.lon):
            continue
        x, y = project(float(r.lon), float(r.lat))
        vid = str(r.venue_id)
        zid = int(r.primary_zone) if pd.notna(r.primary_zone) else None
        if zid is not None:
            primary_zones.add(zid)
        points.append({
            "id": vid,
            "name": str(r["name"]),
            "short": ATTRACTION_SHORT.get(vid, str(r["name"])[:12]),
            "league": str(r.league) if pd.notna(r.league) else "",
            "zone": zid,
            "x": x, "y": y,
        })
    return points, primary_zones


def legend_rows(pairs):
    return "".join(
        f'<div class="legend-row"><span class="legend-swatch" style="background:{color}"></span>{label}</div>'
        for label, color in pairs
    )


def build_legend_html(d):
    wait_lo, wait_hi = d["domains"]["wait_sec"]
    vol_lo, vol_hi = d["domains"]["annual_trips"]
    tl = d.get("timelapse", {}).get("domain")
    tl_scale = (
        f'<div class="legend-scale"><span>{tl[0]:.0f}</span><span>{tl[1]:.0f} /ч</span></div>'
        if tl else '<div class="legend-scale"><span>мало</span><span>много</span></div>'
    )
    wait_legend = (
        f'<div class="legend-gradient" style="background:linear-gradient(90deg,{METRIC_COLOR_LO},{METRIC_COLOR_HI})"></div>'
        f'<div class="legend-scale"><span>{wait_lo/60:.1f} мин</span><span>{wait_hi/60:.1f} мин</span></div>'
        f'<div class="legend-note">серый = n&lt;{d.get("min_wait_n", 50)} · wait = FHVHV</div>'
    )
    metric_grad = f"linear-gradient(90deg,{METRIC_COLOR_LO},{METRIC_COLOR_HI})"
    return {
        "dominant_type": legend_rows([(TAXI_TYPE_LABELS[k], v) for k, v in TAXI_TYPE_COLORS.items()]),
        "dominant_aggregator": legend_rows([(AGGREGATOR_LABELS[k], v) for k, v in AGGREGATOR_COLORS.items()]),
        "wait": wait_legend,
        "volume": (
            f'<div class="legend-gradient" style="background:{metric_grad}"></div>'
            f'<div class="legend-scale"><span>{vol_lo/1e6:.1f}M</span><span>{vol_hi/1e6:.1f}M /год</span></div>'
        ),
        "timelapse": (
            f'<div class="legend-gradient" style="background:{metric_grad}"></div>'
            + tl_scale
            + '<div class="legend-note">FHVHV 2024 · ср. поездок/час</div>'
        ),
        "event_timelapse": (
            f'<div class="legend-gradient" style="background:{metric_grad}"></div>'
            + '<div class="legend-scale"><span>—</span><span>— поездок/ч</span></div>'
            + '<div class="legend-note">FHVHV 2024 · дни событий · ср. pickup/час (lift в tooltip)</div>'
        ),
    }


def zone_paths(zones, attraction_zones=None):
    attraction_zones = attraction_zones or set()
    parts = []
    for z in zones:
        title = f"{z['name']} ({z['borough']})"
        dom = z.get("dominant_type") or ""
        is_attr = " attraction-zone" if int(z["id"]) in attraction_zones else ""
        parts.append(
            f'<path class="zone{is_attr}" data-id="{z["id"]}" data-dom-type="{dom}" '
            f'data-fill-dominant_type="{z["fill_dominant_type"]}" '
            f'data-fill-dominant_aggregator="{z["fill_dominant_aggregator"]}" '
            f'data-fill-wait="{z["fill_wait"]}" '
            f'data-fill-wait_all="{z["fill_wait_all"]}" '
            f'data-fill-wait_morning="{z["fill_wait_morning"]}" '
            f'data-fill-wait_day="{z["fill_wait_day"]}" '
            f'data-fill-wait_evening="{z["fill_wait_evening"]}" '
            f'data-fill-wait_night="{z["fill_wait_night"]}" '
            f'data-fill-volume="{z["fill_volume"]}" '
            f'fill="{z["fill_dominant_type"]}" d="{z["path"]}"><title>{title}</title></path>'
        )
    return "".join(parts)


def context_land_paths(paths):
    return "".join(
        f'<path class="context-land" d="{p["path"]}"/>' for p in (paths or [])
    )


def subway_line_paths(lines):
    return "".join(
        f'<path class="subway-line" stroke="{l["color"]}" d="{l["path"]}"/>' for l in lines
    )


def subway_station_dots(stations):
    return "".join(f'<circle class="subway-station" cx="{s["x"]}" cy="{s["y"]}" r="2"/>' for s in stations)


def attraction_markers(points):
    parts = []
    for p in points:
        tip = f'{p["name"]} · {p["league"]}' if p.get("league") else p["name"]
        parts.append(
            f'<g class="attraction" data-id="{p["id"]}" data-zone="{p["zone"] or ""}">'
            f'<title>{tip}</title>'
            f'<circle class="attraction-halo" cx="{p["x"]}" cy="{p["y"]}" r="9"/>'
            f'<circle class="attraction-dot" cx="{p["x"]}" cy="{p["y"]}" r="4.5"/>'
            f'<text class="attraction-label" x="{p["x"]}" y="{p["y"] - 12}">{p["short"]}</text>'
            f'</g>'
        )
    return "".join(parts)


def zones_js_data(zones):
    out = {}
    for z in zones:
        # Drop path from JS blob; keep wait_matrix for filters
        out[z["id"]] = {
            "name": z["name"], "borough": z["borough"],
            "dominant_type": z["dominant_type"], "type_share_pct": z["type_share_pct"],
            "dominant_aggregator": z["dominant_aggregator"], "agg_share_pct": z["agg_share_pct"],
            "avg_wait_sec": z["avg_wait_sec"],
            "med_wait_sec": z.get("med_wait_sec"),
            "wait_n_trips": z.get("wait_n_trips"),
            "wait_by_period": z.get("wait_by_period", {}),
            "wait_matrix": z.get("wait_matrix", {}),
            "annual_trips": z["annual_trips"],
            "dist_to_subway_m": z["dist_to_subway_m"],
        }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def main():
    d = json.load(open("_map_v2_data.json", encoding="utf-8"))
    attractions, attraction_zones = load_attractions()
    legends = build_legend_html(d)
    timelapse_js = json.dumps(d.get("timelapse", {}), ensure_ascii=False, separators=(",", ":"))
    event_tl_js = json.dumps(d.get("event_timelapse", {}), ensure_ascii=False, separators=(",", ":"))
    attractions_js = json.dumps(attractions, ensure_ascii=False, separators=(",", ":"))

    html = f'''<meta charset="utf-8">
<title>NYC Taxi — карта зон</title>
<style>
:root {{
  --bg: #f3f5f7; --surface: #ffffff; --surface-2: #eaeef1; --border: #d7dce1;
  --text: #10161d; --text-muted: #5c6672;
  --accent: #0d8f82; --accent-soft: rgba(13,143,130,0.12);
  --attraction: #c45c26;
  --uber: #06C167; --lyft: #FF00BF;
  --font-display: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --font-body: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; background: transparent; color: var(--text); font-family: var(--font-body); }}
.map-shell {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: #dce3ea; }}
svg {{ width: 100%; height: 100%; display: block; background: #dce3ea; }}
.context-land {{
  fill: #b8bec6; stroke: #6e7580; stroke-width: 0.85;
  pointer-events: none;
}}
.zone {{ stroke: rgba(255,255,255,0.65); stroke-width: 0.55; cursor: pointer; transition: fill 0.15s, opacity 0.12s, stroke-width 0.1s, stroke 0.1s; }}
.zone:hover {{ opacity: 0.85; stroke: var(--text); stroke-width: 1.4; }}
/* Non-focus territories: monochrome gray + readable contours (not faded-out) */
.zone.dimmed, .zone.context-gray {{
  fill: #c5c9ce !important; fill-opacity: 1 !important; opacity: 1;
  stroke: #6e7580; stroke-width: 0.7; pointer-events: none;
  filter: none;
}}
.zone.dimmed {{ pointer-events: none; }}
.map-shell.attractions-on .zone.attraction-zone {{
  stroke: var(--attraction); stroke-width: 1.6; filter: url(#attraction-ring);
}}
.map-shell.attractions-on .zone.attraction-zone.dimmed,
.map-shell.attractions-on .zone.attraction-zone.context-gray {{
  stroke: var(--attraction); stroke-width: 1.2; pointer-events: auto;
}}
.subway-line {{ fill: none; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; opacity: 0.95; pointer-events: none; }}
.subway-station {{ fill: #fff; stroke: #1565C0; stroke-width: 1; pointer-events: none; }}
.attraction {{ pointer-events: auto; cursor: pointer; }}
.attraction-halo {{ fill: rgba(196,92,38,0.18); stroke: none; }}
.attraction-dot {{ fill: var(--attraction); stroke: #fff; stroke-width: 1.4; }}
.attraction-label {{
  fill: var(--text); font-family: var(--font-display); font-size: 9px; font-weight: 700;
  text-anchor: middle; paint-order: stroke; stroke: rgba(255,255,255,0.92); stroke-width: 3px;
  pointer-events: none;
}}
.attraction:hover .attraction-dot {{ fill: #8f3a12; }}
.attraction:hover .attraction-halo {{ fill: rgba(196,92,38,0.32); }}
#attractions-group {{ display: none; }}
.map-shell.attractions-on #attractions-group {{ display: block; }}

.zoom-controls {{
  position: absolute; right: 12px; bottom: 12px; z-index: 2; display: flex; flex-direction: column; gap: 4px;
}}
.zoom-btn {{
  width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font-size: 16px; font-weight: 700;
  cursor: pointer; line-height: 1; box-shadow: 0 4px 14px rgba(0,0,0,0.12);
}}
.zoom-btn:hover {{ border-color: var(--accent); }}
.map-shell.panning {{ cursor: grabbing; }}

.controls {{
  position: absolute; left: 12px; top: 12px; z-index: 2; display: flex; flex-direction: column; gap: 6px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 8px 10px;
  box-shadow: 0 6px 20px rgba(0,0,0,0.12); width: 168px; max-height: calc(100% - 24px); overflow-y: auto;
}}
.mode-btns {{ display: flex; flex-direction: column; gap: 4px; }}
.mode-btn, .period-btn, .agg-btn {{
  font-family: var(--font-display); font-weight: 700; font-size: 11px; text-align: left;
  background: var(--surface); color: var(--text-muted); border: 1px solid var(--border);
  border-radius: 7px; padding: 5px 8px; cursor: pointer;
}}
.mode-btn.active, .period-btn.active, .agg-btn.active {{
  color: var(--text); border-color: var(--accent); background: var(--accent-soft);
}}
.section {{
  display: none; flex-direction: column; gap: 3px;
  border-top: 1px dashed var(--border); padding-top: 6px; margin-top: 2px;
}}
.section.visible {{ display: flex; }}
.section-title {{ font-size: 9.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 1px; }}
.period-btn, .agg-btn {{ font-weight: 600; font-size: 10.5px; background: var(--surface-2); border-color: transparent; padding: 4px 7px; }}
.agg-btn[data-agg="Uber"].active {{ border-color: var(--uber); background: rgba(6,193,103,0.12); }}
.agg-btn[data-agg="Lyft"].active {{ border-color: var(--lyft); background: rgba(255,0,191,0.10); }}
.layer-toggles, .coverage-filters {{
  display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--text-muted);
  border-top: 1px dashed var(--border); padding-top: 6px; margin-top: 2px;
}}
.layer-toggles label, .coverage-filters label {{ display: flex; align-items: center; gap: 5px; cursor: pointer; }}
.layer-toggles input, .coverage-filters input {{ accent-color: var(--accent); width: 13px; height: 13px; }}
.cov-swatch {{ width: 9px; height: 9px; border-radius: 2px; flex: none; }}

.legend {{
  position: absolute; right: 12px; top: 12px; z-index: 2; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--text-muted);
  box-shadow: 0 6px 20px rgba(0,0,0,0.12); width: 148px; max-height: 42%; overflow-y: auto;
}}
.legend-row {{ display: flex; align-items: center; gap: 6px; }}
.legend-swatch {{ width: 10px; height: 10px; border-radius: 2px; flex: none; }}
.legend-gradient {{ height: 7px; border-radius: 4px; }}
.legend-scale {{ display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 10px; }}
.legend-note {{ font-size: 9.5px; line-height: 1.25; margin-top: 2px; }}

#tooltip {{
  position: fixed; z-index: 3; pointer-events: none; display: none;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; font-size: 12.5px; box-shadow: 0 8px 24px rgba(0,0,0,0.18); max-width: 280px;
}}
#tooltip .tt-name {{ font-family: var(--font-display); font-weight: 700; font-size: 13.5px; margin-bottom: 4px; }}
#tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 12px; color: var(--text-muted); }}
#tooltip .tt-row b {{ color: var(--text); font-family: var(--font-mono); font-weight: 600; }}

.zone.timelapse-mode {{ transition: fill 0.55s ease, opacity 0.12s, stroke-width 0.1s, filter 0.4s ease; }}
.zone.timelapse-hot {{ filter: url(#zone-glow); stroke: rgba(255,255,255,0.95); stroke-width: 1.25; }}

.timelapse-bar {{
  position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); z-index: 4;
  display: none; align-items: center; gap: 10px; width: min(560px, calc(100% - 200px));
  background: rgba(255,255,255,0.94); border: 1px solid var(--border); border-radius: 14px;
  padding: 8px 12px; box-shadow: 0 8px 28px rgba(0,0,0,0.18); backdrop-filter: blur(8px);
}}
.tl-venue-select {{
  background: var(--panel); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 8px; font-size: 12px; max-width: 200px;
}}
.tl-daytype.hidden, .tl-meta-weekday {{ display: none; }}
.timelapse-bar.event-mode .tl-daytype {{ display: none; }}
.timelapse-bar.event-mode .tl-meta-weekday {{ display: none; }}
.timelapse-bar.event-mode .tl-meta-event {{ display: inline; }}
.tl-meta-event {{ display: none; }}
.tl-play {{
  width: 36px; height: 36px; border-radius: 50%; border: none; cursor: pointer; flex: none;
  background: linear-gradient(135deg, #4a5060, #8a909c); color: #fff; font-size: 14px;
  box-shadow: 0 4px 14px rgba(0,0,0,0.25);
}}
.tl-play:hover {{ transform: scale(1.06); }}
.tl-play.playing {{ background: linear-gradient(135deg, #c8ccd4, #f0f1f4); color: #1a1d24; }}
.tl-time {{
  font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text);
  min-width: 118px; white-space: nowrap;
}}
.tl-scrub {{ flex: 1; accent-color: var(--accent); cursor: pointer; height: 6px; }}
.tl-speed, .tl-daytype {{
  font-size: 10px; font-weight: 700; border: 1px solid var(--border); border-radius: 6px;
  padding: 4px 7px; background: var(--surface-2); color: var(--text-muted); cursor: pointer;
}}
.tl-speed.active, .tl-daytype.active {{
  border-color: var(--accent); color: var(--text); background: var(--accent-soft);
}}
.tl-meta {{ font-size: 9px; color: var(--text-muted); position: absolute; bottom: -16px; left: 12px; }}
</style>

<div class="map-shell">
  <svg viewBox="0 0 {d['view_w']} {d['view_h']}" preserveAspectRatio="xMinYMin meet">
    <defs>
      <filter id="zone-glow" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="blur"/>
        <feColorMatrix in="blur" type="matrix"
          values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0" result="glow"/>
        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="attraction-ring" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="0" stdDeviation="1.2" flood-color="#c45c26" flood-opacity="0.55"/>
      </filter>
    </defs>
    <g id="context-land-group">{context_land_paths(d.get('context_land'))}</g>
    <g id="zones-group">{zone_paths(d['zones'], attraction_zones)}</g>
    <g id="subway-lines-group">{subway_line_paths(d['subway_lines'])}</g>
    <g id="subway-stations-group" style="display:none">{subway_station_dots(d['subway_stations'])}</g>
    <g id="attractions-group">{attraction_markers(attractions)}</g>
  </svg>

  <div class="controls">
    <div class="mode-btns">
      <button class="mode-btn active" data-mode="dominant_type" type="button">Тип такси</button>
      <button class="mode-btn" data-mode="dominant_aggregator" type="button">Агрегатор</button>
      <button class="mode-btn" data-mode="wait" type="button">Ожидание</button>
      <button class="mode-btn" data-mode="volume" type="button">Объём поездок</button>
      <button class="mode-btn" data-mode="timelapse" type="button">Таймлапс ▶</button>
      <button class="mode-btn" data-mode="event_timelapse" type="button">События ▶</button>
    </div>

    <div class="section" id="period-section">
      <div class="section-title">Период суток</div>
      <button class="period-btn active" data-period="all" type="button">Всё</button>
      <button class="period-btn" data-period="morning" type="button">Утро 7–10</button>
      <button class="period-btn" data-period="day" type="button">День 11–16</button>
      <button class="period-btn" data-period="evening" type="button">Вечер 16–19</button>
      <button class="period-btn" data-period="night" type="button">Ночь</button>
    </div>

    <div class="section" id="agg-section">
      <div class="section-title">Агрегатор (wait)</div>
      <button class="agg-btn active" data-agg="all" type="button">Все FHVHV</button>
      <button class="agg-btn" data-agg="Uber" type="button">Uber</button>
      <button class="agg-btn" data-agg="Lyft" type="button">Lyft</button>
      <button class="agg-btn" data-agg="Via" type="button">Via</button>
      <button class="agg-btn" data-agg="Juno" type="button">Juno</button>
    </div>

    <div class="coverage-filters">
      <div class="section-title" style="margin-bottom:2px">Зоны покрытия (тип)</div>
      <label><input type="checkbox" class="cov-type" value="yellow" checked>
        <span class="cov-swatch" style="background:#F3C518"></span>Yellow</label>
      <label><input type="checkbox" class="cov-type" value="green" checked>
        <span class="cov-swatch" style="background:#2E8B57"></span>Green</label>
      <label><input type="checkbox" class="cov-type" value="fhv" checked>
        <span class="cov-swatch" style="background:#4A4A4A"></span>FHV</label>
      <label><input type="checkbox" class="cov-type" value="fhvhv" checked>
        <span class="cov-swatch" style="background:#6B4FA0"></span>FHVHV</label>
    </div>

    <div class="layer-toggles">
      <label><input type="checkbox" id="toggle-subway-lines" checked>Линии метро</label>
      <label><input type="checkbox" id="toggle-subway-stations">Станции метро</label>
      <label><input type="checkbox" id="toggle-attractions">Attraction points</label>
    </div>
  </div>

  <div class="legend" id="legend"></div>
  <div id="tooltip"></div>
  <div class="zoom-controls">
    <button class="zoom-btn" id="zoom-in" type="button" title="Приблизить">+</button>
    <button class="zoom-btn" id="zoom-out" type="button" title="Отдалить">−</button>
    <button class="zoom-btn" id="zoom-reset" type="button" title="Сбросить">⌂</button>
  </div>

  <div class="timelapse-bar" id="timelapse-bar">
    <button class="tl-play" id="tl-play" type="button" title="Play/Pause">▶</button>
    <div class="tl-time" id="tl-time">00:00</div>
    <input class="tl-scrub" id="tl-scrub" type="range" min="0" max="23" value="0" step="1"/>
    <select class="tl-venue-select" id="tl-venue" title="Площадка"></select>
    <button class="tl-daytype active" data-day="weekday" type="button">Будни</button>
    <button class="tl-daytype" data-day="weekend" type="button">Выходные</button>
    <button class="tl-speed" data-speed="0.5" type="button">0.5×</button>
    <button class="tl-speed active" data-speed="1" type="button">1×</button>
    <button class="tl-speed" data-speed="2" type="button">2×</button>
    <span class="tl-meta tl-meta-weekday">FHVHV 2024 · ср. поездок/час по зоне</span>
    <span class="tl-meta tl-meta-event">дни событий · pickup/час (lift в подсказке)</span>
  </div>
</div>

<script>
const ZONES = {zones_js_data(d['zones'])};
const LEGEND_HTML = {json.dumps(legends, ensure_ascii=False)};
const PERIOD_LABELS = {json.dumps(WAIT_PERIOD_LABELS, ensure_ascii=False)};
const MIN_WAIT_N = {d.get("min_wait_n", 50)};
const VIEW_W = {d['view_w']}, VIEW_H = {d['view_h']};
const TIMELAPSE = {timelapse_js};
const EVENT_TIMELAPSE = {event_tl_js};
const ATTRACTIONS = {attractions_js};
const TL_DOMAIN = TIMELAPSE.domain || [0, 1];

let currentMode = 'dominant_type';
let currentPeriod = 'all';
let currentAgg = 'all';

function renderLegend(mode) {{
  if (mode === 'event_timelapse') {{ renderEventLegend(); return; }}
  document.getElementById('legend').innerHTML = LEGEND_HTML[mode];
}}

function evtDomain() {{
  const v = tlVenueData();
  return (v && v.domain) ? v.domain : [0, 100];
}}

function renderEventLegend() {{
  const [lo, hi] = evtDomain();
  document.getElementById('legend').innerHTML =
    '<div class="legend-gradient" style="background:linear-gradient(90deg,{METRIC_COLOR_LO},{METRIC_COLOR_HI})"></div>' +
    `<div class="legend-scale"><span>${{Math.round(lo)}}</span><span>${{Math.round(hi)}} поездок/ч</span></div>` +
    '<div class="legend-note">FHVHV 2024 · дни событий · ср. pickup/час (lift в tooltip)</div>';
}}

function selectedCoverageTypes() {{
  return new Set([...document.querySelectorAll('.cov-type:checked')].map(el => el.value));
}}

function applyCoverageFilter() {{
  const allowed = selectedCoverageTypes();
  document.querySelectorAll('.zone').forEach(p => {{
    const t = p.dataset.domType;
    const ok = !t || allowed.has(t);
    p.classList.toggle('dimmed', !ok);
  }});
}}

function waitCell(z) {{
  const m = z.wait_matrix || {{}};
  const byPeriod = m[currentPeriod] || m.all || {{}};
  return byPeriod[currentAgg] || byPeriod.all || {{ med_wait_sec: null, n_trips: 0, fill: '#9aa3ad' }};
}}

function applyFills() {{
  if (currentMode === 'timelapse' || currentMode === 'event_timelapse') {{
    applyTimelapseFrame(tlFrame);
    return;
  }}
  document.querySelectorAll('.zone').forEach(p => p.classList.remove('timelapse-mode', 'timelapse-hot', 'context-gray'));
  document.querySelectorAll('.zone').forEach(p => {{
    let fill;
    if (currentMode === 'wait') {{
      const z = ZONES[p.dataset.id];
      if (z && z.wait_matrix) {{
        fill = waitCell(z).fill;
      }} else {{
        fill = p.dataset['fillWait_' + currentPeriod] || p.dataset.fillWait;
      }}
    }} else {{
      const key = 'fill' + currentMode.charAt(0).toUpperCase() + currentMode.slice(1);
      fill = p.dataset[key];
    }}
    if (fill) p.setAttribute('fill', fill);
    p.removeAttribute('fill-opacity');
  }});
  applyCoverageFilter();
}}

function applyMode(mode) {{
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('period-section').classList.toggle('visible', mode === 'wait');
  document.getElementById('agg-section').classList.toggle('visible', mode === 'wait');
  const tlBar = document.getElementById('timelapse-bar');
  const isTl = mode === 'timelapse' || mode === 'event_timelapse';
  tlBar.classList.toggle('visible', isTl);
  tlBar.classList.toggle('event-mode', mode === 'event_timelapse');
  document.getElementById('tl-venue').style.display = mode === 'event_timelapse' ? 'inline-block' : 'none';
  if (mode === 'timelapse' || mode === 'event_timelapse') {{
    stopTimelapse(false);
    if (mode === 'event_timelapse') {{
      tlFrame = 19;
      renderEventLegend();
      setTimeout(() => zoomToVenue(tlVenue), 60);
    }} else {{
      renderLegend('timelapse');
    }}
    applyTimelapseFrame(tlFrame);
  }} else {{
    stopTimelapse(true);
    applyFills();
    renderLegend(mode);
  }}
}}

function applyPeriod(period) {{
  currentPeriod = period;
  document.querySelectorAll('.period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  if (currentMode === 'wait') applyFills();
}}

function applyAgg(agg) {{
  currentAgg = agg;
  document.querySelectorAll('.agg-btn').forEach(b => b.classList.toggle('active', b.dataset.agg === agg));
  if (currentMode === 'wait') applyFills();
}}

document.querySelectorAll('.mode-btn').forEach(btn => btn.addEventListener('click', () => applyMode(btn.dataset.mode)));
document.querySelectorAll('.period-btn').forEach(btn => btn.addEventListener('click', () => applyPeriod(btn.dataset.period)));
document.querySelectorAll('.agg-btn').forEach(btn => btn.addEventListener('click', () => applyAgg(btn.dataset.agg)));
document.querySelectorAll('.cov-type').forEach(el => el.addEventListener('change', applyCoverageFilter));

document.getElementById('toggle-subway-lines').addEventListener('change', e => {{
  document.getElementById('subway-lines-group').style.display = e.target.checked ? 'block' : 'none';
}});
document.getElementById('toggle-subway-stations').addEventListener('change', e => {{
  document.getElementById('subway-stations-group').style.display = e.target.checked ? 'block' : 'none';
}});
document.getElementById('toggle-attractions').addEventListener('change', e => {{
  document.querySelector('.map-shell').classList.toggle('attractions-on', e.target.checked);
}});

document.getElementById('attractions-group').addEventListener('click', e => {{
  const g = e.target.closest('.attraction');
  if (!g) return;
  const zoneId = g.dataset.zone;
  const venueId = g.dataset.id;
  if (zoneId) {{
    const el = document.querySelector(`.zone[data-id="${{zoneId}}"]`);
    if (el) {{
      const b = el.getBBox();
      const k = Math.min(12, Math.min(VIEW_W / (b.width * 2.4), VIEW_H / (b.height * 2.4)));
      zoomK = Math.max(4.5, k);
      zoomX = b.x + b.width / 2 - (VIEW_W / zoomK) / 2;
      zoomY = b.y + b.height / 2 - (VIEW_H / zoomK) / 2;
      clampPan();
      applyZoom();
    }}
  }}
  if (currentMode === 'event_timelapse' && EVENT_TIMELAPSE.venues && EVENT_TIMELAPSE.venues[venueId]) {{
    const sel = document.getElementById('tl-venue');
    if (sel) {{
      sel.value = venueId;
      tlVenue = venueId;
      renderEventLegend();
      applyTimelapseFrame(tlFrame);
      setTimeout(() => zoomToVenue(tlVenue), 60);
    }}
  }}
}});

const tooltip = document.getElementById('tooltip');
const zonesGroup = document.getElementById('zones-group');

function fmtNum(n) {{ return n === null || n === undefined ? '—' : n.toLocaleString('ru-RU'); }}
function fmtWait(sec) {{
  if (sec === null || sec === undefined) return 'нет данных';
  return (sec / 60).toFixed(1).replace('.', ',') + ' мин';
}}

zonesGroup.addEventListener('pointermove', e => {{
  const el = e.target.closest('.zone');
  if (!el || el.classList.contains('dimmed')) {{ tooltip.style.display = 'none'; return; }}
  const z = ZONES[el.dataset.id];
  if (!z) {{ tooltip.style.display = 'none'; return; }}

  let waitHtml = '';
  if (currentMode === 'timelapse' || currentMode === 'event_timelapse') {{
    const trips = tlCurrentTrips()[el.dataset.id];
    const lift = tlCurrentLift()[el.dataset.id];
    const liftTxt = lift != null ? '×' + lift.toFixed(2) : '—';
    waitHtml = `
      <div class="tt-row"><span>Час</span><b>${{tlFrameLabel()}}</b></div>
      <div class="tt-row"><span>Поездок/ч</span><b>${{trips != null ? fmtNum(Math.round(trips)) : '—'}}</b></div>
      ${{currentMode === 'event_timelapse' ? `<div class="tt-row"><span>Lift pickup</span><b>${{liftTxt}}</b></div>` : ''}}
    `;
  }} else if (currentMode === 'wait') {{
    const cell = waitCell(z);
    const sparse = cell.n_trips > 0 && cell.n_trips < MIN_WAIT_N;
    waitHtml = `
      <div class="tt-row"><span>Период</span><b>${{PERIOD_LABELS[currentPeriod]}}</b></div>
      <div class="tt-row"><span>Агрегатор</span><b>${{currentAgg === 'all' ? 'Все FHVHV' : currentAgg}}</b></div>
      <div class="tt-row"><span>Ожидание</span><b>${{sparse ? 'мало данных' : fmtWait(cell.med_wait_sec)}}</b></div>
      <div class="tt-row"><span>Поездок</span><b>${{fmtNum(cell.n_trips)}}</b></div>
    `;
  }} else {{
    waitHtml = `<div class="tt-row"><span>Ожидание (мед.)</span><b>${{fmtWait(z.med_wait_sec)}}</b></div>`;
  }}

  tooltip.innerHTML = `
    <div class="tt-name">${{z.name}}</div>
    <div class="tt-row"><span>Округ</span><b>${{z.borough}}</b></div>
    <div class="tt-row"><span>Покрытие</span><b>${{z.dominant_type ? z.dominant_type + ' (' + z.type_share_pct + '%)' : '—'}}</b></div>
    <div class="tt-row"><span>Агрегатор</span><b>${{z.dominant_aggregator ? z.dominant_aggregator + ' (' + z.agg_share_pct + '%)' : '—'}}</b></div>
    ${{waitHtml}}
    <div class="tt-row"><span>Поездок/год</span><b>${{fmtNum(z.annual_trips)}}</b></div>
  `;
  tooltip.style.display = 'block';
  tooltip.style.left = Math.min(e.clientX + 14, window.innerWidth - 290) + 'px';
  tooltip.style.top = Math.min(e.clientY + 14, window.innerHeight - 220) + 'px';
}});
zonesGroup.addEventListener('pointerleave', () => {{ tooltip.style.display = 'none'; }});

// --- timelapse ------------------------------------------------------------
let tlFrame = 0, tlDay = 'weekday', tlSpeed = 1, tlTimer = null, tlPlaying = false;
let tlVenue = Object.keys(EVENT_TIMELAPSE.venues || {{}})[0] || 'msg';

function tlVenueData() {{
  return (EVENT_TIMELAPSE.venues || {{}})[tlVenue] || null;
}}
function tlFrames() {{
  if (currentMode === 'event_timelapse') {{
    const v = tlVenueData();
    return v ? v.frames : [];
  }}
  return (TIMELAPSE[tlDay] || []);
}}
function tlFrameLabel() {{
  const f = tlFrames()[tlFrame];
  return f ? f.label : String(tlFrame).padStart(2, '0') + ':00';
}}
function tlCurrentTrips() {{
  const f = tlFrames()[tlFrame];
  return f && f.trips ? f.trips : {{}};
}}
function tlCurrentLift() {{
  const f = tlFrames()[tlFrame];
  return f && f.lift ? f.lift : {{}};
}}
function zoomToVenue(vid) {{
  const v = (EVENT_TIMELAPSE.venues || {{}})[vid];
  if (!v) return;
  const ids = new Set((v.zones || []).map(String));
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  document.querySelectorAll('.zone').forEach(p => {{
    if (!ids.has(p.dataset.id)) return;
    const b = p.getBBox();
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.width);
    maxY = Math.max(maxY, b.y + b.height);
  }});
  if (!isFinite(minX)) return;
  const pad = 1.85;
  const w = Math.max(maxX - minX, 10) * pad;
  const h = Math.max(maxY - minY, 10) * pad;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  zoomK = Math.min(14, Math.max(4.5, Math.min(VIEW_W / w, VIEW_H / h)));
  zoomX = cx - (VIEW_W / zoomK) / 2;
  zoomY = cy - (VIEW_H / zoomK) / 2;
  clampPan();
  applyZoom();
}}
function applyTimelapseFrame(idx) {{
  tlFrame = Math.max(0, Math.min(23, idx));
  const frame = tlFrames()[tlFrame];
  if (!frame) return;
  const fills = frame.fills || {{}};
  const isEvent = currentMode === 'event_timelapse';
  const venueZones = isEvent ? new Set((tlVenueData()?.zones || []).map(String)) : null;
  const dom = isEvent ? evtDomain() : TL_DOMAIN;
  const hotTh = dom[0] + (dom[1] - dom[0]) * 0.72;
  document.querySelectorAll('.zone').forEach(p => {{
    p.classList.add('timelapse-mode');
    const id = p.dataset.id;
    if (isEvent && venueZones && !venueZones.has(id)) {{
      p.classList.add('context-gray');
      p.classList.remove('timelapse-hot', 'dimmed');
      p.removeAttribute('fill-opacity');
      return;
    }}
    p.classList.remove('dimmed', 'context-gray');
    p.setAttribute('fill-opacity', '1');
    const fill = fills[id] || (isEvent ? '#c5c9ce' : '{METRIC_COLOR_LO}');
    p.setAttribute('fill', fill);
    const metric = frame.trips && frame.trips[id];
    p.classList.toggle('timelapse-hot', metric != null && metric >= hotTh);
  }});
  if (!isEvent) applyCoverageFilter();
  document.getElementById('tl-scrub').value = tlFrame;
  document.getElementById('tl-time').textContent = frame.label;
}}
function stopTimelapse(resetFrame) {{
  tlPlaying = false;
  if (tlTimer) {{ clearInterval(tlTimer); tlTimer = null; }}
  const btn = document.getElementById('tl-play');
  if (btn) {{ btn.textContent = '▶'; btn.classList.remove('playing'); }}
  if (resetFrame) tlFrame = 0;
}}
function startTimelapse() {{
  if (!tlFrames().length) return;
  if (tlTimer) clearInterval(tlTimer);
  tlPlaying = true;
  const btn = document.getElementById('tl-play');
  btn.textContent = '⏸';
  btn.classList.add('playing');
  const ms = () => Math.round(900 / tlSpeed);
  tlTimer = setInterval(() => {{
    const next = (tlFrame + 1) % 24;
    applyTimelapseFrame(next);
  }}, ms());
}}
function toggleTimelapse() {{
  if (tlPlaying) stopTimelapse(false);
  else startTimelapse();
}}

(function initVenueSelect() {{
  const sel = document.getElementById('tl-venue');
  if (!sel || !EVENT_TIMELAPSE.venues) return;
  sel.innerHTML = '';
  Object.entries(EVENT_TIMELAPSE.venues).forEach(([id, v]) => {{
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = v.name;
    sel.appendChild(opt);
  }});
  if (sel.options.length) {{ sel.value = tlVenue; }}
  sel.addEventListener('change', () => {{
    tlVenue = sel.value;
    stopTimelapse(false);
    renderEventLegend();
    applyTimelapseFrame(tlFrame);
    if (currentMode === 'event_timelapse') setTimeout(() => zoomToVenue(tlVenue), 60);
    if (tlPlaying) startTimelapse();
  }});
}})();

document.getElementById('tl-play').addEventListener('click', toggleTimelapse);
document.getElementById('tl-scrub').addEventListener('input', e => {{
  stopTimelapse(false);
  applyTimelapseFrame(parseInt(e.target.value, 10));
}});
document.querySelectorAll('.tl-daytype').forEach(btn => btn.addEventListener('click', () => {{
  tlDay = btn.dataset.day;
  document.querySelectorAll('.tl-daytype').forEach(b => b.classList.toggle('active', b === btn));
  stopTimelapse(false);
  applyTimelapseFrame(tlFrame);
  if (tlPlaying) startTimelapse();
}}));
document.querySelectorAll('.tl-speed').forEach(btn => btn.addEventListener('click', () => {{
  tlSpeed = parseFloat(btn.dataset.speed);
  document.querySelectorAll('.tl-speed').forEach(b => b.classList.toggle('active', b === btn));
  if (tlPlaying) {{ stopTimelapse(false); startTimelapse(); }}
}}));

// --- zoom & pan -----------------------------------------------------------
const svg = document.querySelector('svg');
const mapShell = document.querySelector('.map-shell');
let zoomK = 1, zoomX = 0, zoomY = 0;

function applyZoom() {{
  svg.setAttribute('viewBox', `${{zoomX}} ${{zoomY}} ${{VIEW_W / zoomK}} ${{VIEW_H / zoomK}}`);
}}
function clampPan() {{
  const vw = VIEW_W / zoomK, vh = VIEW_H / zoomK;
  zoomX = Math.max(0, Math.min(VIEW_W - vw, zoomX));
  zoomY = Math.max(0, Math.min(VIEW_H - vh, zoomY));
}}
function zoomAt(clientX, clientY, factor) {{
  const rect = svg.getBoundingClientRect();
  const vx = zoomX + (clientX - rect.left) / rect.width * (VIEW_W / zoomK);
  const vy = zoomY + (clientY - rect.top) / rect.height * (VIEW_H / zoomK);
  zoomK = Math.max(1, Math.min(12, zoomK * factor));
  if (zoomK === 1) {{ zoomX = 0; zoomY = 0; applyZoom(); return; }}
  zoomX = vx - (clientX - rect.left) / rect.width * (VIEW_W / zoomK);
  zoomY = vy - (clientY - rect.top) / rect.height * (VIEW_H / zoomK);
  clampPan();
  applyZoom();
}}
svg.addEventListener('wheel', e => {{
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.2 : 1/1.2);
}}, {{ passive: false }});
document.getElementById('zoom-in').addEventListener('click', () =>
  zoomAt(mapShell.getBoundingClientRect().left + mapShell.clientWidth / 2,
         mapShell.getBoundingClientRect().top + mapShell.clientHeight / 2, 1.4));
document.getElementById('zoom-out').addEventListener('click', () =>
  zoomAt(mapShell.getBoundingClientRect().left + mapShell.clientWidth / 2,
         mapShell.getBoundingClientRect().top + mapShell.clientHeight / 2, 1/1.4));
document.getElementById('zoom-reset').addEventListener('click', () => {{
  zoomK = 1; zoomX = 0; zoomY = 0; applyZoom();
}});

let panLast = null;
svg.addEventListener('pointerdown', e => {{
  if (zoomK <= 1) return;
  panLast = [e.clientX, e.clientY];
  mapShell.classList.add('panning');
}});
window.addEventListener('pointermove', e => {{
  if (!panLast) return;
  const rect = svg.getBoundingClientRect();
  zoomX -= (e.clientX - panLast[0]) / rect.width * (VIEW_W / zoomK);
  zoomY -= (e.clientY - panLast[1]) / rect.height * (VIEW_H / zoomK);
  panLast = [e.clientX, e.clientY];
  clampPan();
  applyZoom();
}});
window.addEventListener('pointerup', () => {{
  panLast = null;
  mapShell.classList.remove('panning');
}});
// double-click a zone to zoom to it
svg.addEventListener('dblclick', e => {{
  const el = e.target.closest('.zone');
  if (!el) return;
  const b = el.getBBox();
  const k = Math.min(12, Math.min(VIEW_W / (b.width * 2.2), VIEW_H / (b.height * 2.2)));
  zoomK = k;
  zoomX = b.x + b.width / 2 - (VIEW_W / zoomK) / 2;
  zoomY = b.y + b.height / 2 - (VIEW_H / zoomK) / 2;
  clampPan();
  applyZoom();
}});

renderLegend('dominant_type');
applyCoverageFilter();
</script>
'''
    report_path = Path("reports/nyc_zone_map_v2.html")
    grafana_path = Path("grafana_provisioning/nyc_map/index.html")
    report_path.write_text(html, encoding="utf-8")
    print(f"saved {report_path} ({len(html)/1e6:.2f} MB)")
    grafana_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, grafana_path)
    print(f"copied -> {grafana_path}")


if __name__ == "__main__":
    main()

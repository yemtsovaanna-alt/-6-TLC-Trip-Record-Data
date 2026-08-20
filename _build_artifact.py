import json

d = json.load(open("_map_data.json", encoding="utf-8"))
P = d["periods"]

def period_layer(key, active):
    v = P[key]
    disp = "block" if active else "none"
    return f'''
      <g class="flow-layer" data-period="{key}" style="display:{disp}">
        <path class="road green" d="{v['green_path']}"/>
        <path class="road amber" d="{v['amber_path']}"/>
        <path class="road red" d="{v['red_path']}"/>
      </g>'''

def top5_rows(key):
    rows = []
    for i, t in enumerate(P[key]["top5"], 1):
        rows.append(
            f'<li><span class="rank">{i:02d}</span>'
            f'<span class="od"><b>{t["pu"]}</b><span class="arrow">&#8594;</span>{t["do"]}</span>'
            f'<span class="trips">{t["trips"]:,}</span></li>'
        )
    return "\n".join(rows)

def panel(key, active):
    v = P[key]
    disp = "flex" if active else "none"
    total_edges = v["green_n"] + v["amber_n"] + v["red_n"]
    return f'''
      <div class="panel" data-period="{key}" style="display:{disp}">
        <div class="stat-row">
          <div class="stat"><span class="stat-num">{v['total_trips_routed']:,}</span><span class="stat-label">поездок в топ-{v['routed_flows']} потоках</span></div>
          <div class="stat"><span class="stat-num">{total_edges:,}</span><span class="stat-label">участков дороги задействовано</span></div>
          <div class="stat"><span class="stat-num">{v['max_load']:,}</span><span class="stat-label">макс. нагрузка на участок</span></div>
        </div>
        <h3 class="panel-h">Топ-5 маршрутов периода</h3>
        <ol class="top5">{top5_rows(key)}</ol>
      </div>'''

def tab_btn(key, active, dot_class):
    cls = "tab active" if active else "tab"
    return f'<button class="{cls}" data-period="{key}" type="button"><span class="dot {dot_class}"></span>{P[key]["label"]}</button>'

html = f'''<meta charset="utf-8">
<title>NYC Taxi — маршруты самого загруженного дня</title>
<style>
:root {{
  --bg: #f3f5f7;
  --surface: #ffffff;
  --surface-2: #eaeef1;
  --border: #d7dce1;
  --text: #10161d;
  --text-muted: #5c6672;
  --accent: #0d8f82;
  --accent-soft: rgba(13,143,130,0.10);
  --road-base: #c7ced5;
  --green: #1a9e6a;
  --amber: #b8791f;
  --red: #c33f36;
  --font-display: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --font-body: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #0a0e13;
    --surface: #121821;
    --surface-2: #1a222c;
    --border: #262f3a;
    --text: #e8edf3;
    --text-muted: #8b95a3;
    --accent: #4fd8c4;
    --accent-soft: rgba(79,216,196,0.12);
    --road-base: #2b3542;
    --green: #34d399;
    --amber: #fbbf24;
    --red: #f0564d;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #0a0e13;
  --surface: #121821;
  --surface-2: #1a222c;
  --border: #262f3a;
  --text: #e8edf3;
  --text-muted: #8b95a3;
  --accent: #4fd8c4;
  --accent-soft: rgba(79,216,196,0.12);
  --road-base: #2b3542;
  --green: #34d399;
  --amber: #fbbf24;
  --red: #f0564d;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 15px;
  line-height: 1.5;
}}

.wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 24px 48px; }}

header.masthead {{
  display: flex; flex-direction: column; gap: 6px;
  margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid var(--border);
}}
.eyebrow {{
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--accent); font-weight: 600;
}}
h1 {{
  font-family: var(--font-display); font-weight: 800; letter-spacing: -0.01em;
  font-size: clamp(26px, 3.4vw, 38px); margin: 2px 0 0; text-wrap: balance;
}}
.subtitle {{ color: var(--text-muted); font-size: 14.5px; max-width: 62ch; margin-top: 4px; }}

.tabs {{ display: flex; gap: 8px; margin: 22px 0 16px; flex-wrap: wrap; }}
.tab {{
  font-family: var(--font-display); font-weight: 700; font-size: 13.5px;
  display: flex; align-items: center; gap: 8px;
  background: var(--surface); color: var(--text-muted); border: 1px solid var(--border);
  border-radius: 999px; padding: 9px 16px 9px 12px; cursor: pointer;
}}
.tab .dot {{ width: 9px; height: 9px; border-radius: 50%; flex: none; }}
.tab.active {{ color: var(--text); border-color: var(--accent); background: var(--accent-soft); }}
.dot.d-morning {{ background: #f2b84a; }}
.dot.d-day {{ background: var(--accent); }}
.dot.d-evening {{ background: #7c6ff2; }}

.layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; align-items: start; }}
@media (max-width: 860px) {{ .layout {{ grid-template-columns: 1fr; }} }}

.map-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px; position: relative; overflow: hidden;
}}
.map-card svg {{ width: 100%; height: auto; display: block; }}
.road {{ fill: none; stroke-linecap: round; stroke-linejoin: round; }}
.road-base {{ fill: none; stroke: var(--road-base); stroke-width: 1.1; stroke-linecap: round; opacity: 0.75; }}
.road.green {{ stroke: var(--green); stroke-width: 1.6; opacity: 0.85; }}
.road.amber {{ stroke: var(--amber); stroke-width: 2.1; opacity: 0.9; }}
.road.red {{ stroke: var(--red); stroke-width: 2.7; opacity: 0.95; }}

.legend {{
  position: absolute; left: 28px; bottom: 24px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px;
  display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--text-muted);
  box-shadow: 0 6px 20px rgba(0,0,0,0.12);
}}
.legend-title {{ font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.1em; font-size: 10.5px; color: var(--text-muted); margin-bottom: 2px; }}
.legend-row {{ display: flex; align-items: center; gap: 8px; }}
.legend-swatch {{ width: 22px; height: 4px; border-radius: 2px; flex: none; }}
.legend-row.lg .legend-swatch {{ background: var(--green); }}
.legend-row.la .legend-swatch {{ background: var(--amber); }}
.legend-row.lr .legend-swatch {{ background: var(--red); }}
.legend-row b {{ color: var(--text); font-family: var(--font-mono); font-variant-numeric: tabular-nums; }}

.side {{ display: flex; flex-direction: column; gap: 14px; }}
.panel {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; flex-direction: column; gap: 14px;
}}
.stat-row {{ display: flex; flex-direction: column; gap: 10px; }}
.stat {{ display: flex; flex-direction: column; border-bottom: 1px dashed var(--border); padding-bottom: 10px; }}
.stat:last-child {{ border-bottom: none; padding-bottom: 0; }}
.stat-num {{ font-family: var(--font-mono); font-weight: 700; font-size: 22px; font-variant-numeric: tabular-nums; }}
.stat-label {{ color: var(--text-muted); font-size: 12px; }}
.panel-h {{
  font-family: var(--font-display); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-muted); margin: 4px 0 0;
}}
.top5 {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }}
.top5 li {{ display: flex; align-items: baseline; gap: 10px; font-size: 13px; }}
.rank {{ font-family: var(--font-mono); color: var(--accent); font-weight: 700; font-size: 11.5px; flex: none; }}
.od {{ flex: 1; min-width: 0; }}
.od .arrow {{ color: var(--text-muted); margin: 0 5px; }}
.trips {{ font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--text-muted); font-size: 12.5px; }}

.method {{
  margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border);
  color: var(--text-muted); font-size: 12.5px; max-width: 80ch;
}}
.method b {{ color: var(--text); }}
</style>

<div class="wrap">
  <header class="masthead">
    <span class="eyebrow">TLC Trip Data · A* routing</span>
    <h1>Самый загруженный день архива: 14 декабря 2019</h1>
    <p class="subtitle">1&nbsp;268&nbsp;715 поездок за сутки (yellow + green + fhv + fhvhv, суббота) — топ-60 маршрутов район&#8594;район
    на период проложены A* по реальной дорожной сети OSM, дороги окрашены по относительной нагрузке внутри периода.</p>
  </header>

  <div class="tabs">
    {tab_btn("morning", True, "d-morning")}
    {tab_btn("day", False, "d-day")}
    {tab_btn("evening", False, "d-evening")}
  </div>

  <div class="layout">
    <div class="map-card">
      <svg viewBox="0 0 {d['view_w']} {d['view_h']}" xmlns="http://www.w3.org/2000/svg">
        <path class="road-base" d="{d['base_path']}"/>
        {period_layer("morning", True)}
        {period_layer("day", False)}
        {period_layer("evening", False)}
      </svg>
      <div class="legend" id="legend">
        <div class="legend-title">Нагрузка на участок (поездок)</div>
        <div class="legend-row lg">Свободно <b id="lg-g">&le; 72</b></div>
        <div class="legend-row la">Плотно <b id="lg-a">72&ndash;138</b></div>
        <div class="legend-row lr">Затор <b id="lg-r">&gt; 138</b></div>
      </div>
    </div>

    <div class="side">
      {panel("morning", True)}
      {panel("day", False)}
      {panel("evening", False)}
    </div>
  </div>

  <p class="method"><b>Методология.</b> Дорожная сеть — основные классы OSM (motorway&hellip;tertiary) в границах такси-зон NYC,
  380&nbsp;605 узлов. Для каждого периода взяты топ-60 пар зона&#8594;зона по числу поездок (без служебных кодов 264/265 &laquo;Unknown&raquo;/&laquo;Outside&nbsp;NYC&raquo;),
  каждая пара маршрутизирована A* (эвристика — geodesic-расстояние до цели, вес ребра — длина в метрах), нагрузка на дорогу — сумма поездок
  всех маршрутов, проходящих через неё. Цвет — терциль нагрузки <i>внутри своего периода</i> (день агрегирует 5 часов, час пик — 3, поэтому шкалы не общие).</p>
</div>

<script>
(function() {{
  var thresholds = {json.dumps({k: v["thresholds"] for k, v in P.items()})};
  var tabs = document.querySelectorAll(".tab");
  tabs.forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      var period = btn.getAttribute("data-period");
      tabs.forEach(function(b) {{ b.classList.toggle("active", b === btn); }});
      document.querySelectorAll(".flow-layer").forEach(function(g) {{
        g.style.display = (g.getAttribute("data-period") === period) ? "block" : "none";
      }});
      document.querySelectorAll(".panel").forEach(function(p) {{
        p.style.display = (p.getAttribute("data-period") === period) ? "flex" : "none";
      }});
      var t = thresholds[period];
      document.getElementById("lg-g").textContent = "\\u2264 " + t[0];
      document.getElementById("lg-a").textContent = t[0] + "\\u2013" + t[1];
      document.getElementById("lg-r").textContent = "> " + t[1];
    }});
  }});
}})();
</script>
'''

out_path = r"C:\Users\andrn\AppData\Local\Temp\claude\C--Users-andrn-HSE-NYC\e9bb64d4-676f-4446-97a9-a4164a16a604\scratchpad\nyc_taxi_flows.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", out_path, len(html), "chars")

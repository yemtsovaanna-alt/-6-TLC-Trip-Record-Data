"""Render two 16:9 presentation slides → PNG via Playwright."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "slides" / "_data.json").read_text(encoding="utf-8"))
OUT = ROOT / "slides"
OUT.mkdir(exist_ok=True)

LO, HI = "#9BACD8", "#F98513"
BG = "#0f1419"
SURFACE = "#1a222c"
TEXT = "#e8ecf1"
MUTED = "#8b95a3"

# --- weather slide data ---
weather = [w for w in DATA["weather"] if w["borough"] != "Citywide"]
w_max = max(abs(w["pct"]) for w in weather) or 1
cong = DATA["congestion"]
c_max = max(abs(c["yoy"]) for c in cong) or 1
tiers = DATA["subway_tier"]

def bar_rows(items, label_key, val_key, vmax, unit="%", pos_color=HI, neg_ok=True):
    rows = []
    for it in items:
        v = it[val_key]
        w = min(100, abs(v) / vmax * 100)
        color = pos_color if v >= 0 else "#c45c6a"
        sig = ""
        if "p" in it:
            sig = " · значимо" if it["p"] < 0.05 else " · н/з"
        rows.append(f"""
        <div class="bar-row">
          <div class="bar-label">{it[label_key]}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%;background:{color}"></div></div>
          <div class="bar-val" style="color:{color}">{v:+.1f}{unit}{sig}</div>
        </div>""")
    return "\n".join(rows)

weather_bars = bar_rows(weather, "borough", "pct", w_max, unit="% / 10мм")
cong_bars = bar_rows(cong, "borough", "yoy", c_max, unit="% YoY")
tier_bars = bar_rows(tiers, "tier", "pct", max(t["pct"] for t in tiers) or 1, unit="% / 10мм", pos_color=LO)

# --- events slide ---
events = [e for e in DATA["events"] if e["type"] not in ("Super Bowl",)]  # Super Bowl n=1 outlier for chart; mention in KPI
events_chart = sorted(events, key=lambda e: e["lift"], reverse=True)
e_max = max(abs(e["lift"]) for e in events_chart) or 1
event_bars = bar_rows(events_chart, "type", "lift", e_max, unit="%")
avg = DATA["avg"]
dowhy = {d["model"]: d for d in DATA["dowhy"]}

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 1920px; height: 1080px; overflow: hidden; background: {BG}; color: {TEXT};
  font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
.slide {{ width: 1920px; height: 1080px; padding: 56px 64px 48px; display: flex; flex-direction: column;
  background: radial-gradient(1200px 700px at 85% -10%, rgba(249,133,19,0.12), transparent 55%),
              radial-gradient(900px 600px at -5% 110%, rgba(155,172,216,0.14), transparent 50%),
              {BG}; }}
.eyebrow {{ font-family: Manrope, sans-serif; font-size: 18px; font-weight: 600; letter-spacing: 0.14em;
  text-transform: uppercase; color: {LO}; margin-bottom: 14px; }}
h1 {{ font-family: Manrope, sans-serif; font-size: 52px; font-weight: 800; line-height: 1.12;
  letter-spacing: -0.02em; max-width: 1600px; margin-bottom: 18px; }}
.lead {{ font-size: 24px; line-height: 1.45; color: {MUTED}; max-width: 1500px; margin-bottom: 36px; }}
.lead strong {{ color: {TEXT}; font-weight: 600; }}
.accent {{ color: {HI}; }}
.grid {{ display: grid; gap: 28px; flex: 1; min-height: 0; }}
.grid-2 {{ grid-template-columns: 1.15fr 0.85fr; }}
.grid-3 {{ grid-template-columns: 1fr 1fr 1fr; }}
.card {{ background: {SURFACE}; border: 1px solid rgba(255,255,255,0.06); border-radius: 18px;
  padding: 28px 30px; display: flex; flex-direction: column; min-height: 0; }}
.card h2 {{ font-family: Manrope, sans-serif; font-size: 22px; font-weight: 700; margin-bottom: 6px; }}
.card .sub {{ font-size: 15px; color: {MUTED}; margin-bottom: 20px; }}
.kpi-row {{ display: flex; gap: 18px; margin-bottom: 28px; }}
.kpi {{ flex: 1; background: {SURFACE}; border: 1px solid rgba(255,255,255,0.06); border-radius: 16px;
  padding: 22px 26px; }}
.kpi .num {{ font-family: Manrope, sans-serif; font-size: 48px; font-weight: 800; color: {HI}; line-height: 1; }}
.kpi .num.blue {{ color: {LO}; }}
.kpi .lbl {{ margin-top: 10px; font-size: 16px; color: {MUTED}; line-height: 1.35; }}
.bar-row {{ display: grid; grid-template-columns: 150px 1fr 160px; gap: 14px; align-items: center;
  margin-bottom: 12px; }}
.bar-label {{ font-size: 16px; font-weight: 500; color: {TEXT}; }}
.bar-track {{ height: 14px; background: rgba(255,255,255,0.06); border-radius: 8px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 8px; }}
.bar-val {{ font-size: 15px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }}
.footer {{ margin-top: auto; padding-top: 18px; font-size: 14px; color: {MUTED};
  display: flex; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.06); }}
.pill {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 600;
  background: rgba(249,133,19,0.15); color: {HI}; margin-left: 8px; }}
.pill.blue {{ background: rgba(155,172,216,0.18); color: {LO}; }}
.findings {{ list-style: none; display: flex; flex-direction: column; gap: 16px; }}
.findings li {{ font-size: 18px; line-height: 1.4; padding-left: 18px; border-left: 3px solid {HI}; color: {TEXT}; }}
.findings li.muted-border {{ border-left-color: {LO}; }}
.findings li span {{ color: {MUTED}; display: block; font-size: 15px; margin-top: 4px; }}
"""

slide_weather = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="slide">
  <div class="eyebrow">NYC Taxi · аналитика</div>
  <h1>Карта города и погода: где дождь реально двигает спрос</h1>
  <p class="lead">Дождь поднимает поездки на <strong class="accent">+1.44% на 10&nbsp;мм</strong> по городу —
  но эффект живет рядом с метро и почти исчезает на Статен-Айленде.
  Congestion pricing с янв.&nbsp;2025 бьет только по Манхэттену.</p>

  <div class="kpi-row">
    <div class="kpi"><div class="num">+2.11%</div><div class="lbl">Manhattan · эффект дождя на 10&nbsp;мм<br>(p&nbsp;&lt;&nbsp;0.001)</div></div>
    <div class="kpi"><div class="num blue">+1.77%</div><div class="lbl">Зоны ≤354&nbsp;м от метро<br>субституция с MTA</div></div>
    <div class="kpi"><div class="num" style="color:#c45c6a">−4.2%</div><div class="lbl">Manhattan YoY после<br>congestion pricing</div></div>
  </div>

  <div class="grid grid-2">
    <div class="card">
      <h2>Эффект дождя по округам</h2>
      <div class="sub">Δ поездок на 10&nbsp;мм осадков · красный = не значимо</div>
      {weather_bars}
    </div>
    <div class="card">
      <h2>Congestion pricing · YoY</h2>
      <div class="sub">Объем поездок год к году · только Manhattan падает</div>
      {cong_bars}
      <div style="margin-top:28px">
        <h2>Дождь × доступность метро</h2>
        <div class="sub">Терцили dist_to_subway</div>
        {tier_bars}
      </div>
    </div>
  </div>

  <div class="footer">
    <span>Источник: daily_citywide · weather_effect_by_borough · rain_effect_by_subway_tier · 2019–2025</span>
    <span>NYC Taxi Dashboard</span>
  </div>
</div></body></html>"""

slide_events = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="slide">
  <div class="eyebrow">NYC Taxi · мероприятия</div>
  <h1>События города → всплески такси вокруг площадок</h1>
  <p class="lead">На <strong>{avg['n']:,}</strong> событиях (NFL/NBA/MLB/MLS/концерты/парады)
  медианный <strong class="accent">разъезд после</strong> дает
  <strong class="accent">+{avg['post']}%</strong> pickups к обычной базе того же часа и дня недели;
  приезд до старта — <strong>+{avg['pre']}%</strong>.</p>

  <div class="kpi-row">
    <div class="kpi"><div class="num">+{avg['post']}%</div><div class="lbl">Средний post-PU lift<br>+3…+5&nbsp;ч после старта</div></div>
    <div class="kpi"><div class="num blue">+{avg['pre']}%</div><div class="lbl">Средний pre-DO lift<br>−2…0&nbsp;ч до старта</div></div>
    <div class="kpi"><div class="num">{avg['n']:,}</div><div class="lbl">Событий в выборке<br>2019–2025 · FHVHV</div></div>
  </div>

  <div class="grid grid-2">
    <div class="card">
      <h2>Разъезд после события по типу</h2>
      <div class="sub">Медиана post_pu_lift_pct к same-DOW baseline</div>
      {event_bars}
    </div>
    <div class="card">
      <h2>Что усиливает разъезд</h2>
      <div class="sub">DoWhy · backdoor linear regression</div>
      <ul class="findings">
        <li>
          <strong>Ближе к метро → сильнее такси-разъезд</strong>
          <span>ATE log(dist): {dowhy['dist_to_metro']['ate']:+.1f} п.п. на ln(м)
          · p&nbsp;=&nbsp;{dowhy['dist_to_metro']['p']:.3f} · контроль на тип события и погоду</span>
        </li>
        <li class="muted-border">
          <strong>Price tier: +{dowhy['price_tier']['ate']:.1f} п.п. на ступень</strong>
          <span>направление как в гипотезе, но p&nbsp;=&nbsp;{dowhy['price_tier']['p']:.2f} — пока не значимо</span>
        </li>
        <li>
          <strong>Парады / street closure режут спрос</strong>
          <span>перекрытия улиц: медиана −22.8% · марафон −11.8% — не «ивент-лифт», а блок трафика</span>
        </li>
        <li class="muted-border">
          <strong>Карта: режим «События ▶»</strong>
          <span>таймлапс pickup/час вокруг MSG, Yankee, Citi, Barclays + серые контуры соседей</span>
        </li>
      </ul>
    </div>
  </div>

  <div class="footer">
    <span>Источник: event_impact · event_dowhy_results · FHVHV 2019–2025 · n={avg['n']}</span>
    <span>NYC Taxi Dashboard</span>
  </div>
</div></body></html>"""

(OUT / "slide_weather.html").write_text(slide_weather, encoding="utf-8")
(OUT / "slide_events.html").write_text(slide_events, encoding="utf-8")


async def shot(html_name: str, png_name: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        await page.goto((OUT / html_name).as_uri(), wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / png_name), type="png")
        await browser.close()
        print("wrote", OUT / png_name)


async def main():
    await shot("slide_weather.html", "01_weather_map.png")
    await shot("slide_events.html", "02_events_lift.png")


if __name__ == "__main__":
    asyncio.run(main())

"""Export NYC zone map as white-theme 16:9 PNG for slides."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "slides"
DATA = json.loads((ROOT / "_map_v2_data.json").read_text(encoding="utf-8"))

LO, HI = "#9BACD8", "#F98513"
WATER = "#E8EEF3"
CONTEXT = "#C5C9CE"
CONTEXT_STROKE = "#6E7580"
ZONE_STROKE = "rgba(255,255,255,0.75)"


def zone_paths():
    parts = []
    for z in DATA["zones"]:
        fill = z.get("fill_wait") or z.get("fill_volume") or "#9aa3ad"
        parts.append(
            f'<path fill="{fill}" stroke="{ZONE_STROKE}" stroke-width="0.45" d="{z["path"]}"/>'
        )
    return "".join(parts)


def context_paths():
    return "".join(
        f'<path fill="{CONTEXT}" stroke="{CONTEXT_STROKE}" stroke-width="0.85" d="{p["path"]}"/>'
        for p in DATA.get("context_land", [])
    )


def subway_paths():
    return "".join(
        f'<path fill="none" stroke="{l["color"]}" stroke-width="1.4" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="0.9" d="{l["path"]}"/>'
        for l in DATA.get("subway_lines", [])
    )


vw, vh = DATA["view_w"], DATA["view_h"]
# Fit map into right side of 16:9 slide; legend on left
html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 1920px; height: 1080px; background: #fff; color: #1a1f26;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; overflow: hidden; }}
.slide {{ width: 1920px; height: 1080px; padding: 44px 56px 56px; display: grid;
  grid-template-columns: 400px 1fr; gap: 40px; align-items: start; }}
.left {{ display: flex; flex-direction: column; gap: 0; min-height: 0; padding-bottom: 8px; }}
.eyebrow {{ font-family: Manrope, sans-serif; font-size: 15px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase; color: {LO}; margin-bottom: 10px; }}
h1 {{ font-family: Manrope, sans-serif; font-size: 34px; font-weight: 800; line-height: 1.2;
  margin-bottom: 12px; }}
.lead {{ font-size: 16px; line-height: 1.45; color: #5c6672; margin-bottom: 22px; }}
.legend {{ background: #f4f6f8; border: 1px solid #d7dce1; border-radius: 14px; padding: 18px 20px; }}
.legend h2 {{ font-size: 15px; font-weight: 700; margin-bottom: 6px; }}
.legend .sub {{ font-size: 13px; color: #5c6672; margin-bottom: 14px; }}
.grad {{ height: 14px; border-radius: 8px;
  background: linear-gradient(90deg, {LO}, {HI}); margin-bottom: 6px; }}
.scale {{ display: flex; justify-content: space-between; font-size: 12px; color: #5c6672; margin-bottom: 18px; }}
.sw {{ display: flex; align-items: center; gap: 10px; font-size: 14px; margin-bottom: 10px; color: #1a1f26; line-height: 1.3; }}
.sw i {{ width: 16px; height: 16px; border-radius: 4px; display: inline-block; border: 1px solid #d7dce1; flex-shrink: 0; }}
.note {{ margin-top: 16px; font-size: 13px; color: #5c6672; line-height: 1.45; }}
.map-wrap {{ background: {WATER}; border: 1px solid #d7dce1; border-radius: 18px;
  overflow: hidden; display: flex; align-items: center; justify-content: center; height: 920px; }}
svg {{ width: 100%; height: 100%; display: block; }}
.footer {{ position: absolute; left: 56px; right: 56px; bottom: 22px; font-size: 12px; color: #8b95a3;
  display: flex; justify-content: space-between; }}
</style></head>
<body>
<div class="slide" style="position:relative">
  <div class="left">
    <div class="eyebrow">NYC TAXI · КАРТА</div>
    <h1>Зоны ожидания подачи по городу</h1>
    <p class="lead">Медианное wait FHVHV (request→pickup).
    Соседние округа — монохромный серый контур; поверх — метрика синий→оранжевый.</p>
    <div class="legend">
      <h2>Время ожидания</h2>
      <div class="sub">минуты · надежные зоны (n ≥ {DATA.get('min_wait_n', 50)})</div>
      <div class="grad"></div>
      <div class="scale"><span>быстрее</span><span>дольше</span></div>
      <div class="sw"><i style="background:{CONTEXT}"></i>Соседние территории (NJ / Westchester / Nassau)</div>
      <div class="sw"><i style="background:#9aa3ad"></i>Мало данных / нет wait</div>
      <div class="note">Линии метро поверх зон. Режим wait — та же палитра, что на дашборде.</div>
    </div>
  </div>
  <div class="map-wrap">
    <svg viewBox="0 0 {vw} {vh}" preserveAspectRatio="xMidYMid meet">
      <rect width="{vw}" height="{vh}" fill="{WATER}"/>
      <g id="context">{context_paths()}</g>
      <g id="zones">{zone_paths()}</g>
      <g id="subway">{subway_paths()}</g>
    </svg>
  </div>
  <div class="footer">
    <span>Источник: zone_wait_by_period_agg · taxi_zones · FHVHV 2024</span>
    <span>NYC Taxi</span>
  </div>
</div>
</body></html>
"""

OUT.mkdir(exist_ok=True)
html_path = OUT / "slide_map.html"
html_path.write_text(html, encoding="utf-8")
print("wrote", html_path)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        await page.goto(html_path.as_uri(), wait_until="networkidle")
        await page.wait_for_timeout(600)
        png = OUT / "03_zone_map.png"
        await page.screenshot(path=str(png), type="png")
        await browser.close()
        print("wrote", png)


if __name__ == "__main__":
    asyncio.run(main())

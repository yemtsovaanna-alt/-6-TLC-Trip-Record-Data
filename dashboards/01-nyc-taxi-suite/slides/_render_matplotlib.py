"""Two 16:9 presentation slides as PNG — white theme, no overlapping text."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "slides" / "_data.json").read_text(encoding="utf-8"))
OUT = ROOT / "slides"

BG = "#FFFFFF"
SURFACE = "#F4F6F8"
TEXT = "#1A1F26"
MUTED = "#5C6672"
BORDER = "#D7DCE1"
LO = "#9BACD8"
HI = "#F98513"
NEG = "#C45C6A"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
    "axes.facecolor": SURFACE,
    "figure.facecolor": BG,
    "text.color": TEXT,
})


def panel(ax, title, subtitle=None):
    """Title + subtitle ABOVE the axes box — never inside the plot area."""
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_color(BORDER)
        spine.set_linewidth(1.0)
    ax.text(0.0, 1.16, title, transform=ax.transAxes, fontsize=15, fontweight="bold",
            color=TEXT, va="bottom", ha="left", clip_on=False)
    if subtitle:
        ax.text(0.0, 1.05, subtitle, transform=ax.transAxes, fontsize=11, color=MUTED,
                va="bottom", ha="left", clip_on=False)


def hbars(ax, labels, values, vmax, title, subtitle, label_fs=12):
    panel(ax, title, subtitle)
    colors = [HI if v >= 0 else NEG for v in values]
    ypos = list(range(len(labels)))[::-1]
    ax.barh(ypos, [abs(v) for v in values], color=colors, height=0.58, zorder=2)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=label_fs, color=TEXT)
    ax.set_xlim(0, vmax * 1.28)
    ax.set_xticks([])
    ax.tick_params(length=0, pad=6)
    ax.set_ylim(-0.65, len(labels) - 0.35)
    for i, v in enumerate(values):
        ax.text(abs(v) + vmax * 0.03, ypos[i], f"{v:+.1f}",
                va="center", ha="left", fontsize=11, fontweight="600", color=colors[i],
                clip_on=False)


def kpi_box(fig, x, y, w, h, num, label, color=HI):
    ax = fig.add_axes([x, y, w, h])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch(
        (0.01, 0.01), 0.98, 0.98, boxstyle="round,pad=0.02,rounding_size=0.04",
        facecolor=SURFACE, edgecolor=BORDER, linewidth=1.2, transform=ax.transAxes,
    ))
    ax.text(0.07, 0.68, num, fontsize=32, fontweight="bold", color=color, va="center")
    ax.text(0.07, 0.28, label, fontsize=12, color=MUTED, va="center", linespacing=1.35)


def footer(fig, text):
    fig.text(0.04, 0.018, text, fontsize=10, color=MUTED)
    fig.text(0.96, 0.018, "NYC Taxi", fontsize=10, color=MUTED, ha="right")


def slide_weather():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)

    # Header block — fixed vertical bands, no collision
    fig.text(0.04, 0.945, "NYC TAXI  ·  АНАЛИТИКА", fontsize=12, fontweight="600", color=LO)
    fig.text(0.04, 0.90, "Карта города и погода: где дождь реально двигает спрос",
             fontsize=28, fontweight="bold", color=TEXT, va="top")
    fig.text(0.04, 0.825,
             "Дождь: +1.44% поездок на 10 мм по городу. Эффект сильнее рядом с метро; "
             "на Staten Island не значим.\nCongestion pricing (янв 2025) бьет только Manhattan.",
             fontsize=14, color=MUTED, linespacing=1.45, va="top")

    kpi_box(fig, 0.04, 0.64, 0.29, 0.13, "+2.11%", "Manhattan · дождь / 10 мм\n(p < 0.001)", HI)
    kpi_box(fig, 0.355, 0.64, 0.29, 0.13, "+1.77%", "Зоны ≤354 м от метро\nсубституция с MTA", LO)
    kpi_box(fig, 0.67, 0.64, 0.29, 0.13, "−4.2%", "Manhattan YoY после\ncongestion pricing", NEG)

    weather = [w for w in DATA["weather"] if w["borough"] != "Citywide"]
    # Charts sit lower so titles (above axes at 1.05–1.16) clear the KPI row
    ax1 = fig.add_axes([0.11, 0.08, 0.37, 0.44])
    hbars(ax1,
          [w["borough"] for w in weather],
          [w["pct"] for w in weather],
          max(w["pct"] for w in weather),
          "Эффект дождя по округам",
          "% Δ поездок на 10 мм осадков")

    cong = DATA["congestion"]
    ax2 = fig.add_axes([0.58, 0.33, 0.35, 0.19])
    hbars(ax2,
          [c["borough"] for c in cong],
          [c["yoy"] for c in cong],
          max(abs(c["yoy"]) for c in cong),
          "Congestion pricing · объем YoY",
          "год к году после введения сбора",
          label_fs=11)

    tiers = DATA["subway_tier"]
    short = {
        "near (<=354m)": "near ≤354 м",
        "mid (354-893m)": "mid 354–893 м",
        "far (>893m)": "far >893 м",
    }
    ax3 = fig.add_axes([0.58, 0.08, 0.35, 0.15])
    labels = [short.get(t["tier"], t["tier"]) for t in tiers]
    vals = [t["pct"] for t in tiers]
    vmax = max(vals) or 1
    panel(ax3, "Дождь × доступность метро", "терцили dist_to_subway")
    ypos = list(range(len(labels)))[::-1]
    ax3.barh(ypos, vals, color=LO, height=0.55)
    ax3.set_yticks(ypos)
    ax3.set_yticklabels(labels, fontsize=11, color=TEXT)
    ax3.set_xlim(0, vmax * 1.35)
    ax3.set_xticks([])
    ax3.tick_params(length=0, pad=6)
    ax3.set_ylim(-0.65, len(labels) - 0.35)
    for i, v in enumerate(vals):
        ax3.text(v + vmax * 0.04, ypos[i], f"{v:+.2f}%",
                 va="center", fontsize=11, color=LO, fontweight="600", clip_on=False)

    footer(fig, "Источник: weather_effect_by_borough · rain_effect_by_subway_tier · congestion_pricing_yoy · 2019–2025")
    path = OUT / "01_weather_map.png"
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    print("wrote", path)


def slide_events():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)
    avg = DATA["avg"]
    dowhy = {d["model"]: d for d in DATA["dowhy"]}

    fig.text(0.04, 0.945, "NYC TAXI  ·  МЕРОПРИЯТИЯ", fontsize=12, fontweight="600", color=LO)
    fig.text(0.04, 0.90, "События города → всплески такси вокруг площадок",
             fontsize=28, fontweight="bold", color=TEXT, va="top")
    fig.text(0.04, 0.825,
             f"На {avg['n']:,} событиях (NFL/NBA/MLB/MLS/концерты/парады) медианный разъезд после "
             f"старта дает +{avg['post']}% pickups\nк обычной базе того же часа и дня недели.",
             fontsize=14, color=MUTED, linespacing=1.45, va="top")

    kpi_box(fig, 0.04, 0.64, 0.29, 0.13, f"+{avg['post']}%", "Средний post-PU lift\n+3…+5 ч после старта", HI)
    kpi_box(fig, 0.355, 0.64, 0.29, 0.13, f"+{avg['pre']}%", "Средний pre-DO lift\n−2…0 ч до старта", LO)
    kpi_box(fig, 0.67, 0.64, 0.29, 0.13, f"{avg['n']:,}", "Событий в выборке\n2019–2025 · FHVHV", HI)

    events = [e for e in DATA["events"] if e["type"] != "Super Bowl"]
    events = sorted(events, key=lambda e: e["lift"])
    ax1 = fig.add_axes([0.13, 0.08, 0.38, 0.44])
    hbars(ax1,
          [e["type"] for e in events],
          [e["lift"] for e in events],
          max(abs(e["lift"]) for e in events),
          "Разъезд после события по типу",
          "медиана post_pu_lift_pct к same-DOW baseline",
          label_fs=11)

    ax2 = fig.add_axes([0.58, 0.08, 0.38, 0.44])
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.axis("off")
    ax2.add_patch(FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0, boxstyle="round,pad=0.01,rounding_size=0.03",
        facecolor=SURFACE, edgecolor=BORDER, linewidth=1.2, transform=ax2.transAxes,
    ))
    ax2.text(0.06, 0.94, "Что усиливает разъезд", fontsize=15, fontweight="bold",
             color=TEXT, va="top")
    ax2.text(0.06, 0.875, "DoWhy · backdoor linear regression", fontsize=11,
             color=MUTED, va="top")

    blocks = [
        (HI, "Ближе к метро → сильнее разъезд",
         f"ATE log(dist): {dowhy['dist_to_metro']['ate']:+.1f} п.п. на ln(м), "
         f"p = {dowhy['dist_to_metro']['p']:.3f}"),
        (LO, f"Price tier: +{dowhy['price_tier']['ate']:.1f} п.п. на ступень",
         f"как в гипотезе, но p = {dowhy['price_tier']['p']:.2f} — пока не значимо"),
        (HI, "Парады / street closure режут спрос",
         "перекрытия −22.8% · марафон −11.8% — блок трафика"),
        (LO, "Карта: режим «События»",
         "таймлапс у MSG, Yankee, Citi, Barclays + серые соседи"),
    ]
    # Fixed slots — no stacking
    slots = [0.78, 0.58, 0.38, 0.18]
    for (color, title, body), y0 in zip(blocks, slots):
        ax2.plot([0.06, 0.06], [y0 - 0.01, y0 - 0.10], color=color, lw=3.5,
                 solid_capstyle="round", clip_on=False)
        ax2.text(0.10, y0, title, fontsize=13, fontweight="bold", color=TEXT, va="top")
        ax2.text(0.10, y0 - 0.055, body, fontsize=11, color=MUTED, va="top")

    footer(fig, f"Источник: event_impact · event_dowhy_results · FHVHV 2019–2025 · n={avg['n']}")
    path = OUT / "02_events_lift.png"
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    slide_weather()
    slide_events()

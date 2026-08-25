"""A/B test scheme tree — topology matching user's reference (01–08)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "slides" / "05_ab_test_scheme.png"

BG = "#FFFFFF"
NODE = "#E8E4F0"
NODE_EDGE = "#C8C2D8"
TEXT = "#1A1F26"
MUTED = "#5C6672"
LINE = "#A8B0C0"
LO = "#9BACD8"

# Figure coords; y decreasing downward like reference
POS = {
    "01": (0.50, 0.78),
    "02": (0.22, 0.58),
    "03": (0.66, 0.58),
    "04": (0.22, 0.36),
    "05": (0.50, 0.36),
    "06": (0.82, 0.36),
    "07": (0.38, 0.12),
    "08": (0.62, 0.12),
}

NODES = {
    "01": ("01", "Гипотеза",
           "Pre-positioning к площадкам\nдо разъезда → ниже wait\nбез просадки pay водителя"),
    "02": ("02", "Контроль A",
           "Обычный matching\nбез event-boost"),
    "03": ("03", "Treatment B",
           "Event routing:\nboost + incentive\nв buffer-зонах"),
    "04": ("04", "Unit A",
           "Venue × вечер\nбез вмешательства"),
    "05": ("05", "Интервенция",
           "За N мин до конца:\nподтянуть пул к зоне\nразъезда (+3…+5 ч)"),
    "06": ("06", "Рандомизация",
           "По вечерам / площадкам\nstratify: тип события"),
    "07": ("07", "Primary",
           "Med wait, % cancel\nв post-window"),
    "08": ("08", "Guardrails",
           "$/час, ETA города,\nотказы вне venue"),
}

BOX_W = {
    "01": 0.28, "02": 0.20, "03": 0.20, "04": 0.20,
    "05": 0.22, "06": 0.20, "07": 0.20, "08": 0.20,
}
BOX_H = 0.145


def draw_box(ax, key):
    x, y = POS[key]
    w, h = BOX_W[key], BOX_H
    num, title, body = NODES[key]
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.006,rounding_size=0.018",
        facecolor=NODE, edgecolor=NODE_EDGE, linewidth=1.5,
        transform=ax.transAxes, zorder=3,
    ))
    ax.text(x, y + h * 0.30, num, transform=ax.transAxes,
            ha="center", va="center", fontsize=11, fontweight="bold",
            color=MUTED, zorder=4)
    ax.text(x, y + h * 0.06, title, transform=ax.transAxes,
            ha="center", va="center", fontsize=14, fontweight="bold",
            color=TEXT, zorder=4)
    ax.text(x, y - h * 0.28, body, transform=ax.transAxes,
            ha="center", va="center", fontsize=10, color=MUTED,
            linespacing=1.25, zorder=4)


def elbow(ax, parent, children):
    """Orthogonal tree: down from parent, horizontal bar, down to each child."""
    px, py = POS[parent]
    ph = BOX_H / 2
    mid_y = (py - ph + min(POS[c][1] + BOX_H / 2 for c in children)) / 2
    # vertical from parent to mid
    ax.plot([px, px], [py - ph, mid_y], color=LINE, lw=1.8,
            transform=ax.transAxes, zorder=1, solid_capstyle="round")
    xs = [POS[c][0] for c in children]
    if len(xs) > 1:
        ax.plot([min(xs), max(xs)], [mid_y, mid_y], color=LINE, lw=1.8,
                transform=ax.transAxes, zorder=1, solid_capstyle="round")
    for c in children:
        cx, cy = POS[c]
        ax.plot([cx, cx], [mid_y, cy + BOX_H / 2], color=LINE, lw=1.8,
                transform=ax.transAxes, zorder=1, solid_capstyle="round")


def main():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.text(0.04, 0.955, "NYC TAXI  ·  A/B ТЕСТ", fontsize=12, fontweight="600", color=LO)
    fig.text(0.04, 0.905, "Схема эксперимента: маршрутизация на разъезде",
             fontsize=26, fontweight="bold", color=TEXT, va="top")
    fig.text(0.04, 0.855,
             "Кейс MSG 07.12.2022: +91% pickups · wait +2.1 мин (+41%) — закрываем всплеск заранее?",
             fontsize=13, color=MUTED, va="top")

    # Tree edges (same topology as reference)
    elbow(ax, "01", ["02", "03"])
    elbow(ax, "02", ["04"])
    elbow(ax, "03", ["05", "06"])
    elbow(ax, "05", ["07", "08"])

    for key in NODES:
        draw_box(ax, key)

    fig.text(0.04, 0.025,
             "Primary: медиана wait / cancel в окне +3…+5 ч   ·   Guardrails: оплата водителя, ETA города   ·   Unit: venue × вечер",
             fontsize=11, color=MUTED)
    fig.text(0.96, 0.025, "NYC Taxi", fontsize=11, color=MUTED, ha="right")

    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, dpi=100, facecolor=BG)
    plt.close(fig)
    print("wrote", OUT)


if __name__ == "__main__":
    main()

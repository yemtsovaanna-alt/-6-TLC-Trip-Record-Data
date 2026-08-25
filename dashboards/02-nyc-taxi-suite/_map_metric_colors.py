"""Shared blue→orange palette for metrics without aggregator affinity."""

METRIC_COLOR_LO = "#9BACD8"
METRIC_COLOR_HI = "#F98513"
METRIC_NO_DATA = "#9aa3ad"


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def metric_color_stops(n: int = 5) -> list[tuple[int, int, int]]:
    lo, hi = hex_to_rgb(METRIC_COLOR_LO), hex_to_rgb(METRIC_COLOR_HI)
    if n < 2:
        return [lo, hi]
    return [
        tuple(round(lo[k] + (hi[k] - lo[k]) * i / (n - 1)) for k in range(3))
        for i in range(n)
    ]


METRIC_STOPS_2 = metric_color_stops(2)
METRIC_STOPS_5 = metric_color_stops(5)

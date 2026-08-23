"""Project the routed-flow edges + a base road skeleton into SVG path data,
and pull top-5 corridors per period (with zone names) for the side panel.
Writes _map_data.json, consumed when hand-assembling the HTML artifact.
"""
import json
import math
import pickle

import geopandas as gpd
import networkx as nx
import pandas as pd

PERIODS = ["morning", "day", "evening"]
PERIOD_LABELS = {
    "morning": "Утренний час пик (7:00–10:00)",
    "day": "День (11:00–16:00)",
    "evening": "Вечерний час пик (16:00–19:00)",
}

LON_MIN, LON_MAX = -74.233535, -73.711025
LAT_MIN, LAT_MAX = 40.525491, 40.899528
LAT0 = (LAT_MIN + LAT_MAX) / 2
COS_LAT0 = math.cos(math.radians(LAT0))

PAD = 40
VIEW_H = 1000
USABLE_H = VIEW_H - 2 * PAD
SCALE = USABLE_H / (LAT_MAX - LAT_MIN)
USABLE_W = (LON_MAX - LON_MIN) * COS_LAT0 * SCALE
VIEW_W = USABLE_W + 2 * PAD


def project(lon, lat):
    x = PAD + (lon - LON_MIN) * COS_LAT0 * SCALE
    y = PAD + (LAT_MAX - lat) * SCALE
    return round(x, 1), round(y, 1)


def main():
    # Базовый "скелет" города для контекста — только motorway (магистрали), геометрия
    # упрощена (Douglas-Peucker), чтобы не рисовать сотни тысяч мелких сегментов.
    gdf = gpd.read_file(
        "NewYork.osm.pbf", layer="lines", columns=["highway"],
        where="highway IN ('motorway','motorway_link')",
    )
    gdf["geometry"] = gdf.geometry.simplify(0.0003, preserve_topology=False)
    base_paths = []
    for geom in gdf.geometry:
        if geom is None or geom.geom_type != "LineString":
            continue
        pts = [project(lon, lat) for lon, lat in geom.coords]
        if len(pts) < 2:
            continue
        d = f"M{pts[0][0]},{pts[0][1]}" + "".join(f"L{x},{y}" for x, y in pts[1:])
        base_paths.append(d)
    print(f"base skeleton: {len(base_paths)} simplified ways")

    with open("nyc_road_graph.gpickle", "rb") as f:
        G = pickle.load(f)

    routed = json.load(open("_routed_flows.json", encoding="utf-8"))
    zones = pd.read_csv("_zone_centroids.csv").set_index("LocationID")
    flows = pd.read_csv("_od_flows_2019-12-14.csv")
    flows = flows[~flows.pu.isin([264, 265]) & ~flows.do_.isin([264, 265])]

    out = {
        "view_w": round(VIEW_W, 1), "view_h": VIEW_H,
        "base_path": "".join(base_paths),
        "periods": {},
    }

    for period in PERIODS:
        # Undirected агрегация нагрузки — одна линия на физический сегмент дороги,
        # а не две перекрывающиеся (u->v и v->u).
        undirected_load = {}
        node_xy = {}
        for e in routed[period]["edges"]:
            u, v, load = e["u"], e["v"], e["load"]
            key = (min(u, v), max(u, v))
            undirected_load[key] = undirected_load.get(key, 0) + load
            node_xy[u] = (e["ux"], e["uy"])
            node_xy[v] = (e["vx"], e["vy"])

        loads = sorted(undirected_load.values())
        n = len(loads)
        t1 = loads[n // 3] if n else 0
        t2 = loads[2 * n // 3] if n else 0

        tiers = {"green": [], "amber": [], "red": []}
        for (u, v), load in undirected_load.items():
            lon1, lat1 = node_xy[u]
            lon2, lat2 = node_xy[v]
            x1, y1 = project(lon1, lat1)
            x2, y2 = project(lon2, lat2)
            seg = f"M{x1},{y1}L{x2},{y2}"
            tier = "green" if load <= t1 else ("amber" if load <= t2 else "red")
            tiers[tier].append(seg)

        pf = flows[flows.period == period].nlargest(5, "trips")
        top5 = []
        for _, r in pf.iterrows():
            pu_name = zones.loc[int(r.pu), "zone"] if int(r.pu) in zones.index else "?"
            do_name = zones.loc[int(r.do_), "zone"] if int(r.do_) in zones.index else "?"
            top5.append({"pu": pu_name, "do": do_name, "trips": int(r.trips)})

        out["periods"][period] = {
            "label": PERIOD_LABELS[period],
            "green_path": "".join(tiers["green"]),
            "amber_path": "".join(tiers["amber"]),
            "red_path": "".join(tiers["red"]),
            "green_n": len(tiers["green"]), "amber_n": len(tiers["amber"]), "red_n": len(tiers["red"]),
            "thresholds": [t1, t2],
            "max_load": loads[-1] if loads else 0,
            "routed_flows": routed[period]["routed_flows"],
            "total_trips_routed": routed[period]["total_trips_routed"],
            "top5": top5,
        }
        print(f"{period}: green={len(tiers['green'])} amber={len(tiers['amber'])} "
              f"red={len(tiers['red'])} thresholds={t1},{t2} max={loads[-1] if loads else 0}")

    with open("_map_data.json", "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("saved _map_data.json")


if __name__ == "__main__":
    main()

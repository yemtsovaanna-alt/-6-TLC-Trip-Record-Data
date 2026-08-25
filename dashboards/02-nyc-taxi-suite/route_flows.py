"""A* routing of the busiest-day taxi flows over the real NYC road network.

For each of the 3 time periods (morning rush / day / evening rush) on the
busiest day (2019-12-14): take the top-N zone-to-zone flows by trip volume,
route each with A* over the OSM major-roads graph (heuristic = great-circle
distance to target, weight = edge length in meters), and accumulate a
"load" per road edge = sum of trip counts of every flow whose route uses it.

Output: one JSON per period with the graph's edge geometries + load, consumed
by the visualization step.
"""
import json
import pickle
import time

import networkx as nx
import osmnx as ox
import pandas as pd

TOP_N_FLOWS = 60
GRAPH_PATH = "nyc_road_graph.gpickle"
FLOWS_PATH = "_od_flows_2019-12-14.csv"
CENTROIDS_PATH = "_zone_centroids.csv"
PERIODS = ["morning", "day", "evening"]


def main():
    print("Loading graph...")
    with open(GRAPH_PATH, "rb") as f:
        G = pickle.load(f)
    print(f"nodes={len(G.nodes)} edges={len(G.edges)}")

    centroids = pd.read_csv(CENTROIDS_PATH).set_index("LocationID")
    flows = pd.read_csv(FLOWS_PATH)
    # 264/265 — служебные коды TLC ("Unknown"/"Outside NYC"), без геометрии зоны в
    # taxi_zones.shp: реальные, не отфильтрованные при очистке поездки, но они
    # физически некуда маршрутизировать по дорожной сети.
    flows = flows[~flows.pu.isin([264, 265]) & ~flows.do_.isin([264, 265])]

    node_xs = {n: d["x"] for n, d in G.nodes(data=True)}
    node_ys = {n: d["y"] for n, d in G.nodes(data=True)}

    # Снап центроидов зон на ближайший узел графа (один раз, переиспользуем по периодам)
    zone_to_node = {}
    for loc_id, row in centroids.iterrows():
        try:
            nearest = ox.distance.nearest_nodes(G, row["lon"], row["lat"])
            zone_to_node[loc_id] = nearest
        except Exception:
            pass
    print(f"snapped {len(zone_to_node)} zones to graph nodes")

    def heuristic(a, b):
        return ox.distance.great_circle(node_ys[a], node_xs[a], node_ys[b], node_xs[b])

    results = {}
    for period in PERIODS:
        t0 = time.time()
        pf = flows[flows.period == period].nlargest(TOP_N_FLOWS, "trips")
        edge_load = {}  # (u, v) -> trips
        routed = 0
        failed = 0
        route_paths = []
        for _, r in pf.iterrows():
            pu, do_, trips = int(r.pu), int(r.do_), int(r.trips)
            if pu not in zone_to_node or do_ not in zone_to_node:
                failed += 1
                continue
            src, dst = zone_to_node[pu], zone_to_node[do_]
            if src == dst:
                continue
            try:
                path = nx.astar_path(G, src, dst, heuristic=heuristic, weight="length")
            except nx.NetworkXNoPath:
                failed += 1
                continue
            routed += 1
            route_paths.append({"pu": pu, "do": do_, "trips": trips, "nodes": path})
            for a, b in zip(path[:-1], path[1:]):
                key = (a, b)
                edge_load[key] = edge_load.get(key, 0) + trips

        elapsed = time.time() - t0
        print(f"[{period}] routed={routed} failed={failed} in {elapsed:.1f}s, "
              f"{len(edge_load)} loaded edges")

        edges_out = []
        for (a, b), load in edge_load.items():
            edges_out.append({
                "u": a, "v": b, "load": load,
                "ux": node_xs[a], "uy": node_ys[a],
                "vx": node_xs[b], "vy": node_ys[b],
            })
        results[period] = {
            "edges": edges_out,
            "routed_flows": routed,
            "failed_flows": failed,
            "total_trips_routed": int(pf["trips"].sum()),
        }

    with open("_routed_flows.json", "w", encoding="utf-8") as f:
        json.dump(results, f)
    print("saved _routed_flows.json")


if __name__ == "__main__":
    main()

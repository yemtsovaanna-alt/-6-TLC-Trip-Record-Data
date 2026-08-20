"""Build a routable NetworkX road graph directly from the NewYork.osm.pbf extract,
bypassing the (unreliable) Overpass API. Reads the 'lines' layer via GDAL's OSM
driver (through geopandas/pyogrio), keeps only major road classes, and stitches
ways into a graph by matching shared endpoint coordinates (the way OSM ways are
topologically connected at intersections).

Node attrs mirror osmnx's convention (x=lon, y=lat) so downstream code
(ox.distance.nearest_nodes, ox.distance.great_circle) keeps working unchanged.
"""
import math
import pickle
import time

import geopandas as gpd
import networkx as nx

MAJOR_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
}
ROUND = 6  # ~0.11m precision at NYC latitude — enough to merge shared endpoints


def haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    t0 = time.time()
    gdf = gpd.read_file(
        "NewYork.osm.pbf", layer="lines", columns=["highway", "name", "oneway"],
        where="highway IS NOT NULL",
    )
    gdf = gdf[gdf["highway"].isin(MAJOR_HIGHWAYS)]
    print(f"loaded {len(gdf)} major-road ways in {time.time()-t0:.1f}s")

    G = nx.MultiDiGraph()
    G.graph["crs"] = "epsg:4326"

    # osmnx (nearest_nodes, graph_to_gdfs, ...) expects scalar node IDs, not tuples —
    # используем целочисленный id на координату вместо самого кортежа (lon, lat).
    coord_to_id: dict[tuple[float, float], int] = {}

    def node_id(lon, lat):
        key = (round(lon, ROUND), round(lat, ROUND))
        nid = coord_to_id.get(key)
        if nid is None:
            nid = len(coord_to_id)
            coord_to_id[key] = nid
            G.add_node(nid, x=key[0], y=key[1])
        return nid

    n_edges = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != "LineString":
            continue
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        oneway = str(row.get("oneway") or "").lower() in ("yes", "true", "1")
        name = row.get("name")
        for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:]):
            k1, k2 = node_id(lon1, lat1), node_id(lon2, lat2)
            if k1 == k2:
                continue
            dist = haversine(lon1, lat1, lon2, lat2)
            G.add_edge(k1, k2, length=dist, highway=row["highway"], name=name)
            n_edges += 1
            if not oneway:
                G.add_edge(k2, k1, length=dist, highway=row["highway"], name=name)
                n_edges += 1

    print(f"graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges "
          f"({n_edges} directed segment-edges added) in {time.time()-t0:.1f}s")

    # Оставляем только крупнейшую слабосвязную компоненту — иначе A* будет падать
    # на парах узлов из разных изолированных кусков графа (обрывки съездов и т.п.).
    largest = max(nx.weakly_connected_components(G), key=len)
    print(f"largest weakly-connected component: {len(largest)} of {G.number_of_nodes()} nodes")
    G = G.subgraph(largest).copy()

    with open("nyc_road_graph.gpickle", "wb") as f:
        pickle.dump(G, f)
    print(f"saved nyc_road_graph.gpickle, total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

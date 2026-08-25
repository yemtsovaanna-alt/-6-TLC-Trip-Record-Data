"""Data prep for the new custom JS zone map (replaces the 16-layer Grafana
geomap). Two-stage pattern established by _prepare_map_svg.py: this script
does all the heavy lifting (spatial simplify, projection, color computation)
in Python/SQL and writes a single JSON; _build_map_v2_artifact.py just
assembles the HTML around it.

Projection block is copied verbatim from _prepare_map_svg.py so this map
shares the exact same coordinate system as the existing flow-map artifact.

Requires zone_wait_time + zone_wait_by_period from _build_zone_wait_tables.py
(or run the whole chain via _run_wait_heatmaps.py / run_wait_heatmaps.bat).
"""
import json
import math

from pathlib import Path

import duckdb
import pandas as pd
from shapely import wkb
from shapely.geometry import box, mapping
from shapely.ops import unary_union

from _map_metric_colors import METRIC_NO_DATA, METRIC_STOPS_2

CONTEXT_CACHE = Path("grafana_provisioning/geojson/map_context_neighbors.geojson")
CONTEXT_PLACES = [
    "Hudson County, New Jersey, USA",
    "Bergen County, New Jersey, USA",
    "Essex County, New Jersey, USA",
    "Union County, New Jersey, USA",
    "Westchester County, New York, USA",
    "Nassau County, New York, USA",
]


def clean(v):
    """None-safe scalar unwrap for values coming out of a pandas row (handles
    both np.nan and pandas NA-family types, which don't support `is None`)."""
    return None if pd.isna(v) else v

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

WAIT_PERIODS = ("all", "morning", "day", "evening", "night")
WAIT_AGGS = ("all", "Uber", "Lyft", "Via", "Juno")
MIN_WAIT_N = 50


def project(lon, lat):
    x = PAD + (lon - LON_MIN) * COS_LAT0 * SCALE
    y = PAD + (LAT_MAX - lat) * SCALE
    return round(x, 1), round(y, 1)


# keep in sync with _build_grafana_dashboards.py TAXI_TYPE_COLORS/AGGREGATOR_COLORS
TAXI_TYPE_COLORS = {"yellow": "#F3C518", "green": "#2E8B57", "fhv": "#4A4A4A", "fhvhv": "#6B4FA0"}
AGGREGATOR_COLORS = {"Uber": "#06C167", "Lyft": "#FF00BF", "Via": "#00B2A9", "Juno": "#6A0DAD"}
NO_DATA_COLOR = METRIC_NO_DATA

# keep in sync with _build_subway_line_groups.py GROUPS
SUBWAY_GROUPS = {
    "red_1_2_3": (["1", "2", "3"], "#EE352E", "Линии 1/2/3"),
    "green_4_5_6": (["4", "5", "5 Peak", "6"], "#00933C", "Линии 4/5/6"),
    "purple_7": (["7"], "#B933AD", "Линия 7"),
    "blue_A_C_E": (["A", "C", "E"], "#0039A6", "Линии A/C/E"),
    "orange_B_D_F_M": (["B", "D", "F", "M"], "#FF6319", "Линии B/D/F/M"),
    "lightgreen_G": (["G"], "#6CBE45", "Линия G"),
    "brown_J_Z": (["J", "Z"], "#996633", "Линии J/Z"),
    "grey_L": (["L"], "#A7A9AC", "Линия L"),
    "yellow_N_Q_R_W": (["N", "Q", "R", "W"], "#FCCC0A", "Линии N/Q/R/W"),
    "darkgrey_shuttles": (["SF", "SR", "ST"], "#808183", "Шаттлы"),
    "cyan_SIR": (["SIR"], "#00A1DE", "Staten Island Railway"),
}


def interpolate_color(value, lo, hi, stops):
    """3-stop linear interpolation, e.g. green->yellow->red."""
    if value is None or hi <= lo:
        return NO_DATA_COLOR
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    seg = t * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    local_t = seg - i
    c0, c1 = stops[i], stops[i + 1]
    rgb = tuple(round(c0[k] + (c1[k] - c0[k]) * local_t) for k in range(3))
    return "#%02x%02x%02x" % rgb


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


WAIT_STOPS = METRIC_STOPS_2
VOLUME_STOPS = METRIC_STOPS_2


def ring_to_path(coords):
    # coords come out as (lat, lon) per the ST_Transform axis-order gotcha above
    pts = [project(lon, lat) for lat, lon, *_ in coords]
    if len(pts) < 2:
        return ""
    d = f"M{pts[0][0]},{pts[0][1]}" + "".join(f"L{x},{y}" for x, y in pts[1:]) + "Z"
    return d


def ring_to_path_lonlat(coords):
    """Shapely/GeoJSON rings are (lon, lat)."""
    pts = [project(lon, lat) for lon, lat, *_ in coords]
    if len(pts) < 2:
        return ""
    return f"M{pts[0][0]},{pts[0][1]}" + "".join(f"L{x},{y}" for x, y in pts[1:]) + "Z"


def geom_to_path(geom):
    if geom.geom_type == "Polygon":
        polys = [geom]
    elif geom.geom_type == "MultiPolygon":
        polys = list(geom.geoms)
    else:
        return ""
    parts = []
    for poly in polys:
        parts.append(ring_to_path(list(poly.exterior.coords)))
    return "".join(parts)


def geom_to_path_lonlat(geom):
    if geom is None or geom.is_empty:
        return ""
    if geom.geom_type == "Polygon":
        polys = [geom]
    elif geom.geom_type == "MultiPolygon":
        polys = list(geom.geoms)
    else:
        return ""
    parts = []
    for poly in polys:
        parts.append(ring_to_path_lonlat(list(poly.exterior.coords)))
        for hole in poly.interiors:
            parts.append(ring_to_path_lonlat(list(hole.coords)))
    return "".join(parts)


def load_or_fetch_context_land():
    """Neighbor counties as gray basemap (cached GeoJSON)."""
    if CONTEXT_CACHE.exists():
        print(f"  context land cache: {CONTEXT_CACHE}")
        return json.loads(CONTEXT_CACHE.read_text(encoding="utf-8"))

    import osmnx as ox

    print("fetching neighbor county polygons (Nominatim)...")
    pad = 0.04
    clip = box(LON_MIN - pad, LAT_MIN - pad, LON_MAX + pad, LAT_MAX + pad)
    polys = []
    for place in CONTEXT_PLACES:
        try:
            gdf = ox.geocode_to_gdf(place)
            geom = gdf.geometry.iloc[0].intersection(clip)
            if not geom.is_empty:
                polys.append(geom)
                print(f"    + {place}")
        except Exception as e:
            print(f"    ! {place}: {e}")
    if not polys:
        return {"type": "FeatureCollection", "features": []}

    # Subtract TLC taxi zones so only "other territories" remain
    import geopandas as gpd
    zones = gpd.read_file("taxi_zones/taxi_zones.shp").to_crs(4326)
    nyc = unary_union(zones.geometry.values)
    other = unary_union(polys).difference(nyc)
    if other.is_empty:
        other = unary_union(polys)

    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": "neighbors"},
        "geometry": mapping(other),
    }]}
    CONTEXT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_CACHE.write_text(json.dumps(fc), encoding="utf-8")
    print(f"  wrote {CONTEXT_CACHE}")
    return fc


def context_land_paths(fc):
    paths = []
    for feat in fc.get("features", []):
        from shapely.geometry import shape
        geom = shape(feat["geometry"])
        d = geom_to_path_lonlat(geom)
        if d:
            paths.append({"path": d, "name": feat.get("properties", {}).get("name", "")})
    return paths


def wait_fill(med, n, wait_lo, wait_hi):
    if med is None or n is None or n < MIN_WAIT_N:
        return NO_DATA_COLOR
    return interpolate_color(med, wait_lo, wait_hi, WAIT_STOPS)


def main():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL postgres; LOAD postgres;")
    con.execute("ATTACH 'dbname=nyc_taxi host=localhost user=postgres' AS pg (TYPE postgres);")

    print("reading + simplifying zone polygons...")
    # Simplify in the native EPSG:2263 feet CRS (tolerance in feet, not
    # degrees), THEN transform to WGS84. Note: DuckDB spatial's ST_Transform
    # to EPSG:4326 respects the authority-defined (lat, lon) axis order, not
    # the "GIS convention" (lon, lat) — the resulting geometry stores
    # (lat, lon) pairs, same gotcha as ST_X/ST_Y elsewhere in this project.
    zdf = con.execute("""
        SELECT LocationID, zone AS zone_name, borough,
               ST_AsWKB(ST_Transform(ST_Simplify(geom, 50), 'EPSG:2263', 'EPSG:4326')) AS wkb
        FROM ST_Read('taxi_zones/taxi_zones.shp')
    """).fetchdf()
    print(f"  {len(zdf)} zones read")

    print("merging metrics from postgres...")
    metrics = con.execute("""
        SELECT z.LocationID AS zone,
               zdt.dominant_type, zdt.dominant_share_pct AS type_share_pct,
               zda.dominant_aggregator, zda.dominant_share_pct AS agg_share_pct,
               zw.med_wait_sec, zw.avg_wait_sec, zw.n_trips AS wait_n_trips,
               sa.annual_trips, sa.dist_to_subway_m, sa.avg_trip_miles, sa.fare_per_mile
        FROM (SELECT LocationID FROM ST_Read('taxi_zones/taxi_zones.shp')) z
        LEFT JOIN pg.zone_dominant_type zdt ON zdt.zone = z.LocationID
        LEFT JOIN pg.zone_dominant_aggregator zda ON zda.zone = z.LocationID
        LEFT JOIN pg.zone_wait_time zw ON zw.zone = z.LocationID
        LEFT JOIN pg.subway_access sa ON sa."LocationID" = z.LocationID
    """).fetchdf().set_index("zone")

    wait_pag = con.execute("""
        SELECT zone, period, aggregator, med_wait_sec, n_trips
        FROM pg.zone_wait_by_period_agg
    """).fetchdf()
    wpag = wait_pag.set_index(["zone", "period", "aggregator"])

    # Shared color domain across period×aggregator (reliable cells only)
    reliable = wait_pag[wait_pag["n_trips"] >= MIN_WAIT_N]["med_wait_sec"].dropna()
    wait_lo, wait_hi = reliable.quantile(0.05), reliable.quantile(0.95)
    vol_vals = metrics["annual_trips"].dropna()
    vol_lo, vol_hi = vol_vals.quantile(0.05), vol_vals.quantile(0.95)
    print(f"  wait domain (p5-p95, n>={MIN_WAIT_N}): {wait_lo:.0f}-{wait_hi:.0f}s, "
          f"volume domain: {vol_lo:.0f}-{vol_hi:.0f}")

    zones_out = []
    n_no_geom = 0
    for _, row in zdf.iterrows():
        geom = wkb.loads(bytes(row["wkb"]))
        path_d = geom_to_path(geom)
        if not path_d:
            n_no_geom += 1
            continue
        loc_id = int(row["LocationID"])
        m = metrics.loc[loc_id] if loc_id in metrics.index else None

        dom_type = clean(m["dominant_type"]) if m is not None else None
        dom_agg = clean(m["dominant_aggregator"]) if m is not None else None
        type_share = clean(m["type_share_pct"]) if m is not None else None
        agg_share = clean(m["agg_share_pct"]) if m is not None else None
        vol = clean(m["annual_trips"]) if m is not None else None
        dist = clean(m["dist_to_subway_m"]) if m is not None else None

        wait_matrix = {}
        for period in WAIT_PERIODS:
            wait_matrix[period] = {}
            for agg in WAIT_AGGS:
                key = (loc_id, period, agg)
                if key in wpag.index:
                    r = wpag.loc[key]
                    med = clean(r["med_wait_sec"])
                    n_tr = clean(r["n_trips"])
                    n_int = int(n_tr) if n_tr is not None else 0
                    med_f = round(float(med), 0) if med is not None else None
                    wait_matrix[period][agg] = {
                        "med_wait_sec": med_f,
                        "n_trips": n_int,
                        "fill": wait_fill(
                            float(med) if med is not None else None,
                            n_int, wait_lo, wait_hi,
                        ),
                    }
                else:
                    wait_matrix[period][agg] = {
                        "med_wait_sec": None, "n_trips": 0, "fill": NO_DATA_COLOR,
                    }

        all_w = wait_matrix["all"]["all"]
        # legacy period-only fills (aggregator=all) for attribute fallbacks
        waits = {p: wait_matrix[p]["all"] for p in WAIT_PERIODS}

        zones_out.append({
            "id": loc_id,
            "name": row["zone_name"],
            "borough": row["borough"],
            "path": path_d,
            "dominant_type": dom_type,
            "type_share_pct": round(float(type_share), 1) if type_share is not None else None,
            "dominant_aggregator": dom_agg,
            "agg_share_pct": round(float(agg_share), 1) if agg_share is not None else None,
            "avg_wait_sec": all_w["med_wait_sec"],
            "med_wait_sec": all_w["med_wait_sec"],
            "wait_n_trips": all_w["n_trips"],
            "wait_by_period": {p: {"med_wait_sec": waits[p]["med_wait_sec"],
                                   "n_trips": waits[p]["n_trips"]} for p in WAIT_PERIODS},
            "wait_matrix": wait_matrix,
            "annual_trips": int(vol) if vol is not None else None,
            "dist_to_subway_m": round(float(dist), 0) if dist is not None else None,
            "fill_dominant_type": TAXI_TYPE_COLORS.get(dom_type, NO_DATA_COLOR),
            "fill_dominant_aggregator": AGGREGATOR_COLORS.get(dom_agg, NO_DATA_COLOR),
            "fill_wait": all_w["fill"],
            "fill_wait_all": waits["all"]["fill"],
            "fill_wait_morning": waits["morning"]["fill"],
            "fill_wait_day": waits["day"]["fill"],
            "fill_wait_evening": waits["evening"]["fill"],
            "fill_wait_night": waits["night"]["fill"],
            "fill_volume": interpolate_color(vol, vol_lo, vol_hi, VOLUME_STOPS) if vol is not None else NO_DATA_COLOR,
        })
    print(f"  {len(zones_out)} zones with geometry ({n_no_geom} skipped, no polygon)")

    print("projecting subway lines...")
    subway_raw = json.load(open("subway_lines.geojson", encoding="utf-8"))
    subway_lines = []
    for key, (services, color, label) in SUBWAY_GROUPS.items():
        feats = [f for f in subway_raw["features"] if f["properties"]["service"] in services]
        parts = []
        for f in feats:
            geom = f["geometry"]
            lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            for line in lines:
                pts = [project(lon, lat) for lon, lat in line]
                if len(pts) < 2:
                    continue
                parts.append(f"M{pts[0][0]},{pts[0][1]}" + "".join(f"L{x},{y}" for x, y in pts[1:]))
        if parts:
            subway_lines.append({"key": key, "label": label, "color": color, "path": "".join(parts)})
    print(f"  {len(subway_lines)} line groups")

    print("projecting subway stations...")
    stations_df = con.execute('SELECT station_name, lat, lon FROM pg.subway_stations').fetchdf()
    stations = []
    for _, r in stations_df.iterrows():
        x, y = project(r["lon"], r["lat"])
        stations.append({"name": r["station_name"], "x": x, "y": y})
    print(f"  {len(stations)} stations")

    print("building context land (neighbor counties, monochrome)...")
    ctx_fc = load_or_fetch_context_land()
    context_land = context_land_paths(ctx_fc)
    print(f"  {len(context_land)} context path(s)")

    out = {
        "view_w": round(VIEW_W, 1), "view_h": VIEW_H,
        "zones": zones_out,
        "context_land": context_land,
        "subway_lines": subway_lines,
        "subway_stations": stations,
        "min_wait_n": MIN_WAIT_N,
        "domains": {
            "wait_sec": [round(float(wait_lo), 0), round(float(wait_hi), 0)],
            "annual_trips": [round(float(vol_lo), 0), round(float(vol_hi), 0)],
        },
    }
    # Preserve timelapse blocks merged by other builders
    prev_path = Path("_map_v2_data.json")
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            for key in ("timelapse", "event_timelapse"):
                if key in prev:
                    out[key] = prev[key]
        except Exception:
            pass
    with open("_map_v2_data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("saved _map_v2_data.json")


if __name__ == "__main__":
    main()

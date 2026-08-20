"""Split subway_lines.geojson into one GeoJSON file per official MTA trunk-line
color group, for Grafana Geomap fixed-color layers (field-based categorical
color proved unreliable — see dashboard iteration notes).
"""
import json
import os

data = json.load(open("subway_lines.geojson", encoding="utf-8"))

GROUPS = {
    "red_1_2_3": (["1", "2", "3"], "#EE352E"),
    "green_4_5_6": (["4", "5", "5 Peak", "6"], "#00933C"),
    "purple_7": (["7"], "#B933AD"),
    "blue_A_C_E": (["A", "C", "E"], "#0039A6"),
    "orange_B_D_F_M": (["B", "D", "F", "M"], "#FF6319"),
    "lightgreen_G": (["G"], "#6CBE45"),
    "brown_J_Z": (["J", "Z"], "#996633"),
    "grey_L": (["L"], "#A7A9AC"),
    "yellow_N_Q_R_W": (["N", "Q", "R", "W"], "#FCCC0A"),
    "darkgrey_shuttles": (["SF", "SR", "ST"], "#808183"),
    "cyan_SIR": (["SIR"], "#00A1DE"),
}

out_dir = "grafana_provisioning/geojson"
os.makedirs(out_dir, exist_ok=True)

manifest = []
for key, (services, color) in GROUPS.items():
    feats = [f for f in data["features"] if f["properties"]["service"] in services]
    if not feats:
        print(f"  {key}: 0 features, skipped")
        continue
    fc = {"type": "FeatureCollection", "features": feats}
    fname = f"subway_{key}.geojson"
    with open(f"{out_dir}/{fname}", "w", encoding="utf-8") as f:
        json.dump(fc, f)
    manifest.append({"key": key, "file": fname, "color": color, "services": services, "n": len(feats)})
    print(f"  {key}: {len(feats)} features -> {fname} ({color})")

with open(f"{out_dir}/_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
print("done")

"""Topsoil properties from ISRIC SoilGrids v2.0 (250 m), for any point.

Values are converted with each layer's d_factor and depth-weighted over 0-30 cm.
The REST API is in beta and can be slow or down; responses are cached.
"""

from __future__ import annotations

from .http import get_json

URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = {
    "phh2o": "ph",               # pH in water
    "soc": "soc_g_kg",           # soil organic carbon, g/kg
    "nitrogen": "nitrogen_g_kg", # total nitrogen, g/kg
    "clay": "clay_pct",          # %
    "sand": "sand_pct",          # %
    "cec": "cec_cmol_kg",        # cation exchange capacity, cmol(c)/kg
}
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
SOURCE = "soilgrids_v2"


def parse(payload: dict) -> dict:
    out: dict[str, float | None] = {v: None for v in PROPERTIES.values()}
    for layer in payload["properties"]["layers"]:
        name = layer["name"]
        if name not in PROPERTIES:
            continue
        d_factor = layer["unit_measure"]["d_factor"] or 1
        total = weight = 0.0
        for depth in layer["depths"]:
            value = depth["values"].get("mean")
            if value is None:
                continue
            thickness = depth["range"]["bottom_depth"] - depth["range"]["top_depth"]
            total += (value / d_factor) * thickness
            weight += thickness
        out[PROPERTIES[name]] = round(total / weight, 3) if weight else None
    return out


def fetch_point(lat: float, lon: float) -> dict:
    payload = get_json(
        URL,
        {"lon": round(lon, 4), "lat": round(lat, 4), "property": list(PROPERTIES), "depth": DEPTHS, "value": "mean"},
        source=SOURCE,
        timeout=60,
    )
    return parse(payload)

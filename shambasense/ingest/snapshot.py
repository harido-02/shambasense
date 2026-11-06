"""Save and restore the real-data snapshot kept in data/real/.

The snapshot holds what the server needs to train and advise without calling slow outside APIs on
every start: county weather (NASA POWER), county topsoil (SoilGrids) and market prices. It is
refreshed by the GitHub workflow "Fetch open data" (.github/workflows/fetch-data.yml) and loaded by
`bootstrap` when SHAMBA_DEMO=0.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, db

log = logging.getLogger(__name__)

CLIMATE = "climate_daily.csv.gz"
SOIL = "soil_profile.csv"
LOCATIONS = "locations.csv"
META = "snapshot.json"


def default_dir() -> Path:
    return config.ROOT / "data" / "real"


def _none(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


def export(directory: str | Path | None = None) -> dict:
    """Write the county weather, soil and locations currently in the database."""
    out = Path(directory or default_dir())
    out.mkdir(parents=True, exist_ok=True)
    locs = db.read_df("SELECT id, kind, name, lat, lon, county_id FROM location WHERE kind = 'county' ORDER BY id")
    clim = db.read_df("SELECT location_id, date, rain_mm, tmean_c, tmax_c, tmin_c, source FROM climate_daily "
                      "WHERE location_id LIKE 'county:%' ORDER BY location_id, date")
    soil = db.read_df("SELECT * FROM soil_profile WHERE location_id LIKE 'county:%' ORDER BY location_id")
    if clim.empty:
        raise RuntimeError("no county weather in the database; run `ingest-live` first")
    locs.to_csv(out / LOCATIONS, index=False)
    clim.round({"rain_mm": 2, "tmean_c": 2, "tmax_c": 2, "tmin_c": 2}).to_csv(out / CLIMATE, index=False)
    soil.round(3).to_csv(out / SOIL, index=False)
    meta = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counties": sorted(locs["county_id"].dropna().tolist()),
            "weather_days": int(len(clim)),
            "weather_range": [str(clim["date"].min()), str(clim["date"].max())],
            "soil_locations": int(len(soil)),
            "sources": {"weather": "NASA POWER daily (community AG)", "soil": "SoilGrids v2.0, 0-30 cm"}}
    (out / META).write_text(json.dumps(meta, indent=2) + "\n")
    log.info("snapshot written to %s: %s", out, meta)
    return meta


def available(directory: str | Path | None = None) -> bool:
    d = Path(directory or default_dir())
    return (d / CLIMATE).exists() and (d / SOIL).exists() and (d / LOCATIONS).exists()


def load(directory: str | Path | None = None) -> dict:
    """Load county weather, soil and locations from the snapshot into the database."""
    d = Path(directory or default_dir())
    if not available(d):
        raise FileNotFoundError(f"no weather/soil snapshot in {d}; run the 'Fetch open data' workflow")
    locs = pd.read_csv(d / LOCATIONS)
    for r in locs.itertuples():
        db.upsert_location(r.id, r.kind, r.name, float(r.lat), float(r.lon), _none(r.county_id))
    clim = pd.read_csv(d / CLIMATE, parse_dates=["date"])
    clim["date"] = clim["date"].dt.date
    days = 0
    for loc_id, part in clim.groupby("location_id"):
        records = [{k: _none(v) for k, v in rec.items()} for rec in part.to_dict("records")]
        days += db.replace_rows(db.ClimateDaily, {"location_id": loc_id}, records)
    soil = pd.read_csv(d / SOIL)
    for rec in soil.to_dict("records"):
        db.replace_rows(db.SoilProfile, {"location_id": rec["location_id"]}, [{k: _none(v) for k, v in rec.items()}])
    log.info("snapshot loaded from %s: %d locations, %d weather days, %d soil profiles", d, len(locs), days, len(soil))
    return {"locations": int(len(locs)), "weather_days": days, "soil_profiles": int(len(soil))}

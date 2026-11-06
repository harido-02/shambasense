"""Fetch open data for counties (training) and for any point a farmer picks (prediction)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config, db
from . import nasa_power, soilgrids

log = logging.getLogger(__name__)


def _climate_records(frame: pd.DataFrame, loc_id: str, source: str) -> list[dict]:
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    out = []
    for rec in frame.to_dict("records"):
        out.append({k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
                   | {"location_id": loc_id, "source": source})
    return out


def latest_weather_day() -> date:
    """NASA POWER publishes daily data with a few days' delay; never ask for days that do not exist yet."""
    return date.today() - timedelta(days=7)


def ingest_county(county_id: str, start_year: int | None = None, end_year: int | None = None) -> dict:
    """Average NASA POWER weather and SoilGrids soil over a county's reference points."""
    cfg = config.counties()[county_id]
    s = config.settings()["climate"]
    start = date(start_year or s["start_year"], 1, 1)
    end = min(date(end_year or s["end_year"], 12, 31), latest_weather_day())
    points = cfg.get("reference_points", [[cfg["lat"], cfg["lon"]]])

    # Several reference points can share one POWER grid cell; fetch each cell once.
    cells = sorted({nasa_power.grid_cell(lat, lon) for lat, lon in points})
    frames = [nasa_power.fetch_daily(lat, lon, start, end).set_index("date") for lat, lon in cells]
    climate = pd.concat(frames).groupby(level=0).mean().reset_index()

    soils = []
    for lat, lon in points:
        try:
            soils.append(soilgrids.fetch_point(lat, lon))
        except RuntimeError as exc:
            log.warning("SoilGrids failed for %s (%s, %s): %s", county_id, lat, lon, exc)
    soil = {k: float(np.nanmean([p[k] for p in soils if p.get(k) is not None]))
            if any(p.get(k) is not None for p in soils) else None
            for k in soilgrids.PROPERTIES.values()}

    loc_id = f"county:{county_id}"
    db.upsert_location(loc_id, "county", cfg["name"], cfg["lat"], cfg["lon"], county_id)
    n = db.replace_rows(db.ClimateDaily, {"location_id": loc_id}, _climate_records(climate, loc_id, "NASA POWER"))
    db.replace_rows(db.SoilProfile, {"location_id": loc_id},
                    [{"location_id": loc_id, **soil, "source": f"SoilGrids v2.0 ({len(soils)} points)"}])
    log.info("%s: %d days of weather from %d grid cell(s); soil from %d point(s)", county_id, n, len(cells), len(soils))
    return {"county": county_id, "days": n, "grid_cells": len(cells), "soil_points": len(soils)}


def ingest_point(lat: float, lon: float, county_id: str | None) -> tuple[str, str]:
    """Fetch and store weather (by POWER grid cell) and soil (by 0.01 degree point).

    Returns (climate_location_id, soil_location_id). Raises on network failure.
    """
    s = config.settings()["climate"]
    glat, glon = nasa_power.grid_cell(lat, lon)
    clim_id = f"grid:{glat:.3f}_{glon:.3f}"
    if db.read_df("SELECT 1 FROM climate_daily WHERE location_id = :l LIMIT 1", {"l": clim_id}).empty:
        frame = nasa_power.fetch_daily(glat, glon, date(s["start_year"], 1, 1),
                                       min(date(s["end_year"], 12, 31), latest_weather_day()))
        db.upsert_location(clim_id, "grid", f"POWER cell {glat}, {glon}", glat, glon, county_id)
        db.replace_rows(db.ClimateDaily, {"location_id": clim_id}, _climate_records(frame, clim_id, "NASA POWER"))

    soil_id = f"pt:{lat:.2f}_{lon:.2f}"
    if db.soil_dict(soil_id) is None:
        soil = soilgrids.fetch_point(lat, lon)
        if all(v is None for v in soil.values()):
            raise RuntimeError("SoilGrids has no data here (water, town or rock?)")
        db.upsert_location(soil_id, "grid", f"Point {lat:.2f}, {lon:.2f}", lat, lon, county_id)
        db.replace_rows(db.SoilProfile, {"location_id": soil_id}, [{"location_id": soil_id, **soil, "source": "SoilGrids v2.0"}])
    return clim_id, soil_id

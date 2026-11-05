"""Resolve a farmer's location to the weather and soil data used for advice."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .. import config, db
from ..features.climate import DailySeries
from ..features.dataset import county_climate_frame
from ..ingest import live
from ..ingest.loaders import nearest_county

log = logging.getLogger(__name__)


@dataclass
class Site:
    county_id: str
    lat: float
    lon: float
    distance_km: float
    in_study_area: bool
    series: DailySeries
    soil: dict
    data_level: str          # "point" or "county"
    note: str | None = None


def resolve(lat: float | None = None, lon: float | None = None, county_id: str | None = None) -> Site:
    rec = config.settings()["recommendation"]
    counties = config.counties()
    if lat is None or lon is None:
        if county_id not in counties:
            raise ValueError("give a latitude and longitude, or one of the counties: " + ", ".join(counties))
        cfg = counties[county_id]
        return _county_site(county_id, cfg["lat"], cfg["lon"], 0.0, None)

    nearest, dist = nearest_county(lat, lon)
    county_id = county_id if county_id in counties else nearest
    in_area = dist <= rec["study_area_radius_km"]
    if dist <= rec["same_site_km"]:
        return _county_site(county_id, lat, lon, dist, None)
    if config.demo_mode():
        site = _county_site(county_id, lat, lon, dist, None)
        site.in_study_area = in_area
        return site

    try:
        clim_id, soil_id = live.ingest_point(lat, lon, county_id)
        frame = db.climate_df(clim_id)
        soil = db.soil_dict(soil_id) or db.soil_dict(f"county:{county_id}") or {}
        site = Site(county_id, lat, lon, dist, in_area, DailySeries.from_frame(frame), soil, "point")
    except Exception as exc:  # noqa: BLE001 - any failure falls back to county data
        log.info("point data unavailable for %.3f, %.3f: %s", lat, lon, exc)
        name = counties[county_id]["name"]
        site = _county_site(county_id, lat, lon, dist,
                            f"Live weather and soil data for this exact point were unavailable, "
                            f"so {name} county averages were used.")
    site.in_study_area = in_area
    return site


def _county_site(county_id: str, lat: float, lon: float, dist: float, note: str | None) -> Site:
    frame = county_climate_frame(county_id)
    if frame.empty:
        raise RuntimeError(f"no weather data loaded for {county_id}; run `ingest-live` or `ingest-sample`")
    soil = db.soil_dict(f"county:{county_id}") or {}
    return Site(county_id, lat, lon, dist, True, DailySeries.from_frame(frame), soil, "county", note)

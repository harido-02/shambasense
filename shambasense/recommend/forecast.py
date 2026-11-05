"""Seasonal outlook as tercile probabilities, from KMD, ECMWF SEAS5, or climatology."""

from __future__ import annotations

import logging

import pandas as pd

from .. import config, db
from ..features.climate import season_window
from ..ingest import open_meteo

log = logging.getLogger(__name__)
EQUAL = {"p_below": 1 / 3, "p_normal": 1 / 3, "p_above": 1 / 3}


def outlook(county_id: str, season: str, year: int, lat: float, lon: float, clim: pd.DataFrame) -> dict:
    fc_cfg = config.settings()["forecast"]
    season_cfg = config.counties()[county_id]["seasons"][season]
    for source in fc_cfg["priority"]:
        if source == "kmd":
            rows = db.read_df("SELECT p_below, p_normal, p_above, source, issued_on FROM seasonal_outlook "
                              "WHERE county_id = :c AND year = :y AND season = :s",
                              {"c": county_id, "y": year, "s": season})
            if not rows.empty:
                r = rows.iloc[0]
                return {"source": r["source"], "p_below": float(r["p_below"]), "p_normal": float(r["p_normal"]),
                        "p_above": float(r["p_above"]), "issued_on": None if pd.isna(r["issued_on"]) else str(r["issued_on"])}
        elif source == "open_meteo" and not config.offline():
            try:
                members = open_meteo.fetch_members(lat, lon, fc_cfg["open_meteo_forecast_days"])
                probs = open_meteo.tercile_probabilities(
                    members, season_window(year, season_cfg["outlook_months"]),
                    clim.attrs["lower_mm"], clim.attrs["upper_mm"], fc_cfg["open_meteo_trust"])
                if probs:
                    return {"source": "ECMWF SEAS5 via Open-Meteo (not bias-corrected; tilted toward equal odds)", **probs}
            except Exception as exc:  # noqa: BLE001
                log.info("Open-Meteo forecast unavailable: %s", exc)
        elif source == "climatology":
            break
    return {"source": "climatology (no seasonal forecast available; all past seasons weighted equally)", **EQUAL}


def analog_weights(categories: pd.Series, fc: dict) -> pd.Series:
    """Weight each past season by the forecast probability of its tercile, shared within the tercile."""
    probs = {0: fc["p_below"], 1: fc["p_normal"], 2: fc["p_above"]}
    counts = categories.value_counts()
    w = categories.map(lambda c: probs[c] / counts[c])
    return w / w.sum()

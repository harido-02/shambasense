"""ECMWF SEAS5 seasonal forecast through the Open-Meteo Seasonal API.

The forecast is not bias-corrected, so it is only used to tilt the odds of a
below-, near- or above-normal season, and the tilt is shrunk toward equal odds
by `forecast.open_meteo_trust` in settings.yaml. A KMD outlook takes priority.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .http import get_json

URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
SOURCE = "open_meteo_seas5"


def parse_members(payload: dict, variable: str = "precipitation_sum") -> pd.DataFrame:
    """One column per ensemble member (the control plus *_memberNN), indexed by date."""
    daily = payload["daily"]
    cols = {k: v for k, v in daily.items() if k == variable or k.startswith(variable + "_member")}
    frame = pd.DataFrame(cols, index=pd.to_datetime(daily["time"])).astype(float)
    return frame


def fetch_members(lat: float, lon: float, forecast_days: int = 210) -> pd.DataFrame:
    params = {"latitude": round(lat, 3), "longitude": round(lon, 3), "daily": "precipitation_sum",
              "forecast_days": forecast_days, "timezone": "Africa/Nairobi"}
    try:
        payload = get_json(URL, params, source=SOURCE, ttl_days=1)
    except RuntimeError:
        params["forecast_days"] = 183     # documented default of six months
        payload = get_json(URL, params, source=SOURCE, ttl_days=1)
    return parse_members(payload)


def tercile_probabilities(members: pd.DataFrame, window: tuple[date, date], lower: float, upper: float,
                          trust: float) -> dict | None:
    """Share of members with a season total below `lower`, between, or above `upper`.

    Returns None when the forecast does not cover at least 90% of the window.
    """
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    span = members.loc[(members.index >= start) & (members.index <= end)]
    needed = (end - start).days + 1
    if len(span) < 0.9 * needed or span.empty:
        return None
    totals = span.sum(axis=0, skipna=True).to_numpy()
    p_below = float(np.mean(totals < lower))
    p_above = float(np.mean(totals > upper))
    p_normal = 1.0 - p_below - p_above
    shrunk = [trust * p + (1 - trust) / 3 for p in (p_below, p_normal, p_above)]
    return {"p_below": round(shrunk[0], 3), "p_normal": round(shrunk[1], 3), "p_above": round(shrunk[2], 3),
            "members": int(len(totals)), "median_total_mm": round(float(np.median(totals)), 1)}

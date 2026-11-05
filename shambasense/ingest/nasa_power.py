"""Daily weather from NASA POWER (community AG), for any point.

Publications using these data must include: "These data were obtained from the
NASA Langley Research Center POWER Project funded through the NASA Earth
Science Directorate Applied Science Program."
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .http import get_json

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = {
    "PRECTOTCORR": "rain_mm",   # precipitation, bias-corrected (mm/day)
    "T2M": "tmean_c",
    "T2M_MAX": "tmax_c",
    "T2M_MIN": "tmin_c",
}
SOURCE = "nasa_power"


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    """Centre of the 0.5 x 0.625 degree MERRA-2 cell that POWER weather comes from."""
    glat = round(round(lat / 0.5) * 0.5, 3)
    glon = round(round(lon / 0.625) * 0.625, 3)
    return glat, glon


def parse(payload: dict) -> pd.DataFrame:
    params = payload["properties"]["parameter"]
    fill = payload.get("header", {}).get("fill_value", -999.0)
    frame = pd.DataFrame({PARAMETERS[k]: pd.Series(v) for k, v in params.items() if k in PARAMETERS})
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
    frame = frame.replace(fill, np.nan).astype(float)
    frame[frame <= -998] = np.nan
    frame.loc[frame["rain_mm"] < 0, "rain_mm"] = np.nan
    return frame.rename_axis("date").reset_index()


def fetch_daily(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Daily rain_mm, tmean_c, tmax_c, tmin_c between start and end (inclusive)."""
    payload = get_json(
        URL,
        {
            "parameters": ",".join(PARAMETERS),
            "community": "AG",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        },
        source=SOURCE,
    )
    return parse(payload)

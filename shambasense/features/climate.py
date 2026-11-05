"""Season windows, onset of rains and growing-period weather features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config


@dataclass
class DailySeries:
    """Daily weather as numpy arrays for fast window slicing."""

    dates: np.ndarray       # datetime64[D], sorted, contiguous after reindexing
    rain: np.ndarray
    tmean: np.ndarray
    tmax: np.ndarray
    tmin: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "DailySeries":
        if frame.empty:
            raise ValueError("no weather data for this location")
        f = frame.copy()
        f["date"] = pd.to_datetime(f["date"])
        f = f.set_index("date").sort_index()
        f = f[~f.index.duplicated()]
        full = pd.date_range(f.index.min(), f.index.max(), freq="D")
        f = f.reindex(full)
        col = lambda name: f[name].to_numpy(dtype=float) if name in f else np.full(len(f), np.nan)  # noqa: E731
        return cls(full.to_numpy().astype("datetime64[D]"), col("rain_mm"), col("tmean_c"), col("tmax_c"), col("tmin_c"))

    @property
    def first(self) -> date:
        return pd.Timestamp(self.dates[0]).date()

    @property
    def last(self) -> date:
        return pd.Timestamp(self.dates[-1]).date()

    def index_of(self, day: date) -> int:
        return int((np.datetime64(day, "D") - self.dates[0]).astype(int))

    def covers(self, start: date, end: date) -> bool:
        return start >= self.first and end <= self.last


def longest_run(mask: np.ndarray) -> int:
    best = run = 0
    for flag in mask:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def season_window(year: int, months: list[int]) -> tuple[date, date]:
    """First and last day of a list of consecutive months; wraps into the next year if needed."""
    start = date(year, months[0], 1)
    end_year = year + (1 if months[-1] < months[0] else 0)
    last_month = months[-1]
    end = (date(end_year + (last_month == 12), (last_month % 12) + 1, 1) - timedelta(days=1))
    return start, end


def onset_search_start(year: int, season_cfg: dict) -> date:
    month, day = (int(x) for x in season_cfg["onset_start"].split("-"))
    return date(year, month, day)


def detect_onset(series: DailySeries, start: date, cfg: dict | None = None) -> date | None:
    """First wet spell after `start` not followed by a long dry spell (agronomic onset)."""
    cfg = cfg or config.settings()["onset"]
    if not series.covers(start, start + timedelta(days=cfg["search_days"] + cfg["check_days"])):
        return None
    i0 = series.index_of(start)
    rain = np.nan_to_num(series.rain, nan=0.0)
    for i in range(i0, i0 + cfg["search_days"]):
        if rain[i] < cfg["dry_day_mm"] or rain[i:i + cfg["wet_days"]].sum() < cfg["wet_mm"]:
            continue
        following = rain[i + 1:i + 1 + cfg["check_days"]]
        if longest_run(following < cfg["dry_day_mm"]) < cfg["dry_spell_days"]:
            return pd.Timestamp(series.dates[i]).date()
    return None


def window_features(series: DailySeries, start: date, days: int) -> dict:
    """Weather over a crop's growing period [start, start + days)."""
    end = start + timedelta(days=days - 1)
    if not series.covers(start, end):
        return {"coverage": 0.0}
    i, j = series.index_of(start), series.index_of(end) + 1
    rain = series.rain[i:j]
    valid = ~np.isnan(rain)
    with np.errstate(all="ignore"):
        return {
            "rain_mm": float(np.nansum(rain)),
            "rain_days": int(np.sum(rain[valid] >= 1.0)),
            "max_dry_spell": int(longest_run(np.nan_to_num(rain, nan=0.0) < 1.0)),
            "tmean_c": float(np.nanmean(series.tmean[i:j])),
            "tmax_c": float(np.nanmean(series.tmax[i:j])),
            "tmin_c": float(np.nanmean(series.tmin[i:j])),
            "coverage": float(valid.mean()),
        }


def season_total(series: DailySeries, start: date, end: date) -> float | None:
    if not series.covers(start, end):
        return None
    i, j = series.index_of(start), series.index_of(end) + 1
    rain = series.rain[i:j]
    if np.isnan(rain).mean() > 0.1:
        return None
    return float(np.nansum(rain))


def climatology(series: DailySeries, season_cfg: dict) -> pd.DataFrame:
    """Per year: outlook-window rain total, its tercile, and the onset of rains.

    Columns: year, total_mm, category (0 below, 1 normal, 2 above), onset (date or NaT),
    onset_offset (days after the search start; search_days when no onset was found).
    """
    onset_cfg = config.settings()["onset"]
    rows = []
    for year in range(series.first.year, series.last.year + 1):
        start, end = season_window(year, season_cfg["outlook_months"])
        total = season_total(series, start, end)
        if total is None:
            continue
        search = onset_search_start(year, season_cfg)
        onset = detect_onset(series, search, onset_cfg)
        offset = (onset - search).days if onset else onset_cfg["search_days"]
        rows.append({"year": year, "total_mm": total, "onset": onset, "onset_offset": offset,
                     "onset_found": onset is not None})
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    lower, upper = np.percentile(table["total_mm"], [100 / 3, 200 / 3])
    table["category"] = np.where(table["total_mm"] < lower, 0, np.where(table["total_mm"] > upper, 2, 1))
    table.attrs["lower_mm"], table.attrs["upper_mm"] = float(lower), float(upper)
    found = table.loc[table["onset_found"], "onset_offset"]
    table.attrs["median_offset"] = float(found.median()) if len(found) else 30.0
    return table


def crop_window_start(year: int, season_cfg: dict, clim_row: dict | None, median_offset: float) -> date:
    """Planting date for a year: the onset when found, otherwise the typical onset."""
    search = onset_search_start(year, season_cfg)
    if clim_row and clim_row.get("onset_found"):
        return clim_row["onset"]
    return search + timedelta(days=int(round(median_offset)))

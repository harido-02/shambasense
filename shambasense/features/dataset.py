"""Build model features for a place, a season, a year and a crop; and the training table."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import config, db
from ..models import suitability
from .climate import DailySeries, climatology, crop_window_start, window_features

log = logging.getLogger(__name__)

SOIL_KEYS = ["ph", "soc_g_kg", "nitrogen_g_kg", "clay_pct", "sand_pct", "cec_cmol_kg"]


def county_climate_frame(county_id: str) -> pd.DataFrame:
    """County reference weather; KMD station data, where loaded, replaces POWER values day by day."""
    base = db.climate_df(f"county:{county_id}")
    stations = db.read_df("SELECT id FROM location WHERE kind = 'station' AND county_id = :c", {"c": county_id})
    if stations.empty:
        return base
    parts = [db.climate_df(sid) for sid in stations["id"]]
    parts = [p.set_index("date") for p in parts if not p.empty]
    if not parts:
        return base
    station_mean = pd.concat(parts).groupby(level=0).mean()
    if base.empty:
        return station_mean.reset_index()
    merged = station_mean.combine_first(base.set_index("date"))
    return merged.reset_index().rename(columns={"index": "date"})


def season_for(county_id: str, season: str) -> str:
    """Map 'annual' yields to the county's main season."""
    seasons = config.counties()[county_id]["seasons"]
    if season in seasons:
        return season
    return config.counties()[county_id]["main_season"]


def crop_features(series: DailySeries, clim: pd.DataFrame, soil: dict | None, county_id: str,
                  season: str, year: int, crop_id: str) -> dict | None:
    """Features for one crop grown in one season of one year at one place."""
    season_cfg = config.counties()[county_id]["seasons"][season]
    median_offset = clim.attrs.get("median_offset", 30.0)
    by_year = clim.attrs.get("_by_year")
    if by_year is None:   # one dict lookup per crop and year instead of a pandas filter
        by_year = {int(r["year"]): r for r in clim.to_dict("records")}
        clim.attrs["_by_year"] = by_year
    clim_row = by_year.get(int(year))
    start = crop_window_start(year, season_cfg, clim_row, median_offset)
    days = config.maturity_days(crop_id, county_id)
    feats = window_features(series, start, days)
    if feats.get("coverage", 0) < 0.9:
        return None
    offset = clim_row["onset_offset"] if clim_row else median_offset
    soil = soil or {}
    row = {
        "crop": crop_id,
        **{k: feats[k] for k in ("rain_mm", "rain_days", "max_dry_spell", "tmean_c", "tmax_c", "tmin_c")},
        "onset_delay_days": float(offset - median_offset),
        **{k: soil.get(k) for k in SOIL_KEYS},
    }
    suit = suitability.score(crop_id, row["rain_mm"], row["tmean_c"], row["ph"])
    row["suitability"] = suit["score"]
    row["_limiting"] = suit["limiting"]
    row["_planting_date"] = start
    row["_onset_found"] = bool(clim_row and clim_row.get("onset_found"))
    return row


def build_training_table() -> pd.DataFrame:
    """One row per (county, year, season, crop) yield with its weather and soil features."""
    yields = db.read_df("SELECT county_id, year, season, crop, yield_t_ha, source FROM crop_yield")
    if yields.empty:
        raise RuntimeError("no yields loaded; run `load-yields` (or `ingest-sample` for the demo)")
    rows = []
    for county_id, part in yields.groupby("county_id"):
        if county_id not in config.counties():
            continue
        frame = county_climate_frame(county_id)
        if frame.empty:
            log.warning("%s: no weather data; skipping %d yield rows", county_id, len(part))
            continue
        series = DailySeries.from_frame(frame)
        soil = db.soil_dict(f"county:{county_id}")
        clims: dict[str, pd.DataFrame] = {}
        for r in part.itertuples():
            if r.crop not in config.crops():
                continue
            season = season_for(county_id, r.season)
            if season not in clims:
                clims[season] = climatology(series, config.counties()[county_id]["seasons"][season])
            feats = crop_features(series, clims[season], soil, county_id, season, int(r.year), r.crop)
            if feats is None:
                log.warning("%s %s %s: weather incomplete; skipped", county_id, r.year, r.crop)
                continue
            rows.append({"county_id": county_id, "year": int(r.year), "season": season,
                         "yield_t_ha": float(r.yield_t_ha), "source": r.source, **feats})
    table = pd.DataFrame(rows)
    return table.drop(columns=[c for c in table.columns if c.startswith("_")])


def data_quality(table: pd.DataFrame) -> str:
    sources = " ".join(table["source"].astype(str).unique()).upper() if "source" in table else ""
    return "synthetic" if "SYNTHETIC" in sources else "real"


def describe_table(table: pd.DataFrame) -> dict:
    return {
        "rows": int(len(table)),
        "counties": sorted(table["county_id"].unique().tolist()),
        "crops": sorted(table["crop"].unique().tolist()),
        "years": [int(table["year"].min()), int(table["year"].max())],
        "missing_soil": int(table["ph"].isna().sum()),
        "data_quality": data_quality(table),
    }


def weighted_mean_row(rows: list[dict], weights: np.ndarray) -> dict:
    keys = [k for k in rows[0] if not k.startswith("_") and k != "crop"]
    out = {"crop": rows[0]["crop"]}
    for k in keys:
        vals = np.array([r[k] if r[k] is not None else np.nan for r in rows], dtype=float)
        mask = ~np.isnan(vals)
        out[k] = float(np.average(vals[mask], weights=weights[mask])) if mask.any() and weights[mask].sum() > 0 else None
    return out

"""Real county yields from HarvestStat Africa (FEWS NET compilation of Ministry of Agriculture statistics).

HarvestStat Africa harmonises FEWS NET Data Warehouse crop statistics to fixed boundaries; for Kenya
these are the 47 counties (2013 boundaries, applied to every year). Each record is one county, crop,
season and indicator (area in ha, production in t, yield in t/ha).

    Lee, D. et al. (2025). HarvestStat Africa - harmonized subnational crop statistics for
    sub-Saharan Africa. Scientific Data. Data: doi:10.5061/dryad.vq83bk42w; code and per-country
    files: github.com/HarvestStat/HarvestStat-Africa (MIT licence).

Only calendar-year ("Annual") records are used: they run from the 1970s to 2021 with one consistent
definition. Seasonal records exist for a few crops and recent years only, and their bean yields are
three to five times the annual figures for the same county, so they are left out.

Cleaning, in order (every dropped value is listed in the cleaning log with its reason):
1. years before the weather record starts are skipped (NASA POWER daily data begin in 1981);
2. yield = production / area where both are given, otherwise the reported yield;
3. values outside a plausible range for the crop are dropped (placeholders such as 1.0 t/ha for
   tomatoes, or 38.8 t/ha for green grams);
4. runs of the same value in three or more consecutive years keep only the first (gap filling);
5. values more than 3.5 robust standard deviations (median absolute deviation, on log yield) ABOVE
   the county-crop median are dropped. Unusually low values are kept: they are mostly real droughts
   (2000, 2009 ...), exactly what the model has to learn.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config
from .loaders import _store_yields, normalise_county

log = logging.getLogger(__name__)

SOURCE = "HarvestStat Africa (FEWS NET / MoALD county statistics)"

PRODUCTS = {"Maize": "maize", "Beans (mixed)": "beans", "Potato": "potatoes", "Sorghum": "sorghum",
            "Mung bean": "green_grams", "Tomato": "tomatoes"}

# Plausible county-average yields (t/ha). Generous on purpose: they catch placeholders and unit
# slips, not bad seasons. Kenyan county means sit well inside them.
PLAUSIBLE_T_HA = {"maize": (0.15, 8.0), "beans": (0.03, 2.5), "potatoes": (2.0, 40.0),
                  "sorghum": (0.1, 5.0), "green_grams": (0.05, 2.0), "tomatoes": (3.0, 80.0)}
FIRST_WEATHER_YEAR = 1981
ROBUST_Z = 3.5


def read(path: str | Path) -> pd.DataFrame:
    """A HarvestStat country file (adm_crop_production_KE.csv) or a subset of it with the same columns."""
    raw = pd.read_csv(path)
    raw = raw.drop(columns=[c for c in raw.columns if c.startswith("Unnamed")], errors="ignore")
    need = {"admin_1", "product", "season_name", "harvest_year", "indicator", "value"}
    missing = need - set(raw.columns)
    if missing:
        raise ValueError(f"not a HarvestStat file (missing columns: {', '.join(sorted(missing))})")
    return raw


def subset_for_study(raw: pd.DataFrame) -> pd.DataFrame:
    """The study counties and crops, every season and indicator (what data/real/ keeps)."""
    names = {cfg["name"] for cfg in config.counties().values()}
    return raw[raw["admin_1"].isin(names) & raw["product"].isin(PRODUCTS)].reset_index(drop=True)


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (yields, log): yields has county_id, year, crop, area_ha, production_t, yield_t_ha."""
    df = raw[raw["product"].isin(PRODUCTS) & (raw["season_name"] == "Annual")].copy()
    df["county_id"] = df["admin_1"].map(normalise_county)
    df["crop"] = df["product"].map(PRODUCTS)
    df = df[df["county_id"].notna()]
    wide = (df.pivot_table(index=["county_id", "crop", "harvest_year"], columns="indicator", values="value",
                           aggfunc="first").reset_index().rename(columns={"harvest_year": "year"}))
    for col in ("area", "production", "yield"):
        if col not in wide:
            wide[col] = np.nan
    computed = np.where((wide["area"] > 0) & (wide["production"] > 0), wide["production"] / wide["area"], np.nan)
    wide["yield_t_ha"] = np.where(np.isnan(computed), wide["yield"], computed)
    wide = wide.rename(columns={"area": "area_ha", "production": "production_t"})
    wide = wide[["county_id", "crop", "year", "area_ha", "production_t", "yield_t_ha"]].sort_values(
        ["county_id", "crop", "year"]).reset_index(drop=True)

    dropped: list[dict] = []

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal wide
        for r in wide[mask].itertuples():
            dropped.append({"county_id": r.county_id, "crop": r.crop, "year": int(r.year),
                            "yield_t_ha": round(float(r.yield_t_ha), 3) if pd.notna(r.yield_t_ha) else None,
                            "reason": reason})
        wide = wide[~mask].reset_index(drop=True)

    drop(wide["year"] < FIRST_WEATHER_YEAR, f"before {FIRST_WEATHER_YEAR} (no daily weather)")
    drop(wide["yield_t_ha"].isna() | (wide["yield_t_ha"] <= 0), "no yield")
    low = wide["crop"].map(lambda c: PLAUSIBLE_T_HA[c][0])
    high = wide["crop"].map(lambda c: PLAUSIBLE_T_HA[c][1])
    drop((wide["yield_t_ha"] < low) | (wide["yield_t_ha"] > high), "outside the plausible range for the crop")

    repeat = pd.Series(False, index=wide.index)
    for _, part in wide.groupby(["county_id", "crop"]):
        vals = part["yield_t_ha"].round(2).to_numpy()
        years = part["year"].to_numpy()
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[j + 1] == vals[i] and years[j + 1] == years[j] + 1:
                j += 1
            if j - i + 1 >= 3:
                repeat.loc[part.index[i + 1:j + 1]] = True
            i = j + 1
    drop(repeat, "same value repeated in consecutive years (gap filling)")

    outlier = pd.Series(False, index=wide.index)
    for _, part in wide.groupby(["county_id", "crop"]):
        if len(part) < 6:
            continue
        logs = np.log(part["yield_t_ha"])
        mad = 1.4826 * np.median(np.abs(logs - np.median(logs)))
        if mad > 0:
            outlier.loc[part.index] = (logs - np.median(logs)) / mad > ROBUST_Z
    drop(outlier, f"more than {ROBUST_Z} robust standard deviations above the county median")

    return wide, pd.DataFrame(dropped, columns=["county_id", "crop", "year", "yield_t_ha", "reason"])


def load(path: str | Path, log_path: str | Path | None = None) -> int:
    """Clean and store the yields; optionally write the cleaning log as CSV."""
    yields, dropped = clean(read(path))
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        dropped.to_csv(log_path, index=False)
    rows = {(r.county_id, int(r.year), "annual", r.crop): {
        "area_ha": r.area_ha, "production_t": r.production_t, "yield_t_ha": r.yield_t_ha, "source": SOURCE}
        for r in yields.itertuples()}
    n = _store_yields(rows, SOURCE)
    log.info("HarvestStat: %d yields stored, %d values dropped in cleaning", n, len(dropped))
    return n

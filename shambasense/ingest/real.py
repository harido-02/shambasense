"""Load the real-data snapshot in data/real/ (and replace any SYNTHETIC demo data first).

data/real/ holds:
  harveststat_kenya_study_counties.csv  county yields (HarvestStat Africa; FEWS NET / MoALD)
  climate_daily.csv.gz, soil_profile.csv, locations.csv, snapshot.json
                                        NASA POWER weather and SoilGrids soil, refreshed by the
                                        "Fetch open data" GitHub workflow
  wfp_food_prices_kenya.csv             WFP wholesale market prices (HDX), from the same workflow
  market_prices.csv                     other market prices (KAMIS layout), optional
  production_costs.csv                  production costs per crop, with sources (optional)
"""

from __future__ import annotations

import logging
from pathlib import Path

from .. import db
from . import harveststat, loaders, snapshot, wfp

log = logging.getLogger(__name__)

YIELDS = "harveststat_kenya_study_counties.csv"
PRICES = "market_prices.csv"
WFP = "wfp_food_prices_kenya.csv"
COSTS = "production_costs.csv"
SYNTHETIC_TABLES = ["climate_daily", "soil_profile", "crop_yield", "market_price", "production_cost",
                    "seasonal_outlook"]


def has_synthetic() -> bool:
    for table in ("climate_daily", "crop_yield"):
        found = db.read_df(f"SELECT 1 FROM {table} WHERE UPPER(source) LIKE '%SYNTHETIC%' LIMIT 1")
        if not found.empty:
            return True
    return False


def purge_synthetic() -> dict:
    from sqlalchemy import text

    removed = {}
    with db.engine().begin() as conn:
        for table in SYNTHETIC_TABLES:
            res = conn.execute(text(f"DELETE FROM {table} WHERE UPPER(source) LIKE '%SYNTHETIC%'"))
            removed[table] = res.rowcount
    log.info("removed SYNTHETIC rows: %s", removed)
    return removed


def available(directory: str | Path | None = None) -> bool:
    d = Path(directory or snapshot.default_dir())
    return snapshot.available(d) and (d / YIELDS).exists()


def load_all(directory: str | Path | None = None) -> dict:
    """Replace SYNTHETIC data with the snapshot: weather, soil, yields, and prices/costs when present."""
    d = Path(directory or snapshot.default_dir())
    out = {"purged": purge_synthetic() if has_synthetic() else {}}
    out.update(snapshot.load(d))
    out["yields"] = harveststat.load(d / YIELDS)
    if (d / WFP).exists() or (d / PRICES).exists():
        db.replace_rows(db.MarketPrice, {}, [])
    if (d / WFP).exists():
        out["prices_wfp"] = wfp.load(d / WFP)
    if (d / PRICES).exists():
        out["prices"] = loaders.load_kamis(d / PRICES)
    if (d / COSTS).exists():
        db.replace_rows(db.ProductionCost, {}, [])
        out["costs"] = loaders.load_costs(d / COSTS)
    return out


def needs_loading() -> bool:
    """True when the database is empty or still holds SYNTHETIC weather or yields."""
    def none(table: str) -> bool:
        return db.read_df(f"SELECT 1 FROM {table} LIMIT 1").empty

    d = snapshot.default_dir()
    missing = none("climate_daily") or none("crop_yield")
    missing |= (d / WFP).exists() and none("market_price")        # a half-finished earlier load
    missing |= (d / COSTS).exists() and none("production_cost")
    return missing or has_synthetic()

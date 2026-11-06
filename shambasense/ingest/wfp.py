"""Market prices from the World Food Programme (WFP VAM, published on HDX).

Wholesale prices only (the engine values a harvest at wholesale prices), converted to KES/kg.
A market within MARKET_RADIUS_KM of a study county's reference point counts as that county's market;
the rest count as national markets (the engine falls back to them when a county has no recent prices).
Source: World Food Programme, "Kenya - Food Prices", HDX dataset wfp-food-prices-for-kenya (CC BY-IGO).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from .. import config, db

log = logging.getLogger(__name__)

SOURCE = "WFP VAM market prices (HDX)"
MARKET_RADIUS_KM = 75
FIRST_YEAR = 2018
COMMODITIES = [  # (pattern on WFP commodity name, crop id); first match wins
    (r"flour", None),
    (r"^maize", "maize"),
    (r"^beans \(mung\)", "green_grams"),
    (r"^beans", "beans"),
    (r"^potatoes \(irish", "potatoes"),
    (r"^sorghum", "sorghum"),
    (r"^tomatoes", "tomatoes"),
]


def crop_for(commodity: str) -> str | None:
    name = str(commodity).strip().lower()
    for pattern, crop in COMMODITIES:
        if re.search(pattern, name):
            return crop
    return None


def county_for(lat: float, lon: float) -> str | None:
    from .loaders import nearest_county

    county, dist = nearest_county(float(lat), float(lon))
    return county if dist <= MARKET_RADIUS_KM else None


def prepare(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw = raw[~raw["date"].astype(str).str.startswith("#")]
    raw = raw[(raw["pricetype"] == "Wholesale") & (raw["currency"] == "KES")].copy()
    raw["crop"] = raw["commodity"].map(crop_for)
    raw = raw[raw["crop"].notna()]
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw[raw["date"].dt.year >= FIRST_YEAR]
    kg = raw["unit"].astype(str).str.extract(r"(\d+)\s*KG", flags=re.I, expand=False).astype(float)
    raw["kg"] = kg.where(kg.notna(), 1.0)
    raw.loc[raw["unit"].astype(str).str.upper() == "KG", "kg"] = 1.0
    raw["kes_kg"] = pd.to_numeric(raw["price"], errors="coerce") / raw["kg"]
    raw = raw[raw["kes_kg"] > 0]
    markets = raw[["market", "latitude", "longitude"]].drop_duplicates("market")
    county_of = {m.market: county_for(m.latitude, m.longitude) for m in markets.itertuples()}
    raw["county_id"] = raw["market"].map(county_of)
    # One value per market, crop and month (several bean or potato varieties -> their median).
    raw["month"] = raw["date"].dt.to_period("M").dt.to_timestamp() + pd.Timedelta(days=14)
    out = (raw.groupby(["county_id", "market", "crop", "month"], dropna=False)["kes_kg"].median()
           .reset_index().rename(columns={"month": "date", "kes_kg": "wholesale_kes_kg"}))
    return out


def load(path: str | Path) -> int:
    prices = prepare(path)
    records = [{"county_id": r.county_id if isinstance(r.county_id, str) else None, "market": str(r.market)[:64],
                "crop": r.crop, "date": r.date.date(), "wholesale_kes_kg": round(float(r.wholesale_kes_kg), 2),
                "retail_kes_kg": None, "source": SOURCE} for r in prices.itertuples()]
    n = db.replace_rows(db.MarketPrice, {"source": SOURCE}, records)
    counties = sorted({r["county_id"] for r in records if r["county_id"]})
    log.info("WFP: %d monthly wholesale prices (county markets for %s)", n, ", ".join(counties) or "none")
    return n

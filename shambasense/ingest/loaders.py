"""Loaders for agency files: KilimoSTAT yields, KMD stations, KAMIS prices, costs, outlooks.

Agency exports change format often, so column matching is case-insensitive and
tolerant of extra columns. Every loader returns the rows it stored and logs
anything it had to skip, so nothing disappears silently.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config, db

log = logging.getLogger(__name__)

CROP_ALIASES = {
    "maize": ["maize", "dry maize", "maize (dry)", "maize grain", "corn"],
    "beans": ["beans", "dry beans", "bean", "common beans", "beans (dry)"],
    "potatoes": ["irish potatoes", "irish potato", "potatoes", "potato", "irish potatos"],
    "sorghum": ["sorghum"],
    "green_grams": ["green grams", "green gram", "greengrams", "greengram", "mung beans", "mung bean", "ndengu"],
    "tomatoes": ["tomatoes", "tomato"],
}

# Conversion of production units to tonnes.
PRODUCTION_TO_T = {"tonnes": 1, "tonne": 1, "tons": 1, "ton": 1, "mt": 1, "t": 1, "kg": 0.001, "kgs": 0.001,
                   "90 kg bags": 0.09, "90kg bags": 0.09, "90 kg bag": 0.09, "bags (90kg)": 0.09,
                   "50 kg bags": 0.05, "50kg bags": 0.05}
AREA_TO_HA = {"ha": 1, "hectares": 1, "hectare": 1, "acres": 0.404686, "acre": 0.404686}
YIELD_TO_T_HA = {"t/ha": 1, "tonnes/ha": 1, "tons/ha": 1, "mt/ha": 1, "tonnes per ha": 1, "kg/ha": 0.001}


def normalise_crop(name) -> str | None:
    if not isinstance(name, str):
        return None
    key = name.strip().lower()
    for crop_id, aliases in CROP_ALIASES.items():
        if key == crop_id or key in aliases:
            return crop_id
    return None


def normalise_county(name) -> str | None:
    if not isinstance(name, str):
        return None
    key = re.sub(r"\s+county$", "", name.strip().lower()).replace("-", " ").replace("_", " ")
    for county_id, cfg in config.counties().items():
        if key in (county_id.replace("_", " "), cfg["name"].lower()):
            return county_id
    return None


def _season(text) -> str:
    text = str(text or "").lower()
    if "long" in text:
        return "long_rains"
    if "short" in text:
        return "short_rains"
    return "annual"


def _col(frame: pd.DataFrame, *names: str) -> str | None:
    lower = {c.lower().strip(): c for c in frame.columns}
    for name in names:
        if name in lower:
            return lower[name]
    for name in names:
        for key, original in lower.items():
            if name in key:
                return original
    return None


def _number(value) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return float(value)
    match = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    return float(match.group().replace(",", "")) if match else np.nan


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".json":
        payload = json.loads(path.read_text())
        if isinstance(payload, dict):
            for key in ("data", "results", "records", "items"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        return pd.DataFrame(payload)
    return pd.read_csv(path)


# --------------------------------------------------------------------------- yields

def load_kilimostat(path: str | Path, source: str = "KilimoSTAT (MoALD)") -> int:
    """KilimoSTAT crop download: columns County, Element, Item, Value, Unit, Year[, Subdomain]."""
    raw = read_table(path)
    c_county, c_elem, c_item = _col(raw, "county"), _col(raw, "element"), _col(raw, "item")
    c_val, c_unit, c_year = _col(raw, "value"), _col(raw, "unit"), _col(raw, "year")
    c_sub = _col(raw, "subdomain")
    if not all([c_county, c_elem, c_item, c_val, c_year]):
        raise ValueError(f"KilimoSTAT file needs County, Element, Item, Value, Year columns; got {list(raw.columns)}")

    rows: dict[tuple, dict] = {}
    skipped = 0
    for _, r in raw.iterrows():
        county, crop = normalise_county(r[c_county]), normalise_crop(r[c_item])
        if not county or not crop:
            continue
        element = str(r[c_elem]).lower()
        unit = str(r[c_unit]).strip().lower() if c_unit else ""
        value = _number(r[c_val])
        if np.isnan(value):
            continue
        season = _season(f"{r[c_sub] if c_sub else ''} {element}")
        key = (county, int(_number(r[c_year])), season, crop)
        rec = rows.setdefault(key, {})
        if "yield" in element:
            factor = YIELD_TO_T_HA.get(unit)
            if factor is None:
                skipped += 1
                continue
            rec["yield_t_ha"] = value * factor
        elif "area" in element:
            rec["area_ha"] = value * AREA_TO_HA.get(unit, 1 if not unit else np.nan)
        elif "production" in element or "quantity" in element:
            factor = PRODUCTION_TO_T.get(unit, 1 if not unit else None)
            if factor is None:
                skipped += 1
                continue
            rec["production_t"] = value * factor
    if skipped:
        log.warning("KilimoSTAT: skipped %d values with unrecognised units", skipped)
    return _store_yields(rows, source)


def load_yields_csv(path: str | Path) -> int:
    """Generic template: county, year, season, crop, area_ha, production_t, yield_t_ha, source."""
    raw = read_table(path)
    rows: dict[tuple, dict] = {}
    for _, r in raw.iterrows():
        county, crop = normalise_county(r.get("county")), normalise_crop(r.get("crop"))
        if not county or not crop:
            log.warning("yields: skipped row with unknown county/crop: %s", dict(r))
            continue
        season = r.get("season") if r.get("season") in ("long_rains", "short_rains", "annual") else "annual"
        rows[(county, int(r["year"]), season, crop)] = {
            "area_ha": _number(r.get("area_ha")), "production_t": _number(r.get("production_t")),
            "yield_t_ha": _number(r.get("yield_t_ha")), "source": r.get("source") or "county report",
        }
    return _store_yields(rows, None)


def _store_yields(rows: dict[tuple, dict], source: str | None) -> int:
    stored = 0
    for (county, year, season, crop), rec in rows.items():
        y = rec.get("yield_t_ha")
        if (y is None or np.isnan(y)) and rec.get("area_ha") and rec.get("production_t"):
            y = rec["production_t"] / rec["area_ha"] if rec["area_ha"] > 0 else np.nan
        if y is None or np.isnan(y) or y <= 0:
            continue
        clean = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)  # noqa: E731
        db.replace_rows(db.CropYield, {"county_id": county, "year": year, "season": season, "crop": crop}, [{
            "county_id": county, "year": year, "season": season, "crop": crop,
            "area_ha": clean(rec.get("area_ha")), "production_t": clean(rec.get("production_t")),
            "yield_t_ha": float(y), "source": rec.get("source") or source,
        }])
        stored += 1
    log.info("yields: stored %d rows", stored)
    return stored


# --------------------------------------------------------------------------- KMD stations

def load_kmd_stations(path: str | Path) -> int:
    """KMD station file: station, lat, lon, date, rain_mm[, tmax_c, tmin_c, county]."""
    raw = read_table(path)
    c_station, c_lat, c_lon, c_date = _col(raw, "station"), _col(raw, "lat"), _col(raw, "lon"), _col(raw, "date")
    c_rain, c_tmax, c_tmin, c_county = _col(raw, "rain"), _col(raw, "tmax"), _col(raw, "tmin"), _col(raw, "county")
    stored = 0
    for station, part in raw.groupby(c_station):
        lat, lon = float(part[c_lat].iloc[0]), float(part[c_lon].iloc[0])
        county = normalise_county(part[c_county].iloc[0]) if c_county else None
        if county is None:
            county = nearest_county(lat, lon)[0]
        loc_id = "station:" + re.sub(r"[^a-z0-9]+", "_", str(station).lower()).strip("_")
        db.upsert_location(loc_id, "station", str(station), lat, lon, county)
        frame = pd.DataFrame({
            "date": pd.to_datetime(part[c_date]).dt.date,
            "rain_mm": part[c_rain].map(_number),
            "tmax_c": part[c_tmax].map(_number) if c_tmax else np.nan,
            "tmin_c": part[c_tmin].map(_number) if c_tmin else np.nan,
        })
        frame["tmean_c"] = (frame["tmax_c"] + frame["tmin_c"]) / 2
        records = [{**{k: (None if pd.isna(v) else v) for k, v in rec.items()}, "location_id": loc_id, "source": "KMD"}
                   for rec in frame.to_dict("records")]
        stored += db.replace_rows(db.ClimateDaily, {"location_id": loc_id}, records)
    return stored


# --------------------------------------------------------------------------- KAMIS prices

def load_kamis(path: str | Path) -> int:
    """KAMIS export: commodity, market, county, date, wholesale, retail (KES; per kg unless a unit says otherwise)."""
    raw = read_table(path)
    c_crop, c_market, c_county = _col(raw, "commodity", "product"), _col(raw, "market"), _col(raw, "county")
    c_date, c_whole, c_retail, c_unit = _col(raw, "date"), _col(raw, "wholesale"), _col(raw, "retail"), _col(raw, "unit")
    c_source = _col(raw, "source")
    records, skipped = [], 0
    for _, r in raw.iterrows():
        crop = normalise_crop(r[c_crop])
        county = normalise_county(r[c_county]) if c_county else None
        if not crop:
            continue
        per_kg = 1.0
        if c_unit:
            m = re.search(r"(\d+)\s*kg", str(r[c_unit]).lower())
            per_kg = float(m.group(1)) if m else 1.0
        whole = _number(r[c_whole]) / per_kg if c_whole else np.nan
        retail = _number(r[c_retail]) / per_kg if c_retail else np.nan
        if np.isnan(whole) and np.isnan(retail):
            skipped += 1
            continue
        records.append({"county_id": county, "market": str(r[c_market]) if c_market else None, "crop": crop,
                        "date": pd.to_datetime(r[c_date]).date(),
                        "wholesale_kes_kg": None if np.isnan(whole) else whole,
                        "retail_kes_kg": None if np.isnan(retail) else retail,
                        "source": str(r[c_source]) if c_source and pd.notna(r[c_source]) else "KAMIS"})
    if skipped:
        log.warning("prices: skipped %d rows without a price", skipped)
    sources = sorted({rec["source"] for rec in records})
    with db.session() as s, s.begin():
        if sources:
            s.query(db.MarketPrice).filter(db.MarketPrice.source.in_(sources)).delete(synchronize_session=False)
        if records:
            s.execute(db.insert(db.MarketPrice), records)
    return len(records)


# --------------------------------------------------------------------------- costs and outlooks

def load_costs(path: str | Path) -> int:
    """county, crop, cost_kes_ha or cost_kes_acre, source."""
    raw = read_table(path)
    records = []
    for _, r in raw.iterrows():
        crop = normalise_crop(r.get("crop"))
        if not crop:
            continue
        cost = _number(r.get("cost_kes_ha"))
        if np.isnan(cost):
            cost = _number(r.get("cost_kes_acre")) * 2.47105
        if np.isnan(cost):
            continue
        records.append({"county_id": normalise_county(r.get("county")), "crop": crop, "cost_kes_ha": cost,
                        "source": str(r.get("source") or "county agriculture office")[:128]})
    with db.session() as s, s.begin():
        s.query(db.ProductionCost).filter(~db.ProductionCost.source.like("SYNTHETIC%")).delete(synchronize_session=False)
    with db.session() as s, s.begin():
        s.add_all([db.ProductionCost(**rec) for rec in records])
    return len(records)


CATEGORY_PROBS = {  # used when an outlook gives only the most likely category
    "below": (0.45, 0.35, 0.20),
    "normal": (0.25, 0.50, 0.25),
    "near normal": (0.25, 0.50, 0.25),
    "above": (0.20, 0.35, 0.45),
}


def load_outlooks(path: str | Path) -> int:
    """county, year, season, p_below, p_normal, p_above (or category), source, issued_on."""
    raw = read_table(path)
    stored = 0
    for _, r in raw.iterrows():
        county = normalise_county(r.get("county"))
        if not county:
            continue
        probs = [_number(r.get(k)) for k in ("p_below", "p_normal", "p_above")]
        if any(np.isnan(p) for p in probs):
            cat = str(r.get("category", "")).strip().lower()
            cat = next((k for k in CATEGORY_PROBS if cat.startswith(k)), None)
            if not cat:
                continue
            probs = list(CATEGORY_PROBS[cat])
        total = sum(probs)
        probs = [p / total for p in probs]
        issued = r.get("issued_on")
        db.replace_rows(db.SeasonalOutlook, {"county_id": county, "year": int(r["year"]), "season": r["season"]}, [{
            "county_id": county, "year": int(r["year"]), "season": r["season"],
            "p_below": probs[0], "p_normal": probs[1], "p_above": probs[2],
            "source": r.get("source") or "KMD seasonal outlook",
            "issued_on": pd.to_datetime(issued).date() if isinstance(issued, str) and issued else None,
        }])
        stored += 1
    return stored


# --------------------------------------------------------------------------- geography

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(2 * 6371 * np.arcsin(np.sqrt(a)))


def nearest_county(lat: float, lon: float) -> tuple[str, float]:
    """County whose reference points are closest, and the distance in km."""
    best, best_d = None, float("inf")
    for county_id, cfg in config.counties().items():
        for plat, plon in cfg.get("reference_points", [[cfg["lat"], cfg["lon"]]]):
            d = haversine_km(lat, lon, plat, plon)
            if d < best_d:
                best, best_d = county_id, d
    return best, best_d

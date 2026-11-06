"""SYNTHETIC test data, so the whole system runs before real data arrives.

Everything written here is tagged source = "SYNTHETIC (test data)". A model
trained on it is flagged as synthetic in every API response and in the web app.
Never report results from this data.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .. import config, db
from ..features.climate import DailySeries, climatology
from ..features.dataset import crop_features

SOURCE = "SYNTHETIC (test data)"

# Rough monthly rainfall shapes (mm), Jan..Dec, loosely modelled on each county's pattern.
MONTHLY_MM = {
    "trans_nzoia": [25, 35, 75, 160, 170, 120, 150, 165, 110, 85, 55, 30],
    "nakuru": [30, 40, 65, 130, 110, 80, 95, 100, 65, 50, 60, 40],
    "meru": [40, 30, 110, 300, 150, 25, 20, 25, 25, 160, 250, 100],
    "machakos": [35, 25, 75, 170, 50, 5, 3, 3, 5, 70, 190, 100],
}
TMEAN_C = {"trans_nzoia": 19.0, "nakuru": 17.5, "meru": 19.5, "machakos": 21.0}
SOIL = {
    "trans_nzoia": {"ph": 5.6, "soc_g_kg": 18, "nitrogen_g_kg": 1.6, "clay_pct": 35, "sand_pct": 40, "cec_cmol_kg": 15},
    "nakuru": {"ph": 6.4, "soc_g_kg": 22, "nitrogen_g_kg": 1.9, "clay_pct": 30, "sand_pct": 40, "cec_cmol_kg": 20},
    "meru": {"ph": 5.4, "soc_g_kg": 28, "nitrogen_g_kg": 2.4, "clay_pct": 45, "sand_pct": 25, "cec_cmol_kg": 18},
    "machakos": {"ph": 6.5, "soc_g_kg": 9, "nitrogen_g_kg": 0.8, "clay_pct": 25, "sand_pct": 60, "cec_cmol_kg": 12},
}
POTENTIAL_T_HA = {"maize": 4.0, "beans": 1.2, "potatoes": 16.0, "sorghum": 2.0, "green_grams": 1.0, "tomatoes": 30.0}
PRICE_KES_KG = {"maize": 40, "beans": 110, "potatoes": 35, "sorghum": 50, "green_grams": 120, "tomatoes": 60}
COST_KES_HA = {"maize": 90_000, "beans": 70_000, "potatoes": 250_000, "sorghum": 60_000,
               "green_grams": 55_000, "tomatoes": 400_000}
NOT_GROWN = {("trans_nzoia", "green_grams"), ("nakuru", "green_grams"), ("machakos", "potatoes")}


def _climate(county_id: str, start: int, end: int, rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range(date(start, 1, 1), date(end, 12, 31), freq="D")
    monthly = np.array(MONTHLY_MM[county_id], dtype=float)
    # One wetness factor per year for each half of the year, so seasons vary as a whole.
    factors = {(y, h): rng.lognormal(0, 0.28) for y in range(start, end + 1) for h in (0, 1)}
    rain = np.zeros(len(days))
    for i, d in enumerate(days):
        mm = monthly[d.month - 1] * factors[(d.year, 0 if d.month <= 7 else 1)]
        p_wet = min(0.8, 0.08 + mm / 260)
        if rng.random() < p_wet:
            mean_amount = mm / (d.days_in_month * p_wet)
            rain[i] = rng.gamma(0.8, mean_amount / 0.8)
    doy = days.dayofyear.to_numpy()
    trend = (days.year.to_numpy() - start) * 0.02
    tmean = TMEAN_C[county_id] + 1.2 * np.sin(2 * np.pi * (doy - 30) / 365) + trend + rng.normal(0, 0.8, len(days))
    return pd.DataFrame({"date": days.date, "rain_mm": rain.round(1), "tmean_c": tmean.round(2),
                         "tmax_c": (tmean + 6.5).round(2), "tmin_c": (tmean - 6.0).round(2)})


def generate(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    s = config.settings()
    c_start = s["climate"].get("synthetic_start_year", s["climate"]["start_year"])
    c_end = min(s["climate"]["end_year"], 2025)
    y_start, y_end = s["yields"]["start_year"], s["yields"]["end_year"]
    counts = {"climate_days": 0, "yields": 0, "prices": 0}

    for county_id, cfg in config.counties().items():
        loc = f"county:{county_id}"
        db.upsert_location(loc, "county", cfg["name"], cfg["lat"], cfg["lon"], county_id)
        frame = _climate(county_id, c_start, c_end, rng)
        records = [{**r, "location_id": loc, "source": SOURCE} for r in frame.to_dict("records")]
        counts["climate_days"] += db.replace_rows(db.ClimateDaily, {"location_id": loc}, records)
        db.replace_rows(db.SoilProfile, {"location_id": loc}, [{"location_id": loc, **SOIL[county_id], "source": SOURCE}])

        # Yields follow the crop's suitability, soil fertility and dry spells, plus noise,
        # so the model has a real signal to learn and the evaluation means something.
        series = DailySeries.from_frame(frame)
        season = cfg["main_season"]
        clim = climatology(series, cfg["seasons"][season])
        soil = SOIL[county_id]
        fertility = 0.8 + 0.4 * min(soil["soc_g_kg"] / 25, 1.2)
        county_skill = rng.uniform(0.8, 1.1)
        rows = []
        for year in range(y_start, y_end + 1):
            for crop in config.crop_ids():
                if (county_id, crop) in NOT_GROWN:
                    continue
                f = crop_features(series, clim, soil, county_id, season, year, crop)
                if f is None:
                    continue
                dry_penalty = 1 - 0.012 * max(0, f["max_dry_spell"] - 10)
                y = (POTENTIAL_T_HA[crop] * county_skill * fertility * (0.3 + 0.7 * f["suitability"])
                     * max(dry_penalty, 0.5) * rng.lognormal(0, 0.1))
                rows.append({"county_id": county_id, "year": year, "season": "annual", "crop": crop,
                             "area_ha": None, "production_t": None, "yield_t_ha": round(float(y), 3), "source": SOURCE})
        counts["yields"] += db.replace_rows(db.CropYield, {"county_id": county_id}, rows)

        prices = []
        for month in pd.date_range("2019-01-01", "2025-12-01", freq="MS"):
            for crop, base in PRICE_KES_KG.items():
                seasonal = 1 + 0.15 * np.sin(2 * np.pi * (month.month - 3) / 12)
                whole = base * seasonal * rng.lognormal(0, 0.08) * (1 + 0.04 * (month.year - 2019))
                prices.append({"county_id": county_id, "market": cfg["markets"][0], "crop": crop,
                               "date": month.date(), "wholesale_kes_kg": round(float(whole), 1),
                               "retail_kes_kg": round(float(whole * 1.3), 1), "source": SOURCE})
        counts["prices"] += db.replace_rows(db.MarketPrice, {"county_id": county_id, "source": SOURCE}, prices)

    with db.session() as sess, sess.begin():
        sess.query(db.ProductionCost).filter(db.ProductionCost.source == SOURCE).delete()
        sess.add_all([db.ProductionCost(county_id=None, crop=c, cost_kes_ha=v, source=SOURCE)
                      for c, v in COST_KES_HA.items()])
    db.replace_rows(db.SeasonalOutlook, {"county_id": "machakos", "year": 2027, "season": "long_rains"}, [{
        "county_id": "machakos", "year": 2027, "season": "long_rains", "p_below": 0.45, "p_normal": 0.35,
        "p_above": 0.20, "source": SOURCE, "issued_on": None}])
    return counts

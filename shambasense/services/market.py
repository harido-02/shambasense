"""Market prices from KAMIS (or the synthetic demo data): monthly series and summaries."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config, db


def _prices(crop: str | None = None, county_id: str | None = None) -> pd.DataFrame:
    where, params = ["wholesale_kes_kg IS NOT NULL"], {}
    if crop:
        where.append("crop = :crop")
        params["crop"] = crop
    if county_id:
        where.append("county_id = :county")
        params["county"] = county_id
    df = db.read_df("SELECT county_id, market, crop, date, wholesale_kes_kg, source FROM market_price WHERE "
                    + " AND ".join(where), params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df


def series(crop: str, county_id: str | None = None, months: int = 36) -> dict:
    if crop not in config.crops():
        raise ValueError("unknown crop")
    df = _prices(crop, county_id)
    scope = "county"
    if df.empty and county_id:
        df, scope = _prices(crop), "national"
    if df.empty:
        return {"crop": crop, "county": county_id, "scope": "none", "points": [], "source": None}
    monthly = df.groupby("month")["wholesale_kes_kg"].median().sort_index()
    monthly = monthly[monthly.index > monthly.index.max() - pd.DateOffset(months=months)]
    latest = float(monthly.iloc[-1])
    year_ago = monthly.get(monthly.index[-1] - pd.DateOffset(months=12))
    return {
        "crop": crop, "county": county_id, "scope": scope if county_id else "national",
        "points": [{"month": m.strftime("%Y-%m"), "kes_kg": round(float(v), 1)} for m, v in monthly.items()],
        "latest_kes_kg": round(latest, 1), "latest_month": monthly.index[-1].strftime("%Y-%m"),
        "change_12m_pct": round((latest / float(year_ago) - 1) * 100, 1) if year_ago is not None and year_ago > 0 else None,
        "markets": sorted(df["market"].dropna().unique().tolist())[:5],
        "source": ", ".join(sorted(df["source"].dropna().unique())),
    }


def summary(county_id: str | None = None) -> list[dict]:
    out = []
    for crop_id, cfg in config.crops().items():
        s = series(crop_id, county_id, months=13)
        if not s["points"]:
            continue
        values = [p["kes_kg"] for p in s["points"]]
        out.append({"crop": crop_id, "name": cfg["name"], "latest_kes_kg": s["latest_kes_kg"],
                    "latest_month": s["latest_month"], "change_12m_pct": s["change_12m_pct"],
                    "spark": values, "scope": s["scope"], "source": s["source"],
                    "range_12m": [round(float(np.min(values)), 1), round(float(np.max(values)), 1)]})
    return out

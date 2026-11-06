"""Crop recommendation: analog seasons weighted by the forecast, run through the yield model.

For each past season at the location, the model predicts each crop's yield as if
that season's weather came again. Past seasons are weighted by how likely the
seasonal outlook makes their rainfall tercile, so the advice reflects both the
forecast and the full spread of outcomes the place has seen.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config, db
from ..features.climate import climatology, onset_search_start
from ..features.dataset import crop_features, weighted_mean_row
from ..models import suitability
from ..models.yield_model import GROUP_LABELS, YieldModel
from . import forecast as fc_mod
from . import location
from .i18n import day_month, t

log = logging.getLogger(__name__)
HA_PER_ACRE = 0.404686


def hash_user(identifier: str | None) -> str | None:
    if not identifier:
        return None
    return hashlib.sha256(("shambasense:" + identifier).encode()).hexdigest()[:32]


def next_year_for(county_id: str, season: str, today: date | None = None) -> int:
    """Year of the next `season` whose onset window has not long passed."""
    today = today or date.today()
    cfg = config.counties()[county_id]["seasons"][season]
    for year in (today.year, today.year + 1):
        if onset_search_start(year, cfg) >= today - timedelta(days=14):
            return year
    return today.year + 1


def default_season(county_id: str, today: date | None = None) -> tuple[str, int]:
    """The next season (of any kind) whose onset window has not long passed."""
    today = today or date.today()
    options = []
    for season, cfg in config.counties()[county_id]["seasons"].items():
        year = next_year_for(county_id, season, today)
        options.append((onset_search_start(year, cfg), season, year))
    _, season, year = min(options)
    return season, year


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> list[float]:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = (np.cumsum(w) - 0.5 * w) / w.sum()
    return [float(np.interp(q, cum, v)) for q in qs]


def _price(county_id: str, crop: str) -> tuple[float | None, str | None]:
    months = config.settings()["recommendation"]["price_lookback_months"]
    for scope, params in (("county", {"c": county_id, "k": crop}), ("national", {"k": crop})):
        where = "crop = :k AND county_id = :c" if scope == "county" else "crop = :k"
        df = db.read_df(f"SELECT date, market, wholesale_kes_kg FROM market_price WHERE {where} "
                        "AND wholesale_kes_kg IS NOT NULL", params)
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        recent = df[df["date"] > df["date"].max() - pd.DateOffset(months=months)]
        where_txt = ", ".join(sorted(recent["market"].dropna().unique())[:2]) if scope == "county" else "national markets"
        return float(recent["wholesale_kes_kg"].median()), where_txt or "local markets"
    return None, None


def _cost(county_id: str, crop: str) -> float | None:
    df = db.read_df("SELECT county_id, cost_kes_ha FROM production_cost WHERE crop = :k", {"k": crop})
    if df.empty:
        return None
    local = df[df["county_id"] == county_id]
    national = df[df["county_id"].isna()]
    chosen = local if not local.empty else national if not national.empty else df
    return float(chosen["cost_kes_ha"].median())


def recommend(lat: float | None = None, lon: float | None = None, county_id: str | None = None,
              season: str | None = None, year: int | None = None, lang: str = "en", channel: str = "api",
              forecast: dict | None = None, user: str | None = None, model: YieldModel | None = None,
              today: date | None = None, log_request: bool = True, user_id: int | None = None,
              farm_id: int | None = None) -> dict:
    lang = lang if lang in ("en", "sw") else "en"
    rec_cfg = config.settings()["recommendation"]
    site = location.resolve(lat, lon, county_id)
    county = config.counties()[site.county_id]
    if season is None:
        season, d_year = default_season(site.county_id, today)
        year = year or d_year
    if season not in county["seasons"]:
        raise ValueError(f"{county['name']} has no {season} season; choose from {list(county['seasons'])}")
    year = year or next_year_for(site.county_id, season, today)
    season_cfg = county["seasons"][season]

    # Scenarios: the most recent `analog_years` seasons (a climate normal), not the whole record.
    clim = climatology(site.series, season_cfg,
                       first_year=site.series.last.year - rec_cfg.get("analog_years", 30) + 1)
    if len(clim) < 8:
        raise RuntimeError("fewer than 8 seasons of weather data for this location")
    fc = forecast or fc_mod.outlook(site.county_id, season, year, site.lat, site.lon, clim)
    fc.setdefault("source", "user-supplied outlook")
    weights = fc_mod.analog_weights(clim["category"], fc).to_numpy()

    # ---------------------------------------------------------------- planting window
    search = onset_search_start(year, season_cfg)
    found = clim["onset_found"].to_numpy()
    planting = {"onset_found_pct": round(float(weights[found].sum() * 100))}
    if found.any():
        early, median, late = _weighted_quantile(clim.loc[found, "onset_offset"].to_numpy(dtype=float),
                                                 weights[found], [0.2, 0.5, 0.8])
        dates = {k: search + timedelta(days=int(round(v))) for k, v in (("early", early), ("median", median), ("late", late))}
        planting.update({k: v.isoformat() for k, v in dates.items()})
        planting["advice"] = t(lang, "plant_advice", **{k: day_month(v, lang) for k, v in dates.items()})
        if planting["onset_found_pct"] < 85:
            planting["advice"] += " " + t(lang, "no_onset", pct=100 - planting["onset_found_pct"])
        typical_planting = dates["median"]
    else:
        typical_planting = search + timedelta(days=30)
        planting["advice"] = t(lang, "no_onset", pct=100)

    # ---------------------------------------------------------------- per crop
    rng = np.random.default_rng(rec_cfg["random_seed"])
    n = rec_cfg["monte_carlo_samples"]
    results, not_suitable, warnings = [], [], []
    for crop_id, crop_cfg in config.crops().items():
        rows, w = [], []
        for i, y in enumerate(clim["year"]):
            f = crop_features(site.series, clim, site.soil, site.county_id, season, int(y), crop_id)
            if f is not None:
                rows.append(f)
                w.append(weights[i])
        if not rows:
            continue
        w = np.array(w) / np.sum(w)
        rep = weighted_mean_row(rows, w)
        suit = suitability.score(crop_id, rep["rain_mm"], rep["tmean_c"], rep["ph"])
        suit_score = float(np.dot([r["suitability"] for r in rows], w))
        name = crop_cfg["name"][lang]
        limiting_text = (suitability.describe(crop_id, suit["limiting"], rep[suit["limiting"]], lang)
                         if suit["limiting"] and rep.get(suit["limiting"]) is not None else None)
        if suit_score < rec_cfg["min_suitability"]:
            not_suitable.append({"crop": crop_id, "name": name, "suitability": round(suit_score, 2),
                                 "reason": limiting_text})
            continue

        days = config.maturity_days(crop_id, site.county_id)
        item = {"crop": crop_id, "name": name, "suitability": round(suit_score, 2),
                "limiting_factor": suit["limiting"], "days_to_maturity": days,
                "harvest_from": (typical_planting + timedelta(days=days)).isoformat(), "reasons": []}
        if limiting_text:
            item["reasons"].append(limiting_text)

        samples = None
        if model is not None and model.knows(crop_id):
            frame = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
            q = model.predict(frame)
            p10, p50, p90 = (q[c].to_numpy() for c in ("p10", "p50", "p90"))
            idx = rng.choice(len(rows), size=n, p=w)
            z = rng.standard_normal(n)
            lo, hi = (p50 - p10) / 1.2816, (p90 - p50) / 1.2816
            samples = np.clip(p50[idx] + np.where(z < 0, z * lo[idx], z * hi[idx]), 0, None)
            yq = np.percentile(samples, [10, 50, 90])
            item["yield_t_ha"] = {"p10": round(yq[0], 2), "p50": round(yq[1], 2), "p90": round(yq[2], 2)}
            if crop_cfg.get("bag_kg"):
                per_acre = [v * 1000 * HA_PER_ACRE / crop_cfg["bag_kg"] for v in yq]
                item["yield_bags_acre"] = {"p10": round(per_acre[0], 1), "p50": round(per_acre[1], 1),
                                           "p90": round(per_acre[2], 1), "bag_kg": crop_cfg["bag_kg"]}
            item["relative_yield"] = round(float(yq[1] / model.crop_mean[crop_id]), 2)
            for e in model.explain(rep, top=2):
                key = "effect_up" if e["effect_t_ha"] > 0 else "effect_down"
                digits = 2 if model.crop_mean[crop_id] < 3 else 1
                item["reasons"].append(t(lang, key, label=GROUP_LABELS[e["group"]][lang],
                                         v=f"{e['effect_t_ha']:+.{digits}f}"))
            if model.out_of_range(rep):
                item["reasons"].append(t(lang, "out_of_range"))
        else:
            item["reasons"].append(t(lang, "no_model"))

        price, where = _price(site.county_id, crop_id)
        cost = _cost(site.county_id, crop_id)
        if price is not None:
            item["price_kes_kg"] = round(price, 1)
            item["reasons"].append(t(lang, "price", price=price, where=where))
        if cost is not None:
            item["cost_kes_ha"] = round(cost)
        if samples is not None and price is not None and cost is not None:
            margin = samples * 1000 * price - cost
            mq = np.percentile(margin, [10, 50, 90])
            item["gross_margin_kes_ha"] = {"p10": round(mq[0]), "p50": round(mq[1]), "p90": round(mq[2])}
            item["gross_margin_kes_acre"] = {k: round(v * HA_PER_ACRE) for k, v in item["gross_margin_kes_ha"].items()}
            item["prob_loss"] = round(float(np.mean(margin < 0)), 2)
            item["reasons"].append(t(lang, "risk", pct=round(item["prob_loss"] * 100)))
        results.append(item)

    # ---------------------------------------------------------------- ranking
    # Agronomic fit and risk decide the tier; within a tier, expected gross margin
    # (or relative yield when prices or costs are missing) decides the order. This
    # stops a high-value but poorly suited crop topping the list on price alone.
    for r in results:
        risk = r.get("prob_loss", 0.0)
        r["tier"] = 0 if r["suitability"] >= 0.7 and risk < 0.2 else 1 if r["suitability"] >= 0.4 and risk < 0.4 else 2
        r["label"] = t(lang, ("label_high", "label_rec", "label_marginal")[r["tier"]])
    by_margin = bool(results) and all("gross_margin_kes_ha" in r for r in results)
    if by_margin:
        results.sort(key=lambda r: (r["tier"], -r["gross_margin_kes_ha"]["p50"]))
    else:
        results.sort(key=lambda r: (r["tier"], -r.get("relative_yield", 1.0) * r["suitability"]))
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    meta = (model.meta if model is not None else {}) or {}
    if meta.get("data_quality") == "synthetic":
        warnings.append(t(lang, "synthetic"))
    if not site.in_study_area:
        warnings.append(t(lang, "outside_area", km=site.distance_km, county=county["name"]))
    if site.note:
        warnings.append(site.note)

    response = {
        "location": {"lat": site.lat, "lon": site.lon, "county": site.county_id, "county_name": county["name"],
                     "distance_km": round(site.distance_km, 1), "in_study_area": site.in_study_area,
                     "data_level": site.data_level},
        "season": season, "season_name": t(lang, f"season_{season}"), "year": year,
        "forecast": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in fc.items()},
        "analog_seasons": int(len(clim)),
        "planting_window": planting,
        "ranked_by": ("suitability and risk tier, then expected gross margin (KES/ha)" if by_margin
                      else "suitability and risk tier, then expected relative yield"),
        "recommendations": results,
        "not_suitable": not_suitable,
        "warnings": warnings,
        "model": {"version": meta.get("version"), "trained_at": meta.get("trained_at"),
                  "data_quality": meta.get("data_quality", "none"),
                  "requirements_verified": all(c.get("verified") for c in config.crops().values())},
    }
    if log_request:
        response["log_id"] = _log(response, channel, hash_user(user), user_id, farm_id)
    return response


def _log(response: dict, channel: str, user_hash: str | None, user_id: int | None = None,
         farm_id: int | None = None) -> int | None:
    try:
        top = response["recommendations"][0]["crop"] if response["recommendations"] else None
        with db.session() as s, s.begin():
            row = db.RecommendationLog(channel=channel, user_hash=user_hash, lat=response["location"]["lat"],
                                       lon=response["location"]["lon"], county_id=response["location"]["county"],
                                       season=response["season"], year=response["year"], top_crop=top,
                                       response_json=json.dumps(response, default=str), user_id=user_id,
                                       farm_id=farm_id)
            s.add(row)
            s.flush()
            return row.id
    except Exception as exc:  # noqa: BLE001 - logging must never break advice
        log.warning("could not log recommendation: %s", exc)
        return None

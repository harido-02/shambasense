"""Rule-based crop suitability (FAO EcoCrop style).

Each factor scores 1 inside the optimum range, 0 outside the absolute range, and
falls linearly in between. The overall score is the lowest factor score (the
limiting factor, after Liebig's law of the minimum).
"""

from __future__ import annotations

import math

from .. import config

FACTORS = {
    "rain_mm": {"en": "Rainfall over the growing period", "sw": "Mvua wakati wa ukuaji", "unit": "mm"},
    "tmean_c": {"en": "Average temperature", "sw": "Wastani wa joto", "unit": "°C"},
    "ph": {"en": "Soil pH", "sw": "pH ya udongo", "unit": ""},
}


def trapezoid(value: float | None, r: dict) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value <= r["abs_min"] or value >= r["abs_max"]:
        return 0.0
    if r["opt_min"] <= value <= r["opt_max"]:
        return 1.0
    if value < r["opt_min"]:
        return (value - r["abs_min"]) / (r["opt_min"] - r["abs_min"])
    return (r["abs_max"] - value) / (r["abs_max"] - r["opt_max"])


def score(crop_id: str, rain_mm: float | None, tmean_c: float | None, ph: float | None) -> dict:
    """Overall score, per-factor scores and the limiting factor. Unknown factors are ignored."""
    cfg = config.crops()[crop_id]
    values = {"rain_mm": rain_mm, "tmean_c": tmean_c, "ph": ph}
    factor_scores = {k: trapezoid(v, cfg[k]) for k, v in values.items()}
    known = {k: s for k, s in factor_scores.items() if s is not None}
    if not known:
        return {"score": 0.5, "factors": factor_scores, "limiting": None}
    limiting = min(known, key=known.get)
    return {"score": round(known[limiting], 3), "factors": factor_scores, "limiting": limiting}


def describe(crop_id: str, factor: str, value: float, lang: str = "en") -> str:
    """Plain-language sentence comparing a value with the crop's requirement."""
    cfg = config.crops()[crop_id]
    r = cfg[factor]
    crop = cfg["name"][lang]
    crop = crop if crop.startswith("Irish") else crop.lower()   # keep proper nouns capitalised
    label = FACTORS[factor][lang]
    unit = FACTORS[factor]["unit"]
    shown = f"{value:.0f} {unit}".strip() if factor == "rain_mm" else f"{value:.1f}{unit}"
    opt = f"{r['opt_min']:g}–{r['opt_max']:g} {unit}".strip()
    if lang == "sw":
        if value < r["opt_min"]:
            return f"{label} ({shown}) iko chini ya kiwango bora cha {crop} ({opt})."
        if value > r["opt_max"]:
            return f"{label} ({shown}) iko juu ya kiwango bora cha {crop} ({opt})."
        return f"{label} ({shown}) iko ndani ya kiwango bora cha {crop} ({opt})."
    if value < r["opt_min"]:
        return f"{label} ({shown}) is below the optimum for {crop} ({opt})."
    if value > r["opt_max"]:
        return f"{label} ({shown}) is above the optimum for {crop} ({opt})."
    return f"{label} ({shown}) is within the optimum for {crop} ({opt})."

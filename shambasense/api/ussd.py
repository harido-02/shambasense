"""USSD menu for basic phones, in the Africa's Talking callback format.

Africa's Talking POSTs sessionId, serviceCode, phoneNumber and text, where text
holds every answer so far joined by '*' (e.g. "1*4*2"). The reply starts with
CON (menu continues) or END (session closes). Screens are kept under 182 characters.
"""

from __future__ import annotations

import logging

from .. import config
from ..recommend import engine
from ..recommend.i18n import day_month

log = logging.getLogger(__name__)
MAX_CHARS = 182

S = {
    "en": {
        "welcome": "Welcome to ShambaSense\n1. English\n2. Kiswahili",
        "county": "Choose your county:",
        "season": "Choose season:",
        "long_rains": "Long rains (Mar-May)",
        "short_rains": "Short rains (Oct-Dec)",
        "invalid": "Invalid choice. Please dial again.",
        "busy": "Sorry, advice is unavailable right now. Please try later.",
        "head": "{county} {season} {year}:",
        "plant": "Plant {early}-{late}",
        "demo": "DEMO",
        "none": "No suitable crop found for this season.",
    },
    "sw": {
        "welcome": "Karibu ShambaSense\n1. English\n2. Kiswahili",
        "county": "Chagua kaunti yako:",
        "season": "Chagua msimu:",
        "long_rains": "Mvua ndefu (Mac-Mei)",
        "short_rains": "Mvua fupi (Okt-Des)",
        "invalid": "Chaguo si sahihi. Tafadhali piga tena.",
        "busy": "Samahani, ushauri haupatikani sasa. Jaribu baadaye.",
        "head": "{county} {season} {year}:",
        "plant": "Panda {early}-{late}",
        "demo": "MAJARIBIO",
        "none": "Hakuna zao linalofaa msimu huu.",
    },
}
SHORT_SEASON = {"en": {"long_rains": "LR", "short_rains": "SR"}, "sw": {"long_rains": "MN", "short_rains": "MF"}}


def _menu(title: str, options: list[str]) -> str:
    return title + "\n" + "\n".join(f"{i}. {o}" for i, o in enumerate(options, start=1))


def _pick(choice: str, options: list) -> object | None:
    return options[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(options) else None


def summary(result: dict, lang: str) -> str:
    """Top crops and planting window, squeezed into one USSD screen."""
    s = S[lang]
    head = s["head"].format(county=result["location"]["county_name"],
                            season=SHORT_SEASON[lang][result["season"]], year=result["year"])
    lines = [head]
    for r in result["recommendations"][:3]:
        if "yield_bags_acre" in r:
            y = r["yield_bags_acre"]
            amount = f"{y['p10']:.0f}-{y['p90']:.0f} bags/ac" if lang == "en" else f"magunia {y['p10']:.0f}-{y['p90']:.0f}/ekari"
        elif "yield_t_ha" in r:
            y = r["yield_t_ha"]
            amount = f"{y['p10'] * 0.4047:.1f}-{y['p90'] * 0.4047:.1f} t/ac" if lang == "en" else f"tani {y['p10'] * 0.4047:.1f}-{y['p90'] * 0.4047:.1f}/ekari"
        else:
            amount = ""
        lines.append(f"{r['rank']}.{r['name']} {amount}".strip())
    if not result["recommendations"]:
        lines.append(s["none"])
    pw = result["planting_window"]
    if pw.get("early"):
        from datetime import date

        e, l_ = date.fromisoformat(pw["early"]), date.fromisoformat(pw["late"])
        lines.append(s["plant"].format(early=day_month(e, lang), late=day_month(l_, lang)))
    if result["model"]["data_quality"] == "synthetic":
        lines[0] = s["demo"] + " " + lines[0]
    text = "\n".join(lines)
    while len(text) > MAX_CHARS - 4 and len(lines) > 2:     # drop the third crop first if too long
        lines.pop(-2 if pw.get("early") else -1)
        text = "\n".join(lines)
    return text[: MAX_CHARS - 4]


def handle(text: str, phone: str | None, model) -> str:
    parts = [p for p in (text or "").split("*") if p != ""]
    if not parts:
        return "CON " + S["en"]["welcome"]
    lang = _pick(parts[0], ["en", "sw"])
    if lang is None:
        return "END " + S["en"]["invalid"]
    s = S[lang]
    county_ids = list(config.counties())
    if len(parts) == 1:
        return "CON " + _menu(s["county"], [config.counties()[c]["name"] for c in county_ids])
    county_id = _pick(parts[1], county_ids)
    if county_id is None:
        return "END " + s["invalid"]
    seasons = list(config.counties()[county_id]["seasons"])
    if len(seasons) > 1 and len(parts) == 2:
        return "CON " + _menu(s["season"], [s[x] for x in seasons])
    season = seasons[0] if len(seasons) == 1 else _pick(parts[2], seasons)
    if season is None:
        return "END " + s["invalid"]
    try:
        result = engine.recommend(county_id=county_id, season=season, lang=lang, channel="ussd",
                                  user=phone, model=model)
    except Exception as exc:  # noqa: BLE001
        log.exception("USSD recommendation failed: %s", exc)
        return "END " + s["busy"]
    return "END " + summary(result, lang)

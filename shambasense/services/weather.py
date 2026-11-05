"""14-day weather forecast for a farm, from the Open-Meteo forecast API (no key needed)."""

from __future__ import annotations

from datetime import date

from ..ingest.http import get_json
from ..recommend.i18n import day_month

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["precipitation_sum", "precipitation_probability_max", "temperature_2m_max", "temperature_2m_min",
         "weather_code"]

TEXT = {
    "en": {
        "total": "About {mm:.0f} mm of rain is expected over the next {days} days.",
        "plant": "Rain heavy enough to plant (about 20 mm in 3 days) is forecast from {date}.",
        "dry": "No planting rain (20 mm in 3 days) is forecast in the next {days} days.",
    },
    "sw": {
        "total": "Takriban mm {mm:.0f} za mvua zinatarajiwa katika siku {days} zijazo.",
        "plant": "Mvua ya kutosha kupanda (takriban mm 20 ndani ya siku 3) inatarajiwa kuanzia {date}.",
        "dry": "Hakuna mvua ya kupanda (mm 20 ndani ya siku 3) inayotarajiwa katika siku {days} zijazo.",
    },
}


def parse(payload: dict) -> list[dict]:
    d = payload["daily"]
    days = []
    for i, day in enumerate(d["time"]):
        get = lambda k: (d.get(k) or [None] * len(d["time"]))[i]  # noqa: E731
        days.append({"date": day, "rain_mm": get("precipitation_sum"), "rain_prob": get("precipitation_probability_max"),
                     "tmax_c": get("temperature_2m_max"), "tmin_c": get("temperature_2m_min"),
                     "code": get("weather_code")})
    return days


def summarise(days: list[dict], lang: str = "en") -> list[str]:
    t = TEXT.get(lang, TEXT["en"])
    rain = [d["rain_mm"] or 0 for d in days]
    lines = [t["total"].format(mm=sum(rain), days=len(days))]
    start = next((i for i in range(len(rain) - 2) if sum(rain[i:i + 3]) >= 20 and rain[i] >= 1), None)
    lines.append(t["plant"].format(date=day_month(date.fromisoformat(days[start]["date"]), lang)) if start is not None else t["dry"].format(days=len(days)))
    return lines


def forecast(lat: float, lon: float, days: int = 14, lang: str = "en") -> dict:
    payload = get_json(URL, {"latitude": round(lat, 3), "longitude": round(lon, 3), "daily": ",".join(DAILY),
                             "forecast_days": days, "timezone": "Africa/Nairobi"},
                       source="open_meteo_forecast", ttl_days=0.125)
    out = parse(payload)
    return {"lat": lat, "lon": lon, "days": out, "summary": summarise(out, lang),
            "source": "Open-Meteo weather forecast (open-meteo.com, CC BY 4.0)"}

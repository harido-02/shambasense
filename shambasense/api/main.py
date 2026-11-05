"""ShambaSense REST API, USSD callback, web app and admin dashboard.

Run with:  uvicorn shambasense.api.main:app --reload
Interactive API docs are served at /docs.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, config, db
from ..features.climate import climatology
from ..models.registry import get_model
from ..models.yield_model import metadata
from ..recommend import engine, forecast, location
from ..services import market, reminders, weather
from . import routes_account, routes_admin, ussd
from .deps import optional_user
from .schemas import FeedbackIn, RecommendRequest

log = logging.getLogger(__name__)
WEB_DIR = config.ROOT / "web"
__all__ = ["app", "get_model"]


async def _reminder_loop() -> None:
    """Send due SMS reminders once an hour while the service is running."""
    while True:
        try:
            counts = await asyncio.to_thread(reminders.send_due, date.today())
            if any(counts.values()):
                log.info("reminders: %s", counts)
        except Exception as exc:  # noqa: BLE001
            log.warning("reminder run failed: %s", exc)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if get_model() is None:
        log.warning("no trained model found; advice will rank crops on suitability only")
    task = asyncio.create_task(_reminder_loop()) if config.reminders_enabled() else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="ShambaSense API",
    version=__version__,
    description="Crop recommendations for Kenyan farmers from soil, seasonal forecasts, "
                "a machine learning yield model and market prices.",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["*"])
app.include_router(routes_account.router)
app.include_router(routes_admin.router)


def _run(fn, **kwargs):
    try:
        return fn(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health", tags=["system"])
def health():
    meta = metadata() or {}
    return {"status": "ok", "version": __version__, "model_loaded": get_model() is not None,
            "data_quality": meta.get("data_quality", "none"), "trained_at": meta.get("trained_at"),
            "sms_configured": bool(config.sms_settings()["api_key"])}


@app.get("/api/counties", tags=["reference"])
def counties():
    return [{"id": cid, "name": c["name"], "lat": c["lat"], "lon": c["lon"], "seasons": list(c["seasons"]),
             "main_season": c["main_season"], "default_season": engine.default_season(cid)[0]}
            for cid, c in config.counties().items()]


@app.get("/api/crops", tags=["reference"])
def crops():
    return [{"id": cid, "name": c["name"], "days_to_maturity": c["days_to_maturity"],
             "requirements": {k: c[k] for k in ("rain_mm", "tmean_c", "ph")}, "bag_kg": c.get("bag_kg"),
             "verified": c.get("verified", False), "source": c.get("source")}
            for cid, c in config.crops().items()]


@app.post("/api/recommend", tags=["advice"])
def recommend(req: RecommendRequest, user=Depends(optional_user)):
    """Ranked crops for a point (lat/lon) or a county, for a season."""
    return _run(engine.recommend, lat=req.lat, lon=req.lon, county_id=req.county, season=req.season,
                year=req.year, lang=req.lang, channel="api",
                forecast=req.outlook.model_dump() if req.outlook else None, model=get_model(),
                user_id=user.id if user else None)


@app.get("/api/recommend", tags=["advice"])
def recommend_get(county: str | None = None, lat: float | None = None, lon: float | None = None,
                  season: str | None = None, year: int | None = None, lang: str = "en",
                  channel: str = Query("web", pattern="^(web|app|api)$"), user=Depends(optional_user)):
    return _run(engine.recommend, lat=lat, lon=lon, county_id=county, season=season, year=year,
                lang=lang, channel=channel, model=get_model(), user_id=user.id if user else None)


@app.get("/api/outlook/{county}", tags=["advice"])
def outlook(county: str, season: str | None = None, year: int | None = None):
    """The seasonal outlook in use for a county, with the rainfall terciles it refers to."""
    def _go():
        site = location.resolve(county_id=county)
        s, y = (season, year or engine.next_year_for(county, season)) if season else engine.default_season(county)
        clim = climatology(site.series, config.counties()[county]["seasons"][s])
        fc = forecast.outlook(county, s, y, site.lat, site.lon, clim)
        return {"county": county, "season": s, "year": y, "forecast": fc,
                "terciles_mm": {"lower": round(clim.attrs["lower_mm"]), "upper": round(clim.attrs["upper_mm"])},
                "seasons_on_record": int(len(clim))}
    return _run(_go)


@app.get("/api/prices", tags=["markets"])
def prices(crop: str, county: str | None = None, months: int = 36):
    """Monthly median wholesale price (KES/kg) for a crop, in a county or nationally."""
    return _run(market.series, crop=crop, county_id=county, months=min(max(months, 6), 120))


@app.get("/api/prices/summary", tags=["markets"])
def prices_summary(county: str | None = None):
    """Latest price and 12-month change for every crop."""
    return market.summary(county)


@app.get("/api/weather", tags=["weather"])
def weather_forecast(lat: float | None = None, lon: float | None = None, county: str | None = None,
                     days: int = 14, lang: str = "en"):
    """Daily rain, rain probability and temperature for the next days (Open-Meteo)."""
    if lat is None or lon is None:
        if county not in config.counties():
            raise HTTPException(status_code=400, detail="give lat and lon, or a county")
        lat, lon = config.counties()[county]["lat"], config.counties()[county]["lon"]
    try:
        return weather.forecast(lat, lon, min(max(days, 1), 16), lang)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="The weather forecast is unavailable right now. "
                                                    "Check your internet connection and try again.") from exc


@app.get("/api/model", tags=["system"])
def model_info():
    meta = metadata()
    if meta is None:
        raise HTTPException(status_code=404, detail="no trained model; run `python -m shambasense.cli train`")
    return meta


@app.post("/api/feedback", tags=["advice"])
def feedback(body: FeedbackIn, user=Depends(optional_user)):
    """What a farmer planted and how it went; stored to evaluate and retrain the model."""
    with db.session() as s, s.begin():
        s.add(db.Feedback(channel="app" if user else "web", county_id=body.county, season=body.season,
                          year=body.year, crop=body.crop,
                          followed_advice=None if body.followed_advice is None else int(body.followed_advice),
                          rating=body.rating, yield_bags_acre=body.yield_bags_acre, notes=body.notes,
                          user_id=user.id if user else None, farm_id=body.farm_id))
    return {"saved": True}


@app.post("/ussd", response_class=PlainTextResponse, tags=["ussd"])
def ussd_callback(sessionId: str = Form(""), serviceCode: str = Form(""), phoneNumber: str = Form(""),  # noqa: N803
                  text: str = Form("")):
    """Africa's Talking USSD callback."""
    return ussd.handle(text, phoneNumber, get_model())


# ------------------------------------------------------------------ web app (installable) and admin
if (WEB_DIR / "index.html").exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    def _web(name: str, media_type: str | None = None, cache: str = "no-cache"):
        return FileResponse(WEB_DIR / name, media_type=media_type, headers={"Cache-Control": cache})

    @app.get("/", include_in_schema=False)
    def index():
        return _web("index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return _web("admin.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return _web("sw.js", "application/javascript")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return _web("manifest.webmanifest", "application/manifest+json")

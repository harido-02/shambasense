"""Accounts, saved farms, advice history and SMS reminders."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select

from .. import config, db
from ..models.registry import get_model
from ..recommend import engine
from ..services import auth, reminders
from ..services.reminders import farm_location
from .deps import bearer_token, current_user
from .schemas import FarmIn, FarmPatch, LoginIn, PinChangeIn, ProfileIn, RegisterIn, ReminderIn

router = APIRouter(prefix="/api", tags=["account"])


def _auth_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/auth/register")
def register(body: RegisterIn):
    user, token = _auth_call(auth.register, body.phone, body.pin, body.name, body.county, body.lang)
    return {"token": token, "user": auth.public(user)}


@router.post("/auth/login")
def login(body: LoginIn):
    user, token = _auth_call(auth.login, body.phone, body.pin)
    return {"token": token, "user": auth.public(user)}


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    if token:
        auth.logout(token)
    return {"signed_out": True}


@router.get("/me")
def me(user: db.User = Depends(current_user)):
    return auth.public(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: db.User = Depends(current_user)):
    fields = {k: v for k, v in {"name": body.name, "county_id": body.county, "lang": body.lang,
                                "sms_opt_in": body.sms_opt_in}.items() if v is not None}
    return auth.public(_auth_call(auth.update_user, user.id, **fields))


@router.post("/me/pin")
def change_pin(body: PinChangeIn, user: db.User = Depends(current_user)):
    _auth_call(auth.change_pin, user.id, body.old_pin, body.new_pin)
    return {"changed": True}


@router.get("/me/history")
def history(limit: int = 30, user: db.User = Depends(current_user)):
    df = db.read_df("SELECT r.id, r.created_at, r.channel, r.county_id, r.season, r.year, r.top_crop, r.farm_id, "
                    "f.name AS farm_name FROM recommendation_log r LEFT JOIN farm f ON f.id = r.farm_id "
                    "WHERE r.user_id = :u ORDER BY r.id DESC LIMIT :n", {"u": user.id, "n": min(limit, 200)})
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    for r in rows:
        r["crop_name"] = config.crops().get(r["top_crop"], {}).get("name", {}).get(user.lang or "en")
        r["county_name"] = config.counties().get(r["county_id"], {}).get("name")
    return rows


@router.get("/me/history/{log_id}")
def history_item(log_id: int, user: db.User = Depends(current_user)):
    with db.session() as s:
        row = s.get(db.RecommendationLog, log_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return json.loads(row.response_json)


# ------------------------------------------------------------------ farms

def _farm_public(f: db.Farm) -> dict:
    return {"id": f.id, "name": f.name, "lat": f.lat, "lon": f.lon, "county": f.county_id,
            "county_name": config.counties()[f.county_id]["name"], "area_acres": f.area_acres,
            "seasons": list(config.counties()[f.county_id]["seasons"])}


def _own_farm(farm_id: int, user: db.User) -> db.Farm:
    with db.session() as s:
        farm = s.get(db.Farm, farm_id)
    if farm is None or farm.user_id != user.id:
        raise HTTPException(status_code=404, detail="Farm not found")
    return farm


@router.get("/farms")
def list_farms(user: db.User = Depends(current_user)):
    with db.session() as s:
        farms = s.scalars(select(db.Farm).where(db.Farm.user_id == user.id).order_by(db.Farm.id)).all()
    return [_farm_public(f) for f in farms]


@router.post("/farms")
def add_farm(body: FarmIn, user: db.User = Depends(current_user)):
    from ..ingest.loaders import nearest_county

    county = body.county
    if body.lat is not None:
        county = nearest_county(body.lat, body.lon)[0] if county not in config.counties() else county
    if county not in config.counties():
        raise HTTPException(status_code=400, detail="Unknown county")
    with db.session() as s, s.begin():
        if s.scalar(select(db.Farm).where(db.Farm.user_id == user.id).limit(20).offset(19)):
            raise HTTPException(status_code=400, detail="You can save up to 20 farms")
        farm = db.Farm(user_id=user.id, name=body.name.strip(), lat=body.lat, lon=body.lon, county_id=county,
                       area_acres=body.area_acres)
        s.add(farm)
        s.flush()
        farm_id = farm.id
    return _farm_public(_own_farm(farm_id, user))


@router.patch("/farms/{farm_id}")
def edit_farm(farm_id: int, body: FarmPatch, user: db.User = Depends(current_user)):
    _own_farm(farm_id, user)
    with db.session() as s, s.begin():
        farm = s.get(db.Farm, farm_id)
        if body.name is not None:
            farm.name = body.name.strip()
        if body.area_acres is not None:
            farm.area_acres = body.area_acres
    return _farm_public(_own_farm(farm_id, user))


@router.delete("/farms/{farm_id}")
def delete_farm(farm_id: int, user: db.User = Depends(current_user)):
    _own_farm(farm_id, user)
    with db.session() as s, s.begin():
        s.query(db.Reminder).filter(db.Reminder.farm_id == farm_id, db.Reminder.status == "scheduled") \
            .update({"status": "cancelled"})
        s.delete(s.get(db.Farm, farm_id))
    return {"deleted": True}


@router.get("/farms/{farm_id}/advice")
def farm_advice(farm_id: int, season: str | None = None, year: int | None = None, lang: str | None = None,
                user: db.User = Depends(current_user)):
    farm = _own_farm(farm_id, user)
    try:
        result = engine.recommend(**farm_location(farm), season=season, year=year, lang=lang or user.lang or "en",
                                  channel="app", model=get_model(), user_id=user.id, farm_id=farm.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    result["farm"] = _farm_public(farm)
    return result


# ------------------------------------------------------------------ reminders

@router.get("/reminders")
def list_reminders(user: db.User = Depends(current_user)):
    return reminders.list_for(user.id)


@router.post("/farms/{farm_id}/reminders")
def add_reminder(farm_id: int, body: ReminderIn, user: db.User = Depends(current_user)):
    _own_farm(farm_id, user)
    try:
        rem = reminders.schedule(user, farm_id, body.season, body.year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return reminders.public(rem, _own_farm(farm_id, user).name)


@router.delete("/reminders/{reminder_id}")
def cancel_reminder(reminder_id: int, user: db.User = Depends(current_user)):
    try:
        reminders.cancel(user, reminder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Reminder not found") from exc
    return {"cancelled": True}

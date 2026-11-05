"""Administrator endpoints: statistics, feedback, users, SMS, outlooks, retraining."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import config, db
from ..models.yield_model import metadata
from ..services import admin, auth, reminders, sms
from .deps import require_admin
from .schemas import OutlookUpload, TestSmsIn

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stats")
def stats(days: int = 30):
    return admin.stats(min(max(days, 7), 180))


@router.get("/feedback")
def feedback(limit: int = 100):
    return admin.feedback(min(limit, 500))


@router.get("/users")
def users(limit: int = 200):
    return admin.users(min(limit, 1000))


@router.get("/sms")
def sms_log(limit: int = 100):
    return admin.sms_log(min(limit, 500))


@router.get("/model")
def model():
    return metadata() or {}


@router.post("/outlook")
def upload_outlook(body: OutlookUpload):
    if body.county not in config.counties():
        raise HTTPException(status_code=400, detail="unknown county")
    total = body.p_below + body.p_normal + body.p_above
    if total <= 0:
        raise HTTPException(status_code=400, detail="probabilities must be positive")
    db.replace_rows(db.SeasonalOutlook, {"county_id": body.county, "year": body.year, "season": body.season}, [{
        "county_id": body.county, "year": body.year, "season": body.season, "p_below": body.p_below / total,
        "p_normal": body.p_normal / total, "p_above": body.p_above / total, "source": body.source, "issued_on": None}])
    return {"saved": True}


@router.get("/outlooks")
def outlooks():
    df = db.read_df("SELECT county_id, year, season, p_below, p_normal, p_above, source FROM seasonal_outlook "
                    "ORDER BY year DESC, county_id")
    return df.astype(object).where(df.notna(), None).to_dict("records")


@router.post("/retrain")
def retrain():
    return admin.start_retrain()


@router.get("/retrain")
def retrain_status():
    return admin.retrain_status()


@router.post("/reminders/run")
def run_reminders():
    return reminders.send_due()


@router.post("/sms/test")
def test_sms(body: TestSmsIn):
    phone = auth.normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Enter a Kenyan mobile number")
    return sms.send(phone, body.message)

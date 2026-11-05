"""SMS planting reminders: scheduled a few days before the usual onset of rains."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .. import config, db
from ..models.registry import get_model
from ..recommend import engine
from ..recommend.i18n import day_month
from . import sms

log = logging.getLogger(__name__)
DAYS_BEFORE_ONSET = 3

TEXT = {
    "en": "ShambaSense: {farm}, {season} {year}. Rains usually become reliable {early}-{late}. "
          "Plant after about 20mm falls in 3 days. Best bets: {crops}.",
    "sw": "ShambaSense: {farm}, {season} {year}. Mvua kwa kawaida hutulia {early}-{late}. "
          "Panda baada ya mvua ya mm 20 ndani ya siku 3. Mazao bora: {crops}.",
}


def farm_location(farm: db.Farm) -> dict:
    if farm.lat is not None and farm.lon is not None:
        return {"lat": farm.lat, "lon": farm.lon, "county_id": farm.county_id}
    return {"county_id": farm.county_id}


def compose(farm: db.Farm, season: str, year: int, lang: str) -> tuple[date, str]:
    """When to send the reminder and what it says, from the farm's advice."""
    result = engine.recommend(**farm_location(farm), season=season, year=year, lang=lang,
                              model=get_model(), log_request=False)
    pw = result["planting_window"]
    early = date.fromisoformat(pw["early"]) if pw.get("early") else None
    late = date.fromisoformat(pw["late"]) if pw.get("late") else None
    send_on = (early or date(year, 3 if season == "long_rains" else 10, 1)) - timedelta(days=DAYS_BEFORE_ONSET)
    send_on = max(send_on, date.today())
    crops = ", ".join(r["name"] for r in result["recommendations"][:2]) or "-"
    message = TEXT[lang].format(farm=farm.name[:24], season=result["season_name"], year=year,
                                early=day_month(early, lang) if early else "?",
                                late=day_month(late, lang) if late else "?", crops=crops)
    return send_on, message[:300]


def schedule(user: db.User, farm_id: int, season: str, year: int | None = None) -> db.Reminder:
    with db.session() as s:
        farm = s.get(db.Farm, farm_id)
    if farm is None or farm.user_id != user.id:
        raise LookupError("farm not found")
    if season not in config.counties()[farm.county_id]["seasons"]:
        raise ValueError(f"{config.counties()[farm.county_id]['name']} has no {season} season")
    year = year or engine.next_year_for(farm.county_id, season)
    send_on, message = compose(farm, season, year, user.lang or "en")
    with db.session() as s, s.begin():
        existing = s.scalar(select(db.Reminder).where(db.Reminder.farm_id == farm_id, db.Reminder.season == season,
                                                      db.Reminder.year == year))
        if existing:
            existing.send_on, existing.message, existing.status = send_on, message, "scheduled"
            reminder_id = existing.id
        else:
            rem = db.Reminder(user_id=user.id, farm_id=farm_id, season=season, year=year, send_on=send_on,
                              message=message)
            s.add(rem)
            s.flush()
            reminder_id = rem.id
        u = s.get(db.User, user.id)
        u.sms_opt_in = 1
    with db.session() as s:
        return s.get(db.Reminder, reminder_id)


def cancel(user: db.User, reminder_id: int) -> None:
    with db.session() as s, s.begin():
        rem = s.get(db.Reminder, reminder_id)
        if rem is None or rem.user_id != user.id:
            raise LookupError("reminder not found")
        rem.status = "cancelled"


def list_for(user_id: int) -> list[dict]:
    with db.session() as s:
        rows = s.execute(select(db.Reminder, db.Farm.name).join(db.Farm, db.Farm.id == db.Reminder.farm_id)
                         .where(db.Reminder.user_id == user_id).order_by(db.Reminder.send_on.desc())).all()
    return [public(r, farm_name) for r, farm_name in rows]


def public(rem: db.Reminder, farm_name: str | None = None) -> dict:
    return {"id": rem.id, "farm_id": rem.farm_id, "farm_name": farm_name, "season": rem.season, "year": rem.year,
            "send_on": rem.send_on.isoformat(), "status": rem.status, "message": rem.message,
            "sent_at": rem.sent_at.isoformat() if rem.sent_at else None}


def send_due(today: date | None = None) -> dict:
    """Send every scheduled reminder whose date has come. Safe to run repeatedly."""
    today = today or date.today()
    counts = {"sent": 0, "failed": 0, "not_configured": 0}
    with db.session() as s:
        due = s.execute(select(db.Reminder, db.User.phone).join(db.User, db.User.id == db.Reminder.user_id)
                        .where(db.Reminder.status == "scheduled", db.Reminder.send_on <= today,
                               db.User.sms_opt_in == 1)).all()
    for rem, phone in due:
        result = sms.send(phone, rem.message)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        with db.session() as s, s.begin():
            r = s.get(db.Reminder, rem.id)
            # Keep "scheduled" when SMS is not configured, so it goes out once keys are added.
            if result["status"] == "sent":
                r.status, r.sent_at = "sent", datetime.now(timezone.utc)
            elif result["status"] == "failed":
                r.status = "failed"
    return counts

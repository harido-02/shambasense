"""Administration: usage statistics, feedback, SMS log and background retraining."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from .. import config, db
from ..models.yield_model import metadata
from .auth import mask_phone

log = logging.getLogger(__name__)
_retrain = {"running": False, "started_at": None, "finished_at": None, "error": None, "result": None}
_retrain_lock = threading.Lock()


def _scalar(sql: str, params: dict | None = None):
    df = db.read_df(sql, params)
    return None if df.empty else df.iloc[0, 0]


def stats(days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    recs = db.read_df("SELECT created_at, channel, top_crop, county_id FROM recommendation_log")
    if not recs.empty:
        recs["created_at"] = recs["created_at"].astype(str).str.slice(0, 10)
    daily = []
    if not recs.empty:
        recent = recs[recs["created_at"] >= since.date().isoformat()]
        counts = recent.groupby(["created_at", "channel"]).size().unstack(fill_value=0)
        for day in [(since + timedelta(days=i)).date().isoformat() for i in range(days + 1)]:
            row = counts.loc[day].to_dict() if day in counts.index else {}
            daily.append({"date": day, **{ch: int(row.get(ch, 0)) for ch in ("web", "ussd", "api", "app")}})
    fb = db.read_df("SELECT rating FROM feedback WHERE rating IS NOT NULL")
    meta = metadata() or {}
    return {
        "users": int(_scalar("SELECT COUNT(*) FROM app_user") or 0),
        "farms": int(_scalar("SELECT COUNT(*) FROM farm") or 0),
        "recommendations": int(len(recs)),
        "by_channel": recs["channel"].value_counts().to_dict() if not recs.empty else {},
        "by_county": recs["county_id"].value_counts().to_dict() if not recs.empty else {},
        "top_crops": recs["top_crop"].value_counts().head(6).to_dict() if not recs.empty else {},
        "daily": daily,
        "feedback": {"count": int(_scalar("SELECT COUNT(*) FROM feedback") or 0),
                     "avg_rating": round(float(fb["rating"].mean()), 2) if not fb.empty else None},
        "reminders": db.read_df("SELECT status, COUNT(*) AS n FROM reminder GROUP BY status")
                       .set_index("status")["n"].astype(int).to_dict(),
        "sms": db.read_df("SELECT status, COUNT(*) AS n FROM sms_log GROUP BY status")
                 .set_index("status")["n"].astype(int).to_dict(),
        "sms_configured": bool(config.sms_settings()["api_key"]),
        "model": {k: meta.get(k) for k in ("version", "trained_at", "data_quality")}
                 | {"rows": (meta.get("training_data") or {}).get("rows"),
                    "mae_year": ((meta.get("evaluation") or {}).get("year") or {}).get("shambasense", {}).get("mae_t_ha"),
                    "mape_year": ((meta.get("evaluation") or {}).get("year") or {}).get("shambasense", {}).get("mape_pct")},
    }


def feedback(limit: int = 100) -> list[dict]:
    df = db.read_df("SELECT f.id, f.created_at, f.channel, f.county_id, f.season, f.year, f.crop, f.rating, "
                    "f.yield_bags_acre, f.followed_advice, f.notes, u.name AS user_name FROM feedback f "
                    "LEFT JOIN app_user u ON u.id = f.user_id ORDER BY f.id DESC LIMIT :n", {"n": limit})
    return df.astype(object).where(df.notna(), None).to_dict("records")


def sms_log(limit: int = 100) -> list[dict]:
    df = db.read_df("SELECT id, created_at, to_phone, message, status FROM sms_log ORDER BY id DESC LIMIT :n",
                    {"n": limit})
    if not df.empty:
        df["to_phone"] = df["to_phone"].map(mask_phone)
    return df.astype(object).where(df.notna(), None).to_dict("records")


def users(limit: int = 200) -> list[dict]:
    df = db.read_df("SELECT u.id, u.name, u.phone, u.county_id, u.lang, u.is_admin, u.sms_opt_in, u.created_at, "
                    "(SELECT COUNT(*) FROM farm f WHERE f.user_id = u.id) AS farms FROM app_user u "
                    "ORDER BY u.id DESC LIMIT :n", {"n": limit})
    if not df.empty:
        df["phone"] = df["phone"].map(mask_phone)
    return df.astype(object).where(df.notna(), None).to_dict("records")


def retrain_status() -> dict:
    return dict(_retrain)


def start_retrain() -> dict:
    with _retrain_lock:
        if _retrain["running"]:
            return retrain_status()
        _retrain.update(running=True, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        finished_at=None, error=None, result=None)

    def _run():
        try:
            from ..features.dataset import build_training_table
            from ..models.yield_model import train_and_evaluate

            model = train_and_evaluate(build_training_table(), config.ROOT / "reports" / "figures")
            model.save()
            ev = model.meta["evaluation"].get("year", {}).get("shambasense", {})
            _retrain["result"] = {"rows": model.meta["training_data"]["rows"],
                                  "data_quality": model.meta["data_quality"],
                                  "mae_t_ha": ev.get("mae_t_ha"), "mape_pct": ev.get("mape_pct")}
        except Exception as exc:  # noqa: BLE001
            log.exception("retraining failed")
            _retrain["error"] = str(exc)
        finally:
            _retrain["running"] = False
            _retrain["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    threading.Thread(target=_run, daemon=True).start()
    return retrain_status()

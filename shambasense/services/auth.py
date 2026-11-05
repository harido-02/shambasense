"""Farmer accounts: phone number + 4-digit PIN, with hashed PINs, lockout and bearer sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import config, db

PHONE_RE = re.compile(r"^\+254(7|1)\d{8}$")
PIN_RE = re.compile(r"^\d{4}$")
WEAK_PINS = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321"}
SESSION_DAYS = 30
MAX_FAILURES = 5
LOCK_MINUTES = 15


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:          # SQLite returns naive datetimes
        return dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_phone(raw: str | None) -> str | None:
    """Kenyan mobile number in E.164 (+2547XXXXXXXX or +2541XXXXXXXX), or None."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+"):
        phone = digits
    elif digits.startswith("254"):
        phone = "+" + digits
    elif digits.startswith("0") and len(digits) == 10:
        phone = "+254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        phone = "+254" + digits
    else:
        return None
    return phone if PHONE_RE.match(phone) else None


def mask_phone(phone: str) -> str:
    return phone[:5] + "•••" + phone[-3:] if phone else ""


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(dk.hex(), dk_hex)


def _check_pin(pin: str) -> None:
    if not PIN_RE.match(pin or ""):
        raise AuthError("PIN must be exactly 4 digits")
    if pin in WEAK_PINS:
        raise AuthError("Choose a PIN that is harder to guess")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with db.session() as s, s.begin():
        s.add(db.AuthSession(token_hash=_token_hash(token), user_id=user_id,
                             expires_at=_now() + timedelta(days=SESSION_DAYS)))
    return token


def register(phone: str, pin: str, name: str | None = None, county_id: str | None = None,
             lang: str = "en", is_admin: bool = False) -> tuple[db.User, str]:
    norm = normalize_phone(phone)
    if not norm:
        raise AuthError("Enter a Kenyan mobile number, for example 0712 345 678")
    _check_pin(pin)
    if county_id and county_id not in config.counties():
        raise AuthError("Unknown county")
    with db.session() as s, s.begin():
        if s.scalar(select(db.User).where(db.User.phone == norm)):
            raise AuthError("This number already has an account. Sign in instead.", 409)
        user = db.User(phone=norm, pin_hash=hash_pin(pin), name=(name or "").strip()[:80] or None,
                       county_id=county_id, lang=lang if lang in ("en", "sw") else "en",
                       is_admin=int(is_admin), last_login_at=_now())
        s.add(user)
        s.flush()
        user_id = user.id
    return get_user(user_id), create_session(user_id)


def login(phone: str, pin: str) -> tuple[db.User, str]:
    norm = normalize_phone(phone)
    if not norm:
        raise AuthError("Enter a Kenyan mobile number, for example 0712 345 678")
    error: AuthError | None = None
    with db.session() as s, s.begin():      # commits the failure count even when the PIN is wrong
        user = s.scalar(select(db.User).where(db.User.phone == norm))
        if user is None:
            raise AuthError("Wrong phone number or PIN", 401)
        locked = _aware(user.locked_until)
        if locked and locked > _now():
            minutes = int((locked - _now()).total_seconds() // 60) + 1
            raise AuthError(f"Too many wrong PINs. Try again in {minutes} minutes.", 429)
        if verify_pin(pin or "", user.pin_hash):
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = _now()
        else:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILURES:
                user.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
            error = AuthError("Wrong phone number or PIN", 401)
        user_id = user.id
    if error:
        raise error
    return get_user(user_id), create_session(user_id)


def user_from_token(token: str | None) -> db.User | None:
    if not token:
        return None
    with db.session() as s:
        sess = s.get(db.AuthSession, _token_hash(token))
        if sess is None or _aware(sess.expires_at) < _now():
            return None
        return s.get(db.User, sess.user_id)


def logout(token: str) -> None:
    with db.session() as s, s.begin():
        sess = s.get(db.AuthSession, _token_hash(token))
        if sess:
            s.delete(sess)


def get_user(user_id: int) -> db.User | None:
    with db.session() as s:
        return s.get(db.User, user_id)


def update_user(user_id: int, **fields) -> db.User:
    with db.session() as s, s.begin():
        user = s.get(db.User, user_id)
        if "county_id" in fields and fields["county_id"] and fields["county_id"] not in config.counties():
            raise AuthError("Unknown county")
        if "lang" in fields and fields["lang"] not in ("en", "sw"):
            raise AuthError("Language must be en or sw")
        for key, value in fields.items():
            if key == "sms_opt_in":
                value = int(bool(value))
            setattr(user, key, value)
    return get_user(user_id)


def change_pin(user_id: int, old_pin: str, new_pin: str) -> None:
    _check_pin(new_pin)
    with db.session() as s, s.begin():
        user = s.get(db.User, user_id)
        if not verify_pin(old_pin or "", user.pin_hash):
            raise AuthError("Current PIN is wrong", 401)
        user.pin_hash = hash_pin(new_pin)


def public(user: db.User) -> dict:
    return {"id": user.id, "phone": user.phone, "phone_masked": mask_phone(user.phone), "name": user.name,
            "county": user.county_id, "lang": user.lang or "en", "is_admin": bool(user.is_admin),
            "sms_opt_in": bool(user.sms_opt_in)}

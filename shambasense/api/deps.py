"""Request dependencies: who is calling, and whether they may do it."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .. import config, db
from ..services import auth


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def optional_user(authorization: str | None = Header(default=None)) -> db.User | None:
    return auth.user_from_token(bearer_token(authorization))


def current_user(authorization: str | None = Header(default=None)) -> db.User:
    user = optional_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def require_admin(authorization: str | None = Header(default=None),
                  x_admin_token: str | None = Header(default=None)) -> db.User | None:
    """An admin user's session, or the ADMIN_TOKEN for scripts."""
    token = config.admin_token()
    if token and x_admin_token and hmac.compare_digest(x_admin_token, token):
        return None
    user = optional_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in as an administrator")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrators only")
    return user

"""Configuration: YAML files in config/ plus environment-variable overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return Path(os.getenv("SHAMBA_CONFIG_DIR", ROOT / "config"))


def data_dir() -> Path:
    path = Path(os.getenv("SHAMBA_DATA_DIR", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_dir() -> Path:
    path = Path(os.getenv("SHAMBA_MODEL_DIR", ROOT / "models"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    url = os.getenv("DATABASE_URL") or f"sqlite:///{data_dir() / 'shambasense.db'}"
    # Hosts hand out postgres:// or postgresql:// URLs; name the driver (psycopg 3) explicitly,
    # because SQLAlchemy's default PostgreSQL driver differs between versions.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    return url


def sms_settings() -> dict:
    """Africa's Talking credentials. Without them, SMS are logged but not sent."""
    return {
        "username": os.getenv("AT_USERNAME") or None,
        "api_key": os.getenv("AT_API_KEY") or None,
        "sender_id": os.getenv("AT_SENDER_ID") or None,
        "sandbox": os.getenv("AT_USERNAME", "sandbox") == "sandbox",
    }


def demo_mode() -> bool:
    """Demo deployments run entirely on the synthetic test data, including for map points."""
    return os.getenv("SHAMBA_DEMO", "0") == "1"


def reminders_enabled() -> bool:
    return os.getenv("SHAMBA_REMINDERS", "1") == "1"


def offline() -> bool:
    """When true, no network calls are made; only cached responses are used."""
    return os.getenv("SHAMBA_OFFLINE", "0") == "1"


def admin_token() -> str | None:
    return os.getenv("ADMIN_TOKEN") or None


def _load(name: str) -> dict:
    with open(config_dir() / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def settings() -> dict:
    return _load("settings.yaml")


@lru_cache
def counties() -> dict:
    return _load("counties.yaml")["counties"]


@lru_cache
def crops() -> dict:
    return _load("crops.yaml")["crops"]


def crop_ids() -> list[str]:
    return list(crops().keys())


def maturity_days(crop_id: str, county_id: str) -> int:
    cfg = crops()[crop_id]
    return int(cfg.get("days_to_maturity_by_county", {}).get(county_id, cfg["days_to_maturity"]))


def clear_caches() -> None:
    settings.cache_clear()
    counties.cache_clear()
    crops.cache_clear()

"""Cached HTTP GET with retries. Every response is saved under data/cache/<source>/."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from .. import config

log = logging.getLogger(__name__)
USER_AGENT = "ShambaSense/0.1 (final-year research project)"


class OfflineError(RuntimeError):
    """Raised when data is not cached and network access is switched off."""


def _cache_path(source: str, url: str, params: dict) -> Path:
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True, default=str)).encode()).hexdigest()[:24]
    path = config.data_dir() / "cache" / source / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_json(url: str, params: dict, source: str, ttl_days: float | None = None,
             timeout: int = 90, retries: int = 3) -> dict:
    """Return the JSON body for url+params, from cache when fresh enough."""
    path = _cache_path(source, url, params)
    if path.exists():
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if ttl_days is None or age_days <= ttl_days:
            return json.loads(path.read_text())
    if config.offline():
        raise OfflineError(f"{source}: not cached and SHAMBA_OFFLINE=1")

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                data = resp.json()
                path.write_text(json.dumps(data))
                return data
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = RuntimeError(f"{source}: HTTP {resp.status_code}")
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"{source}: HTTP {resp.status_code}: {resp.text[:300]}")
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{source}: request failed after {retries} attempts: {last_error}")

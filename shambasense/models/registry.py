"""Loads the trained yield model once and reloads it after retraining."""

from __future__ import annotations

import threading

from .. import config
from .yield_model import MODEL_FILE, YieldModel

_lock = threading.Lock()
_state: dict = {"model": None, "mtime": None}


def get_model() -> YieldModel | None:
    path = config.model_dir() / MODEL_FILE
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _lock:
        if _state["mtime"] != mtime:
            _state["model"] = YieldModel.load()
            _state["mtime"] = mtime
    return _state["model"]

"""
Tiny JSON-backed data store. All hospital state, history, and incoming
patient queues live in /data and are mutated in-process for the demo.

Not thread-safe — fine for a single Streamlit + FastAPI dev run.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _load(name: str) -> Any:
    if name not in _cache:
        with (DATA_DIR / name).open("r", encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def _save(name: str, value: Any) -> None:
    with (DATA_DIR / name).open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2)
    _cache[name] = value


# ---- public ---------------------------------------------------------------
def all_hospitals() -> list[dict]:
    return list(_load("hospitals.json"))


def get_hospital(hospital_id: str) -> dict | None:
    return next((h for h in all_hospitals() if h["id"] == hospital_id), None)


def update_hospital(hospital_id: str, patch: dict) -> dict:
    with _lock:
        hospitals = _load("hospitals.json")
        for h in hospitals:
            if h["id"] == hospital_id:
                h.update(patch)
                _save("hospitals.json", hospitals)
                return h
        raise KeyError(hospital_id)


def traffic() -> dict:
    return _load("traffic.json")


def wait_history() -> dict:
    return _load("wait_history.json")


def feedback() -> list[dict]:
    return list(_load("feedback.json"))


def add_feedback(record: dict) -> None:
    with _lock:
        rows = _load("feedback.json")
        rows.append(record)
        _save("feedback.json", rows)


def incoming() -> list[dict]:
    return list(_load("incoming_patients.json"))


def add_incoming(record: dict) -> None:
    with _lock:
        rows = _load("incoming_patients.json")
        rows.append(record)
        _save("incoming_patients.json", rows)

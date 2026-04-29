"""
Thin HTTP client used by the Streamlit pages.

Falls back to calling the agent code in-process if the FastAPI server
isn't reachable, so the demo still works if you only want one process.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = 30


def _via_http(method: str, path: str, **kwargs) -> Any:
    url = f"{BASE_URL}{path}"
    resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _in_process_fallback(path: str, payload: dict | None) -> Any:
    """Run the agent code locally if the API isn't up."""
    from backend.agents.orchestrator import assess_and_recommend, confirm_and_notify
    from backend.services.routing import rank_hospitals
    from backend.store import (
        add_feedback, all_hospitals, feedback, incoming, update_hospital, wait_history,
    )

    if path == "/api/hospitals":
        return all_hospitals()
    if path == "/api/hospitals/nearby":
        ranked = rank_hospitals(
            all_hospitals(),
            user_lat=payload["user_lat"], user_lon=payload["user_lon"],
            urgency=payload.get("urgency", "medium"),
            specialty_hint=payload.get("specialty_hint", "general"),
            top_n=payload.get("top_n", 5),
        )
        return [r.__dict__ for r in ranked]
    if path == "/api/assess":
        return assess_and_recommend(**payload)
    if path == "/api/confirm":
        return confirm_and_notify(
            hospital_id=payload["hospital_id"],
            patient={k: payload.get(k) for k in (
                "name", "age", "symptoms", "allergies", "medications",
                "existing_conditions", "emergency_contact", "language",
                "accessibility", "consent_share",
            )},
            urgency=payload.get("urgency", "medium"),
            drive_minutes=payload.get("drive_minutes", 0),
        )
    if path == "/api/feedback":
        add_feedback(payload)
        return {"status": "ok"}
    if path.startswith("/api/admin/dashboard/"):
        hospital_id = path.rsplit("/", 1)[-1]
        hospitals = {h["id"]: h for h in all_hospitals()}
        h = hospitals[hospital_id]
        incoming_for_me = [p for p in incoming() if p["hospital_id"] == hospital_id]
        history = wait_history()["history"].get(hospital_id, [])
        fb = [f for f in feedback() if f["hospital_id"] == hospital_id]
        total_patients = sum(d["patients"] for d in h["departments"].values())
        total_capacity = sum(d["capacity"] for d in h["departments"].values())
        overall_wait = round(
            sum(d["wait_minutes"] * d["patients"] for d in h["departments"].values())
            / max(1, total_patients)
        )
        return {
            "hospital": h,
            "totals": {
                "patients_in_er": total_patients,
                "capacity_total": total_capacity,
                "capacity_pct": round(total_patients / max(1, total_capacity) * 100, 1),
                "overall_wait_minutes": overall_wait,
            },
            "incoming": incoming_for_me,
            "history_hours_24h": history,
            "feedback": fb,
        }
    if path == "/api/admin/capacity":
        h = next((x for x in all_hospitals() if x["id"] == payload["hospital_id"]), None)
        if not h:
            raise KeyError(payload["hospital_id"])
        departments = h["departments"].copy()
        dept_name = payload.get("department")
        if dept_name and dept_name in departments:
            d = departments[dept_name].copy()
            for key in ("patients", "capacity", "wait_minutes"):
                if payload.get(key) is not None:
                    d[key] = payload[key]
            departments[dept_name] = d
        patch: dict[str, Any] = {"departments": departments}
        for k in ("doctors_on_shift", "nurses_on_shift", "diverting", "notes"):
            if payload.get(k) is not None:
                patch[k] = payload[k]
        return update_hospital(payload["hospital_id"], patch)
    raise ValueError(f"unhandled path: {path}")


def get(path: str) -> Any:
    try:
        return _via_http("GET", path)
    except Exception:
        return _in_process_fallback(path, None)


def post(path: str, payload: dict) -> Any:
    try:
        return _via_http("POST", path, json=payload)
    except Exception:
        return _in_process_fallback(path, payload)

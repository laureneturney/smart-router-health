"""
Top-level orchestrator. Chains the triage → recommender → routing
agents in the order a real dispatcher would, and returns one bundle
the UI can render.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone

from backend.agents import triage as triage_agent
from backend.agents import recommender as recommender_agent
from backend.services.routing import rank_hospitals
from backend.store import all_hospitals, add_incoming


def _make_reference() -> str:
    suffix = "".join(random.choices(string.digits, k=4))
    return f"ER-MAN-{suffix}"


def assess_and_recommend(*, symptoms: str, pain_level: int,
                         user_lat: float, user_lon: float,
                         age: int | None = None,
                         existing_conditions: list[str] | None = None,
                         specialty_filter: str | None = None) -> dict:
    """Run triage + ranked recommendation. No commitment yet."""
    triage = triage_agent.run(symptoms, pain_level, age, existing_conditions)

    specialty_for_ranking = specialty_filter or triage["specialty_hint"]

    hospitals = all_hospitals()
    if specialty_filter:
        hospitals = [h for h in hospitals if specialty_filter in h.get("specialties", [])] or hospitals

    ranked = rank_hospitals(
        hospitals,
        user_lat=user_lat, user_lon=user_lon,
        urgency=triage["urgency"],
        specialty_hint=specialty_for_ranking,
    )
    recommendation = recommender_agent.run(triage, ranked)

    return {
        "triage": triage,
        "recommendation": recommendation,
        "ranked": [r for r in recommendation.get("alternatives", [])],
        "chosen": recommendation.get("chosen"),
    }


def confirm_and_notify(*, hospital_id: str, patient: dict, urgency: str,
                       drive_minutes: int) -> dict:
    """Patient picked a hospital — register them in the incoming queue."""
    reference = _make_reference()
    record = {
        "reference": reference,
        "hospital_id": hospital_id,
        "name": patient.get("name", "Anonymous"),
        "age": patient.get("age"),
        "symptoms": patient.get("symptoms", ""),
        "urgency": urgency,
        "eta_minutes": drive_minutes,
        "via_app": True,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    add_incoming(record)
    return record

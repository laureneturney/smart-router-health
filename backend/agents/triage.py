"""
Triage agent — classifies urgency and suggests the best-fit specialty.

The model output is treated as advisory; we always normalise the urgency
to one of {critical, high, medium, low} and the specialty to one of the
hospital department keys, so downstream code can rely on the shape.
"""

from __future__ import annotations

import json
from typing import Any

from backend.llm_provider import get_provider

VALID_URGENCY = {"critical", "high", "medium", "low"}
VALID_SPECIALTY = {
    "general", "trauma", "cardiac", "stroke",
    "paediatric", "respiratory", "neuro", "mental-health", "urgent-care",
}

SYSTEM_PROMPT = """You are an NHS A&E triage assistant. You are not a clinician — you make
a fast, conservative urgency classification to help route a patient.

Output a JSON object with these keys:
  urgency:          one of "critical", "high", "medium", "low"
  specialty_hint:   one of "general", "trauma", "cardiac", "stroke",
                    "paediatric", "respiratory", "neuro", "mental-health", "urgent-care"
  guidance:         one short sentence the patient will see
  red_flags:        array of strings — symptoms that drove the classification

Be conservative: when in doubt between two levels, pick the more urgent.
Treat chest pain, stroke signs, severe bleeding, anaphylaxis, and unconsciousness as critical.
"""


def run(symptoms: str, pain_level: int, age: int | None = None,
        existing_conditions: list[str] | None = None) -> dict[str, Any]:
    user_payload = {
        "symptoms": symptoms,
        "pain_level_0_10": pain_level,
        "age": age,
        "existing_conditions": existing_conditions or [],
    }
    raw = get_provider().complete_json(
        system=SYSTEM_PROMPT,
        user=json.dumps(user_payload),
        schema_hint={"task": "triage"},
    ) or {}

    urgency = str(raw.get("urgency", "")).lower().strip()
    if urgency not in VALID_URGENCY:
        urgency = _fallback_urgency(symptoms, pain_level)

    specialty = str(raw.get("specialty_hint", "")).lower().strip()
    if specialty not in VALID_SPECIALTY:
        specialty = "general"

    guidance = raw.get("guidance") or _default_guidance(urgency)
    red_flags = raw.get("red_flags") or []
    if not isinstance(red_flags, list):
        red_flags = [str(red_flags)]

    return {
        "urgency": urgency,
        "specialty_hint": specialty,
        "guidance": guidance,
        "red_flags": red_flags[:6],
    }


def _fallback_urgency(symptoms: str, pain_level: int) -> str:
    text = (symptoms or "").lower()
    if any(k in text for k in ["chest pain", "stroke", "unconscious", "severe bleed", "can't breathe"]):
        return "critical"
    if pain_level >= 8:
        return "high"
    if pain_level >= 5:
        return "medium"
    return "low"


def _default_guidance(urgency: str) -> str:
    return {
        "critical": "Call 999 now. Do not drive yourself.",
        "high": "Go to A&E now. Call 999 if symptoms worsen.",
        "medium": "A&E or urgent care within the hour.",
        "low": "Try NHS 111 or urgent care first.",
    }[urgency]

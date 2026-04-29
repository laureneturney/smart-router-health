"""
Distance, drive-time, and total-time-to-treatment calculations.

This module does the deterministic numeric work that an LLM should not
be doing on its own. The LLM's job is to *narrate* and *justify*; the
ranking itself is computed here so it's reproducible and testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from backend.store import traffic


@dataclass
class HospitalScore:
    hospital_id: str
    name: str
    distance_miles: float
    drive_minutes: int
    wait_minutes: int
    total_minutes: int
    capacity_pct: float
    specialty_match: bool
    score: float
    reasons: list[str]


# ---------- geo --------------------------------------------------------------
def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def drive_minutes(distance_miles: float, hospital_id: str) -> int:
    """Distance / urban speed * traffic multiplier + incident delays."""
    t = traffic()
    base_speed = t.get("default_speed_mph", 24)
    multiplier = t.get("multipliers", {}).get(hospital_id, 1.0)
    minutes = (distance_miles / base_speed) * 60 * multiplier
    for inc in t.get("incidents", []):
        if hospital_id in inc.get("affected_hospitals", []):
            minutes += inc.get("delay_minutes", 0)
    return max(1, int(round(minutes)))


# ---------- ranking ----------------------------------------------------------
def department_for(hospital: dict, specialty_hint: str) -> tuple[str, dict]:
    """Pick the department row that best fits the specialty hint."""
    depts = hospital.get("departments", {})
    if specialty_hint in depts:
        return specialty_hint, depts[specialty_hint]
    if "general" in depts:
        return "general", depts["general"]
    # fall back to first
    name, row = next(iter(depts.items()))
    return name, row


def score_hospital(
    hospital: dict,
    user_lat: float,
    user_lon: float,
    urgency: str,
    specialty_hint: str,
) -> HospitalScore:
    distance = haversine_miles(user_lat, user_lon, hospital["lat"], hospital["lon"])
    drive = drive_minutes(distance, hospital["id"])

    dept_name, dept = department_for(hospital, specialty_hint)
    wait = int(dept.get("wait_minutes", 30))
    cap_pct = (dept["patients"] / dept["capacity"]) * 100 if dept.get("capacity") else 100.0

    specialty_match = specialty_hint in hospital.get("specialties", []) or specialty_hint == "general"

    # Urgency-aware weighting:
    #   critical → favour drive time + specialty (life-threatening, every minute matters)
    #   high     → balanced
    #   medium   → wait time matters more (patient is stable but uncomfortable)
    #   low      → favour low-capacity sites, deflect from majors
    weights = {
        "critical": (1.5, 0.7, 0.2),  # drive, wait, capacity-penalty
        "high":     (1.2, 1.0, 0.3),
        "medium":   (0.9, 1.2, 0.4),
        "low":      (0.7, 1.0, 0.6),
    }.get(urgency, (1.0, 1.0, 0.4))

    drive_w, wait_w, cap_w = weights
    capacity_penalty = max(0.0, cap_pct - 70) * cap_w  # only penalise above 70% full
    specialty_bonus = -10 if specialty_match else 6
    diversion_penalty = 999 if hospital.get("diverting") and urgency != "low" else 0

    score = (
        drive * drive_w
        + wait * wait_w
        + capacity_penalty
        + specialty_bonus
        + diversion_penalty
    )

    reasons: list[str] = []
    reasons.append(f"{dept_name} dept at {cap_pct:.0f}% capacity")
    if specialty_match:
        reasons.append(f"matches needed specialty ({specialty_hint})")
    if hospital.get("diverting"):
        reasons.append("currently diverting non-critical cases")
    incidents = [
        inc["location"] for inc in traffic().get("incidents", [])
        if hospital["id"] in inc.get("affected_hospitals", [])
    ]
    if incidents:
        reasons.append("traffic delay near " + incidents[0])

    return HospitalScore(
        hospital_id=hospital["id"],
        name=hospital["name"],
        distance_miles=round(distance, 1),
        drive_minutes=drive,
        wait_minutes=wait,
        total_minutes=drive + wait,
        capacity_pct=round(cap_pct, 1),
        specialty_match=specialty_match,
        score=round(score, 2),
        reasons=reasons,
    )


def rank_hospitals(
    hospitals: Iterable[dict],
    user_lat: float,
    user_lon: float,
    urgency: str,
    specialty_hint: str,
    top_n: int = 5,
) -> list[HospitalScore]:
    scored = [
        score_hospital(h, user_lat, user_lon, urgency, specialty_hint)
        for h in hospitals
    ]
    scored.sort(key=lambda s: s.score)
    return scored[:top_n]

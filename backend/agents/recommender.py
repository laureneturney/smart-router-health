"""
Recommender agent — given the triage output and a ranked candidate list,
asks the LLM to narrate the choice in plain English. The actual ranking
is deterministic (services.routing); the LLM only explains *why*.

Returns the chosen hospital score plus a short rationale.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from backend.llm_provider import get_provider
from backend.services.routing import HospitalScore

SYSTEM_PROMPT = """You are an NHS routing assistant. You are given:
  - a triage result (urgency, specialty hint)
  - a ranked list of nearby hospitals with distance, drive time,
    predicted wait, capacity, and reasons

Pick the FIRST hospital in the list (it has already been algorithmically
ranked) and write a short, calm, plain-English rationale a patient can read.

Output JSON:
  rationale:       1-2 sentences — why this hospital is the best fit right now
  tradeoff_notes:  1 sentence — what was traded off vs. the closest option
"""


def run(triage: dict, candidates: list[HospitalScore]) -> dict:
    if not candidates:
        return {"rationale": "No hospital available.", "tradeoff_notes": ""}

    chosen = candidates[0]
    payload = {
        "triage": triage,
        "candidates": [asdict(c) for c in candidates[:5]],
    }
    raw = get_provider().complete_json(
        system=SYSTEM_PROMPT,
        user=json.dumps(payload),
        schema_hint={"task": "recommend"},
    ) or {}

    rationale = raw.get("rationale") or _fallback_rationale(chosen, triage)
    tradeoff = raw.get("tradeoff_notes") or _fallback_tradeoff(candidates)

    return {
        "chosen": asdict(chosen),
        "alternatives": [asdict(c) for c in candidates[1:]],
        "rationale": rationale,
        "tradeoff_notes": tradeoff,
    }


def _fallback_rationale(chosen: HospitalScore, triage: dict) -> str:
    bits = [f"{chosen.name} gives the shortest total time-to-treatment "
            f"(~{chosen.total_minutes} min: {chosen.drive_minutes} min drive + "
            f"{chosen.wait_minutes} min predicted wait)."]
    if chosen.specialty_match and triage.get("specialty_hint") != "general":
        bits.append(f"It also has the right specialty ({triage['specialty_hint']}) for your symptoms.")
    return " ".join(bits)


def _fallback_tradeoff(candidates: list[HospitalScore]) -> str:
    if len(candidates) < 2:
        return ""
    nearest = min(candidates, key=lambda c: c.distance_miles)
    chosen = candidates[0]
    if nearest.hospital_id == chosen.hospital_id:
        return "This was also the closest option."
    return (f"{nearest.name} is closer ({nearest.distance_miles} mi) "
            f"but its predicted wait ({nearest.wait_minutes} min) made the total time longer.")

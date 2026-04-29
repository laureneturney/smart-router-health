"""
FastAPI HTTP layer. Streamlit calls into this so the front-end and the
agent code stay cleanly separated — a real deployment can put the API
behind an internal NHS gateway and run the front-end anywhere.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.agents.orchestrator import assess_and_recommend, confirm_and_notify
from backend.llm_provider import display_provider_name, get_provider
from backend.services.routing import rank_hospitals
from backend.store import (
    add_feedback, all_hospitals, feedback, incoming, update_hospital, wait_history,
)

app = FastAPI(title="A&E Smart Routing API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas --------------------------------------------------------
class AssessRequest(BaseModel):
    symptoms: str
    pain_level: int = Field(ge=0, le=10, default=5)
    age: int | None = None
    existing_conditions: list[str] = []
    user_lat: float
    user_lon: float
    specialty_filter: str | None = None


class ConfirmRequest(BaseModel):
    hospital_id: str
    name: str
    age: int | None = None
    symptoms: str = ""
    urgency: str = "medium"
    drive_minutes: int = 0
    allergies: list[str] = []
    medications: str = ""
    existing_conditions: list[str] = []
    emergency_contact: str | None = None
    language: str | None = None
    accessibility: list[str] = []
    consent_share: bool = False


class FeedbackRequest(BaseModel):
    hospital_id: str
    predicted_wait: int
    actual_wait: int
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class CapacityUpdate(BaseModel):
    hospital_id: str
    department: str
    patients: int | None = None
    capacity: int | None = None
    wait_minutes: int | None = None
    doctors_on_shift: int | None = None
    nurses_on_shift: int | None = None
    diverting: bool | None = None
    notes: str | None = None


class NearbyRequest(BaseModel):
    user_lat: float
    user_lon: float
    urgency: str = "medium"
    specialty_hint: str = "general"
    top_n: int = 5


# ---------- routes ---------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider_internal": get_provider().name,
        "provider_display": display_provider_name(),
    }


@app.get("/api/hospitals")
def list_hospitals() -> list[dict]:
    return all_hospitals()


@app.post("/api/hospitals/nearby")
def hospitals_nearby(req: NearbyRequest) -> list[dict]:
    ranked = rank_hospitals(
        all_hospitals(),
        user_lat=req.user_lat, user_lon=req.user_lon,
        urgency=req.urgency, specialty_hint=req.specialty_hint,
        top_n=req.top_n,
    )
    return [r.__dict__ for r in ranked]


@app.post("/api/assess")
def assess(req: AssessRequest) -> dict:
    return assess_and_recommend(
        symptoms=req.symptoms,
        pain_level=req.pain_level,
        age=req.age,
        existing_conditions=req.existing_conditions,
        user_lat=req.user_lat,
        user_lon=req.user_lon,
        specialty_filter=req.specialty_filter,
    )


@app.post("/api/confirm")
def confirm(req: ConfirmRequest) -> dict:
    record = confirm_and_notify(
        hospital_id=req.hospital_id,
        patient={
            "name": req.name,
            "age": req.age,
            "symptoms": req.symptoms,
            "allergies": req.allergies,
            "medications": req.medications,
            "existing_conditions": req.existing_conditions,
            "emergency_contact": req.emergency_contact,
            "language": req.language,
            "accessibility": req.accessibility,
            "consent_share": req.consent_share,
        },
        urgency=req.urgency,
        drive_minutes=req.drive_minutes,
    )
    return record


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest) -> dict:
    add_feedback(req.model_dump())
    return {"status": "ok"}


# ---------- admin routes ---------------------------------------------------
@app.get("/api/admin/dashboard/{hospital_id}")
def admin_dashboard(hospital_id: str) -> dict:
    hospitals = {h["id"]: h for h in all_hospitals()}
    h = hospitals.get(hospital_id)
    if not h:
        raise HTTPException(status_code=404, detail="hospital not found")

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


@app.post("/api/admin/capacity")
def admin_update_capacity(req: CapacityUpdate) -> dict:
    h = next((x for x in all_hospitals() if x["id"] == req.hospital_id), None)
    if not h:
        raise HTTPException(status_code=404, detail="hospital not found")

    departments = h["departments"].copy()
    if req.department:
        if req.department not in departments:
            raise HTTPException(status_code=404, detail="department not found")
        dept = departments[req.department].copy()
        if req.patients is not None:
            dept["patients"] = max(0, req.patients)
        if req.capacity is not None:
            dept["capacity"] = max(1, req.capacity)
        if req.wait_minutes is not None:
            dept["wait_minutes"] = max(0, req.wait_minutes)
        departments[req.department] = dept

    patch: dict[str, Any] = {"departments": departments}
    if req.doctors_on_shift is not None:
        patch["doctors_on_shift"] = req.doctors_on_shift
    if req.nurses_on_shift is not None:
        patch["nurses_on_shift"] = req.nurses_on_shift
    if req.diverting is not None:
        patch["diverting"] = req.diverting
    if req.notes is not None:
        patch["notes"] = req.notes

    return update_hospital(req.hospital_id, patch)


# entry-point so `python -m backend.api` boots the server.
def main() -> None:
    import os
    import uvicorn

    uvicorn.run(
        "backend.api:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()

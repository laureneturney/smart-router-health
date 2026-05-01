"""
A&E Smart Routing — Streamlit entry point (patient-facing flow).

The flow follows the four screens in the brief:
    1. Welcome / permissions
    2. Hospital list (top 5 nearby)
    3. Patient details + confirmation
    4. "On your way" with reference code

Per spec: the UI always brands the reasoning service as "IBM watsonx",
even when the underlying provider is "mock" or "custom".
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# allow `import backend.*` when streamlit launches us from anywhere
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv

from frontend import api_client

load_dotenv()

# --------------------------------------------------------------------------- #
# Page config + theming overrides                                              #
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="A&E Smart Routing",
    page_icon="🏥",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def _inject_css() -> None:
    font_size_pct = st.session_state.get("font_size_pct", 100)
    st.markdown(
        f"""
        <style>
          html, body, [class*="css"] {{
              font-size: {font_size_pct}% !important;
          }}
          .ae-header {{
              display: flex; justify-content: space-between; align-items: center;
              padding: 8px 0; border-bottom: 1px solid #2a2f3a; margin-bottom: 18px;
          }}
          .ae-title {{
              font-size: 2.2rem; font-weight: 700; color: #4FA3DD; letter-spacing: .3px;
              margin: 0;
          }}
          .ae-subtitle {{ color: #b8c0cc; margin-top: -6px; }}
          .info-card {{
              background: #DCEAF7; color: #0F2A4A; padding: 16px 20px;
              border-radius: 10px; margin: 16px 0;
          }}
          .info-card h4 {{ margin: 0 0 6px 0; color: #0F4C81; }}
          .alert-card {{
              background: #FBE3E3; color: #6E1F1F; padding: 12px 18px;
              border-left: 5px solid #C0392B; border-radius: 6px; margin: 16px 0;
          }}
          .success-card {{
              background: #DDEFE6; color: #0E5230; padding: 18px;
              border-radius: 10px; text-align: center;
          }}
          .ref-code {{
              font-family: ui-monospace, Menlo, monospace; font-size: 1.6rem;
              color: #4FA3DD; letter-spacing: 2px;
          }}
          .hospital-card {{
              border: 1px solid #2a2f3a; border-radius: 10px; padding: 14px 18px;
              margin: 8px 0; background: #1B1F27;
          }}
          .hospital-card.recommended {{
              border-color: #4FA3DD; background: #14242F;
          }}
          .pill {{
              display: inline-block; padding: 2px 10px; border-radius: 999px;
              font-size: .75rem; margin-right: 4px; background: #233140; color: #cdd9e5;
          }}
          .pill.urgent  {{ background: #6E1F1F; color: #fff; }}
          .pill.high    {{ background: #8a4a17; color: #fff; }}
          .pill.medium  {{ background: #5a4d18; color: #fff; }}
          .pill.match   {{ background: #1f5a3b; color: #fff; }}
          .powered {{
              text-align: right; color: #6f7a87; font-size: .8rem; margin-top: 30px;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Session state                                                                #
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    defaults = {
        "step": "welcome",
        "share_location": True,
        "share_health": True,
        "user_lat": float(os.getenv("DEFAULT_LAT", "53.4808")),
        "user_lon": float(os.getenv("DEFAULT_LON", "-2.2426")),
        "font_size_pct": 100,
        "voice_enabled": False,
        "assessment": None,
        "selected_hospital_id": None,
        "patient_form": {},
        "confirmation": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


# --------------------------------------------------------------------------- #
# Header (accessibility toolbar + 999 / 111)                                   #
# --------------------------------------------------------------------------- #
def _render_header() -> None:
    cols = st.columns([1, 1, 4, 1, 1])

    with cols[0]:
        if st.button("A+", help="Increase text size", use_container_width=True):
            st.session_state.font_size_pct = min(150, st.session_state.font_size_pct + 15)
            st.rerun()
    with cols[1]:
        if st.button("A−", help="Decrease text size", use_container_width=True):
            st.session_state.font_size_pct = max(85, st.session_state.font_size_pct - 15)
            st.rerun()
    with cols[2]:
        if st.button("🎤 Voice", help="Enable read-aloud (turn up volume)", use_container_width=True):
            st.session_state.voice_enabled = not st.session_state.voice_enabled
            st.toast(
                "Read-aloud enabled. Please turn up your volume."
                if st.session_state.voice_enabled
                else "Read-aloud disabled."
            )
    with cols[3]:
        st.link_button("📞 999", "tel:999", use_container_width=True, type="primary")
    with cols[4]:
        st.link_button("📞 111", "tel:111", use_container_width=True)


def _render_title() -> None:
    st.markdown(
        '<div class="ae-header"><h1 class="ae-title">A&E Smart Routing</h1></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<p class="ae-subtitle">Find your nearest hospital</p>', unsafe_allow_html=True)


def _render_powered_by() -> None:
    st.markdown(
        '<div class="powered">Reasoning powered by <b>IBM watsonx</b></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Step 1 — welcome / permissions                                               #
# --------------------------------------------------------------------------- #
def _render_welcome() -> None:
    st.markdown(
        """
        <div class="info-card">
          <h4>How we help</h4>
          We'll find the nearest hospital with the shortest wait time and
          notify them you're arriving.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.session_state.share_location = st.checkbox(
        "Share my location",
        value=st.session_state.share_location,
        help="Used only to find nearby hospitals. Not stored after your visit.",
    )
    st.caption("Used only to find nearby hospitals. Not stored after your visit.")

    st.session_state.share_health = st.checkbox(
        "Share my health details with hospital",
        value=st.session_state.share_health,
        help="Helps hospital staff prepare for your arrival.",
    )
    st.caption("Helps hospital staff prepare for your arrival.")

    with st.expander("Use a different location"):
        c1, c2 = st.columns(2)
        st.session_state.user_lat = c1.number_input(
            "Latitude", value=float(st.session_state.user_lat), format="%.4f"
        )
        st.session_state.user_lon = c2.number_input(
            "Longitude", value=float(st.session_state.user_lon), format="%.4f"
        )

    st.divider()
    st.markdown(
        '<div class="alert-card"><b>Disclaimer:</b> Wait-time predictions are guidance, not '
        'a guarantee — clinical emergencies arriving on-site can change priority at any time. '
        'If symptoms worsen, call 999 immediately.</div>',
        unsafe_allow_html=True,
    )

    if st.button("Use my location", type="primary", use_container_width=True,
                 disabled=not st.session_state.share_location):
        st.session_state.step = "hospital_list"
        st.rerun()

    with st.expander("Not sure if you need A&E?"):
        st.write(
            "**Self-check** — non-life-threatening issues such as minor cuts, sprains, "
            "or coughs may be treated faster at a GP, urgent treatment centre, or by "
            "calling 111. Use A&E for chest pain, difficulty breathing, severe bleeding, "
            "stroke symptoms (face droop / arm weakness / slurred speech), severe burns, "
            "or loss of consciousness."
        )


# --------------------------------------------------------------------------- #
# Step 2 — hospital list                                                       #
# --------------------------------------------------------------------------- #
def _render_hospital_list() -> None:
    st.button("← Change location", on_click=lambda: st.session_state.update(step="welcome"))

    st.subheader("Nearest hospitals")
    st.caption("Ordered by predicted total time-to-treatment.")

    ranked = api_client.post("/api/hospitals/nearby", {
        "user_lat": st.session_state.user_lat,
        "user_lon": st.session_state.user_lon,
        "urgency": "medium",
        "specialty_hint": "general",
        "top_n": 5,
    })

    if not ranked:
        st.info("No hospitals found near this location.")
        return

    for idx, h in enumerate(ranked):
        recommended = idx == 0
        cls = "hospital-card recommended" if recommended else "hospital-card"
        badges = []
        if recommended:
            badges.append('<span class="pill match">Recommended</span>')
        if h["specialty_match"]:
            badges.append('<span class="pill match">Specialty match</span>')
        if h["capacity_pct"] > 85:
            badges.append('<span class="pill urgent">High load</span>')

        st.markdown(
            f"""
            <div class="{cls}">
              <div style="display:flex; justify-content:space-between;">
                <div>
                  <h3 style="margin:0">{h['name']}</h3>
                  <div style="color:#9aa6b2; margin-top:4px;">
                    ETA: {h['drive_minutes']} min &nbsp;•&nbsp;
                    Estimated wait: {h['wait_minutes']} min &nbsp;•&nbsp;
                    {h['distance_miles']} mi
                  </div>
                  <div style="margin-top:6px;">{' '.join(badges)}</div>
                </div>
                <div style="text-align:right; min-width: 110px;">
                  <div style="font-size:1.4rem; color:#4FA3DD; font-weight:700;">
                    {h['total_minutes']} min
                  </div>
                  <div style="color:#9aa6b2;">total</div>
                </div>
              </div>
              <div style="color:#cdd9e5; margin-top:10px; font-size:.9rem;">
                {' • '.join(h['reasons'])}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(f"Select {h['name']}", key=f"select-{h['hospital_id']}",
                     use_container_width=True,
                     type="primary" if recommended else "secondary"):
            st.session_state.selected_hospital_id = h["hospital_id"]
            st.session_state.selected_hospital_score = h
            st.session_state.step = "patient_form"
            st.rerun()


# --------------------------------------------------------------------------- #
# Step 3 — patient form                                                        #
# --------------------------------------------------------------------------- #
ALLERGIES = ["NSAIDs", "Penicillin", "Latex", "Other"]
CONDITIONS = ["Diabetes", "Heart disease", "Asthma", "Pregnancy"]
ACCESSIBILITY = ["Wheelchair", "Hearing support", "Mobility support", "Other"]
HOSPITAL_TYPES = ["General A&E", "Trauma centre", "Cardiac specialist", "Stroke specialist",
                  "Paediatric", "Urgent care"]


def _render_patient_form() -> None:
    chosen = st.session_state.get("selected_hospital_score")
    if not chosen:
        st.session_state.step = "hospital_list"
        st.rerun()
        return

    if st.button("← Change hospital"):
        st.session_state.step = "hospital_list"
        st.rerun()

    st.subheader(chosen["name"])
    st.caption(f"ETA: {chosen['drive_minutes']} min • Estimated wait: {chosen['wait_minutes']} min")

    st.markdown("---")

    name = st.text_input("Full name *", placeholder="Your name",
                         value=st.session_state.patient_form.get("name", ""))

    def _sync_age_from_dob() -> None:
        dob_val = st.session_state.get("patient_dob")
        if dob_val:
            today = date.today()
            st.session_state["patient_age"] = (
                today.year - dob_val.year
                - ((today.month, today.day) < (dob_val.month, dob_val.day))
            )

    if "patient_age" not in st.session_state:
        st.session_state["patient_age"] = int(st.session_state.patient_form.get("age", 30))

    c1, c2 = st.columns(2)
    age = c1.number_input("Age *", min_value=0, max_value=120, key="patient_age")
    dob = c2.date_input(
        "Date of birth (optional)",
        value=None,
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        format="MM/DD/YYYY",
        key="patient_dob",
        on_change=_sync_age_from_dob,
        help="Picking a date will fill in the age field for you.",
    )

    symptoms = st.text_area("Main symptoms *",
                            placeholder="e.g., chest pain, shortness of breath",
                            value=st.session_state.patient_form.get("symptoms", ""))

    pain_level = st.slider("Pain level (0–10) *", 0, 10,
                           value=int(st.session_state.patient_form.get("pain_level", 5)))
    c1, c2 = st.columns([1, 1])
    c1.caption("No pain")
    c2.markdown("<div style='text-align:right; color:#9aa6b2'>Severe pain</div>",
                unsafe_allow_html=True)

    st.markdown("**Allergies**")
    cols = st.columns(2)
    allergies = []
    for i, allergy in enumerate(ALLERGIES):
        if cols[i % 2].checkbox(allergy, key=f"allergy-{allergy}"):
            allergies.append(allergy)
    other_allergies = st.text_input("Other allergies", placeholder="Other allergies",
                                    label_visibility="collapsed")
    if other_allergies:
        allergies.append(other_allergies)

    st.markdown("**Current medications**")
    medications = st.text_input("Current medications", placeholder="e.g., Aspirin 75mg daily",
                                label_visibility="collapsed",
                                value=st.session_state.patient_form.get("medications", ""))

    st.markdown("**Existing conditions**")
    cols = st.columns(2)
    conditions = []
    for i, cond in enumerate(CONDITIONS):
        if cols[i % 2].checkbox(cond, key=f"cond-{cond}"):
            conditions.append(cond)

    emergency_contact = st.text_input("Emergency contact phone",
                                      placeholder="+44 7700 000000",
                                      value=st.session_state.patient_form.get("emergency_contact", ""))

    st.markdown("**Accessibility needs**")
    cols = st.columns(2)
    access = []
    for i, a in enumerate(ACCESSIBILITY):
        if cols[i % 2].checkbox(a, key=f"access-{a}"):
            access.append(a)

    hospital_type = st.selectbox("Hospital type needed",
                                 ["No preference"] + HOSPITAL_TYPES, index=0)

    st.markdown("**Parking & transport**")
    st.caption(
        f"Parking: ~{chosen.get('capacity_pct', 0):.0f}% busy site. "
        f"Public transport may be quicker — see hospital details after confirming."
    )

    st.markdown(
        '<div class="alert-card"><b>Important:</b> If you\'re experiencing chest pain, '
        'severe difficulty breathing, or uncontrolled bleeding, call 999 immediately.</div>',
        unsafe_allow_html=True,
    )

    consent = st.checkbox(
        "I agree to share my health data with this hospital to speed up my treatment",
        value=st.session_state.share_health,
    )

    if st.button("Confirm & get directions", type="primary", use_container_width=True,
                 disabled=not (name and symptoms and consent)):
        # save form so a "back" doesn't lose it
        st.session_state.patient_form = {
            "name": name, "age": age, "symptoms": symptoms,
            "pain_level": pain_level, "medications": medications,
            "emergency_contact": emergency_contact,
        }

        # Run agentic assessment to lock in urgency for the chosen hospital.
        assessment = api_client.post("/api/assess", {
            "symptoms": symptoms, "pain_level": pain_level,
            "age": age, "existing_conditions": conditions,
            "user_lat": st.session_state.user_lat,
            "user_lon": st.session_state.user_lon,
        })
        urgency = assessment["triage"]["urgency"]
        st.session_state.assessment = assessment

        confirmation = api_client.post("/api/confirm", {
            "hospital_id": chosen["hospital_id"],
            "name": name, "age": age, "symptoms": symptoms,
            "urgency": urgency, "drive_minutes": chosen["drive_minutes"],
            "allergies": allergies,
            "medications": medications,
            "existing_conditions": conditions,
            "emergency_contact": emergency_contact,
            "language": "English",
            "accessibility": access,
            "consent_share": consent,
        })
        st.session_state.confirmation = confirmation
        st.session_state.step = "on_your_way"
        st.rerun()


# --------------------------------------------------------------------------- #
# Step 4 — on your way                                                         #
# --------------------------------------------------------------------------- #
def _render_on_your_way() -> None:
    confirmation = st.session_state.get("confirmation")
    chosen = st.session_state.get("selected_hospital_score")
    assessment = st.session_state.get("assessment") or {}
    if not (confirmation and chosen):
        st.session_state.step = "welcome"
        st.rerun()
        return

    st.markdown(
        f"""
        <div class="success-card">
          <div style="color:#0E5230; font-weight:600;">✓ Hospital notified</div>
          <h2 style="margin: 6px 0;">You're on your way</h2>
          <div>{chosen['name']} is expecting you</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("&nbsp;")
    st.markdown("**REFERENCE CODE**")
    st.markdown(f'<div class="ref-code">{confirmation["reference"]}</div>',
                unsafe_allow_html=True)
    st.caption("Show this at reception when you arrive.")

    st.markdown("---")
    st.markdown("### Your journey")
    cols = st.columns(2)
    cols[0].metric("Drive time", f"{chosen['drive_minutes']} min")
    cols[1].metric("Expected wait", f"{chosen['wait_minutes']} min")
    cols[0].metric("Distance", f"{chosen['distance_miles']} mi")
    cols[1].metric("Total time", f"{chosen['total_minutes']} min")

    if assessment:
        st.markdown("### Assessment")
        urg = assessment["triage"]["urgency"]
        st.markdown(
            f'<span class="pill {"urgent" if urg == "critical" else urg}">'
            f'Triage: {urg.upper()}</span>',
            unsafe_allow_html=True,
        )
        st.write(assessment["triage"]["guidance"])
        if assessment.get("recommendation"):
            st.info(assessment["recommendation"]["rationale"])

    h_lat, h_lon = None, None
    for row in api_client.get("/api/hospitals"):
        if row["id"] == chosen["hospital_id"]:
            h_lat, h_lon = row["lat"], row["lon"]
            break

    if h_lat is not None:
        maps_url = f"https://www.google.com/maps/dir/?api=1&destination={h_lat},{h_lon}"
        st.link_button("Open in Maps", maps_url, type="primary", use_container_width=True)

    st.markdown("---")
    with st.expander("After your visit — was the wait time accurate?"):
        actual = st.number_input("Actual wait (minutes)", min_value=0, max_value=600,
                                 value=chosen["wait_minutes"])
        rating = st.slider("How accurate was the prediction?", 1, 5, 4)
        comment = st.text_input("Anything to add?")
        if st.button("Submit feedback"):
            api_client.post("/api/feedback", {
                "hospital_id": chosen["hospital_id"],
                "predicted_wait": chosen["wait_minutes"],
                "actual_wait": int(actual),
                "rating": int(rating),
                "comment": comment,
            })
            st.success("Thanks — your feedback helps the model improve.")

    if st.button("Start a new request"):
        for k in ("assessment", "selected_hospital_id", "selected_hospital_score",
                  "patient_form", "confirmation"):
            st.session_state.pop(k, None)
        st.session_state.step = "welcome"
        st.rerun()


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    _init_state()
    _inject_css()
    _render_header()
    _render_title()

    step = st.session_state.step
    if step == "welcome":
        _render_welcome()
    elif step == "hospital_list":
        _render_hospital_list()
    elif step == "patient_form":
        _render_patient_form()
    elif step == "on_your_way":
        _render_on_your_way()
    else:
        st.session_state.step = "welcome"
        st.rerun()

    _render_powered_by()


if __name__ == "__main__":
    main()

"""
Hospital admin dashboard — separate Streamlit page.

Shows live capacity, incoming patients (with severity), historical wait
charts, feedback, and lets staff update capacity / open a divert / leave
notes for the routing engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from frontend import api_client

st.set_page_config(page_title="A&E Admin Dashboard", page_icon="🏥", layout="wide")

st.markdown(
    """
    <style>
      .section-card { background:#1B1F27; padding:18px; border-radius:10px; margin-bottom:14px; }
      .alert-banner {
          background:#3a1f1f; color:#ffb4b4; padding:10px 14px; border-radius:6px;
          border-left:4px solid #c0392b; margin-bottom:10px;
      }
      .powered { text-align:right; color:#6f7a87; font-size:.8rem; margin-top:30px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _hospital_list() -> list[dict]:
    return api_client.get("/api/hospitals")


def _dashboard(hid: str) -> dict:
    return api_client.get(f"/api/admin/dashboard/{hid}")


# --------------------------------------------------------------------------- #
hospitals = _hospital_list()
hosp_options = {h["id"]: h["name"] for h in hospitals}

with st.sidebar:
    st.title("🏥 Admin Dashboard")
    selected = st.selectbox("Hospital", list(hosp_options.keys()),
                            format_func=lambda i: hosp_options[i])
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()
    st.divider()
    st.caption("Reasoning powered by **IBM watsonx**")

dash = _dashboard(selected)
hospital = dash["hospital"]
totals = dash["totals"]

st.title("Admin dashboard")
st.markdown(f"**{hospital['name']}** · {hospital['trust']} · *Emergency Department*")

# alert banner if capacity > 90% or wait > 45m
alerts = []
if totals["capacity_pct"] >= 90:
    alerts.append(f"⚠️  ER at {totals['capacity_pct']}% capacity — consider diverting non-critical")
if totals["overall_wait_minutes"] >= 45:
    alerts.append(f"⚠️  Average wait {totals['overall_wait_minutes']} min — above 45-min threshold")
if hospital.get("diverting"):
    alerts.append("🚨  Currently diverting non-critical arrivals")
for msg in alerts:
    st.markdown(f'<div class="alert-banner">{msg}</div>', unsafe_allow_html=True)

# top-line KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Patients in ER", totals["patients_in_er"])
c2.metric("Capacity", f"{totals['capacity_pct']}%",
          delta=f"{totals['patients_in_er']}/{totals['capacity_total']}",
          delta_color="off")
c3.metric("Avg wait", f"{totals['overall_wait_minutes']} min")
c4.metric("Doctors / Nurses",
          f"{hospital['doctors_on_shift']} / {hospital['nurses_on_shift']}")

st.markdown("---")

# --------------------------------------------------------------------------- #
# Capacity update form                                                         #
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Update capacity")
    dept_names = list(hospital["departments"].keys())
    with st.form("capacity_form", clear_on_submit=False):
        dept = st.selectbox("Department", dept_names)
        d = hospital["departments"][dept]
        c1, c2, c3 = st.columns(3)
        new_patients = c1.number_input("Patients", min_value=0, max_value=200,
                                       value=int(d["patients"]))
        new_capacity = c2.number_input("Capacity", min_value=1, max_value=200,
                                       value=int(d["capacity"]))
        new_wait = c3.number_input("Wait (min)", min_value=0, max_value=600,
                                   value=int(d["wait_minutes"]))

        c1, c2 = st.columns(2)
        new_docs = c1.number_input("Doctors on shift", min_value=0, max_value=200,
                                   value=int(hospital["doctors_on_shift"]))
        new_nurses = c2.number_input("Nurses on shift", min_value=0, max_value=400,
                                     value=int(hospital["nurses_on_shift"]))

        diverting = st.checkbox("Divert new arrivals", value=hospital.get("diverting", False))
        notes = st.text_input("Notes (visible to dispatchers)",
                              value=hospital.get("notes", ""),
                              placeholder="e.g., CT scanner down, diverting trauma")

        submitted = st.form_submit_button("Update", type="primary", use_container_width=True)
        if submitted:
            api_client.post("/api/admin/capacity", {
                "hospital_id": hospital["id"],
                "department": dept,
                "patients": int(new_patients),
                "capacity": int(new_capacity),
                "wait_minutes": int(new_wait),
                "doctors_on_shift": int(new_docs),
                "nurses_on_shift": int(new_nurses),
                "diverting": bool(diverting),
                "notes": notes,
            })
            st.success("Updated.")
            st.rerun()

    # Department status table
    st.subheader("Department status")
    dept_rows = []
    for name, info in hospital["departments"].items():
        cap_pct = round(info["patients"] / max(1, info["capacity"]) * 100)
        dept_rows.append({
            "Department": name.title(),
            "Patients": info["patients"],
            "Capacity": info["capacity"],
            "% Full": cap_pct,
            "Wait (min)": info["wait_minutes"],
        })
    st.dataframe(pd.DataFrame(dept_rows), use_container_width=True, hide_index=True)

with right:
    # Incoming queue
    st.subheader("Incoming patient queue")
    if not dash["incoming"]:
        st.info("No incoming patients.")
    else:
        for p in sorted(dash["incoming"], key=lambda x: x.get("eta_minutes", 99)):
            urg = p.get("urgency", "medium")
            colour = {"critical": "#C0392B", "high": "#E67E22",
                      "medium": "#D4AC0D", "low": "#27AE60"}.get(urg, "#888")
            st.markdown(
                f"""
                <div class="section-card" style="border-left:4px solid {colour};">
                  <div style="display:flex; justify-content:space-between;">
                    <b>{p['name']} · age {p.get('age', '?')}</b>
                    <span style="color:{colour}; font-weight:700;">{urg.upper()}</span>
                  </div>
                  <div style="color:#9aa6b2; margin-top:4px;">{p['symptoms']}</div>
                  <div style="margin-top:6px; font-size:.85rem;">
                    Ref <code>{p['reference']}</code> · ETA {p.get('eta_minutes', '?')} min
                    · {'via app' if p.get('via_app') else 'walk-in'}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown("---")

# --------------------------------------------------------------------------- #
# Charts                                                                       #
# --------------------------------------------------------------------------- #
st.subheader("Wait time — last 24h")
hours = [f"{i:02d}:00" for i in range(24)]
df = pd.DataFrame({"hour": hours, "wait": dash["history_hours_24h"] or [0] * 24})
fig = px.line(df, x="hour", y="wait", markers=True,
              labels={"hour": "Hour", "wait": "Predicted wait (min)"})
fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- #
# Analytics: app vs other arrivals + feedback
# --------------------------------------------------------------------------- #
c1, c2 = st.columns(2)

with c1:
    st.subheader("Arrivals by channel")
    via_app = sum(1 for p in dash["incoming"] if p.get("via_app"))
    other = max(0, totals["patients_in_er"] - via_app)
    arrivals_df = pd.DataFrame({
        "channel": ["Via app", "Other"], "count": [via_app, other],
    })
    fig2 = px.pie(arrivals_df, names="channel", values="count", hole=0.5)
    fig2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=10))
    st.plotly_chart(fig2, use_container_width=True)

with c2:
    st.subheader("Recent patient feedback")
    if not dash["feedback"]:
        st.info("No feedback yet.")
    else:
        for fb in dash["feedback"][-5:][::-1]:
            stars = "★" * fb["rating"] + "☆" * (5 - fb["rating"])
            st.markdown(
                f"""
                <div class="section-card">
                  <div style="color:#ffd479; font-size:1.2rem;">{stars}</div>
                  <div>{fb.get('comment', '')}</div>
                  <div style="color:#9aa6b2; font-size:.85rem; margin-top:4px;">
                    Predicted {fb['predicted_wait']} min · actual {fb['actual_wait']} min
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown('<div class="powered">Reasoning powered by <b>IBM watsonx</b></div>',
            unsafe_allow_html=True)

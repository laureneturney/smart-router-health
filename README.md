# A&E Smart Routing — Agentic AI MVP

End-to-end working demo of an A&E (emergency-room) routing assistant:
patients enter symptoms, the system runs an **agentic** triage →
recommend → route pipeline, picks the hospital with the lowest
predicted total time-to-treatment, and notifies the receiving hospital.

Built for the IBM Experiential AI Learning Lab. Reasoning is provider-
agnostic: swap between **IBM watsonx.ai**, an **OpenAI-compatible**
endpoint (Ollama, vLLM, OpenAI, LM Studio…), or a deterministic
**mock** model that runs offline. The patient UI always brands the
service as *IBM watsonx* per the design spec.

---

## Quick start

```bash
cd ae-smart-routing
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # edit if you want to point at watsonx / a custom LLM
./run.sh                   # starts FastAPI on :8000 and Streamlit on :8501
```

Then open **<http://localhost:8501>** for the patient app, and use the
left-hand sidebar to jump to the **Hospital Admin** dashboard.

> No watsonx creds? Leave `LLM_PROVIDER=mock` — the demo runs end-to-end
> with a deterministic local stub. Real watsonx output drops in by
> setting `LLM_PROVIDER=watsonx` and filling in the watsonx vars in `.env`.

---

## Architecture

```
ae-smart-routing/
├── app.py                       # Streamlit patient flow (4 screens)
├── pages/2_Hospital_Admin.py    # Streamlit admin dashboard
├── backend/
│   ├── api.py                   # FastAPI endpoints
│   ├── llm_provider.py          # watsonx / custom / mock abstraction
│   ├── store.py                 # JSON-backed data layer
│   ├── services/routing.py      # geo + ranking (deterministic)
│   └── agents/
│       ├── triage.py            # urgency + specialty classification
│       ├── recommender.py       # narrates choice, picks chosen hospital
│       └── orchestrator.py      # chains triage → rank → recommend
├── frontend/api_client.py       # HTTP client (in-process fallback)
└── data/                        # synthetic Manchester-area dataset
    ├── hospitals.json
    ├── traffic.json
    ├── wait_history.json
    ├── incoming_patients.json
    └── feedback.json
```

### The agent loop

1. **Triage agent** — takes the symptom text + pain level + age + conditions.
   Returns `{urgency, specialty_hint, guidance, red_flags}`.
2. **Routing service** — deterministic; computes distance, drive-time
   (with traffic + incident multipliers), wait, and a urgency-weighted
   score for each hospital.
3. **Recommender agent** — narrates *why* the top-ranked hospital is the
   best fit and what was traded off vs. the closest option.
4. **Confirmation** — patient is added to the hospital's incoming queue
   with a reference code; the admin dashboard shows them in real time.

### Why split LLM and ranking?

Ranking is pure arithmetic — it has to be reproducible, auditable, and
fast. The LLM's job is the soft-edge work: classifying free-text
symptoms and writing a calm, plain-English rationale. This split also
makes the system testable — agent outputs are constrained to a small
JSON schema and we always normalise / fall back if the model goes off-
piste.

---

## Switching LLM providers

Edit `.env`:

```ini
LLM_PROVIDER=watsonx   # or: custom | mock
```

| Provider | Required env vars |
|----------|-------------------|
| `watsonx` | `WATSONX_APIKEY`, `WATSONX_URL`, `WATSONX_PROJECT_ID`, `WATSONX_MODEL_ID` |
| `custom`  | `CUSTOM_LLM_BASE_URL`, `CUSTOM_LLM_API_KEY`, `CUSTOM_LLM_MODEL` |
| `mock`    | none — runs offline |

The patient-facing UI always says *Reasoning powered by **IBM watsonx***
regardless of the actual provider, per the brief.

---

## Endpoints (FastAPI)

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/health` | provider name + status |
| `GET`  | `/api/hospitals` | full hospital catalogue |
| `POST` | `/api/hospitals/nearby` | top-N ranked by total time |
| `POST` | `/api/assess` | run triage + recommendation |
| `POST` | `/api/confirm` | register patient → reference code |
| `POST` | `/api/feedback` | submit wait-accuracy feedback |
| `GET`  | `/api/admin/dashboard/{id}` | live admin payload |
| `POST` | `/api/admin/capacity` | update department capacity / divert / notes |

If the FastAPI process isn't reachable the Streamlit client falls back
to calling the agent code in-process — handy for debugging.

---

## Data

All synthetic. Eight Manchester-area hospitals with realistic
trust/department/specialty mixes, per-hospital traffic multipliers,
24h wait history (so the admin chart has shape), an incoming queue
seeded with four patients, and a feedback log.

---

## Hard-coded brand

Per spec, the front-end always shows *IBM watsonx* as the reasoning
service, even when `LLM_PROVIDER=mock`. The internal provider name is
still surfaced via `GET /api/health` for debugging.

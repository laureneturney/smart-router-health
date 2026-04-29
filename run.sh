#!/usr/bin/env bash
# Convenience launcher — starts the FastAPI backend, then Streamlit.
# Ctrl-C kills both.
set -euo pipefail

cd "$(dirname "$0")"

# Boot FastAPI in the background.
python -m backend.api &
API_PID=$!
trap 'echo "stopping API ($API_PID)"; kill $API_PID 2>/dev/null || true' EXIT

# Give it a beat to bind.
sleep 1.5

# Streamlit in the foreground.
streamlit run app.py

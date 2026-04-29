"""
LLM provider abstraction for the A&E Smart Routing demo.

Three interchangeable backends, selected by LLM_PROVIDER:
    - "watsonx": IBM watsonx.ai foundation models (e.g. granite-3-8b-instruct)
    - "custom":  any OpenAI-compatible /v1/chat/completions endpoint
                 (vLLM, Ollama, LM Studio, OpenAI itself, etc.)
    - "mock":    deterministic local stub — no network required

All providers expose a single `complete_json(system, user, schema_hint)`
method that returns a parsed Python dict. The caller does not need to
know which backend served the response.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete_json(self, system: str, user: str, schema_hint: dict | None = None) -> dict:
        """Return a parsed JSON object from the model."""

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Pull the first JSON object out of a model response."""
        if not text:
            return {}
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Mock — deterministic, offline-friendly. Drives the demo when no creds set.
# ---------------------------------------------------------------------------
class MockProvider(LLMProvider):
    name = "mock"

    URGENT_KEYWORDS = {
        "critical": [
            "chest pain", "can't breathe", "cannot breathe", "not breathing",
            "unconscious", "stroke", "facial droop", "slurred", "severe bleeding",
            "uncontrolled bleed", "anaphyl", "seizure", "blue lips", "cardiac",
        ],
        "high": [
            "shortness of breath", "broken", "fracture", "deep cut", "head injury",
            "concussion", "severe pain", "pregnan", "high fever", "abdominal pain",
            "vomiting blood", "burn",
        ],
        "medium": [
            "sprain", "twisted", "rash", "infection", "moderate pain",
            "swelling", "cut", "minor bleeding",
        ],
    }

    def complete_json(self, system: str, user: str, schema_hint: dict | None = None) -> dict:
        task = (schema_hint or {}).get("task", "")
        if task == "triage":
            return self._triage(user)
        if task == "recommend":
            return self._recommend(user)
        if task == "explain":
            return self._explain(user)
        return {}

    def _triage(self, user_text: str) -> dict:
        text = user_text.lower()

        urgency = "low"
        matched: list[str] = []
        for level in ("critical", "high", "medium"):
            for kw in self.URGENT_KEYWORDS[level]:
                if kw in text:
                    urgency = level
                    matched.append(kw)
                    break
            if urgency != "low":
                break

        # bump severity if pain >= 8 mentioned
        pain_match = re.search(r"pain[^0-9]{0,12}(\d{1,2})", text)
        if pain_match:
            pain = int(pain_match.group(1))
            if pain >= 8 and urgency in ("low", "medium"):
                urgency = "high"
            elif pain >= 5 and urgency == "low":
                urgency = "medium"

        guidance = {
            "critical": "Call 999 immediately. Do not drive yourself. Stay still and keep someone with you.",
            "high":     "Go to A&E now. If symptoms worsen on the way, call 999.",
            "medium":   "A&E or urgent care within the next hour is appropriate.",
            "low":      "Urgent care or NHS 111 may be a faster option than A&E.",
        }[urgency]

        specialty_hint = "general"
        if any(k in text for k in ["chest", "cardiac", "heart"]):
            specialty_hint = "cardiac"
        elif any(k in text for k in ["stroke", "facial droop", "slurred"]):
            specialty_hint = "stroke"
        elif any(k in text for k in ["fracture", "broken", "trauma", "head injury", "laceration"]):
            specialty_hint = "trauma"
        elif any(k in text for k in ["child", "paediatric", "infant", "baby"]):
            specialty_hint = "paediatric"

        return {
            "urgency": urgency,
            "specialty_hint": specialty_hint,
            "matched_keywords": matched,
            "guidance": guidance,
            "red_flags": matched[:3],
        }

    def _recommend(self, user_text: str) -> dict:
        # Keep model lightweight: just echo a structured rationale template.
        # Actual ranking happens in services.routing — the LLM only narrates.
        return {
            "rationale": "Selected based on shortest weighted total time given current capacity, specialty match, and live traffic.",
            "tradeoff_notes": "A closer hospital was longer overall once predicted wait was added in.",
        }

    def _explain(self, user_text: str) -> dict:
        return {"summary": "Hospital chosen to minimise time-to-treatment."}


# ---------------------------------------------------------------------------
# Custom (OpenAI-compatible)
# ---------------------------------------------------------------------------
class CustomOpenAICompatibleProvider(LLMProvider):
    name = "custom"

    def __init__(self) -> None:
        from openai import OpenAI  # local import — only needed for this provider

        self.model = os.getenv("CUSTOM_LLM_MODEL", "llama-3.1-8b-instruct")
        self.client = OpenAI(
            base_url=os.getenv("CUSTOM_LLM_BASE_URL", "http://localhost:8080/v1"),
            api_key=os.getenv("CUSTOM_LLM_API_KEY", "not-needed"),
        )

    def complete_json(self, system: str, user: str, schema_hint: dict | None = None) -> dict:
        instructions = system + "\n\nReturn ONLY a single JSON object. No prose, no markdown."
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content or ""
        return self._extract_json(content)


# ---------------------------------------------------------------------------
# Watsonx
# ---------------------------------------------------------------------------
class WatsonxProvider(LLMProvider):
    name = "watsonx"

    def __init__(self) -> None:
        from ibm_watsonx_ai import APIClient, Credentials  # local import
        from ibm_watsonx_ai.foundation_models import ModelInference

        api_key = os.getenv("WATSONX_APIKEY")
        url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        project_id = os.getenv("WATSONX_PROJECT_ID")
        model_id = os.getenv("WATSONX_MODEL_ID", "ibm/granite-3-8b-instruct")

        if not api_key or not project_id:
            raise RuntimeError(
                "watsonx provider requires WATSONX_APIKEY and WATSONX_PROJECT_ID."
            )

        creds = Credentials(api_key=api_key, url=url)
        self.model = ModelInference(
            model_id=model_id,
            credentials=creds,
            project_id=project_id,
            params={"decoding_method": "greedy", "max_new_tokens": 600, "temperature": 0.2},
        )

    def complete_json(self, system: str, user: str, schema_hint: dict | None = None) -> dict:
        prompt = (
            f"<|system|>\n{system}\nReturn ONLY a single valid JSON object.\n"
            f"<|user|>\n{user}\n<|assistant|>\n"
        )
        result = self.model.generate_text(prompt=prompt)
        text = result if isinstance(result, str) else result.get("results", [{}])[0].get("generated_text", "")
        return self._extract_json(text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_provider_singleton: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Return the configured LLM provider, instantiating once."""
    global _provider_singleton
    if _provider_singleton is not None:
        return _provider_singleton

    choice = (os.getenv("LLM_PROVIDER") or "mock").strip().lower()
    try:
        if choice == "watsonx":
            _provider_singleton = WatsonxProvider()
        elif choice == "custom":
            _provider_singleton = CustomOpenAICompatibleProvider()
        else:
            _provider_singleton = MockProvider()
    except Exception as exc:  # pragma: no cover — fall back so demo never blocks
        print(f"[llm_provider] {choice!r} init failed ({exc}); falling back to mock.")
        _provider_singleton = MockProvider()

    return _provider_singleton


def display_provider_name() -> str:
    """Brand-locked name shown in the UI per spec — always IBM watsonx."""
    return "IBM watsonx"

"""Provider seam for model-backed continuity observation."""

from __future__ import annotations

import json
import os
from typing import Any


class ContinuityModelAdapterError(RuntimeError):
    """Raised when the continuity observer backend cannot be invoked safely."""


DEFAULT_CONTINUITY_OBSERVER_BACKEND = "noop"
SUPPORTED_CONTINUITY_OBSERVER_BACKENDS = {
    "noop",
    "fixture",
}


def configured_continuity_observer_backend(explicit_backend: str | None = None) -> str:
    backend = str(explicit_backend or os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_BACKEND") or DEFAULT_CONTINUITY_OBSERVER_BACKEND).strip().lower()
    return backend or DEFAULT_CONTINUITY_OBSERVER_BACKEND


def invoke_continuity_observer_backend(*, packet: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    selected = configured_continuity_observer_backend(backend)
    if selected == "noop":
        return {
            "observer_status": "degraded",
            "backend": "noop",
            "provider_status": "not_configured",
            "degraded": True,
            "degraded_reason": "production_model_backend_unresolved",
            "rationale": "No lawful production continuity-observer backend is configured yet.",
            "intents": [],
        }
    if selected == "fixture":
        return _fixture_backend_response(packet)
    return {
        "observer_status": "degraded",
        "backend": selected,
        "provider_status": "unsupported_backend",
        "degraded": True,
        "degraded_reason": f"unsupported_backend:{selected}",
        "rationale": "Configured continuity-observer backend is not supported by this runtime build.",
        "intents": [],
    }


def _fixture_backend_response(packet: dict[str, Any]) -> dict[str, Any]:
    raw_fixture = str(os.environ.get("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON") or "").strip()
    if raw_fixture:
        try:
            payload = json.loads(raw_fixture)
        except json.JSONDecodeError as exc:
            raise ContinuityModelAdapterError("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ContinuityModelAdapterError("SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON must decode to an object.")
        return {
            "observer_status": str(payload.get("observer_status") or "ok").strip().lower() or "ok",
            "backend": "fixture",
            "provider_status": str(payload.get("provider_status") or "fixture").strip() or "fixture",
            "degraded": bool(payload.get("degraded", False)),
            "degraded_reason": str(payload.get("degraded_reason") or "").strip() or None,
            "rationale": str(payload.get("rationale") or "Deterministic continuity observer fixture response.").strip(),
            "intents": list(payload.get("intents") or []),
        }

    summary = str(packet.get("summary") or "").strip()
    notes = [str(item).strip() for item in list(packet.get("notes") or []) if str(item).strip()]
    source_refs = [dict(item) for item in list(packet.get("source_refs") or []) if isinstance(item, dict)]
    intents: list[dict[str, Any]] = []
    if summary or notes:
        captures: list[dict[str, Any]] = []
        if summary:
            captures.append({"kind": "repo_fact", "summary": summary})
        captures.extend({"kind": "repo_fact", "summary": note} for note in notes[:3])
        intents.append(
            {
                "artifact_family": "semantic_capture",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend captured the bounded continuity packet into a draft-safe semantic capture.",
                "source_refs": source_refs,
                "truth_state_label": "working_capture",
                "uncertainty_markers": [],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "title": summary or f"{packet.get('trigger') or 'continuity'} continuity update",
                    "captures": captures,
                    "raw_text": "\n".join([summary, *notes]).strip(),
                },
            }
        )
    if bool(packet.get("decision_boundary")):
        title = summary or "Observer decision boundary"
        intents.append(
            {
                "artifact_family": "decision_log",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend observed an explicit decision boundary in the bounded continuity packet.",
                "source_refs": source_refs,
                "truth_state_label": "decision_draft",
                "uncertainty_markers": [],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "title": title,
                    "summary": summary or title,
                    "why": "Deterministic fixture observer promoted the explicit decision boundary into the decision ledger.",
                },
            }
        )
    if bool(packet.get("uncertainty_present")):
        trigger = summary or (notes[0] if notes else "Continuity observer surfaced uncertainty.")
        intents.append(
            {
                "artifact_family": "disclosure_log",
                "action_type": "create",
                "confidence": "medium",
                "rationale": "Fixture backend observed unresolved uncertainty in the bounded continuity packet.",
                "source_refs": source_refs,
                "truth_state_label": "uncertainty_disclosure",
                "uncertainty_markers": ["uncertainty_present"],
                "draft_safe": True,
                "gated_publication": False,
                "supersedes": [],
                "updates": [],
                "payload": {
                    "trigger": trigger,
                    "expected": "Continuity should remain truthful while the uncertain condition is unresolved.",
                    "provable": "The bounded continuity packet marked uncertainty_present=true.",
                    "status_labels": ["UNCERTAINTY", "RISK"],
                    "impact": trigger,
                    "safe_options": [
                        "Continue draft-safe continuity updates only.",
                        "Clarify the uncertain condition before stronger canon changes.",
                    ],
                    "decision_needed": "Confirm whether the executor should continue, pause, or capture more evidence.",
                },
            }
        )
    return {
        "observer_status": "ok",
        "backend": "fixture",
        "provider_status": "fixture",
        "degraded": False,
        "degraded_reason": None,
        "rationale": "Deterministic fixture observer derived draft-safe intents from the bounded continuity packet.",
        "intents": intents,
    }

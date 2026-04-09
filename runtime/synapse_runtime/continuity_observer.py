"""Bounded continuity packet assembly and validated observer intent normalization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from synapse_runtime.continuity_model_adapter import invoke_continuity_observer_backend
from synapse_runtime.continuity_obligations import obligation_summary
from synapse_runtime.draftshots import draftshot_summary
from synapse_runtime.publication_candidates import publication_candidate_summary
from synapse_runtime.sidecar_store import _read_yaml, live_root
from synapse_runtime.snapshot_candidates import snapshot_candidate_summary


class ContinuityObserverError(RuntimeError):
    """Raised when the continuity observer packet or intents are invalid."""


SUPPORTED_OBSERVER_ARTIFACT_FAMILIES = {
    "noop",
    "semantic_capture",
    "decision_log",
    "disclosure_log",
    "open_obligation",
}


def build_continuity_packet(
    *,
    subject: str,
    data_root: Path,
    trigger: str,
    summary: str | None = None,
    notes: list[str] | None = None,
    changed_files: list[str] | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    boundary: str | None = None,
    decision_boundary: bool = False,
    uncertainty_present: bool = False,
    source_refs: list[dict[str, Any]] | None = None,
    accepted_context: dict[str, Any] | None = None,
    session_mode_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state = _read_yaml(live / "STATE.yaml")
    manifold = _read_yaml(live / "MANIFOLD.yaml")
    state = state if isinstance(state, dict) else {}
    manifold = manifold if isinstance(manifold, dict) else {}
    normalized_notes = [str(item).strip() for item in list(notes or []) if str(item).strip()]
    normalized_files = [str(item).strip() for item in list(changed_files or []) if str(item).strip()]
    normalized_refs = [dict(item) for item in list(source_refs or []) if isinstance(item, dict)]
    packet = {
        "packet_schema_version": 1,
        "subject": subject,
        "trigger": str(trigger).strip(),
        "boundary": str(boundary or "").strip() or None,
        "session_id": str(session_id or "").strip() or None,
        "run_id": str(run_id or "").strip() or None,
        "summary": str(summary or "").strip() or None,
        "notes": normalized_notes,
        "changed_files": normalized_files,
        "decision_boundary": bool(decision_boundary),
        "uncertainty_present": bool(uncertainty_present),
        "source_refs": normalized_refs,
        "accepted_context": dict(accepted_context or {}),
        "session_mode_fields": dict(session_mode_fields or {}),
        "draftshot_summary": draftshot_summary(data_root, session_id=str(session_id or "").strip() or None),
        "snapshot_candidate_summary": snapshot_candidate_summary(data_root),
        "publication_candidate_summary": publication_candidate_summary(data_root),
        "obligation_summary": obligation_summary(data_root),
        "state_projection": {
            "active_session_mode": state.get("active_session_mode"),
            "open_continuity_obligation_count": state.get("open_continuity_obligation_count") or 0,
            "blocker_continuity_obligation_count": state.get("blocker_continuity_obligation_count") or 0,
            "current_active_draftshot_path": state.get("current_active_draftshot_path"),
            "current_eod_candidate_path": state.get("current_eod_candidate_path"),
            "current_control_sync_candidate_path": state.get("current_control_sync_candidate_path"),
            "current_story_candidate_path": state.get("current_story_candidate_path"),
            "current_vision_candidate_path": state.get("current_vision_candidate_path"),
            "published_project_model_path": state.get("published_project_model_path"),
        },
        "manifold_projection": {
            "current_codex_candidate_paths": list(manifold.get("current_codex_candidate_paths") or []),
            "automation_recent_actions": list(manifold.get("automation_recent_actions") or []),
        },
    }
    packet["packet_fingerprint"] = hashlib.sha256(json.dumps(packet, sort_keys=True).encode("utf-8")).hexdigest()
    return packet


def observe_continuity(
    *,
    subject: str,
    data_root: Path,
    trigger: str,
    summary: str | None = None,
    notes: list[str] | None = None,
    changed_files: list[str] | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    boundary: str | None = None,
    decision_boundary: bool = False,
    uncertainty_present: bool = False,
    source_refs: list[dict[str, Any]] | None = None,
    accepted_context: dict[str, Any] | None = None,
    session_mode_fields: dict[str, Any] | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    packet = build_continuity_packet(
        subject=subject,
        data_root=data_root,
        trigger=trigger,
        summary=summary,
        notes=notes,
        changed_files=changed_files,
        session_id=session_id,
        run_id=run_id,
        boundary=boundary,
        decision_boundary=decision_boundary,
        uncertainty_present=uncertainty_present,
        source_refs=source_refs,
        accepted_context=accepted_context,
        session_mode_fields=session_mode_fields,
    )
    raw = invoke_continuity_observer_backend(packet=packet, backend=backend)
    return _normalize_observer_response(packet=packet, raw=raw)


def _normalize_observer_response(*, packet: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContinuityObserverError("Continuity observer backend must return an object.")
    intents = [_normalize_observer_intent(packet=packet, raw_intent=item) for item in list(raw.get("intents") or [])]
    actionable_intents = [item for item in intents if item["artifact_family"] != "noop"]
    return {
        "observer_status": str(raw.get("observer_status") or "degraded").strip().lower() or "degraded",
        "backend": str(raw.get("backend") or "noop").strip() or "noop",
        "provider_status": str(raw.get("provider_status") or "unknown").strip() or "unknown",
        "degraded": bool(raw.get("degraded", False)),
        "degraded_reason": str(raw.get("degraded_reason") or "").strip() or None,
        "rationale": str(raw.get("rationale") or "").strip() or None,
        "observer_triggered": bool(actionable_intents),
        "observer_action_kinds": [item["artifact_family"] for item in actionable_intents],
        "observer_context": {
            "packet_fingerprint": packet["packet_fingerprint"],
            "trigger": packet.get("trigger"),
            "boundary": packet.get("boundary"),
            "session_id": packet.get("session_id"),
            "run_id": packet.get("run_id"),
            "summary": packet.get("summary"),
            "changed_files": list(packet.get("changed_files") or []),
            "decision_boundary": bool(packet.get("decision_boundary")),
            "uncertainty_present": bool(packet.get("uncertainty_present")),
        },
        "observer_intents": intents,
    }


def _normalize_observer_intent(*, packet: dict[str, Any], raw_intent: Any) -> dict[str, Any]:
    if not isinstance(raw_intent, dict):
        raise ContinuityObserverError("Observer intent must be an object.")
    artifact_family = str(raw_intent.get("artifact_family") or "").strip().lower()
    if artifact_family not in SUPPORTED_OBSERVER_ARTIFACT_FAMILIES:
        raise ContinuityObserverError(f"Unsupported observer artifact family: {artifact_family or 'missing'}")
    payload = raw_intent.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ContinuityObserverError("Observer intent payload must be an object when present.")
    source_refs = raw_intent.get("source_refs")
    if isinstance(source_refs, list):
        normalized_source_refs = [dict(item) for item in source_refs if isinstance(item, dict)]
    else:
        normalized_source_refs = [dict(item) for item in list(packet.get("source_refs") or []) if isinstance(item, dict)]
    intent = {
        "artifact_family": artifact_family,
        "action_type": str(raw_intent.get("action_type") or "create").strip().lower() or "create",
        "confidence": str(raw_intent.get("confidence") or "medium").strip().lower() or "medium",
        "rationale": str(raw_intent.get("rationale") or "Observer intent normalized from bounded continuity packet.").strip(),
        "source_refs": normalized_source_refs,
        "truth_state_label": str(raw_intent.get("truth_state_label") or "working_observation").strip(),
        "uncertainty_markers": [str(item).strip() for item in list(raw_intent.get("uncertainty_markers") or []) if str(item).strip()],
        "draft_safe": bool(raw_intent.get("draft_safe", artifact_family != "noop")),
        "gated_publication": bool(raw_intent.get("gated_publication", False)),
        "supersedes": [str(item).strip() for item in list(raw_intent.get("supersedes") or []) if str(item).strip()],
        "updates": [str(item).strip() for item in list(raw_intent.get("updates") or []) if str(item).strip()],
        "payload": dict(payload or {}),
    }
    if not intent["rationale"]:
        raise ContinuityObserverError(f"Observer intent {artifact_family} is missing rationale.")
    return intent

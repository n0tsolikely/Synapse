"""Executor-parallel automation policy and continuity-readiness logic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from synapse_runtime.repo_onboarding import load_onboarding_pointer, onboarding_projection
from synapse_runtime.session_modes import SessionMode
from synapse_runtime.sidecar_store import _read_yaml, live_root


class AutomationLane(str, Enum):
    EXECUTION_LANE = "execution_lane"
    CONTINUITY_LANE = "continuity_lane"
    GATE_LANE = "gate_lane"


class AutomationAction(str, Enum):
    ACTIVITY_TICK = "activity_tick"
    SEMANTIC_CAPTURE = "semantic_capture"
    DECISION_LOG = "decision_log"
    DISCLOSURE_LOG = "disclosure_log"
    CONTINUITY_REFRESH = "continuity_refresh"


@dataclass(frozen=True)
class AutomationPolicy:
    adopted_existing_repo: bool
    onboarding_required: bool
    onboarding_requirement_reason: str | None
    onboarding_confirmed: bool
    project_identity_ready: bool
    continuity_ready: bool
    automation_status: str
    automation_pending_gate: str | None
    current_onboarding_id: str | None
    latest_confirmed_onboarding_id: str | None
    published_project_model_path: str | None
    published_project_story_path: str | None
    published_vision_path: str | None
    missing_publication_fields: tuple[str, ...]


READY_STATE_SESSION_MODES = {
    SessionMode.CONTROL_SYNC,
    SessionMode.SCOPE_PLANNING,
    SessionMode.EXECUTION,
}


_ACTIVITY_HINT_PREFIXES = {
    "question:": "question",
    "unknown:": "unknown",
    "constraint:": "constraint",
    "risk:": "risk",
    "uncertainty:": "risk",
    "fact:": "repo_fact",
    "discovery:": "repo_fact",
    "dependency:": "dependency",
    "non-goal:": "non_goal",
    "milestone:": "milestone",
    "idea:": "idea",
    "decision:": "decision",
}


def _live_yaml(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path)
    return payload if isinstance(payload, dict) else {}


def _readiness_inputs(data_root: Path) -> dict[str, Any]:
    subject = data_root.name[:-5] if data_root.name.endswith("_Data") else data_root.name
    pointer = load_onboarding_pointer(
        subject=subject,
        data_root=data_root,
        rebuild=False,
        persist=False,
        ensure_scaffold=False,
    )
    projection = onboarding_projection(
        subject=subject,
        data_root=data_root,
        rebuild=False,
        persist_pointer=False,
        ensure_scaffold=False,
    )
    state = _live_yaml(live_root(data_root) / "STATE.yaml")
    manifold = _live_yaml(live_root(data_root) / "MANIFOLD.yaml")
    return {
        "pointer": pointer,
        "projection": projection,
        "state": state,
        "manifold": manifold,
    }


def automation_policy_for_context(*, data_root: Path) -> AutomationPolicy:
    inputs = _readiness_inputs(data_root)
    pointer = inputs["pointer"]
    projection = inputs["projection"]
    state = inputs["state"]

    adopted_existing_repo = bool(pointer.get("adopted_existing_repo"))
    latest_confirmed_id = str(projection.get("latest_confirmed_onboarding_id") or "").strip() or None
    published_model_path = str(projection.get("published_project_model_path") or "").strip() or None
    published_story_path = str(projection.get("published_project_story_path") or "").strip() or None
    published_vision_path = str(projection.get("published_vision_path") or "").strip() or None

    missing_publication_fields: list[str] = []
    if not latest_confirmed_id:
        missing_publication_fields.append("latest_confirmed_onboarding_id")
    if not published_model_path:
        missing_publication_fields.append("published_project_model_path")
    if not published_story_path:
        missing_publication_fields.append("published_project_story_path")
    if not published_vision_path:
        missing_publication_fields.append("published_vision_path")

    project_identity_ready = not missing_publication_fields
    onboarding_confirmed = project_identity_ready
    onboarding_required = adopted_existing_repo and not onboarding_confirmed
    onboarding_requirement_reason = (
        "adopted_existing_repo_missing_confirmed_project_identity"
        if onboarding_required
        else None
    )
    continuity_ready = not onboarding_required
    automation_pending_gate = onboarding_requirement_reason
    if not automation_pending_gate and str(state.get("provenance_status") or "").strip() == "blocked":
        automation_pending_gate = "provenance_blocked"
    if onboarding_required:
        automation_status = "onboarding_required"
    elif automation_pending_gate:
        automation_status = "gated"
    else:
        automation_status = "active"

    return AutomationPolicy(
        adopted_existing_repo=adopted_existing_repo,
        onboarding_required=onboarding_required,
        onboarding_requirement_reason=onboarding_requirement_reason,
        onboarding_confirmed=onboarding_confirmed,
        project_identity_ready=project_identity_ready,
        continuity_ready=continuity_ready,
        automation_status=automation_status,
        automation_pending_gate=automation_pending_gate,
        current_onboarding_id=str(projection.get("active_onboarding_id") or "").strip() or None,
        latest_confirmed_onboarding_id=latest_confirmed_id,
        published_project_model_path=published_model_path,
        published_project_story_path=published_story_path,
        published_vision_path=published_vision_path,
        missing_publication_fields=tuple(missing_publication_fields),
    )


def subject_requires_onboarding_confirmation(data_root: Path) -> bool:
    return automation_policy_for_context(data_root=data_root).onboarding_required


def ready_state_allowed(data_root: Path) -> bool:
    return not subject_requires_onboarding_confirmation(data_root)


def target_session_mode_requires_ready_state(target_mode: SessionMode | str | None) -> bool:
    if target_mode is None:
        return False
    mode = target_mode if isinstance(target_mode, SessionMode) else SessionMode(str(target_mode))
    return mode in READY_STATE_SESSION_MODES


def ready_state_gate_for_mode(*, data_root: Path, target_mode: SessionMode | str | None) -> dict[str, Any]:
    policy = automation_policy_for_context(data_root=data_root)
    requires_ready = target_session_mode_requires_ready_state(target_mode)
    blocked = requires_ready and policy.onboarding_required
    return {
        "blocked": blocked,
        "target_mode": (target_mode.value if isinstance(target_mode, SessionMode) else str(target_mode or "").strip()) or None,
        "requires_ready_state": requires_ready,
        "onboarding_required": policy.onboarding_required,
        "onboarding_requirement_reason": policy.onboarding_requirement_reason,
        "continuity_ready": policy.continuity_ready,
        "project_identity_ready": policy.project_identity_ready,
        "missing_publication_fields": list(policy.missing_publication_fields),
    }


def _normalize_texts(summary: str | None, notes: list[str] | None) -> list[str]:
    texts: list[str] = []
    if str(summary or "").strip():
        texts.append(str(summary).strip())
    for item in notes or []:
        text = str(item or "").strip()
        if text:
            texts.append(text)
    return texts


def _classify_text_item(text: str) -> tuple[str | None, str]:
    lowered = text.strip().lower()
    for prefix, kind in _ACTIVITY_HINT_PREFIXES.items():
        if lowered.startswith(prefix):
            return kind, text[len(prefix):].strip() or text.strip()
    if "?" in text:
        return "question", text.strip()
    return "neutral", text.strip()


def _build_capture_payload(classification: dict[str, Any]) -> dict[str, Any] | None:
    captures: list[dict[str, Any]] = []
    for question in classification.get("open_questions") or []:
        captures.append({"kind": "question", "summary": question, "blocking": False})
    for item in classification.get("constraints") or []:
        captures.append({"kind": "constraint", "summary": item})
    for item in classification.get("risks") or []:
        captures.append({"kind": "risk", "summary": item, "blocking": True})
    for item in classification.get("repo_facts") or []:
        captures.append({"kind": "repo_fact", "summary": item})
    if not captures:
        return None
    return {
        "title": classification.get("capture_title"),
        "captures": captures,
    }


def classify_runtime_activity(
    *,
    activity_source: str,
    activity_kind: str,
    session_mode: str | None,
    onboarding_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    subject: str | None = None,
    changed_files: list[str] | None = None,
    summary: str | None = None,
    notes: list[str] | None = None,
    decision_boundary: bool = False,
    uncertainty_present: bool = False,
    explicit_decision_logged: bool = False,
    explicit_disclosure_logged: bool = False,
    explicit_capture_written: bool = False,
    onboarding_response: bool = False,
) -> dict[str, Any]:
    texts = _normalize_texts(summary, notes)
    repo_facts: list[str] = []
    open_questions: list[str] = []
    constraints: list[str] = []
    risks: list[str] = []
    surfaced_decision = None
    for text in texts:
        kind, cleaned = _classify_text_item(text)
        if not cleaned:
            continue
        if kind == "question":
            open_questions.append(cleaned)
        elif kind == "constraint":
            constraints.append(cleaned)
        elif kind == "risk":
            risks.append(cleaned)
        elif kind == "decision":
            surfaced_decision = cleaned
            decision_boundary = True
        elif kind == "repo_fact":
            repo_facts.append(cleaned)

    if uncertainty_present and not risks and texts:
        risks.append(texts[-1])
    code_mutation_progress = bool(changed_files)
    meaningful_activity = bool(
        code_mutation_progress
        or repo_facts
        or open_questions
        or constraints
        or risks
        or decision_boundary
        or onboarding_response
    )
    fingerprint_payload = {
        "activity_source": activity_source,
        "activity_kind": activity_kind,
        "session_mode": session_mode,
        "onboarding_id": onboarding_id,
        "run_id": run_id,
        "session_id": session_id,
        "subject": subject,
        "changed_files": sorted(str(item) for item in changed_files or [] if str(item).strip()),
        "summary": str(summary or "").strip(),
        "notes": texts,
        "repo_facts": repo_facts,
        "open_questions": open_questions,
        "constraints": constraints,
        "risks": risks,
        "decision_boundary": bool(decision_boundary),
        "uncertainty_present": bool(uncertainty_present),
        "explicit_capture_written": bool(explicit_capture_written),
        "onboarding_response": bool(onboarding_response),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    classification = {
        **fingerprint_payload,
        "meaningful_activity": meaningful_activity,
        "code_mutation_progress": code_mutation_progress,
        "decision_boundary": bool(decision_boundary),
        "uncertainty_present": bool(uncertainty_present or risks),
        "explicit_decision_logged": bool(explicit_decision_logged),
        "explicit_disclosure_logged": bool(explicit_disclosure_logged),
        "explicit_capture_written": bool(explicit_capture_written),
        "onboarding_response": bool(onboarding_response),
        "capture_title": str(summary or "").strip() or f"{activity_kind} continuity update",
        "capture_payload": None,
        "decision_title": surfaced_decision,
        "decision_summary": surfaced_decision,
        "automation_fingerprint": fingerprint,
    }
    classification["capture_payload"] = _build_capture_payload(classification)
    return classification


def plan_automation_side_effects(
    *,
    policy: AutomationPolicy,
    activity: dict[str, Any],
    recent_capture_fingerprints: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not activity.get("meaningful_activity"):
        return []
    recent = recent_capture_fingerprints or set()
    fingerprint_seen = activity.get("automation_fingerprint") in recent
    actions: list[dict[str, Any]] = []
    if (
        activity.get("capture_payload")
        and not activity.get("explicit_capture_written")
        and not fingerprint_seen
    ):
        actions.append(
            {
                "action": AutomationAction.SEMANTIC_CAPTURE.value,
                "lane": AutomationLane.CONTINUITY_LANE.value,
                "draft_safe": True,
                "capture_payload": activity.get("capture_payload"),
                "raw_text": "\n".join(_normalize_texts(activity.get("summary"), activity.get("notes"))).strip(),
                "automation_fingerprint": activity.get("automation_fingerprint"),
                "onboarding_session_capture": bool(
                    policy.current_onboarding_id
                    and str(activity.get("session_mode") or "").strip() == SessionMode.ONBOARDING_EXISTING_REPO.value
                ),
            }
        )
    if (
        activity.get("decision_boundary")
        and not activity.get("explicit_decision_logged")
        and not fingerprint_seen
        and not activity.get("explicit_capture_written")
    ):
        title = str(activity.get("decision_title") or activity.get("summary") or "").strip()
        if title:
            actions.append(
                {
                    "action": AutomationAction.DECISION_LOG.value,
                    "lane": AutomationLane.CONTINUITY_LANE.value,
                    "draft_safe": True,
                    "title": title,
                    "summary": str(activity.get("decision_summary") or title).strip(),
                    "why": "Automatically logged from executor activity that crossed a decision boundary.",
                }
            )
    if (
        activity.get("uncertainty_present")
        and not activity.get("explicit_disclosure_logged")
        and not fingerprint_seen
        and not activity.get("explicit_capture_written")
    ):
        trigger = str(activity.get("summary") or "").strip() or "Executor activity surfaced uncertainty."
        actions.append(
            {
                "action": AutomationAction.DISCLOSURE_LOG.value,
                "lane": AutomationLane.CONTINUITY_LANE.value,
                "draft_safe": True,
                "trigger": trigger,
                "expected": "Continuity should stay truthful while unresolved risk or uncertainty remains visible.",
                "provable": "Automation detected uncertainty/risk in the current activity context.",
                "status_labels": ["UNCERTAINTY", "RISK"],
                "impact": "Ready-state reasoning may be incomplete until the uncertainty is clarified or constrained.",
                "safe_options": [
                    "Continue draft-only continuity updates.",
                    "Capture clarifications before binding canon or governed execution.",
                ],
                "decision_needed": "Confirm how the executor should proceed under the surfaced uncertainty.",
            }
        )
    if activity.get("code_mutation_progress") and str(activity.get("activity_kind") or "") not in {"run-update", "session-tick", "record-activity"}:
        actions.append(
            {
                "action": AutomationAction.ACTIVITY_TICK.value,
                "lane": AutomationLane.CONTINUITY_LANE.value,
                "draft_safe": True,
            }
        )
    if actions or activity.get("code_mutation_progress") or activity.get("onboarding_response"):
        actions.append(
            {
                "action": AutomationAction.CONTINUITY_REFRESH.value,
                "lane": AutomationLane.CONTINUITY_LANE.value,
                "draft_safe": True,
            }
        )
    return actions


def automation_summary(data_root: Path) -> dict[str, Any]:
    inputs = _readiness_inputs(data_root)
    policy = automation_policy_for_context(data_root=data_root)
    state = inputs["state"]
    manifold = inputs["manifold"]
    return {
        "adopted_existing_repo": policy.adopted_existing_repo,
        "onboarding_required": policy.onboarding_required,
        "onboarding_requirement_reason": policy.onboarding_requirement_reason,
        "onboarding_confirmed": policy.onboarding_confirmed,
        "project_identity_ready": policy.project_identity_ready,
        "continuity_ready": policy.continuity_ready,
        "automation_status": policy.automation_status,
        "automation_pending_gate": policy.automation_pending_gate,
        "active_onboarding_id": policy.current_onboarding_id,
        "latest_confirmed_onboarding_id": policy.latest_confirmed_onboarding_id,
        "published_project_model_path": policy.published_project_model_path,
        "published_project_story_path": policy.published_project_story_path,
        "published_vision_path": policy.published_vision_path,
        "missing_publication_fields": list(policy.missing_publication_fields),
        "automation_last_activity_at": state.get("automation_last_activity_at") or manifold.get("automation_last_activity_at"),
        "automation_last_continuity_update_at": state.get("automation_last_continuity_update_at")
        or manifold.get("automation_last_continuity_update_at"),
        "automation_recent_actions": list(manifold.get("automation_recent_actions") or []),
    }

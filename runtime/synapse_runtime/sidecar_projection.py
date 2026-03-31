"""Sidecar projection and event-to-sidecar reduction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.accepted_execution_view import (
    load_accepted_quest_details,
    load_completed_quest_details,
    select_current_accepted_quest,
    select_latest_completed_quest,
)
from synapse_runtime.automation_orchestrator import automation_summary
from synapse_runtime.governance_model import (
    AmbientSignal,
    PromotionRecord,
    ProposalKind,
    ProposalState,
    current_session_id,
    derive_world_state,
    evaluate_promotion,
    infer_interaction_mode,
)
from synapse_runtime.ledger_store import _classify_verification_status
from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.provenance import compute_current_provenance_summary, projectable_provenance_summary
from synapse_runtime.repo_onboarding import onboarding_projection
from synapse_runtime.quest_candidates import (
    QUEST_PROPOSAL_KINDS,
    _candidate_summary,
    _candidate_title,
    _load_proposal_records,
    _open_plan_items,
    _proposal_id,
    _sync_candidate_backlog,
    _upsert_quest_candidate,
    _write_proposals,
)
from synapse_runtime.semantic_intake import (
    capture_kinds as semantic_capture_kinds,
    derive_semantic_promotions,
    is_managed_open_questions_text,
    load_capture_batch,
    load_capture_batches,
    matches_open_questions_scaffold,
    merge_semantic_details,
    render_managed_open_questions,
    semantic_detail_lists,
)
from synapse_runtime.session_modes import SessionMode, active_session_mode, policy_for, policy_summary
from synapse_runtime.sidecar_store import (
    _load_active_run,
    _load_manifold,
    _read_yaml,
    _load_state,
    _now_iso,
    _write_yaml,
    canonical_open_questions_path,
    ensure_live_scaffold,
    live_root,
)


def _latest_finalized_run(*, subject: str, data_root: Path) -> dict[str, Any]:
    runs_dir = live_root(data_root) / "RUNS"
    if not runs_dir.exists():
        return {}

    latest_payload: dict[str, Any] | None = None
    latest_stamp = ""
    for path in runs_dir.glob("RUN-*.yaml"):
        payload = _read_yaml(path)
        if not isinstance(payload, dict):
            continue
        if str(payload.get("subject") or "").strip() != subject:
            continue
        if payload.get("active"):
            continue
        stamp = str(payload.get("finalized_at") or payload.get("updated_at") or payload.get("started_at") or "").strip()
        if not stamp:
            continue
        if latest_payload is None or stamp > latest_stamp:
            latest_payload = payload
            latest_stamp = stamp
    return latest_payload or {}


def _append_recent_change(state: dict[str, Any], note: str) -> None:
    entries = state.get("recent_changes")
    if not isinstance(entries, list):
        entries = []
    entries.append(f"{_now_iso()} - {note}")
    state["recent_changes"] = entries[-10:]


def _apply_quest_lifecycle_projection(
    *,
    subject: str,
    data_root: Path,
    state: dict[str, Any],
    manifold: dict[str, Any],
    world_state: Any,
) -> dict[str, Any]:
    accepted_details = load_accepted_quest_details(subject, data_root)
    current_accepted = select_current_accepted_quest(accepted_details)
    completed_details = load_completed_quest_details(subject, data_root)
    latest_completed = select_latest_completed_quest(completed_details)
    governed_execution_ready = bool(current_accepted and world_state.value == "fog_lifted")

    state["governed_execution_ready"] = governed_execution_ready
    state["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    state["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    state["current_accepted_audit_state"] = current_accepted.get("audit_state") if current_accepted else None
    state["last_completed_quest_id"] = latest_completed.get("quest_id") if latest_completed else None
    state["last_completed_quest_path"] = latest_completed.get("path") if latest_completed else None
    state["last_completed_audit_bundle_path"] = (
        latest_completed.get("audit_bundle_path") if latest_completed else None
    )
    state["last_completed_verdict"] = latest_completed.get("completion_verdict") if latest_completed else None

    manifold["accepted_quest_ids"] = [str(item.get("quest_id")) for item in accepted_details if item.get("quest_id")]
    manifold["accepted_quest_details"] = accepted_details
    manifold["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    manifold["current_accepted_quest_path"] = current_accepted.get("path") if current_accepted else None
    manifold["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    manifold["current_accepted_audit_state"] = current_accepted.get("audit_state") if current_accepted else None
    manifold["completed_quest_ids"] = [str(item.get("quest_id")) for item in completed_details if item.get("quest_id")]
    manifold["completed_quest_details"] = completed_details
    manifold["last_completed_quest_id"] = latest_completed.get("quest_id") if latest_completed else None
    manifold["last_completed_quest_path"] = latest_completed.get("path") if latest_completed else None
    manifold["last_completed_audit_bundle_path"] = (
        latest_completed.get("audit_bundle_path") if latest_completed else None
    )
    manifold["last_completed_verdict"] = latest_completed.get("completion_verdict") if latest_completed else None
    manifold["governed_execution_ready"] = governed_execution_ready

    return {
        "accepted_details": accepted_details,
        "current_accepted": current_accepted,
        "completed_details": completed_details,
        "latest_completed": latest_completed,
        "governed_execution_ready": governed_execution_ready,
    }


def _apply_session_posture_projection(
    *,
    active_run: dict[str, Any],
    latest_finalized_run: dict[str, Any],
    state: dict[str, Any],
    manifold: dict[str, Any],
) -> dict[str, Any]:
    active_mode = active_session_mode(active_run)
    active_summary = policy_summary(active_mode) if active_mode else None

    state["active_session_mode"] = active_mode.value if active_mode else None

    manifold["active_session_mode"] = active_mode.value if active_mode else None
    manifold["active_session_mode_source"] = active_run.get("session_mode_source") if active_mode else None
    manifold["active_session_mode_set_at"] = active_run.get("session_mode_set_at") if active_mode else None
    manifold["active_session_mode_reason"] = active_run.get("session_mode_reason") if active_mode else None
    manifold["active_session_mode_policy_version"] = (
        active_run.get("session_mode_policy_version") if active_mode else None
    )
    manifold["active_session_mode_policy"] = active_summary

    last_mode_text = str(
        active_run.get("last_session_mode")
        or latest_finalized_run.get("last_session_mode")
        or state.get("last_session_mode")
        or ""
    ).strip()
    last_mode = SessionMode(last_mode_text) if last_mode_text else None
    last_mode_ended_at = (
        active_run.get("last_session_mode_ended_at")
        or latest_finalized_run.get("last_session_mode_ended_at")
        or state.get("last_session_mode_ended_at")
    )

    state["last_session_mode"] = last_mode.value if last_mode else None
    state["last_session_mode_ended_at"] = last_mode_ended_at
    manifold["last_session_mode"] = last_mode.value if last_mode else None
    manifold["last_session_mode_ended_at"] = last_mode_ended_at

    return {
        "active_session_mode": active_mode.value if active_mode else None,
        "last_session_mode": last_mode.value if last_mode else None,
        "last_session_mode_ended_at": last_mode_ended_at,
        "active_session_mode_policy": active_summary,
    }


def refresh_session_posture_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    active_run = _load_active_run(run_path, subject)
    latest_run = _latest_finalized_run(subject=subject, data_root=data_root)
    projection = _apply_session_posture_projection(
        active_run=active_run,
        latest_finalized_run=latest_run,
        state=state,
        manifold=manifold,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


def refresh_quest_lifecycle_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    world_state = derive_world_state(data_root)
    projection = _apply_quest_lifecycle_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
        world_state=world_state,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


def _apply_onboarding_projection(
    *,
    subject: str,
    data_root: Path,
    state: dict[str, Any],
    manifold: dict[str, Any],
) -> dict[str, Any]:
    projection = onboarding_projection(subject=subject, data_root=data_root)
    state["onboarding_state"] = projection.get("onboarding_state")
    state["active_onboarding_id"] = projection.get("active_onboarding_id")
    state["latest_confirmed_onboarding_id"] = projection.get("latest_confirmed_onboarding_id")
    state["current_workplan_id"] = projection.get("current_workplan_id")
    state["published_project_model_path"] = projection.get("published_project_model_path")
    state["published_project_story_path"] = projection.get("published_project_story_path")
    state["published_vision_path"] = projection.get("published_vision_path")
    state["published_codex_current_path"] = projection.get("published_codex_current_path")
    state["published_codex_future_path"] = projection.get("published_codex_future_path")
    state["project_model_confirmed_at"] = projection.get("project_model_confirmed_at")
    state["project_model_open_questions_count"] = projection.get("project_model_open_questions_count") or 0
    state["project_model_blocking_questions_count"] = projection.get("project_model_blocking_questions_count") or 0
    state["project_summary"] = projection.get("project_summary")

    manifold["active_onboarding_id"] = projection.get("active_onboarding_id")
    manifold["latest_confirmed_onboarding_id"] = projection.get("latest_confirmed_onboarding_id")
    manifold["onboarding_state"] = projection.get("onboarding_state")
    manifold["current_scan_id"] = projection.get("current_scan_id")
    manifold["current_draft_id"] = projection.get("current_draft_id")
    manifold["current_workplan_id"] = projection.get("current_workplan_id")
    manifold["workplan_step_statuses"] = dict(projection.get("workplan_step_statuses") or {})
    manifold["draft_is_stale"] = bool(projection.get("draft_is_stale"))
    manifold["current_question_set_id"] = projection.get("current_question_set_id")
    manifold["unincorporated_capture_batch_ids"] = list(projection.get("unincorporated_capture_batch_ids") or [])
    manifold["unincorporated_clarification_batch_ids"] = list(projection.get("unincorporated_clarification_batch_ids") or [])
    manifold["published_project_model_path"] = projection.get("published_project_model_path")
    manifold["published_project_story_path"] = projection.get("published_project_story_path")
    manifold["published_vision_path"] = projection.get("published_vision_path")
    manifold["published_codex_current_path"] = projection.get("published_codex_current_path")
    manifold["published_codex_future_path"] = projection.get("published_codex_future_path")
    manifold["project_model_confirmed_at"] = projection.get("project_model_confirmed_at")
    manifold["project_purpose_summary"] = projection.get("project_purpose_summary")
    manifold["project_capability_summary"] = list(projection.get("project_capability_summary") or [])
    manifold["project_constraint_summary"] = list(projection.get("project_constraint_summary") or [])
    manifold["project_history_summary"] = list(projection.get("project_history_summary") or [])
    manifold["project_open_question_details"] = list(projection.get("project_open_question_details") or [])
    return projection


def _apply_automation_projection(
    *,
    data_root: Path,
    state: dict[str, Any],
    manifold: dict[str, Any],
    event_timestamp: str | None = None,
    automation_recent_actions: list[str] | None = None,
    continuity_updated: bool = False,
) -> dict[str, Any]:
    summary = automation_summary(data_root)
    state["onboarding_required"] = bool(summary.get("onboarding_required"))
    state["onboarding_requirement_reason"] = summary.get("onboarding_requirement_reason")
    state["onboarding_confirmed"] = bool(summary.get("onboarding_confirmed"))
    state["project_identity_ready"] = bool(summary.get("project_identity_ready"))
    state["continuity_ready"] = bool(summary.get("continuity_ready"))
    state["automation_status"] = summary.get("automation_status")
    state["automation_pending_gate"] = summary.get("automation_pending_gate")
    state["automation_last_activity_at"] = event_timestamp or summary.get("automation_last_activity_at")
    if continuity_updated or automation_recent_actions:
        state["automation_last_continuity_update_at"] = (
            event_timestamp or summary.get("automation_last_continuity_update_at")
        )
    else:
        state["automation_last_continuity_update_at"] = summary.get("automation_last_continuity_update_at")

    manifold["onboarding_required"] = bool(summary.get("onboarding_required"))
    manifold["onboarding_requirement_reason"] = summary.get("onboarding_requirement_reason")
    manifold["onboarding_confirmed"] = bool(summary.get("onboarding_confirmed"))
    manifold["project_identity_ready"] = bool(summary.get("project_identity_ready"))
    manifold["continuity_ready"] = bool(summary.get("continuity_ready"))
    manifold["automation_status"] = summary.get("automation_status")
    manifold["automation_pending_gate"] = summary.get("automation_pending_gate")
    manifold["automation_last_activity_at"] = event_timestamp or summary.get("automation_last_activity_at")
    if continuity_updated or automation_recent_actions:
        manifold["automation_last_continuity_update_at"] = (
            event_timestamp or summary.get("automation_last_continuity_update_at")
        )
    else:
        manifold["automation_last_continuity_update_at"] = summary.get("automation_last_continuity_update_at")
    recent_actions = list(manifold.get("automation_recent_actions") or [])
    for action in automation_recent_actions or []:
        text = str(action).strip()
        if not text:
            continue
        recent_actions = [text] + [item for item in recent_actions if item != text]
    manifold["automation_recent_actions"] = recent_actions[:10]
    return summary


def refresh_onboarding_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    projection = _apply_onboarding_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
    )
    _apply_automation_projection(
        data_root=data_root,
        state=state,
        manifold=manifold,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


def _apply_provenance_projection(
    *,
    state: dict[str, Any],
    manifold: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    projection = projectable_provenance_summary(summary)
    state["provenance_status"] = projection.get("provenance_status")
    state["provenance_last_observed_at"] = projection.get("provenance_last_observed_at")
    state["provenance_last_watch_at"] = projection.get("provenance_last_watch_at")
    state["provenance_blocker_count"] = len(list(projection.get("provenance_blockers") or []))
    state["provenance_warning_count"] = len(list(projection.get("provenance_warnings") or []))
    state["current_wrapper_proof_status"] = projection.get("current_wrapper_proof_status")
    state["git_hooks_status"] = projection.get("git_hooks_status")

    manifold["provenance_status"] = projection.get("provenance_status")
    manifold["provenance_last_observed_at"] = projection.get("provenance_last_observed_at")
    manifold["provenance_last_watch_at"] = projection.get("provenance_last_watch_at")
    manifold["provenance_blockers"] = list(projection.get("provenance_blockers") or [])
    manifold["provenance_warnings"] = list(projection.get("provenance_warnings") or [])
    manifold["recent_provenance_anomalies"] = list(projection.get("recent_provenance_anomalies") or [])
    manifold["current_wrapper_proof_status"] = projection.get("current_wrapper_proof_status")
    manifold["current_wrapper_proof_path"] = projection.get("current_wrapper_proof_path")
    manifold["current_wrapper_proof_fingerprint"] = projection.get("current_wrapper_proof_fingerprint")
    manifold["git_hooks_status"] = projection.get("git_hooks_status")
    manifold["git_hooks_template_version"] = projection.get("git_hooks_template_version")
    manifold["git_hooks_last_verified_at"] = projection.get("git_hooks_last_verified_at")
    manifold["provenance_baseline_path"] = projection.get("provenance_baseline_path")
    return projection


def refresh_provenance_projection(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    current_summary = summary or compute_current_provenance_summary(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        write_projection=False,
    )
    projection = _apply_provenance_projection(
        state=state,
        manifold=manifold,
        summary=current_summary,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


def _sync_open_questions_thread(*, data_root: Path, details: list[dict[str, Any]]) -> str | None:
    path = canonical_open_questions_path(data_root)
    rendered = render_managed_open_questions(details)
    if not path.exists():
        path.write_text(rendered, encoding="utf-8")
        return str(path)
    try:
        existing = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise LiveMemoryError(f"Unable to read open questions thread: {path}") from exc
    if is_managed_open_questions_text(existing) or matches_open_questions_scaffold(existing):
        if existing.rstrip() != rendered.rstrip():
            path.write_text(rendered, encoding="utf-8")
            return str(path)
        return None
    raise LiveMemoryError(
        f"Open questions thread contains unmanaged custom content: {path}. "
        "Move or convert the file before capture-chunk can manage this derived view."
    )


def _reset_semantic_projection_fields(*, state: dict[str, Any], manifold: dict[str, Any]) -> None:
    state["last_capture_batch_id"] = None
    state["last_capture_at"] = None
    state["open_question_count"] = 0
    state["blocking_question_count"] = 0

    manifold["recent_capture_batch_ids"] = []
    manifold["last_capture_batch_id"] = None
    manifold["last_capture_at"] = None
    manifold["open_question_details"] = []
    manifold["blocking_question_details"] = []
    manifold["recent_idea_details"] = []
    manifold["recent_repo_fact_details"] = []
    manifold["recent_constraint_details"] = []
    manifold["recent_risk_details"] = []
    manifold["recent_dependency_details"] = []
    manifold["recent_non_goal_details"] = []
    manifold["recent_milestone_details"] = []
    manifold["candidate_decision_details"] = []


def _rebuild_semantic_capture_projection(
    *,
    data_root: Path,
    state: dict[str, Any],
    manifold: dict[str, Any],
    semantic_capture_batch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _reset_semantic_projection_fields(state=state, manifold=manifold)
    batches = load_capture_batches(data_root)
    if not batches:
        return {
            "capture_batch_id": None,
            "capture_count": 0,
            "capture_kinds": [],
            "open_questions_path": None,
        }

    all_open_questions: list[dict[str, Any]] = []
    all_blocking_questions: list[dict[str, Any]] = []
    recent_batch_ids: list[str] = []
    for batch in batches:
        detail_lists = semantic_detail_lists(batch)
        for key, incoming in detail_lists.items():
            manifold[key] = merge_semantic_details(manifold.get(key), incoming, cap=10)
        all_open_questions = merge_semantic_details(all_open_questions, detail_lists["open_question_details"], cap=None)
        all_blocking_questions = merge_semantic_details(
            all_blocking_questions,
            detail_lists["blocking_question_details"],
            cap=None,
        )
        batch_id = str(batch.get("capture_batch_id") or "").strip()
        if batch_id:
            recent_batch_ids = [batch_id] + [item for item in recent_batch_ids if item != batch_id]

    last_batch = semantic_capture_batch or batches[-1]
    batch_id = str(last_batch.get("capture_batch_id") or "").strip() or None
    captured_at = str(last_batch.get("captured_at") or "").strip() or None
    manifold["recent_capture_batch_ids"] = recent_batch_ids[:10]
    manifold["last_capture_batch_id"] = batch_id
    manifold["last_capture_at"] = captured_at

    state["last_capture_batch_id"] = batch_id
    state["last_capture_at"] = captured_at
    state["open_question_count"] = len(all_open_questions)
    state["blocking_question_count"] = len(all_blocking_questions)

    open_questions_path = _sync_open_questions_thread(data_root=data_root, details=all_open_questions)
    return {
        "capture_batch_id": batch_id,
        "capture_count": len(list(last_batch.get("captures") or [])),
        "capture_kinds": semantic_capture_kinds(last_batch),
        "open_questions_path": open_questions_path,
    }


def refresh_semantic_capture_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    projection = _rebuild_semantic_capture_projection(
        data_root=data_root,
        state=state,
        manifold=manifold,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


def _sync_sidecar(
    *,
    subject: str,
    data_root: Path,
    active_run: dict[str, Any],
    signal: AmbientSignal | None = None,
    semantic_capture_batch: dict[str, Any] | None = None,
    decisions_path: Path | None = None,
    discoveries_path: Path | None = None,
    disclosures_path: Path | None = None,
    mutate_proposals: bool = True,
    event_timestamp: str | None = None,
    automation_recent_actions: list[str] | None = None,
    continuity_updated: bool = False,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    world_state = derive_world_state(data_root)
    inferred_mode = infer_interaction_mode(signal) if signal is not None else active_run.get("interaction_mode") or "maintenance"
    interaction_mode = str(getattr(inferred_mode, "value", inferred_mode) or "maintenance")
    session_id = active_run.get("session_id") or current_session_id()
    run_id = active_run.get("run_id")

    state["world_state"] = world_state.value
    state["active_phase"] = "execute" if run_id else ("incubation" if world_state.value == "fog_of_war" else "idle")
    state["active_modes"] = ["ambient", interaction_mode]
    state["active_run_id"] = run_id
    state["status"] = "active" if active_run.get("active") else "idle"
    if decisions_path is not None:
        state["last_decision_id"] = decisions_path.stem

    manifold["world_state"] = world_state.value
    manifold["active_phase"] = state["active_phase"]
    manifold["active_modes"] = state["active_modes"]
    manifold["active_run_ids"] = [run_id] if run_id else []
    if session_id:
        manifold["active_session_ids"] = [session_id]
    if decisions_path is not None:
        manifold["current_decision_ledger_path"] = str(decisions_path)
    if discoveries_path is not None:
        manifold["current_discovery_ledger_path"] = str(discoveries_path)
    if disclosures_path is not None:
        manifold["current_disclosure_ledger_path"] = str(disclosures_path)

    _apply_session_posture_projection(
        active_run=active_run,
        latest_finalized_run=_latest_finalized_run(subject=subject, data_root=data_root),
        state=state,
        manifold=manifold,
    )
    onboarding_state = _apply_onboarding_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
    )
    automation_state = _apply_automation_projection(
        data_root=data_root,
        state=state,
        manifold=manifold,
        event_timestamp=event_timestamp,
        automation_recent_actions=automation_recent_actions,
        continuity_updated=continuity_updated,
    )

    semantic_projection = None
    if semantic_capture_batch is not None:
        semantic_projection = _rebuild_semantic_capture_projection(
            data_root=data_root,
            state=state,
            manifold=manifold,
            semantic_capture_batch=semantic_capture_batch,
        )

    accepted_details = load_accepted_quest_details(subject, data_root)
    current_accepted = select_current_accepted_quest(accepted_details)
    provenance_summary = compute_current_provenance_summary(
        subject=subject,
        data_root=data_root,
        engine_root=None,
        write_projection=False,
    )

    proposal_paths: list[str] = []
    build_manual_candidates = list(manifold.get("current_build_manual_candidate_backlog") or [])
    talent_candidates = list(manifold.get("current_talent_candidate_backlog") or [])
    codex_candidates = list(manifold.get("current_codex_shard_backlog") or [])
    disclosure_candidates = list(manifold.get("current_disclosure_candidate_backlog") or [])
    order_candidates = list(manifold.get("active_order_candidates") or [])
    build_manual_candidate_path = manifold.get("current_build_manual_candidate_path")
    disclosure_candidate_path = manifold.get("current_disclosure_candidate_path")
    snapshot_candidate_path = manifold.get("current_snapshot_candidate_path")
    verification_entries = list(manifold.get("latest_verification_entries") or [])
    verification_status = manifold.get("current_verification_status")
    session_mode_text = str(active_run.get("session_mode") or "").strip()
    session_policy = policy_for(SessionMode(session_mode_text)) if session_mode_text else None
    allowed_proposal_kinds = set(session_policy.allowed_proposal_kinds) if session_policy is not None else None
    if signal is not None and signal.verification:
        verification_entries.extend(str(item) for item in signal.verification if str(item).strip())
        verification_entries = verification_entries[-10:]
        verification_status = _classify_verification_status(verification_entries) or verification_status
    if (
        mutate_proposals
        and str(active_run.get("session_mode") or "").strip() == SessionMode.ONBOARDING_EXISTING_REPO.value
    ):
        mutate_proposals = False

    if mutate_proposals:
        if semantic_capture_batch is not None:
            promotions = derive_semantic_promotions(semantic_capture_batch)
        elif signal is not None:
            promotions = evaluate_promotion(signal, data_root)
        else:
            promotions = []
        if (
            (allowed_proposal_kinds is None or ProposalKind.QUEST in allowed_proposal_kinds)
            and not any(promotion.kind in QUEST_PROPOSAL_KINDS for promotion in promotions)
        ):
            if signal is not None and signal.source in {"run-start", "run-update", "run-finalize"} and (
                _open_plan_items(active_run)
                or signal.commands
                or signal.files_touched
                or signal.notes
                or signal.summary
            ):
                promotions.append(
                    PromotionRecord(
                        kind=ProposalKind.QUEST,
                        state=ProposalState.AMBIENT,
                        title=_candidate_title(signal, active_run),
                        summary=_candidate_summary(signal, active_run, _candidate_title(signal, active_run)),
                        reason="Active run signals indicate a bounded work unit that should be tracked as a quest candidate.",
                    )
                )
        if allowed_proposal_kinds is not None:
            promotions = [promotion for promotion in promotions if promotion.kind in allowed_proposal_kinds]
        promotion_payloads: list[dict[str, Any]] = []
        quest_candidate_paths: list[str] = []
        for promotion in promotions:
            source_id = run_id or "NO_RUN"
            if promotion.kind in QUEST_PROPOSAL_KINDS:
                candidate = _upsert_quest_candidate(
                    live=live,
                    subject=subject,
                    data_root=data_root,
                    source_id=source_id,
                    interaction_mode=interaction_mode,
                    active_run=active_run,
                    signal=signal,
                    promotion=promotion,
                    current_accepted=current_accepted,
                )
                if candidate is not None:
                    quest_candidate_paths.append(str(candidate["path"]))
                continue

            proposal_id = _proposal_id(promotion.kind, source_id, promotion.title)
            promotion_payloads.append(
                {
                    "proposal_id": proposal_id,
                    "kind": promotion.kind.value,
                    "state": promotion.state.value,
                    "title": promotion.title,
                    "summary": promotion.summary,
                    "reason": promotion.reason,
                    "blockers": list(promotion.blockers),
                    "evidence": list(promotion.evidence),
                    "codex_implications": list(promotion.codex_implications),
                    "created_at": _now_iso(),
                }
            )
            if promotion.kind == ProposalKind.GUILD_ORDERS and proposal_id not in order_candidates:
                order_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.TALENT and proposal_id not in talent_candidates:
                talent_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.CODEX and proposal_id not in codex_candidates:
                codex_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.BUILD_MANUAL and proposal_id not in build_manual_candidates:
                build_manual_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.DISCLOSURE and proposal_id not in disclosure_candidates:
                disclosure_candidates.append(proposal_id)
        proposal_paths = quest_candidate_paths + _write_proposals(
            live=live,
            subject=subject,
            source_id=run_id or "NO_RUN",
            interaction_mode=interaction_mode,
            promotions=promotion_payloads,
        )

    proposal_records = _load_proposal_records(live)
    _sync_candidate_backlog(manifold, proposal_records)

    manifold["active_order_candidates"] = order_candidates
    manifold["current_build_manual_candidate_backlog"] = build_manual_candidates
    manifold["current_talent_candidate_backlog"] = talent_candidates
    manifold["current_codex_shard_backlog"] = codex_candidates
    manifold["current_disclosure_candidate_backlog"] = disclosure_candidates
    if signal is not None:
        build_manual_candidate_path = next(
            (path for path in proposal_paths if "/build_manual/" in path),
            build_manual_candidate_path,
        )
        disclosure_candidate_path = next(
            (path for path in proposal_paths if "/disclosures/" in path),
            disclosure_candidate_path,
        )
        snapshot_candidate_path = next(
            (path for path in proposal_paths if "/snapshots/" in path),
            snapshot_candidate_path,
        )
    manifold["current_build_manual_candidate_path"] = build_manual_candidate_path
    manifold["current_disclosure_candidate_path"] = disclosure_candidate_path
    manifold["current_snapshot_candidate_path"] = snapshot_candidate_path
    manifold["current_verification_status"] = verification_status
    manifold["latest_verification_entries"] = verification_entries
    projection = _apply_quest_lifecycle_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
        world_state=world_state,
    )
    _apply_provenance_projection(
        state=state,
        manifold=manifold,
        summary=provenance_summary,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)

    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        "proposal_paths": proposal_paths,
        "open_questions_path": semantic_projection.get("open_questions_path") if semantic_projection else None,
        "capture_batch_id": semantic_projection.get("capture_batch_id") if semantic_projection else None,
        "capture_count": semantic_projection.get("capture_count") if semantic_projection else None,
        "capture_kinds": semantic_projection.get("capture_kinds") if semantic_projection else None,
        "interaction_mode": interaction_mode,
        "world_state": world_state.value,
        "active_onboarding_id": onboarding_state.get("active_onboarding_id"),
        "onboarding_state": onboarding_state.get("onboarding_state"),
        "published_project_model_path": onboarding_state.get("published_project_model_path"),
        "onboarding_required": automation_state.get("onboarding_required"),
        "onboarding_confirmed": automation_state.get("onboarding_confirmed"),
        "project_identity_ready": automation_state.get("project_identity_ready"),
        "continuity_ready": automation_state.get("continuity_ready"),
        "automation_status": automation_state.get("automation_status"),
        "automation_pending_gate": automation_state.get("automation_pending_gate"),
        "current_accepted_quest_id": projection["current_accepted"]["quest_id"] if projection["current_accepted"] else None,
        "last_completed_quest_id": projection["latest_completed"]["quest_id"] if projection["latest_completed"] else None,
        "provenance_status": provenance_summary.get("provenance_status"),
    }


def _event_notes(signals: dict[str, Any]) -> tuple[str, ...]:
    raw_notes: list[str] = []
    for key in ("notes", "plan_items", "decisions", "discoveries", "disclosures"):
        value = signals.get(key)
        if isinstance(value, list):
            raw_notes.extend(str(item).strip() for item in value if str(item).strip())
    return tuple(raw_notes)


def _ambient_signal_from_event(subject: str, event: dict[str, Any], active_run: dict[str, Any]) -> AmbientSignal | None:
    action_name = str(event.get("action_name") or "").strip()
    if action_name not in {
        "attach-or-init",
        "live-bootstrap",
        "session-start",
        "run-start",
        "run-update",
        "session-tick",
        "run-finalize",
        "log-decision",
        "log-disclosure",
        "formalize",
        "accept-quest",
        "complete-quest",
    }:
        return None

    signals = event.get("signals")
    if not isinstance(signals, dict):
        signals = {}

    title = (
        str(signals.get("run_title") or "").strip()
        or str(signals.get("decision_title") or "").strip()
        or str(signals.get("disclosure_trigger") or "").strip()
        or str(active_run.get("title") or "").strip()
        or None
    )
    summary = (
        str(signals.get("run_goal") or "").strip()
        or str(signals.get("run_summary") or "").strip()
        or str(event.get("summary") or "").strip()
        or None
    )
    status = (
        str(signals.get("final_status") or "").strip()
        or str(signals.get("run_status") or "").strip()
        or str(event.get("status") or "").strip()
        or None
    )
    return AmbientSignal(
        source=action_name,
        subject=subject,
        title=title,
        summary=summary,
        notes=_event_notes(signals),
        commands=tuple(str(item).strip() for item in signals.get("commands") or [] if str(item).strip()),
        files_touched=tuple(
            str(item).strip()
            for item in (active_run.get("files_touched") or signals.get("changed_files") or [])
            if str(item).strip()
        ),
        verification=tuple(
            str(item).strip() for item in signals.get("verification_entries") or [] if str(item).strip()
        ),
        related_sidequests=tuple(
            str(item).strip() for item in signals.get("related_sidequest_ids") or [] if str(item).strip()
        ),
        related_quests=tuple(
            str(item).strip() for item in signals.get("related_quest_ids") or [] if str(item).strip()
        ),
        status=status,
    )


def reduce_sidecar_from_event(*, subject: str, data_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    ensure_live_scaffold(subject, data_root)
    live = live_root(data_root)
    active_run = _load_active_run(live / "ACTIVE_RUN.yaml", subject)
    signal = _ambient_signal_from_event(subject, event, active_run)
    outputs = event.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    def maybe_path(value: Any) -> Path | None:
        text = str(value or "").strip()
        return Path(text) if text else None

    capture_batch = None
    capture_artifact_path = maybe_path(outputs.get("capture_artifact_path"))
    if capture_artifact_path is not None:
        capture_batch = load_capture_batch(capture_artifact_path)
    signals = event.get("signals")
    if not isinstance(signals, dict):
        signals = {}
    automation_actions = [str(item).strip() for item in signals.get("automation_action_kinds") or [] if str(item).strip()]

    return _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=active_run,
        signal=signal,
        semantic_capture_batch=capture_batch,
        decisions_path=maybe_path(outputs.get("decisions_ledger_path")),
        discoveries_path=maybe_path(outputs.get("discoveries_path")),
        disclosures_path=maybe_path(outputs.get("disclosures_ledger_path")),
        mutate_proposals=False,
        event_timestamp=str(event.get("timestamp") or "").strip() or None,
        automation_recent_actions=automation_actions,
        continuity_updated=bool(signals.get("automation_triggered") or automation_actions),
    )

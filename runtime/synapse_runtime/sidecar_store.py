"""Sidecar scaffold, defaults, and YAML-backed store helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.governance_model import required_sidecar_paths
from synapse_runtime.raw_store import ensure_raw_scaffold
from synapse_runtime.session_modes import backfill_mode_from_active_run


LIVE_DIRNAME = ".synapse"
DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def live_root(data_root: Path) -> Path:
    return data_root / LIVE_DIRNAME


def _default_state(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "status": "idle",
        "world_state": "fog_of_war",
        "active_phase": "idle",
        "active_modes": ["ambient"],
        "current_capabilities": [],
        "active_constraints": [],
        "current_priorities": [],
        "recent_changes": [],
        "open_threads": [],
        "active_run_id": None,
        "last_run_id": None,
        "last_decision_id": None,
        "governed_execution_ready": False,
        "current_accepted_quest_id": None,
        "current_accepted_audit_bundle_path": None,
        "current_accepted_audit_state": None,
        "active_session_mode": None,
        "last_session_mode": None,
        "last_session_mode_ended_at": None,
        "last_completed_quest_id": None,
        "last_completed_quest_path": None,
        "last_completed_audit_bundle_path": None,
        "last_completed_verdict": None,
        "last_capture_batch_id": None,
        "last_capture_at": None,
        "open_question_count": 0,
        "blocking_question_count": 0,
        "last_conversation_segment_id": None,
        "last_execution_segment_id": None,
        "last_semantic_event_id": None,
        "last_semantic_event_at": None,
        "semantic_event_count": 0,
        "plan_event_count": 0,
        "last_plan_revision_id": None,
        "last_plan_revision_path": None,
        "last_governed_record_id": None,
        "working_record_count": 0,
        "open_continuity_obligation_count": 0,
        "blocker_continuity_obligation_count": 0,
        "integration_posture": None,
        "local_integration_health": None,
        "degraded_mode": False,
        "strict_boundary_status": None,
        "last_synthesis_refresh_at": None,
        "codex_packet_count": 0,
        "last_codex_packet_refreshed_at": None,
        "current_eod_candidate_path": None,
        "current_control_sync_candidate_path": None,
        "current_eod_candidate_refreshed_at": None,
        "current_control_sync_candidate_refreshed_at": None,
        "stale_prior_day_candidate_required": False,
        "candidate_obligation_count": 0,
        "current_story_candidate_path": None,
        "current_vision_candidate_path": None,
        "current_publication_candidate_refreshed_at": None,
        "onboarding_state": None,
        "active_onboarding_id": None,
        "latest_confirmed_onboarding_id": None,
        "current_workplan_id": None,
        "onboarding_required": False,
        "onboarding_requirement_reason": None,
        "onboarding_confirmed": False,
        "project_identity_ready": False,
        "continuity_ready": True,
        "automation_status": "active",
        "automation_last_activity_at": None,
        "automation_last_continuity_update_at": None,
        "automation_pending_gate": None,
        "published_project_model_path": None,
        "published_project_story_path": None,
        "published_vision_path": None,
        "published_codex_current_path": None,
        "published_codex_future_path": None,
        "project_model_confirmed_at": None,
        "project_model_open_questions_count": 0,
        "project_model_blocking_questions_count": 0,
        "project_summary": None,
        "last_truth_compile_at": None,
        "last_truth_compile_cycle_id": None,
        "truth_statement_count": 0,
        "truth_active_statement_count": 0,
        "truth_contradiction_count": 0,
        "truth_superseded_count": 0,
        "truth_compile_stale": False,
        "truth_stale_reasons": [],
        "truth_stale_active_run_detected": False,
        "provenance_status": None,
        "provenance_last_observed_at": None,
        "provenance_last_watch_at": None,
        "provenance_blocker_count": 0,
        "provenance_warning_count": 0,
        "current_wrapper_proof_status": None,
        "git_hooks_status": None,
        "last_rehydrate_at": None,
        "last_event_id": None,
        "last_event_at": None,
        "last_reduced_event_id": None,
        "reducer_version": None,
    }


def _default_manifold(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "world_state": "fog_of_war",
        "active_phase": "idle",
        "active_modes": ["ambient"],
        "active_session_ids": [],
        "active_run_ids": [],
        "active_order_candidates": [],
        "active_quest_candidates": [],
        "quest_candidate_details": [],
        "pending_formalizations": [],
        "current_build_manual_candidate_backlog": [],
        "current_codex_shard_backlog": [],
        "current_disclosure_candidate_backlog": [],
        "current_talent_candidate_backlog": [],
        "current_decision_ledger_path": None,
        "current_discovery_ledger_path": None,
        "current_disclosure_ledger_path": None,
        "current_build_manual_candidate_path": None,
        "current_disclosure_candidate_path": None,
        "current_snapshot_candidate_path": None,
        "current_snapshot_candidate_kind": None,
        "current_eod_candidate_path": None,
        "current_control_sync_candidate_path": None,
        "current_eod_candidate_refreshed_at": None,
        "current_control_sync_candidate_refreshed_at": None,
        "current_eod_candidate_summary": None,
        "current_control_sync_candidate_summary": None,
        "current_story_candidate_path": None,
        "current_vision_candidate_path": None,
        "current_codex_candidate_paths": [],
        "current_story_candidate_summary": None,
        "current_vision_candidate_summary": None,
        "current_codex_candidate_summary": None,
        "current_publication_candidate_refreshed_at": None,
        "stale_prior_day_candidate_required": False,
        "candidate_obligation_count": 0,
        "recent_eod_candidate_details": [],
        "recent_control_sync_candidate_details": [],
        "current_verification_status": None,
        "latest_verification_entries": [],
        "accepted_quest_ids": [],
        "accepted_quest_details": [],
        "current_accepted_quest_id": None,
        "current_accepted_quest_path": None,
        "current_accepted_audit_bundle_path": None,
        "current_accepted_audit_state": None,
        "active_session_mode": None,
        "active_session_mode_source": None,
        "active_session_mode_set_at": None,
        "active_session_mode_reason": None,
        "active_session_mode_policy_version": None,
        "active_session_mode_policy": None,
        "last_session_mode": None,
        "last_session_mode_ended_at": None,
        "recent_capture_batch_ids": [],
        "last_capture_batch_id": None,
        "last_capture_at": None,
        "open_question_details": [],
        "blocking_question_details": [],
        "recent_idea_details": [],
        "recent_repo_fact_details": [],
        "recent_constraint_details": [],
        "recent_risk_details": [],
        "recent_dependency_details": [],
        "recent_non_goal_details": [],
        "recent_milestone_details": [],
        "candidate_decision_details": [],
        "recent_conversation_segment_ids": [],
        "recent_execution_segment_ids": [],
        "recent_semantic_event_details": [],
        "recent_plan_event_ids": [],
        "semantic_event_count": 0,
        "transient_semantic_event_count": 0,
        "plan_event_count": 0,
        "last_semantic_event_id": None,
        "last_semantic_event_at": None,
        "recent_working_record_details": [],
        "working_record_family_counts": {},
        "active_scope_campaign_ids": [],
        "last_governed_record_id": None,
        "recent_plan_revision_details": [],
        "last_plan_revision_id": None,
        "last_plan_revision_path": None,
        "recent_lineage_edge_ids": [],
        "open_continuity_obligation_count": 0,
        "blocker_continuity_obligation_count": 0,
        "recent_open_continuity_obligation_details": [],
        "current_active_plan_delta": {},
        "current_active_scope_delta": {},
        "current_obligation_delta": {},
        "current_architecture_delta": {},
        "current_identity_delta": {},
        "current_narrative_delta": {},
        "codex_packet_count": 0,
        "last_codex_packet_refreshed_at": None,
        "recent_codex_packet_details": [],
        "recent_story_candidate_details": [],
        "recent_vision_candidate_details": [],
        "recent_codex_candidate_details": [],
        "packet_section_keys": [],
        "last_synthesis_refresh_at": None,
        "active_onboarding_id": None,
        "latest_confirmed_onboarding_id": None,
        "onboarding_state": None,
        "current_workplan_id": None,
        "workplan_step_statuses": {},
        "onboarding_required": False,
        "onboarding_requirement_reason": None,
        "onboarding_confirmed": False,
        "project_identity_ready": False,
        "continuity_ready": True,
        "automation_status": "active",
        "automation_last_activity_at": None,
        "automation_last_continuity_update_at": None,
        "automation_recent_actions": [],
        "automation_pending_gate": None,
        "current_scan_id": None,
        "current_draft_id": None,
        "draft_is_stale": False,
        "current_question_set_id": None,
        "unincorporated_capture_batch_ids": [],
        "unincorporated_clarification_batch_ids": [],
        "published_project_model_path": None,
        "published_project_story_path": None,
        "published_vision_path": None,
        "published_codex_current_path": None,
        "published_codex_future_path": None,
        "project_model_confirmed_at": None,
        "project_purpose_summary": None,
        "project_capability_summary": [],
        "project_constraint_summary": [],
        "project_history_summary": [],
        "project_open_question_details": [],
        "last_truth_compile_at": None,
        "last_truth_compile_cycle_id": None,
        "truth_statement_count": 0,
        "truth_active_statement_count": 0,
        "truth_contradiction_count": 0,
        "truth_superseded_count": 0,
        "truth_compile_stale": False,
        "truth_stale_reasons": [],
        "stale_active_run_detected": False,
        "current_work_summary": {},
        "truth_publication_paths": {},
        "provenance_status": None,
        "provenance_last_observed_at": None,
        "provenance_last_watch_at": None,
        "provenance_blockers": [],
        "provenance_warnings": [],
        "continuity_blockers": [],
        "continuity_warnings": [],
        "recent_provenance_anomalies": [],
        "current_wrapper_proof_status": None,
        "current_wrapper_proof_path": None,
        "current_wrapper_proof_fingerprint": None,
        "git_hooks_status": None,
        "git_hooks_template_version": None,
        "git_hooks_last_verified_at": None,
        "provenance_baseline_path": None,
        "integration_posture": None,
        "local_integration_health": None,
        "local_integration_missing_assets": [],
        "degraded_mode": False,
        "degraded_mode_reason": None,
        "strict_boundary_status": None,
        "completed_quest_ids": [],
        "completed_quest_details": [],
        "last_completed_quest_id": None,
        "last_completed_quest_path": None,
        "last_completed_audit_bundle_path": None,
        "last_completed_verdict": None,
        "governed_execution_ready": False,
        "last_updated_at": _now_iso(),
    }


def _default_active_run(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active": False,
        "run_id": None,
        "subject": subject,
        "session_id": None,
        "title": None,
        "goal": None,
        "started_at": None,
        "updated_at": _now_iso(),
        "status": "idle",
        "interaction_mode": "maintenance",
        "session_mode": None,
        "session_mode_source": None,
        "session_mode_set_at": None,
        "session_mode_reason": None,
        "session_mode_policy_version": None,
        "plan": {"items": []},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "related_quests": [],
        "pending_questions": [],
        "result_summary": None,
    }


def _default_daily_ledger(subject: str, day: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "date": day,
        "entries": [],
    }


def _default_onboarding_pointer(subject: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "adopted_existing_repo": False,
        "current_onboarding_id": None,
        "latest_confirmed_onboarding_id": None,
        "updated_at": _now_iso(),
    }


def ensure_live_scaffold(subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    raw_receipt = ensure_raw_scaffold(data_root)
    events_dir = live / "EVENTS"
    decisions_dir = live / "DECISIONS"
    discoveries_dir = live / "DISCOVERIES"
    disclosures_dir = live / "DISCLOSURES"
    captures_dir = live / "CAPTURES"
    capture_batches_dir = captures_dir / "BATCHES"
    onboarding_dir = live / "ONBOARDING"
    onboarding_sessions_dir = onboarding_dir / "SESSIONS"
    onboarding_scans_dir = onboarding_dir / "SCANS"
    onboarding_briefs_dir = onboarding_dir / "BRIEFS"
    onboarding_drafts_dir = onboarding_dir / "DRAFTS"
    onboarding_questions_dir = onboarding_dir / "QUESTIONS"
    onboarding_workplans_dir = onboarding_dir / "WORKPLANS"
    onboarding_published_dir = onboarding_dir / "PUBLISHED"
    truth_dir = live / "TRUTH"
    truth_publications_dir = truth_dir / "PUBLICATIONS"
    provenance_dir = live / "PROVENANCE"
    provenance_anomalies_dir = provenance_dir / "ANOMALIES"
    runs_dir = live / "RUNS"
    threads_dir = live / "THREADS"
    proposals_dir = live / "PROPOSALS"
    intent_fragments_dir = live / "INTENT_FRAGMENTS"
    scope_campaigns_dir = live / "SCOPE_CAMPAIGNS"
    quest_links_dir = live / "QUEST_LINKS"
    decision_graph_dir = live / "DECISION_GRAPH"
    architecture_evolution_dir = live / "ARCHITECTURE_EVOLUTION"
    failure_chains_dir = live / "FAILURE_CHAINS"
    narrative_claims_dir = live / "NARRATIVE_CLAIMS"
    project_identity_claims_dir = live / "PROJECT_IDENTITY_CLAIMS"
    imported_evidence_dir = live / "IMPORTED_EVIDENCE"
    continuity_obligations_dir = live / "CONTINUITY_OBLIGATIONS"
    lineage_dir = live / "LINEAGE"
    lineage_edges_dir = lineage_dir / "EDGES"
    codex_packets_dir = live / "CODEX_SECTION_PACKETS"
    proposal_kinds = {
        "quests": proposals_dir / "quests",
        "side_quests": proposals_dir / "side_quests",
        "snapshots": proposals_dir / "snapshots",
        "control_sync": proposals_dir / "control_sync",
        "guild_orders": proposals_dir / "guild_orders",
        "codex": proposals_dir / "codex",
        "build_manual": proposals_dir / "build_manual",
        "talent": proposals_dir / "talent",
        "disclosures": proposals_dir / "disclosures",
    }

    events_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    discoveries_dir.mkdir(parents=True, exist_ok=True)
    disclosures_dir.mkdir(parents=True, exist_ok=True)
    captures_dir.mkdir(parents=True, exist_ok=True)
    capture_batches_dir.mkdir(parents=True, exist_ok=True)
    onboarding_dir.mkdir(parents=True, exist_ok=True)
    onboarding_sessions_dir.mkdir(parents=True, exist_ok=True)
    onboarding_scans_dir.mkdir(parents=True, exist_ok=True)
    onboarding_briefs_dir.mkdir(parents=True, exist_ok=True)
    onboarding_drafts_dir.mkdir(parents=True, exist_ok=True)
    onboarding_questions_dir.mkdir(parents=True, exist_ok=True)
    onboarding_workplans_dir.mkdir(parents=True, exist_ok=True)
    onboarding_published_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    truth_publications_dir.mkdir(parents=True, exist_ok=True)
    provenance_dir.mkdir(parents=True, exist_ok=True)
    provenance_anomalies_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    threads_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    intent_fragments_dir.mkdir(parents=True, exist_ok=True)
    scope_campaigns_dir.mkdir(parents=True, exist_ok=True)
    quest_links_dir.mkdir(parents=True, exist_ok=True)
    decision_graph_dir.mkdir(parents=True, exist_ok=True)
    architecture_evolution_dir.mkdir(parents=True, exist_ok=True)
    failure_chains_dir.mkdir(parents=True, exist_ok=True)
    narrative_claims_dir.mkdir(parents=True, exist_ok=True)
    project_identity_claims_dir.mkdir(parents=True, exist_ok=True)
    imported_evidence_dir.mkdir(parents=True, exist_ok=True)
    continuity_obligations_dir.mkdir(parents=True, exist_ok=True)
    lineage_dir.mkdir(parents=True, exist_ok=True)
    lineage_edges_dir.mkdir(parents=True, exist_ok=True)
    codex_packets_dir.mkdir(parents=True, exist_ok=True)
    for directory in proposal_kinds.values():
        directory.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    existing: list[str] = []

    vision_path = live / "VISION.md"
    vision_template = """# Vision (Live)

This is the concise, living identity for the subject.
Keep it short, truthful, and current.

## Project
- Name:
- One-line summary:

## Purpose
- Why this exists:

## Core experience / feel
- What it should feel like to use or operate:

## What exists now
- Known capabilities:

## What does not exist yet
- Explicit gaps:

## Non-negotiables
- Principles that must not be violated:

## Recent important shifts
- Changes in direction or scope:
"""
    if _write_if_missing(vision_path, vision_template):
        created.append(str(vision_path))
    else:
        existing.append(str(vision_path))

    state_path = live / "STATE.yaml"
    if not state_path.exists():
        _write_yaml(state_path, _default_state(subject))
        created.append(str(state_path))
    else:
        existing.append(str(state_path))

    manifold_path = live / "MANIFOLD.yaml"
    if not manifold_path.exists():
        _write_yaml(manifold_path, _default_manifold(subject))
        created.append(str(manifold_path))
    else:
        existing.append(str(manifold_path))

    rehydrate_path = live / "REHYDRATE.md"
    rehydrate_template = """# Rehydrate

Run `python3 runtime/synapse.py render-rehydrate` to refresh this file.
"""
    if _write_if_missing(rehydrate_path, rehydrate_template):
        created.append(str(rehydrate_path))
    else:
        existing.append(str(rehydrate_path))

    active_run_path = live / "ACTIVE_RUN.yaml"
    if not active_run_path.exists():
        _write_yaml(active_run_path, _default_active_run(subject))
        created.append(str(active_run_path))
    else:
        existing.append(str(active_run_path))

    onboarding_pointer_path = onboarding_dir / "CURRENT.yaml"
    if not onboarding_pointer_path.exists():
        _write_yaml(onboarding_pointer_path, _default_onboarding_pointer(subject))
        created.append(str(onboarding_pointer_path))
    else:
        existing.append(str(onboarding_pointer_path))

    today = _now().date().isoformat()
    decision_ledger_path = decisions_dir / f"{today}.yaml"
    if not decision_ledger_path.exists():
        _write_yaml(decision_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(decision_ledger_path))
    else:
        existing.append(str(decision_ledger_path))

    discovery_ledger_path = discoveries_dir / f"{today}.yaml"
    if not discovery_ledger_path.exists():
        _write_yaml(discovery_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(discovery_ledger_path))
    else:
        existing.append(str(discovery_ledger_path))

    disclosure_ledger_path = disclosures_dir / f"{today}.yaml"
    if not disclosure_ledger_path.exists():
        _write_yaml(disclosure_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(disclosure_ledger_path))
    else:
        existing.append(str(disclosure_ledger_path))

    capture_ledger_path = captures_dir / f"{today}.yaml"
    if not capture_ledger_path.exists():
        _write_yaml(capture_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(capture_ledger_path))
    else:
        existing.append(str(capture_ledger_path))

    open_questions_path = threads_dir / "open_questions.md"
    open_questions_template = """# Open Questions

## Blocking
- None yet.

## Nonblocking
- None yet.
"""
    if _write_if_missing(open_questions_path, open_questions_template):
        created.append(str(open_questions_path))
    else:
        existing.append(str(open_questions_path))

    return {
        "live_root": str(live),
        "created": created,
        "existing": existing,
        "required_paths": {kind.value: str(path) for kind, path in required_sidecar_paths(data_root).items()},
        "raw_scaffold": raw_receipt,
    }


def _load_state(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_state(subject)
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    defaults = _default_state(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def _load_active_run(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_active_run(subject)
    defaults = _default_active_run(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    if "plan" not in data or not isinstance(data["plan"], dict):
        data["plan"] = {"items": []}
    if "items" not in data["plan"] or not isinstance(data["plan"]["items"], list):
        data["plan"]["items"] = []
    normalized, changed = backfill_mode_from_active_run(data, _now_iso())
    if changed:
        _write_yaml(path, normalized)
        return normalized
    return data


def _load_manifold(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_manifold(subject)
    defaults = _default_manifold(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def canonical_open_questions_path(data_root: Path) -> Path:
    return live_root(data_root) / "THREADS" / "open_questions.md"


def authoritative_coordination_paths(data_root: Path) -> list[Path]:
    live = live_root(data_root)
    paths = [
        live / "ACTIVE_RUN.yaml",
        live / "ONBOARDING" / "CURRENT.yaml",
    ]
    return [path.resolve() for path in paths]


def _read_text_strict(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Unable to read canonical sidecar file: {path}") from exc


def load_open_questions_text(data_root: Path) -> str:
    path = canonical_open_questions_path(data_root)
    if not path.exists():
        return ""
    return _read_text_strict(path)


def load_recent_discovery_summaries(data_root: Path, limit: int = 20) -> list[str]:
    from synapse_runtime.ledger_store import _load_recent_daily_entries

    entries = _load_recent_daily_entries(data_root, "DISCOVERIES", limit, strict=True)
    return [str(entry.get("summary") or "").strip() for entry in entries if str(entry.get("summary") or "").strip()]


def load_recent_decision_summaries(data_root: Path, limit: int = 20) -> list[str]:
    from synapse_runtime.ledger_store import _load_recent_daily_entries

    entries = _load_recent_daily_entries(data_root, "DECISIONS", limit, strict=True)
    summaries: list[str] = []
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        if title and summary:
            summaries.append(f"{title}: {summary}")
        elif title:
            summaries.append(title)
        elif summary:
            summaries.append(summary)
    return summaries

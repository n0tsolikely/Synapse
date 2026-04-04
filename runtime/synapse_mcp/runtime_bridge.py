"""In-process bridge from MCP tools/resources to Synapse runtime semantics."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

import synapse as cli_runtime
from synapse_mcp.connection_state import ConnectionState
from synapse_mcp.result_mapping import BridgeFailure, STATUS_BLOCKED, STATUS_FAILED, STATUS_NOOP, STATUS_OK
from synapse_mcp.schemas import ContextInput
from synapse_runtime.governance_model import AmbientSignal, ProposalKind, ProposalState
from synapse_runtime.draftshots import draftshot_summary, refresh_draftshot
from synapse_runtime.live_journal import log_decision, log_disclosure
from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.project_model import ProjectModelError
from synapse_runtime.publication_candidates import (
    load_publication_candidate_body,
    publication_candidate_summary,
    refresh_publication_candidates,
    resolve_publication_candidate,
)
from synapse_runtime.quest_acceptance import QuestAcceptanceError
from synapse_runtime.quest_candidates import list_proposals, mark_proposal_state
from synapse_runtime.reducer import ReducerError
from synapse_runtime.repo_archaeology import RepoArchaeologyError
from synapse_runtime.repo_state import inspect_engaged_kernel_posture
from synapse_runtime.repo_onboarding import (
    RepoOnboardingError,
    archived_project_model_path,
    archived_project_story_path,
    archived_vision_path,
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
    current_onboarding_session,
    mark_adopted_existing_repo,
    onboard_repo,
    onboarding_abandon,
    onboarding_brief_path,
    onboarding_confirm,
    onboarding_current_path,
    onboarding_draft_path,
    onboarding_projection,
    onboarding_question_set_path,
    onboarding_session_path,
    onboarding_status_payload,
    onboarding_update,
    onboarding_respond,
    publication_receipt_path,
)
from synapse_runtime.rehydration_pack import refresh_rehydration_pack
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.run_lifecycle import load_active_run_record, run_finalize, run_start, run_update
from synapse_runtime.semantic_classifier import normalized_semantic_summary
from synapse_runtime.semantic_intake import (
    SemanticIntakeError,
    batch_disclosure_needed,
    batch_uncertainty_present,
    capture_kinds as semantic_capture_kinds,
    normalize_capture_source_role,
    write_capture_batch,
)
from synapse_runtime.session_modes import SessionMode, policy_for_run, session_mode_signal_fields
from synapse_runtime.sidecar_projection import _sync_sidecar, refresh_synthesis_projection
from synapse_runtime.sidecar_store import _load_manifold, _load_state, _read_yaml, canonical_open_questions_path, ensure_live_scaffold, live_root
from synapse_runtime.snapshot_candidates import refresh_snapshot_candidates, snapshot_candidate_summary
from synapse_runtime.subject_bootstrap import initialize_subject_state, repo_subject_defaults
from synapse_runtime.subject_resolver import SubjectResolutionError, resolve_subject, write_focus_lock


def _generated_session_id() -> str:
    return f"mcp-{uuid.uuid4().hex[:16]}"


def _context_dict(context: ContextInput | dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, dict):
        return {key: value for key, value in context.items() if value is not None}
    return context.model_dump(exclude_none=True)


def _subject_from_data_root(data_root: Path) -> str | None:
    name = data_root.name.strip()
    if name.endswith("_Data") and len(name) > 5:
        return name[:-5]
    return None


def _validate_explicit_context(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {}
    subject = str(context.get("subject") or "").strip() or None
    engine_root_raw = context.get("engine_root")
    data_root_raw = context.get("data_root")
    engine_root = Path(str(engine_root_raw)).expanduser().resolve() if engine_root_raw else None
    data_root = Path(str(data_root_raw)).expanduser().resolve() if data_root_raw else None

    derived_subject_from_data = _subject_from_data_root(data_root) if data_root else None
    if subject and derived_subject_from_data and subject != derived_subject_from_data:
        raise BridgeFailure(
            code="CONTEXT_RESOLUTION_FAILED",
            message=(
                f"Explicit context mismatch: subject '{subject}' does not match data_root '{data_root}'."
            ),
        )

    if data_root and not subject and not derived_subject_from_data:
        raise BridgeFailure(
            code="CONTEXT_RESOLUTION_FAILED",
            message="Explicit data_root does not encode a subject and cannot be resolved unambiguously.",
        )

    subject = subject or derived_subject_from_data
    if engine_root and not subject:
        subject = engine_root.name.strip() or None

    if data_root and not engine_root:
        if not subject:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message="Explicit data_root could not resolve a matching engine_root unambiguously.",
            )
        candidates = [data_root.parent / subject, data_root.parent / f"{subject}_Engine"]
        existing = [candidate.resolve() for candidate in candidates if candidate.exists()]
        if len(existing) == 1:
            engine_root = existing[0]
        else:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message="Explicit data_root requires an explicit engine_root when the matching engine root is ambiguous.",
            )

    if engine_root and not data_root:
        if not subject:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message="Explicit engine_root could not resolve a subject context unambiguously.",
            )
        data_root = (engine_root.parent / f"{subject}_Data").resolve()

    if engine_root and data_root:
        try:
            resolved = resolve_subject(
                subject_flag=subject,
                data_root_flag=str(data_root),
                engine_root_flag=str(engine_root),
                allow_switch=True,
                session_id=cli_runtime._normalize_session_id(context.get("session_id")),
            )
        except SubjectResolutionError as exc:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message=f"Explicit engine_root and data_root do not resolve as a coherent subject pair: {exc}",
            ) from exc
        subject = resolved["subject"]
        engine_root = Path(str(resolved["engine_root"])).expanduser().resolve()
        data_root = Path(str(resolved["data_root"])).expanduser().resolve()

    payload = {
        "subject": subject,
        "engine_root": str(engine_root) if engine_root else None,
        "data_root": str(data_root) if data_root else None,
        "session_id": cli_runtime._normalize_session_id(context.get("session_id")),
        "allow_switch": bool(context.get("allow_switch")),
    }
    return payload


def _resolve_subject_context(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None = None,
    allow_attach_current_repo: bool = False,
    require_allow_switch_for_default_change: bool = False,
    prepare_subject_state: bool = True,
) -> tuple[dict[str, Any], bool]:
    explicit = _validate_explicit_context(_context_dict(context))
    allow_switch = bool(explicit.get("allow_switch"))
    explicit_present = any(explicit.get(field) for field in ("subject", "engine_root", "data_root"))

    default_subject = state.default_subject if not explicit.get("subject") else explicit.get("subject")
    default_engine_root = state.default_engine_root if not explicit.get("engine_root") else explicit.get("engine_root")
    default_data_root = state.default_data_root if not explicit.get("data_root") else explicit.get("data_root")
    default_session_id = explicit.get("session_id") or state.default_session_id

    if allow_attach_current_repo:
        args = SimpleNamespace(
            subject=default_subject,
            data_root=default_data_root,
            engine_root=default_engine_root,
            allow_switch=True,
            selected_by="MCP",
            no_home_lock=False,
            session_id=default_session_id,
        )
        try:
            ctx = cli_runtime._resolve_or_attach_subject_from_args(args)
        except Exception as exc:  # pragma: no cover - defensive
            raise BridgeFailure(code="CONTEXT_RESOLUTION_FAILED", message=str(exc)) from exc
        if not ctx:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message="Unable to resolve or adopt the current repo into a Synapse subject context.",
            )
    else:
        try:
            ctx = resolve_subject(
                subject_flag=default_subject,
                data_root_flag=default_data_root,
                engine_root_flag=default_engine_root,
                allow_switch=True,
                session_id=default_session_id,
            )
        except SubjectResolutionError as exc:
            raise BridgeFailure(
                code="CONTEXT_RESOLUTION_FAILED",
                message=str(exc),
                recovery_hint="Use bootstrap_session with adopt_current_repo=true or provide an explicit coherent context.",
            ) from exc
        data_root = Path(str(ctx["data_root"])).expanduser().resolve()
        engine_root = Path(str(ctx["engine_root"])).expanduser().resolve()
        auto_initialized = False
        if not cli_runtime._core_subject_artifacts_present(ctx):
            if not prepare_subject_state:
                raise BridgeFailure(
                    code="CONTEXT_RESOLUTION_FAILED",
                    message="Resolved subject context is missing Synapse subject artifacts.",
                    recovery_hint="Use bootstrap_session or run_repo_onboarding first.",
                )
            initialize_subject_state(ctx["subject"], data_root, engine_root)
            auto_initialized = True
        if prepare_subject_state:
            live_receipt = ensure_live_scaffold(ctx["subject"], data_root)
            ctx["live_root"] = live_receipt.get("live_root")
            ctx["required_paths"] = live_receipt.get("required_paths", {})
        else:
            ctx["live_root"] = str(live_root(data_root))
            ctx["required_paths"] = {}
        ctx["auto_initialized"] = auto_initialized

    if (
        require_allow_switch_for_default_change
        and explicit_present
        and state.default_subject
        and ctx["subject"] != state.default_subject
        and not allow_switch
    ):
        raise BridgeFailure(
            code="CONTEXT_RESOLUTION_FAILED",
            status=STATUS_BLOCKED,
            message=(
                f"Explicit context resolves to subject '{ctx['subject']}', "
                f"but the current connection default subject is '{state.default_subject}'."
            ),
            recovery_hint="Retry with context.allow_switch=true via bootstrap_session or run_repo_onboarding.",
        )

    return ctx, explicit_present


def _resolve_runtime_context(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None = None,
    allow_attach_current_repo: bool = False,
    requires_session: bool = False,
    generate_session: bool = False,
    require_allow_switch_for_default_change: bool = False,
    repair_active_run_session_id: bool = True,
    prepare_subject_state: bool = True,
) -> dict[str, Any]:
    ctx, _ = _resolve_subject_context(
        state=state,
        context=context,
        allow_attach_current_repo=allow_attach_current_repo,
        require_allow_switch_for_default_change=require_allow_switch_for_default_change,
        prepare_subject_state=prepare_subject_state,
    )
    active_run = load_active_run_record(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        ensure_scaffold=prepare_subject_state,
    )
    effective_session_id = (
        cli_runtime._normalize_session_id(_context_dict(context).get("session_id"))
        or cli_runtime._normalize_session_id(state.default_session_id)
        or cli_runtime._normalize_session_id(active_run.get("session_id"))
        or cli_runtime._normalize_session_id(os.environ.get("SYNAPSE_SESSION_ID"))
    )
    if not effective_session_id and generate_session:
        effective_session_id = _generated_session_id()
    if requires_session and not effective_session_id:
        raise BridgeFailure(
            code="CONTEXT_RESOLUTION_FAILED",
            message="This operation requires a session id, but none could be resolved.",
            recovery_hint="Run bootstrap_session first or pass context.session_id explicitly.",
        )
    ctx = dict(ctx)
    ctx["session_id"] = effective_session_id
    ctx["active_run"] = (
        cli_runtime._repair_active_run_session_id(
            data_root=Path(ctx["data_root"]),
            active_run=active_run,
            session_id=effective_session_id,
        )
        if repair_active_run_session_id
        else active_run
    )
    return ctx


def _current_subject_files(ctx: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    live = live_root(Path(ctx["data_root"]))
    return (
        live / "STATE.yaml",
        live / "MANIFOLD.yaml",
        live / "ACTIVE_RUN.yaml",
        live / "REHYDRATE.md",
    )


def _json_file_or_empty(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path)
    return payload if isinstance(payload, dict) else {}


def _text_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _event_is_partial(event_info: dict[str, Any] | None) -> bool:
    if not isinstance(event_info, dict):
        return False
    runtime_status = event_info.get("runtime_status")
    if not isinstance(runtime_status, dict):
        return False
    return str(runtime_status.get("operation_status") or "").strip().lower() == "partial"


def build_current_context_bundle(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None = None,
    include_rehydrate: bool = False,
    include_project_story: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(
        state=state,
        context=context,
        allow_attach_current_repo=False,
        requires_session=False,
        repair_active_run_session_id=False,
        prepare_subject_state=False,
    )
    data_root = Path(ctx["data_root"])
    state_path, manifold_path, run_path, rehydrate_path = _current_subject_files(ctx)
    state_payload = _json_file_or_empty(state_path)
    manifold_payload = _json_file_or_empty(manifold_path)
    active_run = load_active_run_record(subject=ctx["subject"], data_root=data_root, ensure_scaffold=False)
    onboarding_payload = onboarding_status_payload(
        subject=ctx["subject"],
        data_root=data_root,
        persist_pointer=False,
        ensure_scaffold=False,
    )
    project_model_path = canonical_project_model_path(data_root)
    project_model = _json_file_or_empty(project_model_path)

    accepted_summary = {
        "current_accepted_quest_id": manifold_payload.get("current_accepted_quest_id") or state_payload.get("current_accepted_quest_id"),
        "accepted_quest_ids": list(manifold_payload.get("accepted_quest_ids") or []),
        "completed_quest_ids": list(manifold_payload.get("completed_quest_ids") or []),
        "governed_execution_ready": bool(manifold_payload.get("governed_execution_ready") if "governed_execution_ready" in manifold_payload else state_payload.get("governed_execution_ready")),
    }
    semantic_summary = {
        "last_capture_batch_id": state_payload.get("last_capture_batch_id"),
        "last_capture_at": state_payload.get("last_capture_at"),
        "open_question_count": state_payload.get("open_question_count") or 0,
        "blocking_question_count": state_payload.get("blocking_question_count") or 0,
        "last_conversation_segment_id": state_payload.get("last_conversation_segment_id"),
        "last_execution_segment_id": state_payload.get("last_execution_segment_id"),
        "last_semantic_event_id": state_payload.get("last_semantic_event_id"),
        "last_semantic_event_at": state_payload.get("last_semantic_event_at"),
        "semantic_event_count": state_payload.get("semantic_event_count") or 0,
        "plan_event_count": state_payload.get("plan_event_count") or 0,
        "recent_semantic_event_details": list(manifold_payload.get("recent_semantic_event_details") or []),
        "recent_plan_event_ids": list(manifold_payload.get("recent_plan_event_ids") or []),
    }
    governed_summary = {
        "working_record_count": state_payload.get("working_record_count") or 0,
        "last_governed_record_id": state_payload.get("last_governed_record_id"),
        "working_record_family_counts": dict(manifold_payload.get("working_record_family_counts") or {}),
        "active_scope_campaign_ids": list(manifold_payload.get("active_scope_campaign_ids") or []),
        "recent_working_record_details": list(manifold_payload.get("recent_working_record_details") or []),
        "recent_plan_revision_details": list(manifold_payload.get("recent_plan_revision_details") or []),
        "last_plan_revision_id": state_payload.get("last_plan_revision_id"),
        "last_plan_revision_path": state_payload.get("last_plan_revision_path"),
        "open_continuity_obligation_count": state_payload.get("open_continuity_obligation_count") or 0,
        "blocker_continuity_obligation_count": state_payload.get("blocker_continuity_obligation_count") or 0,
        "recent_open_continuity_obligation_details": list(manifold_payload.get("recent_open_continuity_obligation_details") or []),
    }
    synthesis_summary = {
        "last_synthesis_refresh_at": state_payload.get("last_synthesis_refresh_at"),
        "active_plan_delta": dict(manifold_payload.get("current_active_plan_delta") or {}),
        "active_scope_delta": dict(manifold_payload.get("current_active_scope_delta") or {}),
        "obligation_delta": dict(manifold_payload.get("current_obligation_delta") or {}),
        "architecture_delta": dict(manifold_payload.get("current_architecture_delta") or {}),
        "identity_delta": dict(manifold_payload.get("current_identity_delta") or {}),
        "narrative_delta": dict(manifold_payload.get("current_narrative_delta") or {}),
    }
    codex_packet_summary = {
        "codex_packet_count": state_payload.get("codex_packet_count") or 0,
        "last_codex_packet_refreshed_at": state_payload.get("last_codex_packet_refreshed_at"),
        "packet_section_keys": list(manifold_payload.get("packet_section_keys") or []),
        "recent_codex_packet_details": list(manifold_payload.get("recent_codex_packet_details") or []),
    }
    draftshot_state = draftshot_summary(
        data_root,
        session_id=ctx.get("session_id") or active_run.get("session_id"),
    )
    snapshot_candidates_state = snapshot_candidate_summary(data_root)
    publication_candidates_state = publication_candidate_summary(data_root)
    session_posture = {
        "active_session_mode": manifold_payload.get("active_session_mode") or state_payload.get("active_session_mode"),
        "active_session_mode_policy": manifold_payload.get("active_session_mode_policy"),
        "last_session_mode": manifold_payload.get("last_session_mode") or state_payload.get("last_session_mode"),
        "last_session_mode_ended_at": manifold_payload.get("last_session_mode_ended_at") or state_payload.get("last_session_mode_ended_at"),
    }
    provenance_summary = {
        "provenance_status": manifold_payload.get("provenance_status") or state_payload.get("provenance_status"),
        "blocker_count": len(list(manifold_payload.get("provenance_blockers") or [])),
        "warning_count": len(list(manifold_payload.get("provenance_warnings") or [])),
        "open_continuity_obligation_count": state_payload.get("open_continuity_obligation_count") or 0,
        "blocker_continuity_obligation_count": state_payload.get("blocker_continuity_obligation_count") or 0,
        "integration_posture": manifold_payload.get("integration_posture") or state_payload.get("integration_posture"),
        "local_integration_health": manifold_payload.get("local_integration_health") or state_payload.get("local_integration_health"),
        "local_integration_missing_assets": list(manifold_payload.get("local_integration_missing_assets") or []),
        "degraded_mode": bool(manifold_payload.get("degraded_mode") if "degraded_mode" in manifold_payload else state_payload.get("degraded_mode")),
        "degraded_mode_reason": manifold_payload.get("degraded_mode_reason"),
        "strict_boundary_status": manifold_payload.get("strict_boundary_status") or state_payload.get("strict_boundary_status"),
        "current_wrapper_proof_status": manifold_payload.get("current_wrapper_proof_status") or state_payload.get("current_wrapper_proof_status"),
        "git_hooks_status": manifold_payload.get("git_hooks_status") or state_payload.get("git_hooks_status"),
    }
    automation_summary = cli_runtime._readiness_payload(data_root)
    kernel_posture = inspect_engaged_kernel_posture(repo_root=Path(ctx["engine_root"]), data_root=data_root)
    bundle = {
        "resolved_subject_context": {
            "subject": ctx["subject"],
            "engine_root": ctx["engine_root"],
            "data_root": ctx["data_root"],
            "session_id": ctx.get("session_id"),
        },
        "connection_defaults": state.defaults_payload(),
        "active_run": {
            "run_id": active_run.get("run_id"),
            "title": active_run.get("title"),
            "goal": active_run.get("goal"),
            "status": active_run.get("status"),
            "session_id": active_run.get("session_id"),
            "interaction_mode": active_run.get("interaction_mode"),
            "session_mode": active_run.get("session_mode"),
        },
        "session_posture": session_posture,
        "kernel_posture": kernel_posture,
        "automation": automation_summary,
        "provenance": provenance_summary,
        "accepted_and_completed_quests": accepted_summary,
        "semantic_intake": semantic_summary,
        "governed_history": governed_summary,
        "derived_synthesis": synthesis_summary,
        "codex_packets": codex_packet_summary,
        "draftshot": draftshot_state,
        "snapshot_candidates": snapshot_candidates_state,
        "publication_candidates": publication_candidates_state,
        "onboarding": onboarding_payload,
        "published_project_model_summary": {
            "path": str(project_model_path) if project_model_path.exists() else None,
            "confirmed_at": project_model.get("confirmed_at"),
            "purpose": project_model.get("purpose"),
            "vision": project_model.get("vision"),
        } if project_model_path.exists() else None,
    }
    extras: dict[str, Any] = {
        "state": state_payload,
        "manifold": manifold_payload,
        "active_run_raw": active_run,
    }
    if include_rehydrate:
        extras["rehydrate_text"] = _text_or_empty(rehydrate_path)
    if include_project_story:
        story_path = canonical_project_story_path(data_root)
        extras["project_story_text"] = _text_or_empty(story_path)
    return ctx, {"context": bundle, **extras}


def build_session_digest(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None = None, style: str = "concise") -> tuple[dict[str, Any], dict[str, Any]]:
    ctx, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=True, include_project_story=False)
    manifold_payload = bundle["manifold"]
    onboarding_payload = bundle["context"]["onboarding"]
    accepted_summary = bundle["context"]["accepted_and_completed_quests"]
    semantic_summary = bundle["context"]["semantic_intake"]
    lines = [
        f"# Synapse Session Digest ({style})",
        "",
        f"- Subject: {ctx['subject']}",
        f"- Active run: {bundle['context']['active_run'].get('run_id') or 'none'}",
        f"- Session mode: {bundle['context']['session_posture'].get('active_session_mode') or 'none'}",
        f"- Accepted quest: {accepted_summary.get('current_accepted_quest_id') or 'none'}",
        f"- Provenance: {bundle['context']['provenance'].get('provenance_status') or 'unknown'}",
        f"- Trust blockers: {bundle['context']['provenance'].get('blocker_count')}",
        f"- Trust warnings: {bundle['context']['provenance'].get('warning_count')}",
        "- Trust note: clear means no current warnings or blockers under Phase 5 checks; it does not prove universal mediation.",
        f"- Open questions: {semantic_summary.get('open_question_count')}",
        f"- Blocking questions: {semantic_summary.get('blocking_question_count')}",
        f"- Onboarding state: {onboarding_payload.get('state') or 'none'}",
    ]
    if style == "expanded":
        lines.extend([
            "",
            "## Pending formalizations",
        ])
        pending = list(manifold_payload.get("pending_formalizations") or [])
        if pending:
            lines.extend(f"- {item}" for item in pending[:10])
        else:
            lines.append("- none")
        lines.extend(["", "## Rehydrate", bundle.get("rehydrate_text") or "(empty)"])
    digest = "\n".join(lines).rstrip() + "\n"
    return ctx, {
        "digest_markdown": digest,
        "current_session_mode": bundle["context"]["session_posture"].get("active_session_mode"),
        "provenance_summary": bundle["context"]["provenance"],
        "accepted_quest_summary": accepted_summary,
        "open_question_summary": semantic_summary,
        "onboarding_summary": onboarding_payload,
    }


def resource_catalog(*, state: ConnectionState) -> list[dict[str, Any]]:
    resources = [
        {"uri": "synapse://current/context.json", "mime_type": "application/json"},
        {"uri": "synapse://current/state.json", "mime_type": "application/json"},
        {"uri": "synapse://current/manifold.json", "mime_type": "application/json"},
        {"uri": "synapse://current/active-run.json", "mime_type": "application/json"},
        {"uri": "synapse://current/semantic-summary.json", "mime_type": "application/json"},
        {"uri": "synapse://current/semantic-events.json", "mime_type": "application/json"},
        {"uri": "synapse://current/plan-events.json", "mime_type": "application/json"},
        {"uri": "synapse://current/synthesis-summary.json", "mime_type": "application/json"},
        {"uri": "synapse://current/codex-packets.json", "mime_type": "application/json"},
        {"uri": "synapse://current/draftshot-state.json", "mime_type": "application/json"},
        {"uri": "synapse://current/snapshot-candidates.json", "mime_type": "application/json"},
        {"uri": "synapse://current/publication-candidates.json", "mime_type": "application/json"},
        {"uri": "synapse://current/rehydrate.md", "mime_type": "text/markdown"},
        {"uri": "synapse://current/open-questions.md", "mime_type": "text/markdown"},
        {"uri": "synapse://current/onboarding/status.json", "mime_type": "application/json"},
        {"uri": "synapse://current/provenance-status", "mime_type": "application/json"},
        {"uri": "synapse://current/provenance-anomalies", "mime_type": "application/json"},
    ]
    try:
        ctx = _resolve_runtime_context(
            state=state,
            context=None,
            allow_attach_current_repo=False,
            requires_session=False,
            repair_active_run_session_id=False,
            prepare_subject_state=False,
        )
    except BridgeFailure:
        return resources
    data_root = Path(ctx["data_root"])
    session = current_onboarding_session(
        subject=ctx["subject"],
        data_root=data_root,
        require_current=False,
        persist_pointer=False,
        ensure_scaffold=False,
    )
    if session and session.get("current_scan_id"):
        resources.append({"uri": "synapse://current/onboarding/scan.json", "mime_type": "application/json"})
    if session and session.get("analysis_brief_path") and Path(str(session["analysis_brief_path"])).exists():
        resources.append({"uri": "synapse://current/onboarding/brief.md", "mime_type": "text/markdown"})
    if session and session.get("current_draft_id"):
        resources.append({"uri": "synapse://current/onboarding/draft.json", "mime_type": "application/json"})
    if session and session.get("current_question_set_id"):
        resources.append({"uri": "synapse://current/onboarding/questions.json", "mime_type": "application/json"})
    if canonical_project_model_path(data_root).exists():
        resources.append({"uri": "synapse://current/project-model.json", "mime_type": "application/json"})
    if canonical_project_story_path(data_root).exists():
        resources.append({"uri": "synapse://current/project-story.md", "mime_type": "text/markdown"})
    if canonical_vision_path(data_root).exists():
        resources.append({"uri": "synapse://current/vision.md", "mime_type": "text/markdown"})
    if canonical_codex_current_path(data_root).exists():
        resources.append({"uri": "synapse://current/codex-current.md", "mime_type": "text/markdown"})
    if canonical_codex_future_path(data_root).exists():
        resources.append({"uri": "synapse://current/codex-future.md", "mime_type": "text/markdown"})
    publication_summary = publication_candidate_summary(data_root)
    if publication_summary.get("current_story_candidate_path"):
        resources.append({"uri": "synapse://current/publication-candidates/story.md", "mime_type": "text/markdown"})
    if publication_summary.get("current_vision_candidate_path"):
        resources.append({"uri": "synapse://current/publication-candidates/vision.md", "mime_type": "text/markdown"})
    if publication_summary.get("current_codex_candidate_paths"):
        resources.append({"uri": "synapse://current/publication-candidates/codex.md", "mime_type": "text/markdown"})
    return resources


def read_resource(*, state: ConnectionState, uri: str) -> tuple[dict[str, Any], str, str]:
    ctx = _resolve_runtime_context(
        state=state,
        context=None,
        allow_attach_current_repo=False,
        requires_session=False,
        repair_active_run_session_id=False,
        prepare_subject_state=False,
    )
    data_root = Path(ctx["data_root"])
    state_path, manifold_path, run_path, rehydrate_path = _current_subject_files(ctx)
    if uri == "synapse://current/context.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/state.json":
        return ctx, json.dumps(_json_file_or_empty(state_path), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/manifold.json":
        return ctx, json.dumps(_json_file_or_empty(manifold_path), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/active-run.json":
        return ctx, json.dumps(load_active_run_record(subject=ctx["subject"], data_root=data_root, ensure_scaffold=False), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/semantic-summary.json":
        return ctx, json.dumps(normalized_semantic_summary(data_root), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/semantic-events.json":
        payload = normalized_semantic_summary(data_root)
        return ctx, json.dumps(list(payload.get("recent_semantic_event_details") or []), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/plan-events.json":
        payload = normalized_semantic_summary(data_root)
        return ctx, json.dumps(list(payload.get("recent_plan_event_ids") or []), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/synthesis-summary.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"]["derived_synthesis"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/codex-packets.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"]["codex_packets"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/draftshot-state.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"]["draftshot"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/snapshot-candidates.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"]["snapshot_candidates"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/publication-candidates.json":
        _, bundle = build_current_context_bundle(state=state, context=None, include_rehydrate=False, include_project_story=False)
        return ctx, json.dumps(bundle["context"]["publication_candidates"], indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/publication-candidates/story.md":
        return ctx, load_publication_candidate_body(resolve_publication_candidate(data_root, "story")), "text/markdown"
    if uri == "synapse://current/publication-candidates/vision.md":
        return ctx, load_publication_candidate_body(resolve_publication_candidate(data_root, "vision")), "text/markdown"
    if uri == "synapse://current/publication-candidates/codex.md":
        return ctx, load_publication_candidate_body(resolve_publication_candidate(data_root, "codex")), "text/markdown"
    if uri == "synapse://current/rehydrate.md":
        return ctx, _text_or_empty(rehydrate_path), "text/markdown"
    if uri == "synapse://current/open-questions.md":
        return ctx, _text_or_empty(canonical_open_questions_path(data_root)), "text/markdown"
    if uri == "synapse://current/onboarding/status.json":
        payload = onboarding_status_payload(
            subject=ctx["subject"],
            data_root=data_root,
            persist_pointer=False,
            ensure_scaffold=False,
        )
        return ctx, json.dumps(payload, indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/provenance-status":
        payload = cli_runtime._current_provenance_summary(ctx)
        return ctx, json.dumps(payload, indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/provenance-anomalies":
        payload = cli_runtime._current_provenance_summary(ctx)
        return ctx, json.dumps(list(payload.get("recent_provenance_anomalies") or []), indent=2, sort_keys=True) + "\n", "application/json"

    session = current_onboarding_session(
        subject=ctx["subject"],
        data_root=data_root,
        require_current=False,
        persist_pointer=False,
        ensure_scaffold=False,
    )
    if uri == "synapse://current/onboarding/scan.json" and session and session.get("current_scan_id"):
        scan_path = data_root / ".synapse" / "ONBOARDING" / "SCANS" / f"SCAN__{session['current_scan_id']}.yaml"
        return ctx, json.dumps(_json_file_or_empty(scan_path), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/onboarding/brief.md" and session and session.get("analysis_brief_path"):
        return ctx, _text_or_empty(Path(str(session["analysis_brief_path"]))), "text/markdown"
    if uri == "synapse://current/onboarding/draft.json" and session and session.get("current_draft_id"):
        draft_path = onboarding_draft_path(data_root, str(session["current_draft_id"]))
        return ctx, json.dumps(_json_file_or_empty(draft_path), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/onboarding/questions.json" and session and session.get("current_question_set_id"):
        questions_path = onboarding_question_set_path(data_root, str(session["current_question_set_id"]))
        return ctx, json.dumps(_json_file_or_empty(questions_path), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/project-model.json" and canonical_project_model_path(data_root).exists():
        return ctx, json.dumps(_json_file_or_empty(canonical_project_model_path(data_root)), indent=2, sort_keys=True) + "\n", "application/json"
    if uri == "synapse://current/project-story.md" and canonical_project_story_path(data_root).exists():
        return ctx, _text_or_empty(canonical_project_story_path(data_root)), "text/markdown"
    if uri == "synapse://current/vision.md" and canonical_vision_path(data_root).exists():
        return ctx, _text_or_empty(canonical_vision_path(data_root)), "text/markdown"
    if uri == "synapse://current/codex-current.md" and canonical_codex_current_path(data_root).exists():
        return ctx, _text_or_empty(canonical_codex_current_path(data_root)), "text/markdown"
    if uri == "synapse://current/codex-future.md" and canonical_codex_future_path(data_root).exists():
        return ctx, _text_or_empty(canonical_codex_future_path(data_root)), "text/markdown"
    raise BridgeFailure(code="CONTEXT_RESOLUTION_FAILED", message=f"Unknown or unavailable resource: {uri}")


def bootstrap_session(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, session_mode: str | None, title: str | None, goal: str | None, plan_items: list[str], adopt_current_repo: bool) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any] | None]:
    ctx = _resolve_runtime_context(
        state=state,
        context=context,
        allow_attach_current_repo=adopt_current_repo,
        requires_session=False,
        generate_session=True,
        require_allow_switch_for_default_change=True,
    )
    active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    target_mode = session_mode or SessionMode.BRAINSTORM_SPEC.value
    created_subject = bool(ctx.get("auto_initialized"))
    created_run = False
    transitioned_mode = False
    status = STATUS_OK
    event_info: dict[str, Any] | None = None
    onboarding_bootstrap: dict[str, Any] | None = None

    if adopt_current_repo:
        mark_adopted_existing_repo(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
        readiness = cli_runtime._readiness_payload(Path(ctx["data_root"]))
        if readiness.get("onboarding_required"):
            prior_run_id = str(active_run.get("run_id") or "").strip() or None
            onboarding_bootstrap, event_info = cli_runtime._run_onboarding_bootstrap(
                ctx=ctx,
                allow_switch_for_run=True,
            )
            active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
            current_run_id = str(active_run.get("run_id") or "").strip() or None
            created_run = bool(current_run_id) and current_run_id != prior_run_id
            transitioned_mode = (
                str(active_run.get("session_mode") or "").strip()
                == SessionMode.ONBOARDING_EXISTING_REPO.value
            )
            if not _event_is_partial(event_info):
                state.update_after_bootstrap(
                    subject=ctx["subject"],
                    engine_root=ctx["engine_root"],
                    data_root=ctx["data_root"],
                    session_id=ctx.get("session_id") or active_run.get("session_id"),
                )
            current_ctx, bundle = build_current_context_bundle(
                state=state,
                context=ctx if _event_is_partial(event_info) else None,
            )
            data = {
                "created_subject": created_subject,
                "created_run": created_run,
                "transitioned_mode": transitioned_mode,
                "current_context": bundle["context"],
                "onboarding_bootstrap": onboarding_bootstrap,
            }
            return current_ctx, data, status, event_info

    if active_run.get("run_id"):
        current_mode = str(active_run.get("session_mode") or "").strip()
        if current_mode == target_mode:
            status = STATUS_NOOP
        else:
            if not _context_dict(context).get("allow_switch"):
                raise BridgeFailure(
                    code="POSTURE_TRANSITION_BLOCKED",
                    status=STATUS_BLOCKED,
                    message=(
                        f"Active run is already in session mode '{current_mode}'. bootstrap_session will not switch it implicitly."
                    ),
                    recovery_hint="Retry with context.allow_switch=true or use transition_session_mode explicitly.",
                    data={"active_run_id": active_run.get("run_id"), "active_session_mode": current_mode},
                )
            transition = cli_runtime._set_active_run_session_mode(
                ctx=ctx,
                active_run=active_run,
                target_mode=SessionMode(target_mode),
                reason="MCP bootstrap_session posture switch.",
                source="mcp_bootstrap_session",
            )
            transitioned_mode = bool(transition.get("changed"))
            event_info = {
                "runtime_status": transition.get("runtime_status"),
                "event": transition.get("event"),
                "reducer": transition.get("reducer"),
            }
            active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    else:
        result = cli_runtime._start_or_resume_session_run(
            ctx,
            title=title or cli_runtime._default_session_title(ctx),
            goal=goal,
            items=list(plan_items or []),
            command_name="session-start",
            requested_session_mode=target_mode,
        )
        created_run = not bool(result.get("resumed"))
        session_id = cli_runtime._effective_session_id(ctx, session_id=result.get("session_id"))
        event_info = cli_runtime._event_pipeline(
            ctx=ctx,
            action_name="session-start",
            summary=f"Started or resumed session run: {result.get('title') or ctx['subject']}",
            session_id=session_id,
            signals={
                "run_id": result.get("run_id"),
                "run_title": result.get("title"),
                "run_goal": result.get("goal"),
                "plan_items": cli_runtime._compact_plan_items(result.get("items")),
                "resumed": bool(result.get("resumed")),
                "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
                "related_quest_ids": [],
                "related_sidequest_ids": [],
                "changed_files": [],
                "verification_entries": [],
                **session_mode_signal_fields(result),
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "run_path": result.get("run_path"),
                "resumed": bool(result.get("resumed")),
            },
        )
        cli_runtime._write_session_overlay(ctx, result, session_id=session_id)
        active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))

    if not _event_is_partial(event_info):
        state.update_after_bootstrap(
            subject=ctx["subject"],
            engine_root=ctx["engine_root"],
            data_root=ctx["data_root"],
            session_id=ctx.get("session_id") or active_run.get("session_id"),
        )
    current_ctx, bundle = build_current_context_bundle(
        state=state,
        context=ctx if _event_is_partial(event_info) else None,
    )
    data = {
        "created_subject": created_subject,
        "created_run": created_run,
        "transitioned_mode": transitioned_mode,
        "current_context": bundle["context"],
    }
    return current_ctx, data, status, event_info


def transition_session_mode(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, target_mode: str, reason: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any] | None]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        raise BridgeFailure(code="ACTIVE_RUN_REQUIRED", message="transition_session_mode requires an active run.", recovery_hint="Run bootstrap_session first.")
    current_mode = str(active_run.get("session_mode") or "").strip()
    target = SessionMode(target_mode)
    result = cli_runtime._set_active_run_session_mode(
        ctx=ctx,
        active_run=active_run,
        target_mode=target,
        reason=reason,
        source="mcp_transition_session_mode",
    )
    payload = cli_runtime._session_mode_payload(ctx)
    payload["changed"] = bool(result.get("changed"))
    payload["from_session_mode"] = current_mode or None
    payload["to_session_mode"] = target.value
    payload["run_path"] = result.get("run_path")
    event_info = None
    if result.get("event") or result.get("runtime_status"):
        event_info = {
            "event": result.get("event"),
            "reducer": result.get("reducer"),
            "runtime_status": result.get("runtime_status"),
        }
    return ctx, payload, STATUS_OK if result.get("changed") else STATUS_NOOP, event_info


def record_activity(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, summary: str, title: str | None, goal: str | None, plan_items: list[str], commands: list[str], files: list[str], notes: list[str], discoveries: list[str], verifications: list[str], related_quest_ids: list[str], related_sidequest_ids: list[str], status: str | None, decision: dict[str, Any] | None, capture_git: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        raise BridgeFailure(
            code="ACTIVE_RUN_REQUIRED",
            message="record_activity requires an active run and will not create a hidden run.",
            recovery_hint="Call bootstrap_session first.",
        )
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run)
    files_touched = list(files or [])
    if capture_git:
        engine_root = Path(ctx["engine_root"])
        files_touched.extend(cli_runtime._git_status_changed_files(engine_root))
    merged_notes = list(notes or []) + list(discoveries or [])
    result = run_update(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        add_items=list(plan_items or []),
        status_updates=[],
        commands=list(commands or []),
        files_touched=files_touched,
        notes=merged_notes,
        verification=list(verifications or []),
        related_sidequests=list(related_sidequest_ids or []),
        related_quests=list(related_quest_ids or []),
        status=status,
        summary=summary,
    )
    decision_result = None
    if decision:
        decision_result = log_decision(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            title=str(decision.get("title") or ""),
            summary=str(decision.get("summary") or ""),
            why=str(decision.get("why") or "") or None,
            constraints=[],
            tradeoffs=[],
            related_runs=[str(result.get("run_id") or "")],
            related_quests=list(related_quest_ids or []),
        )
    automation = cli_runtime._execute_automation_side_effects(
        ctx=ctx,
        active_run=active_run,
        activity_source="mcp",
        activity_kind="record-activity",
        summary=summary,
        changed_files=list(files_touched),
        notes=list(merged_notes),
        decision_boundary=bool(decision),
        explicit_decision_logged=bool(decision_result),
    )
    signals = {
        "run_id": result.get("run_id"),
        "plan_items": cli_runtime._compact_plan_items(plan_items),
        "commands": list(commands or []),
        "changed_files": list(files_touched),
        "notes": list(merged_notes),
        "discoveries": list(merged_notes),
        "decisions": [decision.get("title")] if decision else [],
        "run_summary": summary,
        "run_status": status,
        "verification_entries": list(verifications or []),
        "decision_titles": [decision.get("title")] if decision else [],
        "related_quest_ids": list(related_quest_ids or []),
        "related_sidequest_ids": list(related_sidequest_ids or []),
        "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
        **cli_runtime._current_session_mode_fields(ctx),
    }
    outputs = {
        "run_id": result.get("run_id"),
        "run_path": result.get("run_path"),
        "discoveries_path": result.get("discoveries_path"),
        "decision_path": decision_result.get("decision_path") if decision_result else None,
        "decisions_ledger_path": decision_result.get("decisions_ledger_path") if decision_result else None,
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "verification_present": bool(verifications),
        "uncertainty_present": False,
    }
    cli_runtime._apply_automation_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        automation=automation,
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="session-tick",
        summary=summary,
        session_id=session_id,
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = cli_runtime._apply_automation_partial_status(event_info=event_info, automation=automation)
    cli_runtime._write_session_overlay(ctx, result, session_id=session_id)
    payload = {
        "run_update": result,
        "decision": decision_result,
        "automation": automation,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
        "rehydrate": event_info.get("reducer", {}).get("rehydrate"),
        "continuity": event_info.get("reducer", {}).get("continuity"),
    }
    return ctx, payload, event_info


def record_decision(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, title: str, summary: str, why: str | None, constraints: list[str], tradeoffs: list[str], related_run_ids: list[str], related_quest_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run)
    result = log_decision(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        title=title,
        summary=summary,
        why=why,
        constraints=list(constraints or []),
        tradeoffs=list(tradeoffs or []),
        related_runs=list(related_run_ids or []),
        related_quests=list(related_quest_ids or []),
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="log-decision",
        summary=summary,
        session_id=session_id,
        signals={
            "decision_title": title,
            "decisions": [title],
            "notes": [why] if why else [],
            "decision_constraints": list(constraints or []),
            "decision_tradeoffs": list(tradeoffs or []),
            "related_quest_ids": list(related_quest_ids or []),
            "related_sidequest_ids": [],
            "changed_files": [result.get("decision_path")] if result.get("decision_path") else [],
            "verification_entries": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "decision_path": result.get("decision_path"),
            "decisions_ledger_path": result.get("decisions_ledger_path"),
        },
    )
    payload = dict(result)
    payload.update({
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
        "rehydrate": event_info.get("reducer", {}).get("rehydrate"),
        "continuity": event_info.get("reducer", {}).get("continuity"),
    })
    return ctx, payload, event_info


def record_disclosure(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, trigger: str, expected: str, provable: str, status_labels: list[str], impact: str, safe_options: list[str], decision_needed: str, related_run_ids: list[str], related_quest_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run)
    result = log_disclosure(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        trigger=trigger,
        expected=expected,
        provable=provable,
        status_labels=list(status_labels or []),
        impact=impact,
        safe_options=list(safe_options or []),
        decision_needed=decision_needed,
        related_runs=list(related_run_ids or []),
        related_quests=list(related_quest_ids or []),
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="log-disclosure",
        summary=impact,
        session_id=session_id,
        signals={
            "disclosure_trigger": trigger,
            "disclosures": [trigger],
            "notes": [value for value in [expected, provable, decision_needed, *(safe_options or [])] if str(value).strip()],
            "status_labels": list(status_labels or []),
            "safe_options": list(safe_options or []),
            "related_quest_ids": list(related_quest_ids or []),
            "related_sidequest_ids": [],
            "changed_files": [result.get("disclosure_path")] if result.get("disclosure_path") else [],
            "verification_entries": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
            "disclosure_open": True,
        },
        outputs={
            "disclosure_path": result.get("disclosure_path"),
            "disclosures_ledger_path": result.get("disclosures_ledger_path"),
        },
    )
    payload = dict(result)
    payload.update({
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
        "rehydrate": event_info.get("reducer", {}).get("rehydrate"),
        "continuity": event_info.get("reducer", {}).get("continuity"),
    })
    return ctx, payload, event_info


def capture_chunk(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, text: str, captures: dict[str, Any], title: str | None, source_role: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=True)
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        raise BridgeFailure(code="ACTIVE_RUN_REQUIRED", message="capture_chunk requires an active run.", recovery_hint="Call bootstrap_session first.")
    if not active_run.get("session_mode"):
        raise BridgeFailure(code="CONTEXT_RESOLUTION_FAILED", message="capture_chunk requires an active session posture.", recovery_hint="Call bootstrap_session first.")
    source_role_value = normalize_capture_source_role(source_role)
    receipt = write_capture_batch(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        run_data=active_run,
        raw_text=text,
        payload=captures,
        source_role=source_role_value,
        title_override=title,
    )
    capture_batch = receipt["batch"]
    capture_ids = [str(item.get("capture_id")) for item in capture_batch.get("captures") or [] if str(item.get("capture_id") or "").strip()]
    capture_signal = AmbientSignal(
        source="capture-chunk",
        subject=ctx["subject"],
        title=str(title or capture_batch.get("title") or "Semantic capture batch"),
        summary=f"Recorded {len(capture_ids)} semantic captures.",
        notes=tuple(str(item.get("summary") or "").strip() for item in capture_batch.get("captures") or [] if isinstance(item, dict) and str(item.get("summary") or "").strip()),
        status="captured",
    )
    try:
        sidecar = _sync_sidecar(
            subject=ctx["subject"],
            data_root=data_root,
            active_run=active_run,
            signal=capture_signal,
            semantic_capture_batch=capture_batch,
            mutate_proposals=True,
        )
    except (LiveMemoryError, SemanticIntakeError) as exc:
        event_info = cli_runtime._partial_after_primary_mutation(
            error_code="THREAD_CONFLICT",
            error_message=str(exc),
            recovery_hint=(
                "Raw capture truth was written, but semantic projection failed before the event append. Repair the projection conflict, then rerun refresh_continuity."
            ),
        )
        payload = {
            "capture_batch_id": capture_batch.get("capture_batch_id"),
            "capture_artifact_path": receipt["artifact_path"],
            "capture_ledger_path": receipt["ledger_path"],
            "capture_ids": capture_ids,
            "open_questions_path": None,
            "proposal_paths": [],
            "written_artifacts": [receipt["artifact_path"], receipt["ledger_path"]],
        }
        return ctx, payload, event_info

    proposal_paths = list(sidecar.get("proposal_paths") or [])
    open_questions_path = sidecar.get("open_questions_path")
    written_artifacts = [receipt["artifact_path"], receipt["ledger_path"]]
    if open_questions_path:
        written_artifacts.append(str(open_questions_path))
    written_artifacts.extend(proposal_paths)
    automation = cli_runtime._execute_automation_side_effects(
        ctx=ctx,
        active_run=active_run,
        activity_source="mcp",
        activity_kind="capture-chunk",
        summary=str(title or capture_batch.get("title") or "Recorded semantic capture batch."),
        notes=[
            str(item.get("summary") or "").strip()
            for item in capture_batch.get("captures") or []
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ],
        uncertainty_present=batch_uncertainty_present(capture_batch),
        explicit_capture_written=True,
    )
    signals = {
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_count": len(capture_ids),
        "capture_kinds": semantic_capture_kinds(capture_batch),
        "capture_source_role": source_role_value.value,
        "changed_files": written_artifacts,
        "verification_entries": [],
        "related_quest_ids": [],
        "related_sidequest_ids": [],
        **session_mode_signal_fields(active_run),
    }
    outputs = {
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_artifact_path": receipt["artifact_path"],
        "capture_ledger_path": receipt["ledger_path"],
        "open_questions_path": open_questions_path,
        "proposal_paths": proposal_paths,
        "written_artifacts": written_artifacts,
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "uncertainty_present": batch_uncertainty_present(capture_batch),
        "disclosure_open": batch_disclosure_needed(capture_batch),
    }
    cli_runtime._apply_automation_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        automation=automation,
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="capture-chunk",
        summary=str(title or capture_batch.get("title") or "Recorded semantic capture batch."),
        session_id=cli_runtime._effective_session_id(ctx, active_run=active_run),
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = cli_runtime._apply_automation_partial_status(event_info=event_info, automation=automation)
    payload = {
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_artifact_path": receipt["artifact_path"],
        "capture_ledger_path": receipt["ledger_path"],
        "capture_ids": capture_ids,
        "open_questions_path": open_questions_path,
        "proposal_paths": proposal_paths,
        "written_artifacts": written_artifacts,
        "sidecar": sidecar,
        "automation": automation,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
        "rehydrate": event_info.get("reducer", {}).get("rehydrate"),
        "continuity": event_info.get("reducer", {}).get("continuity"),
    }
    return ctx, payload, event_info


def run_repo_onboarding_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, depth: str, rescan: bool, restart: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(
        state=state,
        context=context,
        allow_attach_current_repo=True,
        requires_session=False,
        generate_session=True,
        require_allow_switch_for_default_change=True,
    )
    mark_adopted_existing_repo(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    active_run, session_id = cli_runtime._require_onboarding_context(
        ctx=ctx,
        action_name="run_repo_onboarding",
        allow_create_onboard_run=True,
        allow_replace_onboard_run=bool(_context_dict(context).get("allow_switch")),
    )
    result = onboard_repo(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        engine_root=Path(ctx["engine_root"]),
        active_run=active_run,
        depth=depth,
        rescan=bool(rescan),
        restart=bool(restart),
    )
    if result.get("resumed_existing") or result.get("already_completed"):
        state.update_after_onboarding(
            subject=ctx["subject"],
            engine_root=ctx["engine_root"],
            data_root=ctx["data_root"],
            session_id=session_id,
        )
        status_payload = onboarding_status_payload(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
        data = {
            "onboarding_status": status_payload,
            "analysis_brief_resource_uri": "synapse://current/onboarding/brief.md" if status_payload.get("analysis_brief_path") else None,
            "scan_resource_uri": "synapse://current/onboarding/scan.json" if status_payload.get("current_scan_id") else None,
            "current_question_set_resource_uri": "synapse://current/onboarding/questions.json" if status_payload.get("current_question_set_id") else None,
        }
        return ctx, data, None, STATUS_NOOP

    written_artifacts = [
        str(item)
        for item in [
            result.get("session_path"),
            result.get("pointer_path"),
            result.get("scan_artifact_path"),
            result.get("analysis_brief_path"),
        ]
        if str(item or "").strip()
    ]
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="onboard-repo",
        summary=f"Prepared onboarding scan {result.get('scan_id')} for {ctx['subject']}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "scan_id": result.get("scan_id"),
            "changed_files": written_artifacts,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "scan_id": result.get("scan_id"),
            "scan_artifact_path": result.get("scan_artifact_path"),
            "analysis_brief_path": result.get("analysis_brief_path"),
            "session_path": result.get("session_path"),
            "pointer_path": result.get("pointer_path"),
        },
    )
    status_payload = onboarding_status_payload(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    if not _event_is_partial(event_info):
        state.update_after_onboarding(
            subject=ctx["subject"],
            engine_root=ctx["engine_root"],
            data_root=ctx["data_root"],
            session_id=session_id,
        )
    data = {
        "onboarding_status": status_payload,
        "analysis_brief_resource_uri": "synapse://current/onboarding/brief.md",
        "scan_resource_uri": "synapse://current/onboarding/scan.json",
        "current_question_set_resource_uri": "synapse://current/onboarding/questions.json" if status_payload.get("current_question_set_id") else None,
    }
    return ctx, data, event_info, STATUS_OK


def submit_onboarding_draft(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, draft_model: dict[str, Any], question_set: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=True)
    active_run, session_id = cli_runtime._require_onboarding_context(ctx=ctx, action_name="submit_onboarding_draft")
    session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
    if not session:
        raise BridgeFailure(code="ONBOARDING_STATE_BLOCKED", message="No current onboarding session exists.")
    result = onboarding_update(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        session=session,
        draft_payload=draft_model,
        questions_payload=question_set,
    )
    written_artifacts = [str(item) for item in [result.get("draft_path"), result.get("question_set_path"), result.get("delta_path")] if str(item or "").strip()]
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="onboarding-update",
        summary=f"Updated onboarding draft {result.get('draft_revision_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "draft_revision_id": result.get("draft_revision_id"),
            "question_set_id": result.get("question_set_id"),
            "changed_files": written_artifacts,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "draft_revision_id": result.get("draft_revision_id"),
            "question_set_id": result.get("question_set_id"),
            "revision_delta_id": result.get("revision_delta_id"),
            "draft_path": result.get("draft_path"),
            "question_set_path": result.get("question_set_path"),
            "delta_path": result.get("delta_path"),
        },
    )
    payload = {
        "onboarding_id": result.get("onboarding_id"),
        "revision_id": result.get("draft_revision_id"),
        "question_set_id": result.get("question_set_id"),
        "draft_is_stale": bool(result.get("draft_is_stale")),
        "draft_resource_uri": "synapse://current/onboarding/draft.json",
        "questions_resource_uri": "synapse://current/onboarding/questions.json",
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, payload, event_info


def submit_onboarding_responses(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, text: str, captures: dict[str, Any], title: str | None, source_role: str, linked_question_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=True)
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    active_run, session_id = cli_runtime._require_onboarding_context(ctx=ctx, action_name="submit_onboarding_responses")
    session = current_onboarding_session(subject=ctx["subject"], data_root=data_root, require_current=True)
    if not session:
        raise BridgeFailure(code="ONBOARDING_STATE_BLOCKED", message="No current onboarding session exists.")
    result = onboarding_respond(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        session=session,
        active_run=active_run,
        raw_text=text,
        payload=captures,
        title=title,
        source_role=normalize_capture_source_role(source_role).value,
        linked_question_ids=list(linked_question_ids or []),
    )
    sidecar = _sync_sidecar(
        subject=ctx["subject"],
        data_root=data_root,
        active_run=active_run,
        signal=AmbientSignal(
            source="onboarding-respond",
            subject=ctx["subject"],
            title=str(title or "Onboarding clarification"),
            summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
            status="captured",
        ),
        semantic_capture_batch=result["batch"],
        mutate_proposals=False,
    )
    written_artifacts = [result.get("capture_artifact_path"), result.get("capture_ledger_path")]
    if sidecar.get("open_questions_path"):
        written_artifacts.append(sidecar.get("open_questions_path"))
    automation = cli_runtime._execute_automation_side_effects(
        ctx=ctx,
        active_run=active_run,
        activity_source="onboarding_response",
        activity_kind="onboarding-respond",
        summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
        notes=[
            str(item.get("summary") or "").strip()
            for item in result["batch"].get("captures") or []
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ],
        uncertainty_present=batch_uncertainty_present(result["batch"]),
        explicit_capture_written=True,
        onboarding_response=True,
    )
    signals = {
        "run_id": active_run.get("run_id"),
        "onboarding_id": result.get("onboarding_id"),
        "question_set_id": session.get("current_question_set_id"),
        "capture_batch_id": result.get("capture_batch_id"),
        "linked_question_ids": list(result.get("linked_question_ids") or []),
        "changed_files": [str(item) for item in written_artifacts if str(item or "").strip()],
        "verification_entries": [],
        "related_quest_ids": [],
        "related_sidequest_ids": [],
        **session_mode_signal_fields(active_run),
    }
    outputs = {
        "onboarding_id": result.get("onboarding_id"),
        "capture_batch_id": result.get("capture_batch_id"),
        "capture_artifact_path": result.get("capture_artifact_path"),
        "capture_ledger_path": result.get("capture_ledger_path"),
        "linked_question_ids": list(result.get("linked_question_ids") or []),
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "uncertainty_present": True,
    }
    cli_runtime._apply_automation_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        automation=automation,
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="onboarding-respond",
        summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
        session_id=session_id,
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = cli_runtime._apply_automation_partial_status(event_info=event_info, automation=automation)
    payload = {
        "onboarding_id": result.get("onboarding_id"),
        "capture_batch_id": result.get("capture_batch_id"),
        "capture_artifact_path": result.get("capture_artifact_path"),
        "capture_ledger_path": result.get("capture_ledger_path"),
        "linked_question_ids": list(result.get("linked_question_ids") or []),
        "automation": automation,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, payload, event_info


def confirm_onboarding_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, confirm: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not confirm:
        raise BridgeFailure(code="ONBOARDING_STATE_BLOCKED", message="confirm_onboarding requires confirm=true.")
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=True)
    active_run, session_id = cli_runtime._require_onboarding_context(ctx=ctx, action_name="confirm_onboarding")
    session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
    if not session:
        raise BridgeFailure(code="ONBOARDING_STATE_BLOCKED", message="No current onboarding session exists.")
    result = onboarding_confirm(subject=ctx["subject"], data_root=Path(ctx["data_root"]), session=session, active_run=active_run)
    written_artifacts = [
        result.get("published_project_model_path"),
        result.get("published_project_story_path"),
        result.get("published_vision_path"),
        result.get("published_codex_current_path"),
        result.get("published_codex_future_path"),
        result.get("publication_receipt_path"),
        *list(result.get("proposal_paths") or []),
    ]
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="onboarding-confirm",
        summary=f"Confirmed onboarding session {result.get('onboarding_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "publication_receipt_path": result.get("publication_receipt_path"),
            "changed_files": [str(item) for item in written_artifacts if str(item or "").strip()],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "publication_receipt_path": result.get("publication_receipt_path"),
            "published_project_model_path": result.get("published_project_model_path"),
            "published_project_story_path": result.get("published_project_story_path"),
            "published_vision_path": result.get("published_vision_path"),
            "published_codex_current_path": result.get("published_codex_current_path"),
            "published_codex_future_path": result.get("published_codex_future_path"),
            "compile_status": result.get("compile_status"),
            "compiled_current_state_path": result.get("compiled_current_state_path"),
            "proposal_paths": list(result.get("proposal_paths") or []),
        },
    )
    if str(result.get("compile_status") or "").lower() != "ok":
        event_info = cli_runtime._apply_follow_on_partial_status(
            event_info=event_info,
            error_code="POST_PUBLICATION_TRUTH_COMPILE_FAILED",
            error_message=str(
                result.get("compile_error_message")
                or "Canonical onboarding publications were written, but post-publication truth compile did not complete successfully."
            ),
            recovery_hint=(
                "Onboarding publications are already written. Repair the truth-compile path and rerun compile_current_state."
            ),
        )
    truth_compile = result.get("truth_compile")
    payload = {
        "published_project_model_resource_uri": "synapse://current/project-model.json",
        "published_project_story_resource_uri": "synapse://current/project-story.md",
        "published_vision_resource_uri": "synapse://current/vision.md",
        "published_codex_current_resource_uri": "synapse://current/codex-current.md",
        "published_codex_future_resource_uri": "synapse://current/codex-future.md",
        "seeded_proposal_summary": {
            "proposal_paths": list(result.get("proposal_paths") or []),
            "proposal_count": len(list(result.get("proposal_paths") or [])),
        },
        "truth_compile": truth_compile,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, payload, event_info


def abandon_onboarding_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, reason: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    abandon_reason = str(reason or "").strip() or "Abandoned via MCP."
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=True)
    active_run, session_id = cli_runtime._require_onboarding_context(ctx=ctx, action_name="abandon_onboarding")
    session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
    if not session:
        raise BridgeFailure(code="ONBOARDING_STATE_BLOCKED", message="No current onboarding session exists.")
    result = onboarding_abandon(subject=ctx["subject"], data_root=Path(ctx["data_root"]), session=session, reason=abandon_reason)
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="onboarding-abandon",
        summary=f"Abandoned onboarding session {result.get('onboarding_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "changed_files": [result.get("session_path"), result.get("pointer_path")],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "session_path": result.get("session_path"),
            "pointer_path": result.get("pointer_path"),
        },
    )
    payload = dict(result)
    payload.update({"event": event_info.get("event"), "reducer": event_info.get("reducer")})
    return ctx, payload, event_info


def list_formalization_candidates_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, proposal_kind: str | None, limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    kind_filter = ProposalKind(proposal_kind) if proposal_kind else None
    proposals = list_proposals(data_root=Path(ctx["data_root"]), kind=kind_filter)
    proposals = proposals[: max(0, int(limit))]
    return ctx, {"proposals": proposals}


def formalize_candidate_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    proposal_id: str | None,
    candidate_handle: str | None,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    data_root = Path(ctx["data_root"])
    if bool(str(proposal_id or "").strip()) == bool(str(candidate_handle or "").strip()):
        raise BridgeFailure(
            code="FORMALIZATION_INPUT_INVALID",
            message="Provide exactly one of proposal_id or candidate_handle.",
        )
    if dry_run:
        return (
            ctx,
            cli_runtime._formalize_candidate_dry_run(
                ctx,
                proposal_id,
                candidate_handle=candidate_handle,
            ),
            None,
            STATUS_OK,
        )
    if proposal_id:
        proposal = cli_runtime._proposal_by_id(data_root, proposal_id)
        kind = ProposalKind(str(proposal.get("kind")))
    active_run, session_policy = cli_runtime._active_session_policy(ctx)
    if session_policy is not None and not session_policy.manual_formalize_allowed:
        raise BridgeFailure(
            code="FORMALIZATION_BLOCKED",
            status=STATUS_BLOCKED,
            message=f"Session posture '{active_run.get('session_mode')}' blocks formalize.",
            recovery_hint="Transition session posture first.",
            data={"active_run_id": active_run.get("run_id"), "active_session_mode": active_run.get("session_mode")},
        )
    payload = cli_runtime._formalize_candidate_mutation(
        ctx,
        proposal_id,
        candidate_handle=candidate_handle,
        active_run=active_run,
    )
    event_info = {"event": payload.get("event"), "reducer": payload.get("reducer")}
    return ctx, payload, event_info, STATUS_OK


def accept_quest_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, quest_id: str | None, quest_path: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run, session_policy = cli_runtime._active_session_policy(ctx)
    if session_policy is not None and not session_policy.quest_acceptance_allowed:
        raise BridgeFailure(
            code="QUEST_ACCEPTANCE_BLOCKED",
            status=STATUS_BLOCKED,
            message=f"Session posture '{active_run.get('session_mode')}' blocks accept_quest.",
            recovery_hint="Transition session posture first.",
            data={"active_run_id": active_run.get("run_id"), "active_session_mode": active_run.get("session_mode")},
        )
    quest_ref = quest_path or quest_id
    payload = cli_runtime._accept_quest_mutation(ctx, str(quest_ref), active_run=active_run)
    event_info = {"event": payload.get("event"), "reducer": payload.get("reducer")}
    return ctx, payload, event_info


def complete_quest_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    quest_id: str | None,
    quest_path: str | None,
    milestone_statuses: list[str],
    checks: list[str],
    commands_run: list[str],
    changed_files: list[str],
    receipt_refs: list[str],
    skipped_items: list[str],
    unresolved_gaps: list[str],
    known_bugs: list[str],
    blockers: list[str],
    disclosures: list[str],
    notes: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run, session_policy = cli_runtime._active_session_policy(ctx)
    if session_policy is not None and "complete-quest" in session_policy.blocked_mutation_commands:
        raise BridgeFailure(
            code="QUEST_COMPLETION_BLOCKED",
            status=STATUS_BLOCKED,
            message=f"Session posture '{active_run.get('session_mode')}' blocks complete_quest.",
            recovery_hint="Transition session posture first.",
            data={"active_run_id": active_run.get("run_id"), "active_session_mode": active_run.get("session_mode")},
        )
    quest_ref = quest_path or quest_id
    payload = cli_runtime._complete_quest_mutation(
        ctx,
        str(quest_ref),
        milestone_entries=list(milestone_statuses or []),
        check_entries=list(checks or []),
        commands_run=list(commands_run or []),
        changed_files=list(changed_files or []),
        receipt_refs=list(receipt_refs or []),
        skipped_items=list(skipped_items or []),
        unresolved_gaps=list(unresolved_gaps or []),
        known_bugs=list(known_bugs or []),
        blockers=list(blockers or []),
        disclosures=list(disclosures or []),
        notes=list(notes or []),
        active_run=active_run,
    )
    event_info = {"event": payload.get("event"), "reducer": payload.get("reducer")}
    return ctx, payload, event_info


def plan_quests_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    items: list[str],
    title: str | None,
    goal: str | None,
    coherent_outcome: str | None,
    closure_statement: str | None,
    split_triggers: list[str],
    separate_outcomes: list[str],
    dependencies: list[str],
    out_of_scope: str | None,
    verification_plan: str | None,
    guild_orders_ref: str | None,
    dungeon_ref: str | None,
    dungeon_coverage: str,
    plan_id: str | None,
    priority: str,
    risk: str,
    change_class: str,
    vision_delta: str,
    door_impact: str,
    testing_level: str,
    origin: str | None,
    anchors: list[str],
    constraints: list[str],
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    if dry_run:
        payload = cli_runtime._plan_quests_payload(
            ctx,
            items=list(items or []),
            title=title,
            goal=goal,
            coherent_outcome=coherent_outcome,
            closure_statement=closure_statement,
            split_triggers=list(split_triggers or []),
            separate_outcomes=list(separate_outcomes or []),
            dependencies=list(dependencies or []),
            out_of_scope=out_of_scope,
            verification_plan=verification_plan,
            guild_orders_ref=guild_orders_ref,
            dungeon_ref=dungeon_ref,
            dungeon_coverage=dungeon_coverage,
            plan_id=plan_id,
            priority=priority,
            risk=risk,
            change_class=change_class,
            vision_delta=vision_delta,
            door_impact=door_impact,
            testing_level=testing_level,
            origin=origin,
            anchors=list(anchors or []),
            constraints=list(constraints or []),
            deprecated_alias=False,
            dry_run=True,
        )
        return ctx, payload, None
    active_run = cli_runtime._active_session_policy(ctx)[0]
    payload = cli_runtime._plan_quests_mutation(
        ctx,
        items=list(items or []),
        title=title,
        goal=goal,
        coherent_outcome=coherent_outcome,
        closure_statement=closure_statement,
        split_triggers=list(split_triggers or []),
        separate_outcomes=list(separate_outcomes or []),
        dependencies=list(dependencies or []),
        out_of_scope=out_of_scope,
        verification_plan=verification_plan,
        guild_orders_ref=guild_orders_ref,
        dungeon_ref=dungeon_ref,
        dungeon_coverage=dungeon_coverage,
        plan_id=plan_id,
        priority=priority,
        risk=risk,
        change_class=change_class,
        vision_delta=vision_delta,
        door_impact=door_impact,
        testing_level=testing_level,
        origin=origin,
        anchors=list(anchors or []),
        constraints=list(constraints or []),
        deprecated_alias=False,
        active_run=active_run,
    )
    event_info = {"event": payload.get("event"), "reducer": payload.get("reducer")}
    return ctx, payload, event_info


def get_provenance_status_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, strict: bool) -> tuple[dict[str, Any], dict[str, Any], str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    summary = cli_runtime._current_provenance_summary(ctx)
    status = STATUS_OK
    if strict and summary.get("provenance_status") == cli_runtime.ProvenanceStatus.BLOCKED.value:
        status = STATUS_BLOCKED
    return ctx, summary, status


def record_raw_turn_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    role: str,
    text: str,
    source_surface: str,
    run_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    payload = cli_runtime.record_raw_turn(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        role=role,
        text=text,
        source_surface=source_surface,
        session_id=ctx.get("session_id"),
        run_id=run_id,
        metadata=dict(metadata or {}),
    )
    raw_ref = cli_runtime.raw_artifact_ref(
        raw_id=payload["raw_turn_id"],
        family="CONVERSATION_TURNS",
        path=payload["raw_turn_path"],
        sha256=payload["raw_turn_sha256"],
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="record-raw-turn",
        summary=f"Recorded raw {role} turn for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals=cli_runtime.raw_capture_signals(
            accepted_context=cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=cli_runtime._current_session_mode_fields(ctx),
            raw_refs=[raw_ref],
            source_surface=source_surface,
            raw_role=role,
        ),
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "raw_turn_id": payload["raw_turn_id"],
            "raw_turn_path": payload["raw_turn_path"],
            "raw_turn_sha256": payload["raw_turn_sha256"],
            "raw_text_blob_path": payload["text_blob"]["path"],
            "raw_text_blob_sha256": payload["text_blob"]["sha256"],
        },
    )
    result = {
        **payload,
        "kernel_posture": inspect_engaged_kernel_posture(repo_root=Path(ctx["engine_root"]), data_root=Path(ctx["data_root"])),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, result, event_info, STATUS_OK


def record_raw_execution_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    family: str,
    source_surface: str,
    phase: str | None,
    command_text: str | None,
    tool_name: str | None,
    status: str | None,
    changed_files: list[str] | None,
    payload: Any | None,
    run_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    result_payload = cli_runtime.record_raw_execution(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        family=family,
        source_surface=source_surface,
        phase=phase,
        session_id=ctx.get("session_id"),
        run_id=run_id,
        command=command_text,
        tool_name=tool_name,
        status=status,
        changed_files=list(changed_files or []),
        payload=payload,
        metadata=dict(metadata or {}),
    )
    raw_ref = cli_runtime.raw_artifact_ref(
        raw_id=result_payload["raw_event_id"],
        family=result_payload["family"],
        path=result_payload["raw_event_path"],
        sha256=result_payload["raw_event_sha256"],
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="record-raw-execution",
        summary=f"Recorded raw {family} evidence for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals=cli_runtime.raw_capture_signals(
            accepted_context=cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=cli_runtime._current_session_mode_fields(ctx),
            raw_refs=[raw_ref],
            source_surface=source_surface,
            raw_family=result_payload["family"],
        ),
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "raw_event_id": result_payload["raw_event_id"],
            "raw_event_path": result_payload["raw_event_path"],
            "raw_event_sha256": result_payload["raw_event_sha256"],
            "payload_blob_path": result_payload.get("payload_blob", {}).get("path") if result_payload.get("payload_blob") else None,
            "payload_blob_sha256": result_payload.get("payload_blob", {}).get("sha256") if result_payload.get("payload_blob") else None,
        },
    )
    result = {
        **result_payload,
        "kernel_posture": inspect_engaged_kernel_posture(repo_root=Path(ctx["engine_root"]), data_root=Path(ctx["data_root"])),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, result, event_info, STATUS_OK


def import_continuity_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
    source_file: str,
    kind: str,
    source_surface: str,
    run_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    parsed = cli_runtime.parse_imported_continuity_source(
        source_path=Path(str(source_file)),
        source_kind=kind,
    )
    parsed["recorded_at"] = cli_runtime.kernel_now_iso()
    result_payload = cli_runtime.record_raw_execution(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        family="import",
        source_surface=source_surface,
        phase="imported_continuity",
        session_id=ctx.get("session_id"),
        run_id=run_id,
        command=f"import-continuity {parsed.get('source_kind')} {parsed.get('source_path')}",
        tool_name="import-continuity",
        status=str(parsed.get("parser_status") or "parsed"),
        changed_files=[],
        payload=parsed,
        metadata={
            "source_kind": parsed.get("source_kind"),
            "parser_status": parsed.get("parser_status"),
            "confidence_band": parsed.get("confidence_band"),
            "source_path": parsed.get("source_path"),
            "warnings": list(parsed.get("warnings") or []),
        },
    )
    raw_ref = cli_runtime.raw_artifact_ref(
        raw_id=result_payload["raw_event_id"],
        family=result_payload["family"],
        path=result_payload["raw_event_path"],
        sha256=result_payload["raw_event_sha256"],
    )
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="import-continuity",
        summary=f"Imported {parsed.get('source_kind')} continuity evidence for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals=cli_runtime.raw_capture_signals(
            accepted_context=cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=cli_runtime._current_session_mode_fields(ctx),
            raw_refs=[raw_ref],
            source_surface=source_surface,
            raw_family=result_payload["family"],
        ),
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": str(parsed.get("confidence_band") or "").strip().lower() == "low",
        },
        outputs={
            "raw_event_id": result_payload["raw_event_id"],
            "raw_event_path": result_payload["raw_event_path"],
            "raw_event_sha256": result_payload["raw_event_sha256"],
            "payload_blob_path": result_payload.get("payload_blob", {}).get("path") if result_payload.get("payload_blob") else None,
            "payload_blob_sha256": result_payload.get("payload_blob", {}).get("sha256") if result_payload.get("payload_blob") else None,
            "import_source_path": parsed.get("source_path"),
            "import_source_kind": parsed.get("source_kind"),
            "import_parser_status": parsed.get("parser_status"),
            "import_confidence_band": parsed.get("confidence_band"),
        },
    )
    result = {
        **result_payload,
        "import_envelope": parsed,
        "kernel_posture": inspect_engaged_kernel_posture(repo_root=Path(ctx["engine_root"]), data_root=Path(ctx["data_root"])),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, result, event_info, STATUS_OK


def install_local_integration_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    payload = cli_runtime._install_local_integration_receipt(ctx)
    changed_files = [
        str(payload.get("manifest_path") or ""),
        str(payload.get("mcp_config_path") or ""),
        str(payload.get("readme_path") or ""),
        *[str(path) for path in (payload.get("hook_paths") or {}).values()],
    ]
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="install-local-integration",
        summary=f"Installed or refreshed optional local integration for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals={
            "changed_files": [path for path in changed_files if path],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            **cli_runtime._current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "integration_posture": payload.get("integration_posture"),
            "integration_health": payload.get("integration_health"),
            "integration_dir": payload.get("integration_dir"),
            "manifest_path": payload.get("manifest_path"),
            "mcp_config_path": payload.get("mcp_config_path"),
            "readme_path": payload.get("readme_path"),
            "hook_paths": payload.get("hook_paths"),
            "missing_assets": list(payload.get("missing_assets") or []),
        },
    )
    result = {
        **payload,
        "kernel_posture": inspect_engaged_kernel_posture(repo_root=Path(ctx["engine_root"]), data_root=Path(ctx["data_root"])),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, result, event_info, STATUS_OK


def install_git_hooks_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, force: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    payload = cli_runtime._install_hooks_receipt(ctx, force=force)
    if payload.get("git_hooks_status") == cli_runtime.GitHooksStatus.NOT_APPLICABLE.value:
        return ctx, payload, None, STATUS_OK
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="install-hooks",
        summary=f"Installed or verified managed git hooks for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals={
            "changed_files": [payload["hooks_receipt_path"]],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            **cli_runtime._current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "git_hooks_status": payload.get("hooks_status"),
            "hooks_receipt_path": payload.get("hooks_receipt_path"),
            "template_version": payload.get("template_version"),
            "pre_commit_status": payload.get("pre_commit_status"),
            "pre_push_status": payload.get("pre_push_status"),
            "backups": list(payload.get("backups") or []),
        },
    )
    result = dict(payload)
    result.update({"event": event_info.get("event"), "reducer": event_info.get("reducer")})
    return ctx, result, event_info, STATUS_OK


def verify_git_hooks_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    payload = cli_runtime._verify_hooks_receipt(ctx)
    if payload.get("git_hooks_status") == cli_runtime.GitHooksStatus.NOT_APPLICABLE.value:
        return ctx, payload, None, STATUS_OK
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="verify-hooks",
        summary=f"Verified managed git hooks for {ctx['subject']}.",
        session_id=ctx.get("session_id"),
        signals={
            "changed_files": [payload["hooks_receipt_path"]],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            **cli_runtime._current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "git_hooks_status": payload.get("hooks_status"),
            "hooks_receipt_path": payload.get("hooks_receipt_path"),
            "template_version": payload.get("template_version"),
            "pre_commit_status": payload.get("pre_commit_status"),
            "pre_push_status": payload.get("pre_push_status"),
        },
    )
    result = dict(payload)
    result.update({"event": event_info.get("event"), "reducer": event_info.get("reducer")})
    return ctx, result, event_info, STATUS_OK


def refresh_draftshot_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run)
    if not session_id:
        raise BridgeFailure(
            code="SESSION_REQUIRED",
            message="refresh_draftshot requires a session id or active run session context.",
            recovery_hint="Run bootstrap_session first or pass context.session_id explicitly.",
        )

    payload = refresh_draftshot(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        session_id=session_id,
        run_id=active_run.get("run_id"),
    )
    refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    _, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=False, include_project_story=False)
    result = dict(payload)
    result["current_context"] = bundle["context"]
    return ctx, result, None, STATUS_OK if payload.get("status") != "noop" else STATUS_NOOP


def refresh_snapshot_candidates_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run)
    refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    payload = refresh_snapshot_candidates(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        session_id=session_id,
    )
    refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    _, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=False, include_project_story=False)
    result = dict(payload)
    result["current_context"] = bundle["context"]
    return ctx, result, None, STATUS_OK if payload.get("status") != "noop" else STATUS_NOOP


def refresh_publication_candidates_tool(
    *,
    state: ConnectionState,
    context: ContextInput | dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    payload = refresh_publication_candidates(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
    )
    refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    _, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=False, include_project_story=False)
    result = dict(payload)
    result["current_context"] = bundle["context"]
    return ctx, result, None, STATUS_OK if payload.get("status") != "noop" else STATUS_NOOP


def refresh_continuity_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, seal_rehydration_pack: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    if seal_rehydration_pack:
        refreshed = cli_runtime._render_and_refresh_continuity(ctx["subject"], Path(ctx["data_root"]), Path(ctx["engine_root"]))
        rehydrate = refreshed["rehydrate"]
        continuity = refreshed["continuity"]
    else:
        rehydrate = render_rehydrate(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
        continuity = None
    _, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=False, include_project_story=False)
    return ctx, {
        "rehydrate_path": rehydrate.get("rehydrate_path"),
        "continuity_lock_path": continuity.get("continuity_lock_path") if continuity else None,
        "bootstrap_prompt_path": continuity.get("bootstrap_prompt_path") if continuity else None,
        "current_context": bundle["context"],
    }


def finalize_run_tool(*, state: ConnectionState, context: ContextInput | dict[str, Any] | None, outcome_summary: str | None, status: str | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ctx = _resolve_runtime_context(state=state, context=context, allow_attach_current_repo=False, requires_session=False)
    active_run = cli_runtime._load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        raise BridgeFailure(code="ACTIVE_RUN_REQUIRED", message="finalize_run requires an active run.", recovery_hint="Call bootstrap_session first.")
    result = run_finalize(subject=ctx["subject"], data_root=Path(ctx["data_root"]), status=status or "completed", summary=outcome_summary)
    session_id = cli_runtime._effective_session_id(ctx, active_run=active_run, session_id=result.get("session_id"))
    event_info = cli_runtime._event_pipeline(
        ctx=ctx,
        action_name="run-finalize",
        summary=outcome_summary or f"Finalized run {result.get('run_id')}",
        session_id=session_id,
        signals={
            "run_id": result.get("run_id"),
            "final_status": status or "completed",
            "run_status": status or "completed",
            "run_summary": outcome_summary,
            "changed_files": [],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": cli_runtime._accepted_context_snapshot(Path(ctx["data_root"])),
            "session_mode": result.get("session_mode"),
            "session_mode_source": result.get("session_mode_source"),
            "session_mode_policy_version": result.get("session_mode_policy_version"),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "run_id": result.get("run_id"),
            "archive_path": result.get("archive_path"),
        },
    )
    event_info, truth_compile = cli_runtime._merge_truth_compile_follow_on(
        ctx=ctx,
        session_id=session_id,
        event_info=event_info,
        primary_action_label="Run finalization",
    )
    _, bundle = build_current_context_bundle(state=state, context=context, include_rehydrate=False, include_project_story=False)
    payload = {
        "run_id": result.get("run_id"),
        "archive_path": result.get("archive_path"),
        "truth_compile": truth_compile,
        "current_context": bundle["context"],
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }
    return ctx, payload, event_info


def map_runtime_exception(exc: Exception) -> BridgeFailure:
    if isinstance(exc, BridgeFailure):
        return exc
    if isinstance(exc, QuestAcceptanceError):
        message = str(exc)
        code = "QUEST_ACCEPTANCE_FAILED"
        status = STATUS_FAILED
        if "accept" in message.lower() and "blocks" in message.lower():
            code = "QUEST_ACCEPTANCE_BLOCKED"
            status = STATUS_BLOCKED
        return BridgeFailure(code=code, message=message, status=status)
    if isinstance(exc, (SubjectResolutionError, RepoArchaeologyError, ProjectModelError, SemanticIntakeError, RepoOnboardingError, LiveMemoryError, ReducerError)):
        message = str(exc)
        code = "CONTEXT_RESOLUTION_FAILED"
        recovery_hint = None
        status = STATUS_FAILED
        if "active run" in message.lower():
            code = "ACTIVE_RUN_REQUIRED"
            recovery_hint = "Call bootstrap_session first."
        if "Invalid session-mode transition" in message or "requires posture" in message:
            code = "POSTURE_TRANSITION_BLOCKED"
            status = STATUS_BLOCKED
        if "formalize" in message and "blocks" in message:
            code = "FORMALIZATION_BLOCKED"
            status = STATUS_BLOCKED
        if "accept" in message.lower() and "blocks" in message.lower():
            code = "QUEST_ACCEPTANCE_BLOCKED"
            status = STATUS_BLOCKED
        if "onboarding" in message.lower() and ("requires" in message.lower() or "no current onboarding" in message.lower()):
            code = "ONBOARDING_STATE_BLOCKED"
            status = STATUS_BLOCKED if "requires" in message.lower() else STATUS_FAILED
        if "open questions" in message.lower() or "thread" in message.lower():
            code = "THREAD_CONFLICT"
        return BridgeFailure(code=code, message=message, recovery_hint=recovery_hint, status=status)
    return BridgeFailure(code="CONTEXT_RESOLUTION_FAILED", message=str(exc))

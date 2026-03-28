"""Existing-repo onboarding session orchestration and publication helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.accepted_execution_view import load_accepted_quest_details, select_current_accepted_quest
from synapse_runtime.governance_model import AmbientSignal, PromotionRecord, ProposalKind, ProposalState
from synapse_runtime.live_memory_common import LiveMemoryError, _slugify
from synapse_runtime.project_model import (
    ProjectModelError,
    build_published_project_model,
    compute_revision_delta,
    evaluate_confirmation_readiness,
    load_yaml_artifact,
    project_model_projection,
    render_analysis_brief,
    render_draft_codex_current,
    render_draft_codex_future,
    render_draft_story,
    render_draft_vision,
    render_published_codex_current,
    render_published_codex_future,
    render_project_story,
    render_published_vision,
    validate_draft_revision,
    validate_question_set,
)
from synapse_runtime.quest_candidates import QUEST_PROPOSAL_KINDS, _proposal_id, _upsert_quest_candidate, _write_proposals
from synapse_runtime.repo_archaeology import RepoArchaeologyError, ScanDepth, load_scan_artifact, run_repo_archaeology, scan_artifact_path
from synapse_runtime.semantic_intake import write_capture_batch
from synapse_runtime.sidecar_store import _now_iso, ensure_live_scaffold, live_root


class RepoOnboardingError(LiveMemoryError):
    """Raised when Phase 3 onboarding operations cannot proceed safely."""


ONBOARDING_NONTERMINAL_STATES = {
    "needs_scan",
    "needs_draft_submission",
    "awaiting_user_clarification",
    "needs_draft_revision",
    "awaiting_confirmation",
}
ONBOARDING_TERMINAL_STATES = {"confirmed", "abandoned"}
_ALLOWED_TRANSITIONS = {
    "needs_scan": {"needs_draft_submission", "abandoned"},
    "needs_draft_submission": {"awaiting_user_clarification", "awaiting_confirmation", "abandoned"},
    "awaiting_user_clarification": {"needs_draft_revision", "abandoned"},
    "needs_draft_revision": {"awaiting_user_clarification", "awaiting_confirmation", "abandoned"},
    "awaiting_confirmation": {"needs_draft_revision", "confirmed", "abandoned"},
    "confirmed": set(),
    "abandoned": set(),
}


def onboarding_root(data_root: Path) -> Path:
    return live_root(data_root) / "ONBOARDING"


def onboarding_current_path(data_root: Path) -> Path:
    return onboarding_root(data_root) / "CURRENT.yaml"


def onboarding_sessions_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "SESSIONS"


def onboarding_session_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_sessions_dir(data_root) / f"ONBOARDING__{onboarding_id}.yaml"


def onboarding_drafts_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "DRAFTS"


def onboarding_questions_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "QUESTIONS"


def onboarding_workplans_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "WORKPLANS"


def onboarding_briefs_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "BRIEFS"


def onboarding_published_dir(data_root: Path) -> Path:
    return onboarding_root(data_root) / "PUBLISHED"


def onboarding_draft_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"PROJECT_MODEL_DRAFT__{revision_id}.yaml"


def onboarding_delta_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"PROJECT_MODEL_DELTA__{revision_id}.yaml"


def onboarding_question_set_path(data_root: Path, question_set_id: str) -> Path:
    return onboarding_questions_dir(data_root) / f"QUESTION_SET__{question_set_id}.yaml"


def onboarding_workplan_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_workplans_dir(data_root) / f"ONBOARDING_WORKPLAN__{onboarding_id}.yaml"


def onboarding_brief_path(data_root: Path, scan_id: str) -> Path:
    return onboarding_briefs_dir(data_root) / f"ONBOARDING_BRIEF__{scan_id}.md"


def onboarding_story_draft_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"PROJECT_STORY_DRAFT__{revision_id}.md"


def onboarding_vision_draft_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"VISION_DRAFT__{revision_id}.md"


def onboarding_codex_current_draft_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"CODEX_CURRENT_DRAFT__{revision_id}.md"


def onboarding_codex_future_draft_path(data_root: Path, revision_id: str) -> Path:
    return onboarding_drafts_dir(data_root) / f"CODEX_FUTURE_DRAFT__{revision_id}.md"


def archived_project_model_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PROJECT_MODEL__{onboarding_id}.yaml"


def archived_project_story_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PROJECT_STORY__{onboarding_id}.md"


def archived_vision_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"VISION__{onboarding_id}.md"


def archived_codex_current_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"CODEX_CURRENT__{onboarding_id}.md"


def archived_codex_future_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"CODEX_FUTURE__{onboarding_id}.md"


def publication_receipt_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PUBLICATION_RECEIPT__{onboarding_id}.yaml"


def canonical_project_model_path(data_root: Path) -> Path:
    return live_root(data_root) / "PROJECT_MODEL.yaml"


def canonical_project_story_path(data_root: Path) -> Path:
    return live_root(data_root) / "PROJECT_STORY.md"


def canonical_vision_path(data_root: Path) -> Path:
    return live_root(data_root) / "VISION.md"


def canonical_codex_current_path(data_root: Path) -> Path:
    return live_root(data_root) / "CODEX_CURRENT.md"


def canonical_codex_future_path(data_root: Path) -> Path:
    return live_root(data_root) / "CODEX_FUTURE.md"


def _write_publication_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _atomic_publish_copy(source: Path, destination: Path) -> None:
    suffix = _now_iso().replace(":", "").replace("-", "").replace("+", "Z").replace(".", "")
    temp_path = destination.with_name(f".{destination.name}.{os.getpid()}.{suffix}.tmp")
    try:
        shutil.copyfile(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def generate_onboarding_id() -> str:
    return _opaque_id("ONBOARDING")


def generate_scan_id() -> str:
    return _opaque_id("SCAN")


def generate_revision_id() -> str:
    return _opaque_id("REVISION")


def generate_question_set_id() -> str:
    return _opaque_id("QUESTION_SET")


def default_onboarding_pointer(subject: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "adopted_existing_repo": False,
        "current_onboarding_id": None,
        "latest_confirmed_onboarding_id": None,
        "updated_at": _now_iso(),
    }


def default_onboarding_session(
    *,
    subject: str,
    engine_root: Path,
    data_root: Path,
    onboarding_id: str,
    depth: str,
    active_run_id: str,
    session_id: str,
    supersedes_onboarding_id: str | None = None,
) -> dict[str, Any]:
    return {
        "onboarding_id": onboarding_id,
        "subject": subject,
        "engine_root": str(engine_root.resolve()),
        "data_root": str(data_root.resolve()),
        "depth": depth,
        "state": "needs_scan",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "active_run_id": active_run_id,
        "session_id": session_id,
        "supersedes_onboarding_id": supersedes_onboarding_id,
        "superseded_by_onboarding_id": None,
        "scan_ids": [],
        "current_scan_id": None,
        "analysis_brief_path": None,
        "draft_revision_ids": [],
        "current_draft_id": None,
        "question_set_ids": [],
        "current_question_set_id": None,
        "current_workplan_id": onboarding_id,
        "workplan_step_statuses": {},
        "clarification_batch_ids": [],
        "unincorporated_clarification_batch_ids": [],
        "last_incorporated_clarification_batch_id": None,
        "clarification_capture_batch_ids": [],
        "unincorporated_capture_batch_ids": [],
        "revision_delta_ids": [],
        "published_archive_project_model_path": None,
        "published_archive_project_story_path": None,
        "published_archive_vision_path": None,
        "published_archive_codex_current_path": None,
        "published_archive_codex_future_path": None,
        "published_project_model_path": None,
        "published_project_story_path": None,
        "published_vision_path": None,
        "published_codex_current_path": None,
        "published_codex_future_path": None,
        "confirmed_at": None,
        "confirmed_by": None,
        "abandoned_at": None,
        "abandon_reason": None,
    }


def ensure_onboarding_scaffold(subject: str, data_root: Path) -> None:
    ensure_live_scaffold(subject, data_root)


def load_onboarding_pointer(
    *,
    subject: str,
    data_root: Path,
    rebuild: bool = True,
    persist: bool = True,
    ensure_scaffold: bool = True,
) -> dict[str, Any]:
    if ensure_scaffold:
        ensure_onboarding_scaffold(subject, data_root)
    path = onboarding_current_path(data_root)
    payload = _read_yaml(path)
    if isinstance(payload, dict):
        payload.setdefault("subject", subject)
        payload.setdefault("adopted_existing_repo", False)
        payload.setdefault("current_onboarding_id", None)
        payload.setdefault("latest_confirmed_onboarding_id", None)
        payload.setdefault("updated_at", _now_iso())
        if rebuild and _pointer_is_stale(payload, data_root):
            rebuilt = reconstruct_onboarding_pointer(subject=subject, data_root=data_root)
            if persist:
                save_onboarding_pointer(data_root=data_root, pointer=rebuilt)
            return rebuilt
        return payload
    if rebuild:
        rebuilt = reconstruct_onboarding_pointer(subject=subject, data_root=data_root)
        if persist:
            save_onboarding_pointer(data_root=data_root, pointer=rebuilt)
        return rebuilt
    pointer = default_onboarding_pointer(subject)
    if persist:
        save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return pointer


def reconstruct_onboarding_pointer(*, subject: str, data_root: Path) -> dict[str, Any]:
    existing_pointer = _read_yaml(onboarding_current_path(data_root))
    sessions = load_onboarding_sessions(data_root=data_root)
    nonterminal = [session for session in sessions if str(session.get("state") or "") in ONBOARDING_NONTERMINAL_STATES]
    if len(nonterminal) > 1:
        raise RepoOnboardingError("Onboarding pointer reconstruction is ambiguous: multiple nonterminal sessions exist.")
    confirmed = [session for session in sessions if str(session.get("state") or "") == "confirmed"]
    latest_confirmed = None
    if confirmed:
        latest_confirmed = sorted(
            confirmed,
            key=lambda item: (str(item.get("confirmed_at") or ""), str(item.get("onboarding_id") or "")),
        )[-1]
    return {
        "subject": subject,
        "adopted_existing_repo": bool((existing_pointer or {}).get("adopted_existing_repo")),
        "current_onboarding_id": nonterminal[0].get("onboarding_id") if nonterminal else None,
        "latest_confirmed_onboarding_id": latest_confirmed.get("onboarding_id") if latest_confirmed else None,
        "updated_at": _now_iso(),
    }


def load_onboarding_sessions(*, data_root: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for path in sorted(onboarding_sessions_dir(data_root).glob("ONBOARDING__*.yaml")):
        sessions.append(load_onboarding_session(path))
    return sessions


def load_onboarding_session(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path)
    if not isinstance(payload, dict) or not payload.get("onboarding_id"):
        raise RepoOnboardingError(f"Malformed onboarding session artifact: {path}")
    return _normalize_onboarding_session(payload)


def save_onboarding_pointer(*, data_root: Path, pointer: dict[str, Any]) -> str:
    path = onboarding_current_path(data_root)
    payload = dict(pointer)
    payload["updated_at"] = _now_iso()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def save_onboarding_session(*, data_root: Path, session: dict[str, Any]) -> str:
    path = onboarding_session_path(data_root, str(session["onboarding_id"]))
    payload = _normalize_onboarding_session(session)
    payload["updated_at"] = _now_iso()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def load_onboarding_workplan(*, data_root: Path, onboarding_id: str, required: bool) -> dict[str, Any] | None:
    path = onboarding_workplan_path(data_root, onboarding_id)
    payload = _read_yaml(path)
    if payload is None:
        if required:
            raise RepoOnboardingError(f"Onboarding workplan is missing: {path}")
        return None
    if not isinstance(payload, dict) or str(payload.get("onboarding_id") or "").strip() != onboarding_id:
        raise RepoOnboardingError(f"Malformed onboarding workplan artifact: {path}")
    return _normalize_workplan(payload, onboarding_id=onboarding_id)


def save_onboarding_workplan(*, data_root: Path, workplan: dict[str, Any]) -> str:
    onboarding_id = str(workplan.get("onboarding_id") or "").strip()
    if not onboarding_id:
        raise RepoOnboardingError("Onboarding workplan is missing onboarding_id.")
    path = onboarding_workplan_path(data_root, onboarding_id)
    normalized = _normalize_workplan(workplan, onboarding_id=onboarding_id)
    path.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
    return str(path.resolve())


def _rebuild_onboarding_workplan(
    *,
    data_root: Path,
    session: dict[str, Any],
    draft: dict[str, Any] | None,
    question_set: dict[str, Any] | None,
) -> dict[str, Any]:
    from synapse_runtime.truth_compiler import canonical_truth_publication_paths, load_compiler_report

    onboarding_id = str(session.get("onboarding_id") or "").strip()
    if not onboarding_id:
        raise RepoOnboardingError("Cannot rebuild onboarding workplan without onboarding_id.")
    workplan = default_onboarding_workplan(onboarding_id=onboarding_id)
    scan_id = str(session.get("current_scan_id") or "").strip()
    scan_path = scan_artifact_path(data_root, scan_id) if scan_id else None
    brief_path_text = str(session.get("analysis_brief_path") or "").strip()
    if scan_id:
        archaeology_refs = [str(scan_path.resolve())] if scan_path and scan_path.exists() else [scan_id]
        if brief_path_text and Path(brief_path_text).exists():
            archaeology_refs.append(str(Path(brief_path_text).resolve()))
        _set_workplan_step(workplan, "archaeology_complete", status="complete", artifact_refs=archaeology_refs)
    if draft is not None:
        revision_id = str(draft.get("revision_id") or "").strip()
        evidence_refs = [scan_id] if scan_id else []
        if brief_path_text and Path(brief_path_text).exists():
            evidence_refs.append(str(Path(brief_path_text).resolve()))
        _set_workplan_step(workplan, "evidence_review_complete", status="complete", artifact_refs=evidence_refs or [revision_id])
        draft_model_path = onboarding_draft_path(data_root, revision_id)
        if draft_model_path.exists():
            _set_workplan_step(workplan, "draft_model_written", status="complete", artifact_refs=[str(draft_model_path.resolve())])
        draft_story_path = onboarding_story_draft_path(data_root, revision_id)
        if draft_story_path.exists():
            _set_workplan_step(workplan, "draft_story_written", status="complete", artifact_refs=[str(draft_story_path.resolve())])
        draft_vision_path = onboarding_vision_draft_path(data_root, revision_id)
        if draft_vision_path.exists():
            _set_workplan_step(workplan, "draft_vision_written", status="complete", artifact_refs=[str(draft_vision_path.resolve())])
        draft_codex_current_path = onboarding_codex_current_draft_path(data_root, revision_id)
        if draft_codex_current_path.exists():
            _set_workplan_step(
                workplan,
                "draft_current_codex_written",
                status="complete",
                artifact_refs=[str(draft_codex_current_path.resolve())],
            )
        draft_codex_future_path = onboarding_codex_future_draft_path(data_root, revision_id)
        if draft_codex_future_path.exists():
            _set_workplan_step(
                workplan,
                "draft_future_codex_written",
                status="complete",
                artifact_refs=[str(draft_codex_future_path.resolve())],
            )
    if question_set is not None:
        question_set_id = str(question_set.get("question_set_id") or "").strip()
        question_set_path = onboarding_question_set_path(data_root, question_set_id)
        if question_set_path.exists():
            _set_workplan_step(workplan, "question_set_written", status="complete", artifact_refs=[str(question_set_path.resolve())])
    unincorporated = list(session.get("unincorporated_clarification_batch_ids") or session.get("unincorporated_capture_batch_ids") or [])
    clarification_batches = list(session.get("clarification_batch_ids") or session.get("clarification_capture_batch_ids") or [])
    if unincorporated:
        _set_workplan_step(
            workplan,
            "clarification_incorporated",
            status="blocked",
            blocking_reason="Clarification batches remain unincorporated in the current revision.",
            artifact_refs=unincorporated,
        )
    else:
        _set_workplan_step(workplan, "clarification_incorporated", status="complete", artifact_refs=clarification_batches)
    canonical_paths = [
        canonical_project_model_path(data_root),
        canonical_project_story_path(data_root),
        canonical_vision_path(data_root),
        canonical_codex_current_path(data_root),
        canonical_codex_future_path(data_root),
    ]
    if all(path.exists() for path in canonical_paths):
        artifact_refs = [str(path.resolve()) for path in canonical_paths]
        receipt_path = publication_receipt_path(data_root, onboarding_id)
        if receipt_path.exists():
            artifact_refs.append(str(receipt_path.resolve()))
        _set_workplan_step(workplan, "canonical_publication_complete", status="complete", artifact_refs=artifact_refs)
    report = load_compiler_report(data_root)
    truth_paths = canonical_truth_publication_paths(data_root)
    current_state_path = Path(str(truth_paths.get("current_state") or "")).expanduser() if truth_paths.get("current_state") else None
    if report and current_state_path and current_state_path.exists():
        refs = [str(current_state_path.resolve())]
        receipt_path = publication_receipt_path(data_root, onboarding_id)
        if receipt_path.exists():
            refs.append(str(receipt_path.resolve()))
        _set_workplan_step(workplan, "post_publication_compile_complete", status="complete", artifact_refs=refs)
    return workplan


def _ensure_part2_revision_artifacts(
    *,
    data_root: Path,
    session: dict[str, Any],
    draft: dict[str, Any] | None,
    question_set: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    updated_session = dict(session)
    writes: dict[Path, str] = {}
    if draft is not None:
        revision_id = str(draft.get("revision_id") or "").strip()
        if revision_id:
            story_path = onboarding_story_draft_path(data_root, revision_id)
            if not story_path.exists():
                writes[story_path] = render_draft_story(draft, question_set)
            vision_path = onboarding_vision_draft_path(data_root, revision_id)
            if not vision_path.exists():
                writes[vision_path] = render_draft_vision(draft, question_set)
            codex_current_path = onboarding_codex_current_draft_path(data_root, revision_id)
            if not codex_current_path.exists():
                writes[codex_current_path] = render_draft_codex_current(draft)
            codex_future_path = onboarding_codex_future_draft_path(data_root, revision_id)
            if not codex_future_path.exists():
                writes[codex_future_path] = render_draft_codex_future(draft)
    if writes:
        _write_artifact_family(writes)
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(updated_session["onboarding_id"]), required=False)
    if workplan is None:
        workplan = _rebuild_onboarding_workplan(
            data_root=data_root,
            session=updated_session,
            draft=draft,
            question_set=question_set,
        )
        updated_session["current_workplan_id"] = str(updated_session.get("onboarding_id") or "")
        updated_session["workplan_step_statuses"] = _workplan_status_map(workplan)
        save_onboarding_session(data_root=data_root, session=updated_session)
        save_onboarding_workplan(data_root=data_root, workplan=workplan)
    return updated_session, workplan


def transition_onboarding_state(session: dict[str, Any], target_state: str) -> dict[str, Any]:
    current_state = str(session.get("state") or "").strip()
    allowed = _ALLOWED_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise RepoOnboardingError(f"Invalid onboarding transition: {current_state} -> {target_state}")
    updated = dict(session)
    updated["state"] = target_state
    updated["updated_at"] = _now_iso()
    return updated


def current_onboarding_session(
    *,
    subject: str,
    data_root: Path,
    require_current: bool = True,
    rebuild: bool = True,
    persist_pointer: bool = True,
    ensure_scaffold: bool = True,
) -> dict[str, Any] | None:
    pointer = load_onboarding_pointer(
        subject=subject,
        data_root=data_root,
        rebuild=rebuild,
        persist=persist_pointer,
        ensure_scaffold=ensure_scaffold,
    )
    current_id = str(pointer.get("current_onboarding_id") or "").strip()
    if current_id:
        session = load_onboarding_session(onboarding_session_path(data_root, current_id))
        return session
    if not require_current:
        latest_id = str(pointer.get("latest_confirmed_onboarding_id") or "").strip()
        if latest_id:
            return load_onboarding_session(onboarding_session_path(data_root, latest_id))
        return None
    return None


def mark_adopted_existing_repo(*, subject: str, data_root: Path) -> dict[str, Any]:
    pointer = load_onboarding_pointer(
        subject=subject,
        data_root=data_root,
        rebuild=False,
        persist=False,
    )
    pointer["adopted_existing_repo"] = True
    save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return pointer


def onboarding_status_payload(
    *,
    subject: str,
    data_root: Path,
    rebuild: bool = True,
    persist_pointer: bool = True,
    ensure_scaffold: bool = True,
) -> dict[str, Any]:
    pointer = load_onboarding_pointer(
        subject=subject,
        data_root=data_root,
        rebuild=rebuild,
        persist=persist_pointer,
        ensure_scaffold=ensure_scaffold,
    )
    session = current_onboarding_session(
        subject=subject,
        data_root=data_root,
        require_current=False,
        rebuild=rebuild,
        persist_pointer=persist_pointer,
        ensure_scaffold=ensure_scaffold,
    )
    if not session:
        return {
            "onboarding_id": None,
            "state": None,
            "depth": None,
            "adopted_existing_repo": bool(pointer.get("adopted_existing_repo")),
            "current_scan_id": None,
            "current_draft_id": None,
            "current_question_set_id": None,
            "current_workplan_id": None,
            "workplan_path": None,
            "clarification_capture_batch_ids": [],
            "unincorporated_capture_batch_ids": [],
            "clarification_batch_ids": [],
            "unincorporated_clarification_batch_ids": [],
            "blocking_open_question_count": 0,
            "important_open_question_count": 0,
            "draft_is_stale": False,
            "published_project_model_path": None,
            "published_project_story_path": None,
            "published_vision_path": None,
            "published_codex_current_path": None,
            "published_codex_future_path": None,
            "readiness": None,
            "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
        }
    question_set = load_current_question_set(data_root=data_root, session=session, required=False)
    draft = load_current_draft(data_root=data_root, session=session, required=False)
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(session["onboarding_id"]), required=False)
    blocking_count, important_count = _question_priority_counts(question_set)
    readiness = None
    if draft is not None and question_set is not None:
        readiness = evaluate_confirmation_readiness(
            onboarding_state=str(session.get("state") or ""),
            current_scan_id=str(session.get("current_scan_id") or ""),
            unincorporated_capture_batch_ids=list(
                session.get("unincorporated_clarification_batch_ids") or session.get("unincorporated_capture_batch_ids") or []
            ),
            draft=draft,
            question_set=question_set,
            required_artifact_paths=current_revision_artifact_paths(data_root=data_root, session=session),
            workplan=workplan,
        )
    return {
        "onboarding_id": session.get("onboarding_id"),
        "state": session.get("state"),
        "depth": session.get("depth"),
        "adopted_existing_repo": bool(pointer.get("adopted_existing_repo")),
        "current_scan_id": session.get("current_scan_id"),
        "current_draft_id": session.get("current_draft_id"),
        "current_question_set_id": session.get("current_question_set_id"),
        "current_workplan_id": session.get("current_workplan_id"),
        "workplan_path": str(onboarding_workplan_path(data_root, str(session["onboarding_id"])).resolve()),
        "clarification_capture_batch_ids": list(session.get("clarification_capture_batch_ids") or []),
        "unincorporated_capture_batch_ids": list(session.get("unincorporated_capture_batch_ids") or []),
        "clarification_batch_ids": list(session.get("clarification_batch_ids") or []),
        "unincorporated_clarification_batch_ids": list(session.get("unincorporated_clarification_batch_ids") or []),
        "blocking_open_question_count": blocking_count,
        "important_open_question_count": important_count,
        "draft_is_stale": draft_is_stale(session=session, draft=draft),
        "published_project_model_path": session.get("published_project_model_path"),
        "published_project_story_path": session.get("published_project_story_path"),
        "published_vision_path": session.get("published_vision_path"),
        "published_codex_current_path": session.get("published_codex_current_path"),
        "published_codex_future_path": session.get("published_codex_future_path"),
        "readiness": readiness,
        "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
    }


def onboard_repo(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    active_run: dict[str, Any],
    depth: str,
    rescan: bool,
    restart: bool,
) -> dict[str, Any]:
    ensure_onboarding_scaffold(subject, data_root)
    mark_adopted_existing_repo(subject=subject, data_root=data_root)
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=True)
    current_session = current_onboarding_session(subject=subject, data_root=data_root, require_current=True)
    latest_confirmed = None
    latest_confirmed_id = str(pointer.get("latest_confirmed_onboarding_id") or "").strip()
    if latest_confirmed_id:
        latest_confirmed = load_onboarding_session(onboarding_session_path(data_root, latest_confirmed_id))

    resumed_existing = False
    already_completed = False
    supersedes_id: str | None = None
    if current_session and str(current_session.get("state") or "") in ONBOARDING_NONTERMINAL_STATES:
        if restart:
            current_session = abandon_onboarding_session(
                data_root=data_root,
                session=current_session,
                reason="Restarted onboarding session.",
            )
            supersedes_id = str(current_session.get("onboarding_id") or "") or None
        elif rescan:
            pass
        else:
            resumed_existing = True
            status = onboarding_status_payload(subject=subject, data_root=data_root)
            return {
                **status,
                "session_mode": active_run.get("session_mode"),
                "resumed_existing": True,
                "already_completed": False,
            }
    elif latest_confirmed or (current_session and str(current_session.get("state") or "") == "abandoned"):
        if rescan and not restart:
            raise RepoOnboardingError("Cannot rescan a confirmed or abandoned onboarding session without --restart.")
        if not restart:
            already_completed = True
            status = onboarding_status_payload(subject=subject, data_root=data_root)
            return {
                **status,
                "session_mode": active_run.get("session_mode"),
                "resumed_existing": False,
                "already_completed": True,
            }
        supersedes_id = str((latest_confirmed or current_session or {}).get("onboarding_id") or "") or None

    session = current_session
    created_new = False
    if session is None or restart:
        onboarding_id = generate_onboarding_id()
        session = default_onboarding_session(
            subject=subject,
            engine_root=engine_root,
            data_root=data_root,
            onboarding_id=onboarding_id,
            depth=str(depth),
            active_run_id=str(active_run.get("run_id") or "").strip(),
            session_id=str(active_run.get("session_id") or "").strip(),
            supersedes_onboarding_id=supersedes_id,
        )
        created_new = True
        if supersedes_id:
            superseded = load_onboarding_session(onboarding_session_path(data_root, supersedes_id))
            superseded["superseded_by_onboarding_id"] = onboarding_id
            save_onboarding_session(data_root=data_root, session=superseded)
    else:
        session = dict(session)
        session["depth"] = str(depth)
        session["active_run_id"] = str(active_run.get("run_id") or "").strip()
        session["session_id"] = str(active_run.get("session_id") or "").strip()

    scan_id = generate_scan_id()
    archaeology = run_repo_archaeology(
        onboarding_id=str(session["onboarding_id"]),
        engine_root=engine_root,
        data_root=data_root,
        depth=depth,
        scan_id=scan_id,
    )
    scan_artifact = archaeology["scan"]
    session.setdefault("scan_ids", [])
    session["scan_ids"] = list(session.get("scan_ids") or []) + [scan_id]
    session["current_scan_id"] = scan_id
    next_state = "needs_draft_revision" if session.get("current_draft_id") else "needs_draft_submission"
    session["state"] = next_state
    brief_text = render_analysis_brief(
        session=session,
        scan_artifact_path=archaeology["artifact_path"],
        active_session_mode=str(active_run.get("session_mode") or ""),
    )
    brief_path = onboarding_brief_path(data_root, scan_id)
    brief_path.write_text(brief_text, encoding="utf-8")
    session["analysis_brief_path"] = str(brief_path.resolve())
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(session["onboarding_id"]), required=False)
    if workplan is None:
        workplan = default_onboarding_workplan(onboarding_id=str(session["onboarding_id"]))
    _set_workplan_step(
        workplan,
        "archaeology_complete",
        status="complete",
        artifact_refs=[archaeology["artifact_path"], str(brief_path.resolve())],
    )
    _set_workplan_step(
        workplan,
        "evidence_review_complete",
        status="pending",
        blocking_reason="Current scan evidence has not been reviewed into a draft revision yet.",
        artifact_refs=[archaeology["artifact_path"]],
    )
    _set_workplan_step(
        workplan,
        "draft_model_written",
        status="pending",
        blocking_reason="No current draft revision has been written for the latest scan.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "draft_story_written",
        status="pending",
        blocking_reason="No current draft story exists for the latest revision.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "draft_vision_written",
        status="pending",
        blocking_reason="No current draft vision exists for the latest revision.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "draft_current_codex_written",
        status="pending",
        blocking_reason="No current draft codex exists for the latest revision.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "draft_future_codex_written",
        status="pending",
        blocking_reason="No future draft codex exists for the latest revision.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "question_set_written",
        status="pending",
        blocking_reason="No current onboarding question set exists for the latest revision.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "clarification_incorporated",
        status="pending",
        blocking_reason="Clarification has not yet been reviewed or incorporated.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "confirmation_readiness_passed",
        status="pending",
        blocking_reason="Confirmation readiness has not been evaluated successfully.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "canonical_publication_complete",
        status="pending",
        blocking_reason="Canonical onboarding publications have not been written yet.",
        artifact_refs=[],
    )
    _set_workplan_step(
        workplan,
        "post_publication_compile_complete",
        status="pending",
        blocking_reason="Post-publication current-state compile has not completed yet.",
        artifact_refs=[],
    )
    session["current_workplan_id"] = str(session["onboarding_id"])
    session["workplan_step_statuses"] = _workplan_status_map(workplan)
    session_path = save_onboarding_session(data_root=data_root, session=session)
    workplan_path = save_onboarding_workplan(data_root=data_root, workplan=workplan)
    pointer_payload = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=False)
    pointer_payload["current_onboarding_id"] = session.get("onboarding_id")
    if latest_confirmed_id:
        pointer_payload["latest_confirmed_onboarding_id"] = latest_confirmed_id
    pointer_path = save_onboarding_pointer(data_root=data_root, pointer=pointer_payload)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "scan_id": scan_id,
        "scan_artifact_path": archaeology["artifact_path"],
        "analysis_brief_path": str(brief_path.resolve()),
        "session_mode": active_run.get("session_mode"),
        "onboarding_state": session.get("state"),
        "resumed_existing": resumed_existing,
        "already_completed": already_completed,
        "session_path": session_path,
        "pointer_path": pointer_path,
        "workplan_path": workplan_path,
        "created_new_session": created_new,
    }


def onboarding_update(
    *,
    subject: str,
    data_root: Path,
    session: dict[str, Any],
    draft_payload: Any,
    questions_payload: Any,
    reason_summary: str | None = None,
) -> dict[str, Any]:
    state = str(session.get("state") or "")
    if state not in {"needs_draft_submission", "needs_draft_revision"}:
        raise RepoOnboardingError("onboarding-update requires onboarding state needs_draft_submission or needs_draft_revision.")
    current_scan = load_current_scan(data_root=data_root, session=session, required=True)
    prior_draft = load_current_draft(data_root=data_root, session=session, required=False)
    prior_questions = load_current_question_set(data_root=data_root, session=session, required=False)
    normalized_draft = validate_draft_revision(
        draft_payload,
        onboarding_id=str(session["onboarding_id"]),
        current_scan_id=str(session.get("current_scan_id") or ""),
        unincorporated_capture_batch_ids=list(session.get("unincorporated_capture_batch_ids") or []),
        prior_draft=prior_draft,
        scan_artifact=current_scan,
    )
    normalized_questions = validate_question_set(
        questions_payload,
        onboarding_id=str(session["onboarding_id"]),
        draft=normalized_draft,
        linked_capture_batch_ids=list(session.get("clarification_batch_ids") or session.get("clarification_capture_batch_ids") or []),
        prior_question_set=prior_questions,
    )
    revision_path = onboarding_draft_path(data_root, str(normalized_draft["revision_id"]))
    question_path = onboarding_question_set_path(data_root, str(normalized_questions["question_set_id"]))
    story_path = onboarding_story_draft_path(data_root, str(normalized_draft["revision_id"]))
    vision_path = onboarding_vision_draft_path(data_root, str(normalized_draft["revision_id"]))
    codex_current_path = onboarding_codex_current_draft_path(data_root, str(normalized_draft["revision_id"]))
    codex_future_path = onboarding_codex_future_draft_path(data_root, str(normalized_draft["revision_id"]))
    delta = compute_revision_delta(normalized_draft, prior_draft, reason_summary=reason_summary or "Patched onboarding draft.")
    delta_id = None
    delta_path: Path | None = None
    if delta is not None:
        delta_id = str(delta["revision_id"])
        delta_path = onboarding_delta_path(data_root, delta_id)
    draft_story = render_draft_story(normalized_draft, normalized_questions)
    draft_vision = render_draft_vision(normalized_draft, normalized_questions)
    draft_codex_current = render_draft_codex_current(normalized_draft)
    draft_codex_future = render_draft_codex_future(normalized_draft)
    _write_artifact_family(
        {
            revision_path: yaml.safe_dump(normalized_draft, sort_keys=False),
            question_path: yaml.safe_dump(normalized_questions, sort_keys=False),
            story_path: draft_story,
            vision_path: draft_vision,
            codex_current_path: draft_codex_current,
            codex_future_path: draft_codex_future,
            **({delta_path: yaml.safe_dump(delta, sort_keys=False)} if delta_path is not None and delta is not None else {}),
        }
    )
    session = dict(session)
    session.setdefault("draft_revision_ids", [])
    session["draft_revision_ids"] = list(session.get("draft_revision_ids") or []) + [normalized_draft["revision_id"]]
    session["current_draft_id"] = normalized_draft["revision_id"]
    session.setdefault("question_set_ids", [])
    session["question_set_ids"] = list(session.get("question_set_ids") or []) + [normalized_questions["question_set_id"]]
    session["current_question_set_id"] = normalized_questions["question_set_id"]
    if delta_id is not None:
        session.setdefault("revision_delta_ids", [])
        session["revision_delta_ids"] = list(session.get("revision_delta_ids") or []) + [delta_id]
    incorporated = set(normalized_draft.get("based_on_capture_batch_ids") or [])
    remaining_unincorporated = [
        item for item in list(session.get("unincorporated_clarification_batch_ids") or session.get("unincorporated_capture_batch_ids") or []) if item not in incorporated
    ]
    incorporated_batches = [
        item
        for item in list(session.get("unincorporated_clarification_batch_ids") or session.get("unincorporated_capture_batch_ids") or [])
        if item in incorporated
    ]
    session["unincorporated_clarification_batch_ids"] = remaining_unincorporated
    session["unincorporated_capture_batch_ids"] = remaining_unincorporated
    if incorporated_batches:
        session["last_incorporated_clarification_batch_id"] = incorporated_batches[-1]
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(session["onboarding_id"]), required=False)
    if workplan is None:
        workplan = default_onboarding_workplan(onboarding_id=str(session["onboarding_id"]))
    _set_workplan_step(workplan, "evidence_review_complete", status="complete", artifact_refs=[str(current_scan.get("scan_id") or ""), str(session.get("analysis_brief_path") or "")])
    _set_workplan_step(workplan, "draft_model_written", status="complete", artifact_refs=[str(revision_path.resolve())])
    _set_workplan_step(workplan, "draft_story_written", status="complete", artifact_refs=[str(story_path.resolve())])
    _set_workplan_step(workplan, "draft_vision_written", status="complete", artifact_refs=[str(vision_path.resolve())])
    _set_workplan_step(workplan, "draft_current_codex_written", status="complete", artifact_refs=[str(codex_current_path.resolve())])
    _set_workplan_step(workplan, "draft_future_codex_written", status="complete", artifact_refs=[str(codex_future_path.resolve())])
    _set_workplan_step(workplan, "question_set_written", status="complete", artifact_refs=[str(question_path.resolve())])
    if remaining_unincorporated:
        _set_workplan_step(
            workplan,
            "clarification_incorporated",
            status="blocked",
            blocking_reason="Clarification batches remain unincorporated in the current revision.",
            artifact_refs=remaining_unincorporated,
        )
    else:
        _set_workplan_step(
            workplan,
            "clarification_incorporated",
            status="complete",
            artifact_refs=[item for item in incorporated_batches if str(item).strip()],
        )
    workplan_path = save_onboarding_workplan(data_root=data_root, workplan=workplan)
    required_artifact_paths = {
        "draft_model": str(revision_path.resolve()),
        "draft_question_set": str(question_path.resolve()),
        "draft_story": str(story_path.resolve()),
        "draft_vision": str(vision_path.resolve()),
        "draft_codex_current": str(codex_current_path.resolve()),
        "draft_codex_future": str(codex_future_path.resolve()),
        "workplan": workplan_path,
    }
    if delta_path is not None:
        required_artifact_paths["revision_delta"] = str(delta_path.resolve())
    readiness = evaluate_confirmation_readiness(
        onboarding_state="awaiting_confirmation",
        current_scan_id=str(session.get("current_scan_id") or ""),
        unincorporated_capture_batch_ids=remaining_unincorporated,
        draft=normalized_draft,
        question_set=normalized_questions,
        required_artifact_paths=required_artifact_paths,
        workplan=workplan,
    )
    if readiness["ready"]:
        _set_workplan_step(
            workplan,
            "confirmation_readiness_passed",
            status="complete",
            artifact_refs=[str(revision_path.resolve()), str(question_path.resolve())],
        )
    else:
        _set_workplan_step(
            workplan,
            "confirmation_readiness_passed",
            status="blocked",
            blocking_reason="; ".join(readiness["blocking_reasons"]) or "Confirmation readiness has not passed.",
            artifact_refs=[str(revision_path.resolve()), str(question_path.resolve())],
        )
    blocking_count, _ = _question_priority_counts(normalized_questions)
    session["current_workplan_id"] = str(session["onboarding_id"])
    session["workplan_step_statuses"] = _workplan_status_map(workplan)
    session["state"] = "awaiting_confirmation" if blocking_count == 0 and readiness["ready"] else "awaiting_user_clarification"
    save_onboarding_session(data_root=data_root, session=session)
    workplan_path = save_onboarding_workplan(data_root=data_root, workplan=workplan)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "draft_revision_id": normalized_draft["revision_id"],
        "question_set_id": normalized_questions["question_set_id"],
        "revision_delta_id": delta_id,
        "onboarding_state": session.get("state"),
        "superseded_item_count": len((delta or {}).get("superseded_item_ids") or []),
        "draft_path": str(revision_path.resolve()),
        "question_set_path": str(question_path.resolve()),
        "delta_path": str(delta_path.resolve()) if delta_path is not None else None,
        "draft_story_path": str(story_path.resolve()),
        "draft_vision_path": str(vision_path.resolve()),
        "draft_codex_current_path": str(codex_current_path.resolve()),
        "draft_codex_future_path": str(codex_future_path.resolve()),
        "workplan_path": workplan_path,
        "readiness": readiness,
    }


def onboarding_respond(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    session: dict[str, Any],
    active_run: dict[str, Any],
    raw_text: str,
    payload: Any,
    title: str | None,
    source_role: str,
    linked_question_ids: list[str],
) -> dict[str, Any]:
    state = str(session.get("state") or "")
    if state not in {"awaiting_user_clarification", "awaiting_confirmation"}:
        raise RepoOnboardingError("onboarding-respond requires onboarding state awaiting_user_clarification or awaiting_confirmation.")
    question_set = load_current_question_set(data_root=data_root, session=session, required=True)
    current_question_ids = {str(item.get("question_id") or "") for item in question_set.get("questions") or []}
    invalid = [item for item in linked_question_ids if item not in current_question_ids]
    if invalid:
        raise RepoOnboardingError("onboarding-respond referenced unknown question ids: " + ", ".join(invalid))
    receipt = write_capture_batch(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        run_data=active_run,
        raw_text=raw_text,
        payload=payload,
        source_role=source_role,
        title_override=title,
        extra_context={
            "capture_context": "onboarding_response",
            "onboarding_id": session.get("onboarding_id"),
            "question_set_id": session.get("current_question_set_id"),
            "question_ids": linked_question_ids,
            "suppress_proposals": True,
        },
    )
    batch_id = str(receipt["batch"]["capture_batch_id"])
    session = dict(session)
    session.setdefault("clarification_batch_ids", [])
    session.setdefault("unincorporated_clarification_batch_ids", [])
    session.setdefault("clarification_capture_batch_ids", [])
    session.setdefault("unincorporated_capture_batch_ids", [])
    session["clarification_batch_ids"] = list(session.get("clarification_batch_ids") or []) + [batch_id]
    session["clarification_capture_batch_ids"] = list(session.get("clarification_capture_batch_ids") or []) + [batch_id]
    session["unincorporated_clarification_batch_ids"] = list(session.get("unincorporated_clarification_batch_ids") or []) + [batch_id]
    session["unincorporated_capture_batch_ids"] = list(session.get("unincorporated_capture_batch_ids") or []) + [batch_id]
    session["state"] = "needs_draft_revision"
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(session["onboarding_id"]), required=False)
    if workplan is None:
        workplan = default_onboarding_workplan(onboarding_id=str(session["onboarding_id"]))
    _set_workplan_step(
        workplan,
        "clarification_incorporated",
        status="blocked",
        blocking_reason="New clarification batches must be explicitly incorporated into a revision.",
        artifact_refs=[batch_id],
    )
    _set_workplan_step(
        workplan,
        "confirmation_readiness_passed",
        status="blocked",
        blocking_reason="Confirmation readiness is stale until clarification is incorporated into a new revision.",
        artifact_refs=[batch_id],
    )
    session["current_workplan_id"] = str(session["onboarding_id"])
    session["workplan_step_statuses"] = _workplan_status_map(workplan)
    save_onboarding_session(data_root=data_root, session=session)
    workplan_path = save_onboarding_workplan(data_root=data_root, workplan=workplan)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "capture_batch_id": batch_id,
        "capture_artifact_path": receipt["artifact_path"],
        "capture_ledger_path": receipt["ledger_path"],
        "linked_question_ids": linked_question_ids,
        "onboarding_state": session.get("state"),
        "workplan_path": workplan_path,
        "batch": receipt["batch"],
    }


def onboarding_confirm(
    *,
    subject: str,
    data_root: Path,
    session: dict[str, Any],
    active_run: dict[str, Any],
) -> dict[str, Any]:
    draft = load_current_draft(data_root=data_root, session=session, required=True)
    question_set = load_current_question_set(data_root=data_root, session=session, required=True)
    session, workplan = _ensure_part2_revision_artifacts(
        data_root=data_root,
        session=session,
        draft=draft,
        question_set=question_set,
    )
    if workplan is None:
        raise RepoOnboardingError(
            f"Unable to prepare onboarding workplan for confirmation: {onboarding_workplan_path(data_root, str(session['onboarding_id']))}"
        )
    required_artifact_paths = current_revision_artifact_paths(data_root=data_root, session=session)
    readiness = evaluate_confirmation_readiness(
        onboarding_state=str(session.get("state") or ""),
        current_scan_id=str(session.get("current_scan_id") or ""),
        unincorporated_capture_batch_ids=list(session.get("unincorporated_clarification_batch_ids") or session.get("unincorporated_capture_batch_ids") or []),
        draft=draft,
        question_set=question_set,
        required_artifact_paths=required_artifact_paths,
        workplan=workplan,
    )
    if not readiness["ready"]:
        raise RepoOnboardingError("Confirmation readiness failed: " + "; ".join(readiness["blocking_reasons"]))
    onboarding_id = str(session["onboarding_id"])
    confirmed_at = _now_iso()
    confirmed_by = str(active_run.get("session_id") or "").strip() or "unknown_session"
    published_model = build_published_project_model(
        onboarding_id=onboarding_id,
        confirmed_at=confirmed_at,
        confirmed_by=confirmed_by,
        draft=draft,
        question_set=question_set,
    )
    project_story = render_project_story(published_model)
    vision_text = render_published_vision(published_model)
    codex_current_text = render_published_codex_current(published_model)
    codex_future_text = render_published_codex_future(published_model)
    archive_model = archived_project_model_path(data_root, onboarding_id)
    archive_story = archived_project_story_path(data_root, onboarding_id)
    archive_vision = archived_vision_path(data_root, onboarding_id)
    archive_codex_current = archived_codex_current_path(data_root, onboarding_id)
    archive_codex_future = archived_codex_future_path(data_root, onboarding_id)
    archive_receipt = publication_receipt_path(data_root, onboarding_id)
    archive_model.write_text(yaml.safe_dump(published_model, sort_keys=False), encoding="utf-8")
    archive_story.write_text(project_story, encoding="utf-8")
    archive_vision.write_text(vision_text, encoding="utf-8")
    archive_codex_current.write_text(codex_current_text, encoding="utf-8")
    archive_codex_future.write_text(codex_future_text, encoding="utf-8")
    receipt = {
        "onboarding_id": onboarding_id,
        "confirmed_at": confirmed_at,
        "confirmed_by": confirmed_by,
        "draft_revision_id": draft.get("revision_id"),
        "question_set_id": question_set.get("question_set_id"),
        "published_project_model_path": str(archive_model.resolve()),
        "published_project_story_path": str(archive_story.resolve()),
        "published_vision_path": str(archive_vision.resolve()),
        "published_codex_current_path": str(archive_codex_current.resolve()),
        "published_codex_future_path": str(archive_codex_future.resolve()),
        "workplan_path": str(onboarding_workplan_path(data_root, onboarding_id).resolve()),
        "compiled_current_state_path": None,
        "compiled_at": None,
        "compile_status": "pending",
        "proposal_paths": [],
    }
    _write_publication_receipt(archive_receipt, receipt)
    _atomic_publish_copy(archive_model, canonical_project_model_path(data_root))
    _atomic_publish_copy(archive_story, canonical_project_story_path(data_root))
    _atomic_publish_copy(archive_vision, canonical_vision_path(data_root))
    _atomic_publish_copy(archive_codex_current, canonical_codex_current_path(data_root))
    _atomic_publish_copy(archive_codex_future, canonical_codex_future_path(data_root))
    proposal_paths = seed_onboarding_proposals(
        subject=subject,
        data_root=data_root,
        active_run=active_run,
        published_model=published_model,
        question_set=question_set,
    )
    receipt["proposal_paths"] = proposal_paths
    compile_result: dict[str, Any] | None = None
    compile_error_message: str | None = None
    try:
        from synapse_runtime.truth_compiler import canonical_truth_publication_paths, compile_current_state, load_compiler_report

        compile_result = compile_current_state(subject=subject, data_root=data_root, engine_root=Path(str(session["engine_root"])))
        report = load_compiler_report(data_root) or {}
        truth_publication_paths = dict(compile_result.get("publication_paths") or canonical_truth_publication_paths(data_root))
        receipt["compiled_current_state_path"] = str(truth_publication_paths.get("current_state") or "")
        receipt["compiled_at"] = str(report.get("compiled_at") or "")
        receipt["compile_status"] = "ok"
    except Exception as exc:
        compile_error_message = str(exc)
        if exc.__class__.__name__ == "TruthCompilerPartialError":
            payload = dict(getattr(exc, "payload", {}) or {})
            compile_result = payload
            receipt["compiled_current_state_path"] = str((payload.get("publication_paths") or {}).get("current_state") or "")
            receipt["compile_status"] = "partial"
        else:
            receipt["compile_status"] = "failed"
    _write_publication_receipt(archive_receipt, receipt)

    session = dict(session)
    session["state"] = "confirmed"
    session["confirmed_at"] = confirmed_at
    session["confirmed_by"] = confirmed_by
    session["published_archive_project_model_path"] = str(archive_model.resolve())
    session["published_archive_project_story_path"] = str(archive_story.resolve())
    session["published_archive_vision_path"] = str(archive_vision.resolve())
    session["published_archive_codex_current_path"] = str(archive_codex_current.resolve())
    session["published_archive_codex_future_path"] = str(archive_codex_future.resolve())
    session["published_project_model_path"] = str(canonical_project_model_path(data_root).resolve())
    session["published_project_story_path"] = str(canonical_project_story_path(data_root).resolve())
    session["published_vision_path"] = str(canonical_vision_path(data_root).resolve())
    session["published_codex_current_path"] = str(canonical_codex_current_path(data_root).resolve())
    session["published_codex_future_path"] = str(canonical_codex_future_path(data_root).resolve())
    _set_workplan_step(
        workplan,
        "confirmation_readiness_passed",
        status="complete",
        artifact_refs=[str(archive_receipt.resolve())],
    )
    _set_workplan_step(
        workplan,
        "canonical_publication_complete",
        status="complete",
        artifact_refs=[
            str(archive_model.resolve()),
            str(archive_story.resolve()),
            str(archive_vision.resolve()),
            str(archive_codex_current.resolve()),
            str(archive_codex_future.resolve()),
            str(archive_receipt.resolve()),
        ],
    )
    if receipt["compile_status"] == "ok":
        _set_workplan_step(
            workplan,
            "post_publication_compile_complete",
            status="complete",
            artifact_refs=[receipt["compiled_current_state_path"], str(archive_receipt.resolve())],
        )
    else:
        _set_workplan_step(
            workplan,
            "post_publication_compile_complete",
            status="blocked",
            blocking_reason=compile_error_message or "Post-publication compile did not complete successfully.",
            artifact_refs=[str(archive_receipt.resolve())],
        )
    session["current_workplan_id"] = onboarding_id
    session["workplan_step_statuses"] = _workplan_status_map(workplan)
    save_onboarding_session(data_root=data_root, session=session)
    workplan_path = save_onboarding_workplan(data_root=data_root, workplan=workplan)
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=False)
    pointer["current_onboarding_id"] = None
    pointer["latest_confirmed_onboarding_id"] = onboarding_id
    save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return {
        "onboarding_id": onboarding_id,
        "published_project_model_path": str(canonical_project_model_path(data_root).resolve()),
        "published_project_story_path": str(canonical_project_story_path(data_root).resolve()),
        "published_vision_path": str(canonical_vision_path(data_root).resolve()),
        "published_codex_current_path": str(canonical_codex_current_path(data_root).resolve()),
        "published_codex_future_path": str(canonical_codex_future_path(data_root).resolve()),
        "publication_receipt_path": str(archive_receipt.resolve()),
        "workplan_path": workplan_path,
        "proposal_paths": proposal_paths,
        "compile_status": receipt["compile_status"],
        "compiled_current_state_path": receipt["compiled_current_state_path"] or None,
        "compiled_at": receipt["compiled_at"] or None,
        "truth_compile": compile_result,
        "compile_error_message": compile_error_message,
    }


def onboarding_abandon(*, subject: str, data_root: Path, session: dict[str, Any], reason: str) -> dict[str, Any]:
    if str(session.get("state") or "") == "confirmed":
        raise RepoOnboardingError("Confirmed onboarding sessions cannot be abandoned. Use onboard-repo --restart instead.")
    updated = abandon_onboarding_session(data_root=data_root, session=session, reason=reason)
    workplan = load_onboarding_workplan(data_root=data_root, onboarding_id=str(updated["onboarding_id"]), required=False)
    if workplan is not None:
        _set_workplan_step(
            workplan,
            "canonical_publication_complete",
            status="blocked",
            blocking_reason="Onboarding was abandoned before canonical publication completed.",
            artifact_refs=[],
        )
        save_onboarding_workplan(data_root=data_root, workplan=workplan)
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=False)
    pointer["current_onboarding_id"] = None
    save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return {
        "onboarding_id": updated.get("onboarding_id"),
        "state": updated.get("state"),
        "abandon_reason": updated.get("abandon_reason"),
    }


def abandon_onboarding_session(*, data_root: Path, session: dict[str, Any], reason: str) -> dict[str, Any]:
    state = str(session.get("state") or "")
    if state == "confirmed":
        raise RepoOnboardingError("Confirmed onboarding sessions cannot transition to abandoned.")
    updated = dict(session)
    updated["state"] = "abandoned"
    updated["abandoned_at"] = _now_iso()
    updated["abandon_reason"] = str(reason).strip()
    save_onboarding_session(data_root=data_root, session=updated)
    return updated


def onboarding_projection(
    *,
    subject: str,
    data_root: Path,
    rebuild: bool = True,
    persist_pointer: bool = True,
    ensure_scaffold: bool = True,
) -> dict[str, Any]:
    pointer = load_onboarding_pointer(
        subject=subject,
        data_root=data_root,
        rebuild=rebuild,
        persist=persist_pointer,
        ensure_scaffold=ensure_scaffold,
    )
    active_session = current_onboarding_session(
        subject=subject,
        data_root=data_root,
        require_current=False,
        rebuild=rebuild,
        persist_pointer=persist_pointer,
        ensure_scaffold=ensure_scaffold,
    )
    if not active_session:
        return {
            "adopted_existing_repo": bool(pointer.get("adopted_existing_repo")),
            "active_onboarding_id": None,
            "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
            "onboarding_state": None,
            "current_scan_id": None,
            "current_draft_id": None,
            "current_question_set_id": None,
            "current_workplan_id": None,
            "workplan_step_statuses": {},
            "unincorporated_capture_batch_ids": [],
            "unincorporated_clarification_batch_ids": [],
            "published_project_model_path": None,
            "published_project_story_path": None,
            "published_vision_path": None,
            "published_codex_current_path": None,
            "published_codex_future_path": None,
            "project_model_confirmed_at": None,
            "project_summary": None,
            "project_purpose_summary": None,
            "project_capability_summary": [],
            "project_constraint_summary": [],
            "project_history_summary": [],
            "project_open_question_details": [],
            "project_model_open_questions_count": 0,
            "project_model_blocking_questions_count": 0,
            "draft_is_stale": False,
        }
    question_set = load_current_question_set(data_root=data_root, session=active_session, required=False)
    draft = load_current_draft(data_root=data_root, session=active_session, required=False)
    published_model = None
    if active_session.get("published_project_model_path"):
        published_model = load_yaml_artifact(Path(str(active_session["published_project_model_path"])), required_field="onboarding_id")
    projection = {
        "adopted_existing_repo": bool(pointer.get("adopted_existing_repo")),
        "active_onboarding_id": active_session.get("onboarding_id") if active_session.get("state") in ONBOARDING_NONTERMINAL_STATES else None,
        "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
        "onboarding_state": active_session.get("state"),
        "current_scan_id": active_session.get("current_scan_id"),
        "current_draft_id": active_session.get("current_draft_id"),
        "current_question_set_id": active_session.get("current_question_set_id"),
        "current_workplan_id": active_session.get("current_workplan_id"),
        "workplan_step_statuses": dict(active_session.get("workplan_step_statuses") or {}),
        "unincorporated_capture_batch_ids": list(active_session.get("unincorporated_capture_batch_ids") or []),
        "unincorporated_clarification_batch_ids": list(active_session.get("unincorporated_clarification_batch_ids") or []),
        "published_project_model_path": active_session.get("published_project_model_path"),
        "published_project_story_path": active_session.get("published_project_story_path"),
        "published_vision_path": active_session.get("published_vision_path"),
        "published_codex_current_path": active_session.get("published_codex_current_path"),
        "published_codex_future_path": active_session.get("published_codex_future_path"),
        "project_model_confirmed_at": (
            published_model.get("confirmed_at") if isinstance(published_model, dict) and published_model.get("confirmed_at") else active_session.get("confirmed_at")
        ),
        "draft_is_stale": draft_is_stale(session=active_session, draft=draft),
    }
    if published_model is not None:
        projection.update(project_model_projection(published_model, question_set))
    else:
        projection.update(
            {
                "project_summary": None,
                "project_purpose_summary": None,
                "project_capability_summary": [],
                "project_constraint_summary": [],
                "project_history_summary": [],
                "project_open_question_details": [
                    {
                        "question_id": item.get("question_id"),
                        "prompt": item.get("prompt"),
                        "priority": item.get("priority"),
                        "status": item.get("status"),
                    }
                    for item in (question_set or {}).get("questions") or []
                    if item.get("status") == "open"
                ],
                "project_model_open_questions_count": sum(
                    1 for item in (question_set or {}).get("questions") or [] if item.get("status") == "open"
                ),
                "project_model_blocking_questions_count": sum(
                    1
                    for item in (question_set or {}).get("questions") or []
                    if item.get("status") == "open" and item.get("priority") == "blocking"
                ),
            }
        )
    return projection


def draft_is_stale(*, session: dict[str, Any], draft: dict[str, Any] | None) -> bool:
    if not draft:
        return False
    based_on_scan_ids = set(draft.get("based_on_scan_ids") or [])
    if str(session.get("current_scan_id") or "") not in based_on_scan_ids:
        return True
    based_on_capture_ids = set(draft.get("based_on_capture_batch_ids") or [])
    outstanding = list(session.get("unincorporated_capture_batch_ids") or [])
    return any(item not in based_on_capture_ids for item in outstanding)


def register_onboarding_continuity_capture(
    *,
    data_root: Path,
    session: dict[str, Any],
    capture_batch_id: str,
) -> dict[str, Any]:
    updated = dict(session)
    outstanding = list(updated.get("unincorporated_capture_batch_ids") or [])
    if capture_batch_id not in outstanding:
        outstanding.append(capture_batch_id)
    updated["unincorporated_capture_batch_ids"] = outstanding
    clarification_outstanding = list(updated.get("unincorporated_clarification_batch_ids") or [])
    if capture_batch_id not in clarification_outstanding:
        clarification_outstanding.append(capture_batch_id)
    updated["unincorporated_clarification_batch_ids"] = clarification_outstanding
    if str(updated.get("state") or "") == "awaiting_confirmation":
        updated["state"] = "needs_draft_revision"
    save_onboarding_session(data_root=data_root, session=updated)
    return updated


def current_revision_artifact_paths(*, data_root: Path, session: dict[str, Any]) -> dict[str, str | None]:
    revision_id = str(session.get("current_draft_id") or "").strip()
    question_set_id = str(session.get("current_question_set_id") or "").strip()
    onboarding_id = str(session.get("onboarding_id") or "").strip()
    artifact_paths: dict[str, str | None] = {
        "draft_model": str(onboarding_draft_path(data_root, revision_id).resolve()) if revision_id else None,
        "draft_question_set": str(onboarding_question_set_path(data_root, question_set_id).resolve()) if question_set_id else None,
        "draft_story": str(onboarding_story_draft_path(data_root, revision_id).resolve()) if revision_id else None,
        "draft_vision": str(onboarding_vision_draft_path(data_root, revision_id).resolve()) if revision_id else None,
        "draft_codex_current": str(onboarding_codex_current_draft_path(data_root, revision_id).resolve()) if revision_id else None,
        "draft_codex_future": str(onboarding_codex_future_draft_path(data_root, revision_id).resolve()) if revision_id else None,
        "workplan": str(onboarding_workplan_path(data_root, onboarding_id).resolve()) if onboarding_id else None,
    }
    revision_delta_ids = list(session.get("revision_delta_ids") or [])
    if revision_delta_ids:
        artifact_paths["revision_delta"] = str(onboarding_delta_path(data_root, str(revision_delta_ids[-1])).resolve())
    return artifact_paths


def load_current_scan(*, data_root: Path, session: dict[str, Any], required: bool) -> dict[str, Any] | None:
    scan_id = str(session.get("current_scan_id") or "").strip()
    if not scan_id:
        if required:
            raise RepoOnboardingError("Current onboarding session has no current_scan_id.")
        return None
    path = live_root(data_root) / "ONBOARDING" / "SCANS" / f"SCAN__{scan_id}.yaml"
    if not path.exists():
        raise RepoArchaeologyError(f"Referenced onboarding scan artifact is missing: {path}")
    return load_scan_artifact(path)


def load_current_draft(*, data_root: Path, session: dict[str, Any], required: bool) -> dict[str, Any] | None:
    revision_id = str(session.get("current_draft_id") or "").strip()
    if not revision_id:
        if required:
            raise RepoOnboardingError("Current onboarding session has no current_draft_id.")
        return None
    path = onboarding_draft_path(data_root, revision_id)
    if not path.exists():
        raise ProjectModelError(f"Referenced onboarding draft artifact is missing: {path}")
    return load_yaml_artifact(path, required_field="revision_id")


def load_current_question_set(*, data_root: Path, session: dict[str, Any], required: bool) -> dict[str, Any] | None:
    question_set_id = str(session.get("current_question_set_id") or "").strip()
    if not question_set_id:
        if required:
            raise RepoOnboardingError("Current onboarding session has no current_question_set_id.")
        return None
    path = onboarding_question_set_path(data_root, question_set_id)
    if not path.exists():
        raise ProjectModelError(f"Referenced onboarding question-set artifact is missing: {path}")
    return load_yaml_artifact(path, required_field="question_set_id")


def seed_onboarding_proposals(
    *,
    subject: str,
    data_root: Path,
    active_run: dict[str, Any],
    published_model: dict[str, Any],
    question_set: dict[str, Any],
) -> list[str]:
    live = live_root(data_root)
    source_id = str(active_run.get("run_id") or "NO_RUN")
    interaction_mode = str(active_run.get("interaction_mode") or "exploration")
    signal = AmbientSignal(
        source="onboarding-confirm",
        subject=subject,
        title=str(published_model.get("project_identity") or "Published project model"),
        summary=str(published_model.get("purpose") or ""),
        status="confirmed",
    )
    proposal_payloads: list[dict[str, Any]] = []
    proposal_paths: list[str] = []
    current_accepted = select_current_accepted_quest(load_accepted_quest_details(subject, data_root))

    codex_promotion = PromotionRecord(
        kind=ProposalKind.CODEX,
        state=ProposalState.AMBIENT,
        title=f"Codify project picture - {published_model.get('project_identity')}",
        summary="Refresh codex guidance from the confirmed onboarding project model.",
        reason="Confirmed onboarding publication produced repo facts, constraints, non-goals, and interfaces that should be reflected in codex guidance.",
        evidence=(published_model.get("onboarding_id") or "",),
    )
    build_manual_promotion = PromotionRecord(
        kind=ProposalKind.BUILD_MANUAL,
        state=ProposalState.AMBIENT,
        title=f"Refresh build manual - {published_model.get('project_identity')}",
        summary="Reflect confirmed architecture, components, dependencies, and milestones in the build manual backlog.",
        reason="Confirmed onboarding publication surfaced architecture and implementation details that should seed the build manual backlog.",
        evidence=(published_model.get("onboarding_id") or "",),
    )
    for promotion in (codex_promotion, build_manual_promotion):
        proposal_payloads.append(
            {
                "proposal_id": _proposal_id(promotion.kind, source_id, promotion.title),
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

    quest_candidates = [
        item
        for item in published_model.get("partial_or_intended_capabilities") or []
        if item.get("status") in {"partial", "intended"}
    ]
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    for item in sorted(quest_candidates, key=lambda entry: (confidence_rank.get(entry.get("confidence"), 3), str(entry.get("id") or "")))[:3]:
        promotion = PromotionRecord(
            kind=ProposalKind.QUEST,
            state=ProposalState.AMBIENT,
            title=str(item.get("summary") or "Onboarding execution front"),
            summary=f"Confirmed onboarding surfaced a partial or intended capability front: {item.get('summary')}",
            reason="Confirmed onboarding identified a high-confidence execution front that should be tracked as a quest candidate.",
            evidence=(published_model.get("onboarding_id") or "", str(item.get("id") or "")),
        )
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
            proposal_paths.append(str(candidate["path"]))

    important_open_questions = [
        item for item in question_set.get("questions") or [] if item.get("priority") == "important" and item.get("status") == "open"
    ]
    if important_open_questions:
        promotion = PromotionRecord(
            kind=ProposalKind.CONTROL_SYNC,
            state=ProposalState.AMBIENT,
            title=f"Resolve remaining project questions - {published_model.get('project_identity')}",
            summary="Confirmed onboarding left important unresolved questions that should be reviewed in control sync.",
            reason="Confirmed onboarding still has important unresolved questions that merit control-sync review.",
            evidence=(published_model.get("onboarding_id") or "",),
        )
        proposal_payloads.append(
            {
                "proposal_id": _proposal_id(promotion.kind, source_id, promotion.title),
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

    proposal_paths.extend(
        _write_proposals(
            live=live,
            subject=subject,
            source_id=source_id,
            interaction_mode=interaction_mode,
            promotions=proposal_payloads,
        )
    )
    return proposal_paths


def _pointer_is_stale(pointer: dict[str, Any], data_root: Path) -> bool:
    current_id = str(pointer.get("current_onboarding_id") or "").strip()
    latest_id = str(pointer.get("latest_confirmed_onboarding_id") or "").strip()
    if current_id:
        path = onboarding_session_path(data_root, current_id)
        if not path.exists():
            return True
        session = load_onboarding_session(path)
        if str(session.get("state") or "") not in ONBOARDING_NONTERMINAL_STATES:
            return True
    if latest_id:
        path = onboarding_session_path(data_root, latest_id)
        if not path.exists():
            return True
        session = load_onboarding_session(path)
        if str(session.get("state") or "") != "confirmed":
            return True
    return False


def _question_priority_counts(question_set: dict[str, Any] | None) -> tuple[int, int]:
    if not isinstance(question_set, dict):
        return 0, 0
    blocking = 0
    important = 0
    for item in question_set.get("questions") or []:
        if item.get("status") != "open":
            continue
        if item.get("priority") == "blocking":
            blocking += 1
        elif item.get("priority") == "important":
            important += 1
    return blocking, important


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RepoOnboardingError(f"Unable to read onboarding artifact: {path}") from exc


def _opaque_id(prefix: str) -> str:
    return f"{prefix}-{_now_iso().replace(':', '').replace('-', '').replace('+', 'Z').replace('.', '')}"


def default_onboarding_workplan(*, onboarding_id: str) -> dict[str, Any]:
    now = _now_iso()
    return {
        "onboarding_id": onboarding_id,
        "workplan_id": onboarding_id,
        "steps": [
            _workplan_step_payload("archaeology_complete", "Archaeology complete", now),
            _workplan_step_payload("evidence_review_complete", "Evidence review complete", now),
            _workplan_step_payload("draft_model_written", "Draft model written", now),
            _workplan_step_payload("draft_story_written", "Draft story written", now),
            _workplan_step_payload("draft_vision_written", "Draft vision written", now),
            _workplan_step_payload("draft_current_codex_written", "Draft current codex written", now),
            _workplan_step_payload("draft_future_codex_written", "Draft future codex written", now),
            _workplan_step_payload("question_set_written", "Question set written", now),
            _workplan_step_payload("clarification_incorporated", "Clarification incorporated", now),
            _workplan_step_payload("confirmation_readiness_passed", "Confirmation readiness passed", now),
            _workplan_step_payload("canonical_publication_complete", "Canonical publication complete", now),
            _workplan_step_payload("post_publication_compile_complete", "Post-publication compile complete", now),
        ],
        "updated_at": now,
    }


def _workplan_step_payload(step_id: str, label: str, updated_at: str) -> dict[str, Any]:
    blocking = step_id not in {
        "confirmation_readiness_passed",
        "canonical_publication_complete",
        "post_publication_compile_complete",
    }
    return {
        "step_id": step_id,
        "step": label,
        "blocking": blocking,
        "status": "pending",
        "updated_at": updated_at,
        "blocking_reason": None,
        "artifact_refs": [],
    }


def _normalize_workplan(workplan: dict[str, Any], *, onboarding_id: str) -> dict[str, Any]:
    normalized = dict(workplan)
    normalized["onboarding_id"] = onboarding_id
    normalized["workplan_id"] = str(normalized.get("workplan_id") or onboarding_id)
    current_steps = {str(item.get("step_id") or ""): dict(item) for item in list(normalized.get("steps") or []) if isinstance(item, dict)}
    normalized_steps: list[dict[str, Any]] = []
    for template in default_onboarding_workplan(onboarding_id=onboarding_id)["steps"]:
        step_id = str(template["step_id"])
        item = dict(template)
        item.update(current_steps.get(step_id, {}))
        item["step_id"] = step_id
        item["step"] = str(item.get("step") or template["step"])
        item["blocking"] = bool(item.get("blocking", True))
        item["status"] = str(item.get("status") or "pending")
        item["updated_at"] = str(item.get("updated_at") or _now_iso())
        item["blocking_reason"] = str(item.get("blocking_reason") or "").strip() or None
        item["artifact_refs"] = [str(value).strip() for value in list(item.get("artifact_refs") or []) if str(value).strip()]
        normalized_steps.append(item)
    normalized["steps"] = normalized_steps
    normalized["updated_at"] = _now_iso()
    return normalized


def _set_workplan_step(
    workplan: dict[str, Any],
    step_id: str,
    *,
    status: str,
    artifact_refs: list[str] | None = None,
    blocking_reason: str | None = None,
) -> None:
    normalized = _normalize_workplan(workplan, onboarding_id=str(workplan.get("onboarding_id") or ""))
    updated = False
    for item in normalized["steps"]:
        if str(item.get("step_id") or "") != step_id:
            continue
        item["status"] = status
        item["updated_at"] = _now_iso()
        item["blocking_reason"] = str(blocking_reason or "").strip() or None
        item["artifact_refs"] = [str(value).strip() for value in list(artifact_refs or []) if str(value).strip()]
        updated = True
        break
    if not updated:
        raise RepoOnboardingError(f"Unknown onboarding workplan step: {step_id}")
    workplan.clear()
    workplan.update(normalized)


def _workplan_status_map(workplan: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("step_id") or ""): str(item.get("status") or "")
        for item in list(workplan.get("steps") or [])
        if isinstance(item, dict) and str(item.get("step_id") or "").strip()
    }


def _normalize_onboarding_session(session: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(session)
    clarification = list(normalized.get("clarification_batch_ids") or normalized.get("clarification_capture_batch_ids") or [])
    unincorporated = list(
        normalized.get("unincorporated_clarification_batch_ids") or normalized.get("unincorporated_capture_batch_ids") or []
    )
    normalized["clarification_batch_ids"] = clarification
    normalized["clarification_capture_batch_ids"] = clarification
    normalized["unincorporated_clarification_batch_ids"] = unincorporated
    normalized["unincorporated_capture_batch_ids"] = unincorporated
    normalized.setdefault("current_workplan_id", str(normalized.get("onboarding_id") or "") or None)
    normalized["workplan_step_statuses"] = dict(normalized.get("workplan_step_statuses") or {})
    normalized.setdefault("last_incorporated_clarification_batch_id", None)
    normalized.setdefault("published_archive_codex_current_path", None)
    normalized.setdefault("published_archive_codex_future_path", None)
    normalized.setdefault("published_codex_current_path", None)
    normalized.setdefault("published_codex_future_path", None)
    return normalized


def _write_artifact_family(artifacts: dict[Path, str]) -> None:
    written: list[Path] = []
    try:
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
    except Exception as exc:
        for path in reversed(written):
            if path.exists():
                path.unlink()
        raise RepoOnboardingError(f"Unable to write complete onboarding draft artifact family: {exc}") from exc

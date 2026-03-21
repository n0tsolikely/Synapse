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
    render_project_story,
    render_published_vision,
    validate_draft_revision,
    validate_question_set,
)
from synapse_runtime.quest_candidates import QUEST_PROPOSAL_KINDS, _proposal_id, _upsert_quest_candidate, _write_proposals
from synapse_runtime.repo_archaeology import RepoArchaeologyError, ScanDepth, load_scan_artifact, run_repo_archaeology
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


def onboarding_brief_path(data_root: Path, scan_id: str) -> Path:
    return onboarding_briefs_dir(data_root) / f"ONBOARDING_BRIEF__{scan_id}.md"


def archived_project_model_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PROJECT_MODEL__{onboarding_id}.yaml"


def archived_project_story_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PROJECT_STORY__{onboarding_id}.md"


def archived_vision_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"VISION__{onboarding_id}.md"


def publication_receipt_path(data_root: Path, onboarding_id: str) -> Path:
    return onboarding_published_dir(data_root) / f"PUBLICATION_RECEIPT__{onboarding_id}.yaml"


def canonical_project_model_path(data_root: Path) -> Path:
    return live_root(data_root) / "PROJECT_MODEL.yaml"


def canonical_project_story_path(data_root: Path) -> Path:
    return live_root(data_root) / "PROJECT_STORY.md"


def canonical_vision_path(data_root: Path) -> Path:
    return live_root(data_root) / "VISION.md"


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
        "clarification_capture_batch_ids": [],
        "unincorporated_capture_batch_ids": [],
        "revision_delta_ids": [],
        "published_archive_project_model_path": None,
        "published_archive_project_story_path": None,
        "published_archive_vision_path": None,
        "published_project_model_path": None,
        "published_project_story_path": None,
        "published_vision_path": None,
        "confirmed_at": None,
        "confirmed_by": None,
        "abandoned_at": None,
        "abandon_reason": None,
    }


def ensure_onboarding_scaffold(subject: str, data_root: Path) -> None:
    ensure_live_scaffold(subject, data_root)


def load_onboarding_pointer(*, subject: str, data_root: Path, rebuild: bool = True) -> dict[str, Any]:
    ensure_onboarding_scaffold(subject, data_root)
    path = onboarding_current_path(data_root)
    payload = _read_yaml(path)
    if isinstance(payload, dict):
        payload.setdefault("subject", subject)
        payload.setdefault("current_onboarding_id", None)
        payload.setdefault("latest_confirmed_onboarding_id", None)
        payload.setdefault("updated_at", _now_iso())
        if rebuild and _pointer_is_stale(payload, data_root):
            rebuilt = reconstruct_onboarding_pointer(subject=subject, data_root=data_root)
            save_onboarding_pointer(data_root=data_root, pointer=rebuilt)
            return rebuilt
        return payload
    if rebuild:
        rebuilt = reconstruct_onboarding_pointer(subject=subject, data_root=data_root)
        save_onboarding_pointer(data_root=data_root, pointer=rebuilt)
        return rebuilt
    pointer = default_onboarding_pointer(subject)
    save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return pointer


def reconstruct_onboarding_pointer(*, subject: str, data_root: Path) -> dict[str, Any]:
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
    return payload


def save_onboarding_pointer(*, data_root: Path, pointer: dict[str, Any]) -> str:
    path = onboarding_current_path(data_root)
    payload = dict(pointer)
    payload["updated_at"] = _now_iso()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def save_onboarding_session(*, data_root: Path, session: dict[str, Any]) -> str:
    path = onboarding_session_path(data_root, str(session["onboarding_id"]))
    payload = dict(session)
    payload["updated_at"] = _now_iso()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def transition_onboarding_state(session: dict[str, Any], target_state: str) -> dict[str, Any]:
    current_state = str(session.get("state") or "").strip()
    allowed = _ALLOWED_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise RepoOnboardingError(f"Invalid onboarding transition: {current_state} -> {target_state}")
    updated = dict(session)
    updated["state"] = target_state
    updated["updated_at"] = _now_iso()
    return updated


def current_onboarding_session(*, subject: str, data_root: Path, require_current: bool = True) -> dict[str, Any] | None:
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=True)
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


def onboarding_status_payload(*, subject: str, data_root: Path) -> dict[str, Any]:
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=True)
    session = current_onboarding_session(subject=subject, data_root=data_root, require_current=False)
    if not session:
        return {
            "onboarding_id": None,
            "state": None,
            "depth": None,
            "current_scan_id": None,
            "current_draft_id": None,
            "current_question_set_id": None,
            "clarification_capture_batch_ids": [],
            "unincorporated_capture_batch_ids": [],
            "blocking_open_question_count": 0,
            "important_open_question_count": 0,
            "draft_is_stale": False,
            "published_project_model_path": None,
            "published_project_story_path": None,
            "published_vision_path": None,
            "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
        }
    question_set = load_current_question_set(data_root=data_root, session=session, required=False)
    draft = load_current_draft(data_root=data_root, session=session, required=False)
    blocking_count, important_count = _question_priority_counts(question_set)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "state": session.get("state"),
        "depth": session.get("depth"),
        "current_scan_id": session.get("current_scan_id"),
        "current_draft_id": session.get("current_draft_id"),
        "current_question_set_id": session.get("current_question_set_id"),
        "clarification_capture_batch_ids": list(session.get("clarification_capture_batch_ids") or []),
        "unincorporated_capture_batch_ids": list(session.get("unincorporated_capture_batch_ids") or []),
        "blocking_open_question_count": blocking_count,
        "important_open_question_count": important_count,
        "draft_is_stale": draft_is_stale(session=session, draft=draft),
        "published_project_model_path": session.get("published_project_model_path"),
        "published_project_story_path": session.get("published_project_story_path"),
        "published_vision_path": session.get("published_vision_path"),
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
    session_path = save_onboarding_session(data_root=data_root, session=session)
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
        linked_capture_batch_ids=list(session.get("clarification_capture_batch_ids") or []),
        prior_question_set=prior_questions,
    )
    revision_path = onboarding_draft_path(data_root, str(normalized_draft["revision_id"]))
    revision_path.write_text(yaml.safe_dump(normalized_draft, sort_keys=False), encoding="utf-8")
    question_path = onboarding_question_set_path(data_root, str(normalized_questions["question_set_id"]))
    question_path.write_text(yaml.safe_dump(normalized_questions, sort_keys=False), encoding="utf-8")
    delta = compute_revision_delta(normalized_draft, prior_draft, reason_summary=reason_summary or "Patched onboarding draft.")
    delta_id = None
    if delta is not None:
        delta_id = str(delta["revision_id"])
        delta_path = onboarding_delta_path(data_root, delta_id)
        delta_path.write_text(yaml.safe_dump(delta, sort_keys=False), encoding="utf-8")
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
        item for item in list(session.get("unincorporated_capture_batch_ids") or []) if item not in incorporated
    ]
    session["unincorporated_capture_batch_ids"] = remaining_unincorporated
    readiness_ok, _ = evaluate_confirmation_readiness(
        onboarding_state="awaiting_confirmation",
        current_scan_id=str(session.get("current_scan_id") or ""),
        unincorporated_capture_batch_ids=remaining_unincorporated,
        draft=normalized_draft,
        question_set=normalized_questions,
    )
    blocking_count, _ = _question_priority_counts(normalized_questions)
    session["state"] = "awaiting_confirmation" if blocking_count == 0 and readiness_ok else "awaiting_user_clarification"
    save_onboarding_session(data_root=data_root, session=session)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "draft_revision_id": normalized_draft["revision_id"],
        "question_set_id": normalized_questions["question_set_id"],
        "revision_delta_id": delta_id,
        "onboarding_state": session.get("state"),
        "superseded_item_count": len((delta or {}).get("superseded_item_ids") or []),
        "draft_path": str(revision_path.resolve()),
        "question_set_path": str(question_path.resolve()),
        "delta_path": str(onboarding_delta_path(data_root, delta_id).resolve()) if delta_id is not None else None,
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
    session.setdefault("clarification_capture_batch_ids", [])
    session.setdefault("unincorporated_capture_batch_ids", [])
    session["clarification_capture_batch_ids"] = list(session.get("clarification_capture_batch_ids") or []) + [batch_id]
    session["unincorporated_capture_batch_ids"] = list(session.get("unincorporated_capture_batch_ids") or []) + [batch_id]
    session["state"] = "needs_draft_revision"
    save_onboarding_session(data_root=data_root, session=session)
    return {
        "onboarding_id": session.get("onboarding_id"),
        "capture_batch_id": batch_id,
        "capture_artifact_path": receipt["artifact_path"],
        "capture_ledger_path": receipt["ledger_path"],
        "linked_question_ids": linked_question_ids,
        "onboarding_state": session.get("state"),
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
    readiness_ok, readiness_errors = evaluate_confirmation_readiness(
        onboarding_state=str(session.get("state") or ""),
        current_scan_id=str(session.get("current_scan_id") or ""),
        unincorporated_capture_batch_ids=list(session.get("unincorporated_capture_batch_ids") or []),
        draft=draft,
        question_set=question_set,
    )
    if not readiness_ok:
        raise RepoOnboardingError("Confirmation readiness failed: " + "; ".join(readiness_errors))
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
    archive_model = archived_project_model_path(data_root, onboarding_id)
    archive_story = archived_project_story_path(data_root, onboarding_id)
    archive_vision = archived_vision_path(data_root, onboarding_id)
    archive_receipt = publication_receipt_path(data_root, onboarding_id)
    archive_model.write_text(yaml.safe_dump(published_model, sort_keys=False), encoding="utf-8")
    archive_story.write_text(project_story, encoding="utf-8")
    archive_vision.write_text(vision_text, encoding="utf-8")
    receipt = {
        "onboarding_id": onboarding_id,
        "confirmed_at": confirmed_at,
        "confirmed_by": confirmed_by,
        "draft_revision_id": draft.get("revision_id"),
        "question_set_id": question_set.get("question_set_id"),
        "published_project_model_path": str(archive_model.resolve()),
        "published_project_story_path": str(archive_story.resolve()),
        "published_vision_path": str(archive_vision.resolve()),
        "proposal_paths": [],
    }
    _write_publication_receipt(archive_receipt, receipt)
    _atomic_publish_copy(archive_model, canonical_project_model_path(data_root))
    _atomic_publish_copy(archive_story, canonical_project_story_path(data_root))
    _atomic_publish_copy(archive_vision, canonical_vision_path(data_root))
    proposal_paths = seed_onboarding_proposals(
        subject=subject,
        data_root=data_root,
        active_run=active_run,
        published_model=published_model,
        question_set=question_set,
    )
    receipt["proposal_paths"] = proposal_paths
    _write_publication_receipt(archive_receipt, receipt)

    session = dict(session)
    session["state"] = "confirmed"
    session["confirmed_at"] = confirmed_at
    session["confirmed_by"] = confirmed_by
    session["published_archive_project_model_path"] = str(archive_model.resolve())
    session["published_archive_project_story_path"] = str(archive_story.resolve())
    session["published_archive_vision_path"] = str(archive_vision.resolve())
    session["published_project_model_path"] = str(canonical_project_model_path(data_root).resolve())
    session["published_project_story_path"] = str(canonical_project_story_path(data_root).resolve())
    session["published_vision_path"] = str(canonical_vision_path(data_root).resolve())
    save_onboarding_session(data_root=data_root, session=session)
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=False)
    pointer["current_onboarding_id"] = None
    pointer["latest_confirmed_onboarding_id"] = onboarding_id
    save_onboarding_pointer(data_root=data_root, pointer=pointer)
    return {
        "onboarding_id": onboarding_id,
        "published_project_model_path": str(canonical_project_model_path(data_root).resolve()),
        "published_project_story_path": str(canonical_project_story_path(data_root).resolve()),
        "published_vision_path": str(canonical_vision_path(data_root).resolve()),
        "publication_receipt_path": str(archive_receipt.resolve()),
        "proposal_paths": proposal_paths,
    }


def onboarding_abandon(*, subject: str, data_root: Path, session: dict[str, Any], reason: str) -> dict[str, Any]:
    if str(session.get("state") or "") == "confirmed":
        raise RepoOnboardingError("Confirmed onboarding sessions cannot be abandoned. Use onboard-repo --restart instead.")
    updated = abandon_onboarding_session(data_root=data_root, session=session, reason=reason)
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


def onboarding_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    pointer = load_onboarding_pointer(subject=subject, data_root=data_root, rebuild=True)
    active_session = current_onboarding_session(subject=subject, data_root=data_root, require_current=False)
    if not active_session:
        return {
            "active_onboarding_id": None,
            "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
            "onboarding_state": None,
            "current_scan_id": None,
            "current_draft_id": None,
            "current_question_set_id": None,
            "unincorporated_capture_batch_ids": [],
            "published_project_model_path": None,
            "published_project_story_path": None,
            "published_vision_path": None,
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
        "active_onboarding_id": active_session.get("onboarding_id") if active_session.get("state") in ONBOARDING_NONTERMINAL_STATES else None,
        "latest_confirmed_onboarding_id": pointer.get("latest_confirmed_onboarding_id"),
        "onboarding_state": active_session.get("state"),
        "current_scan_id": active_session.get("current_scan_id"),
        "current_draft_id": active_session.get("current_draft_id"),
        "current_question_set_id": active_session.get("current_question_set_id"),
        "unincorporated_capture_batch_ids": list(active_session.get("unincorporated_capture_batch_ids") or []),
        "published_project_model_path": active_session.get("published_project_model_path"),
        "published_project_story_path": active_session.get("published_project_story_path"),
        "published_vision_path": active_session.get("published_vision_path"),
        "project_model_confirmed_at": active_session.get("confirmed_at"),
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

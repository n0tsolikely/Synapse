"""Runtime Draftshot orchestration for noncanonical session continuity."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.kernel_types import stable_kernel_id
from synapse_runtime.live_memory_common import _slugify


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
DRAFTSHOT_SCHEMA_VERSION = 1
_STATUS_LINE = re.compile(r"(?im)^(?:-\s*)?Status:\s*([A-Z_]+)\s*$")


class DraftshotError(RuntimeError):
    """Raised when Draftshot runtime operations cannot proceed safely."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def draftshots_body_root(data_root: Path) -> Path:
    return data_root / "Snapshots" / "Draft Shots"


def draftshot_index_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "DRAFTSHOT_INDEX"


def draftshot_state_path(data_root: Path) -> Path:
    return draftshot_index_root(data_root) / "STATE.yaml"


def draftshot_revision_root(data_root: Path) -> Path:
    return draftshot_index_root(data_root) / "REVISIONS"


def ensure_draftshot_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    for path in (draftshots_body_root(data_root), draftshot_index_root(data_root), draftshot_revision_root(data_root)):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.resolve()))
    return created


def _read_yaml(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else dict(default or {})


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _normalize_source_refs(source_refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        source_id = str(item.get("id") or "").strip()
        path = str(item.get("path") or "").strip()
        key = (kind, source_id, path)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return normalized


def _normalize_lines(lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = " ".join(str(raw or "").split()).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def draftshot_source_refs_from_synthesis(synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key in (
        "active_plan_delta",
        "active_scope_delta",
        "obligation_delta",
        "architecture_delta",
        "identity_delta",
        "narrative_delta",
    ):
        payload = synthesis.get(key)
        if not isinstance(payload, dict):
            continue
        refs.extend(payload.get("source_refs") or [])
    return _normalize_source_refs(refs)


def draftshot_detail_lines_from_synthesis(synthesis: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    mapping = (
        ("Active Plan", synthesis.get("active_plan_delta")),
        ("Active Scope", synthesis.get("active_scope_delta")),
        ("Open Obligations", synthesis.get("obligation_delta")),
        ("Architecture Delta", synthesis.get("architecture_delta")),
        ("Identity Delta", synthesis.get("identity_delta")),
        ("Narrative Delta", synthesis.get("narrative_delta")),
    )
    for label, payload in mapping:
        if not isinstance(payload, dict):
            continue
        summary = " ".join(str(payload.get("summary") or "").split()).strip()
        if summary:
            lines.append(f"{label}: {summary}")
        for item in list(payload.get("detail_lines") or [])[:3]:
            text = " ".join(str(item or "").split()).strip()
            if text:
                lines.append(f"{label}: {text}")
    return _normalize_lines(lines)


def draftshot_source_signature(source_refs: Iterable[dict[str, Any]]) -> str:
    normalized = _normalize_source_refs(source_refs)
    return stable_kernel_id(
        "DRAFTSRC",
        *(
            f"{item.get('kind')}|{item.get('id')}|{item.get('path')}"
            for item in normalized
        ),
    )


def _load_state(data_root: Path) -> dict[str, Any]:
    return _read_yaml(
        draftshot_state_path(data_root),
        default={
            "schema_version": DRAFTSHOT_SCHEMA_VERSION,
            "active_sessions": {},
            "latest_revision": None,
        },
    )


def _save_state(data_root: Path, payload: dict[str, Any]) -> None:
    _write_yaml(draftshot_state_path(data_root), payload)


def _body_filename(*, refreshed_at: str, title: str, revision_number: int) -> str:
    date_token = str(refreshed_at or "").split("T", 1)[0] or _now().date().isoformat()
    slug = _slugify(title)[:64] or "draftshot"
    return f"DRAFTSHOT__{date_token}__{slug}__REV{revision_number}.txt"


def _family_id(subject: str, session_id: str) -> str:
    return stable_kernel_id("DRAFTFAM", subject, session_id)


def _revision_id(subject: str, session_id: str, revision_number: int) -> str:
    return stable_kernel_id("DRAFTREV", subject, session_id, revision_number)


def _revision_path(data_root: Path, revision_id: str) -> Path:
    return draftshot_revision_root(data_root) / f"DRAFTSHOT_REV__{revision_id}.yaml"


def _load_revision(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = _read_yaml(Path(str(path)))
    if not payload:
        return None
    payload["path"] = str(Path(str(path)).resolve())
    return payload


def _update_body_status(path: Path, status: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    replacement = f"- Status: {status}"
    if _STATUS_LINE.search(text):
        updated = _STATUS_LINE.sub(replacement, text, count=1)
    else:
        updated = text + f"\n{replacement}\n"
    path.write_text(updated, encoding="utf-8")


def _draftshot_body(
    *,
    subject: str,
    session_id: str,
    run_id: str | None,
    revision_number: int,
    refreshed_at: str,
    summary_lines: list[str],
    source_refs: list[dict[str, Any]],
) -> str:
    headline = summary_lines[0] if summary_lines else "No material continuity delta captured."
    lines = [
        "================================================================================",
        "DRAFTSHOT",
        "================================================================================",
        "A) Header",
        f"- Subject: {subject}",
        f"- Session ID: {session_id}",
        f"- Run ID: {run_id or 'none'}",
        f"- Date: {str(refreshed_at).split('T', 1)[0]}",
        "- Status: ACTIVE",
        f"- Revision: REV{revision_number}",
        "",
        "B) Current Continuity Summary",
        f"- Headline: {headline}",
    ]
    for item in summary_lines[:12]:
        lines.append(f"- {item}")
    lines.extend(["", "C) Source Refs"])
    if source_refs:
        for ref in source_refs[:12]:
            lines.append(
                f"- {ref.get('kind') or 'source'} :: {ref.get('id') or 'unknown'} :: {ref.get('path') or 'missing'}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "D) Notes",
            "- Draftshot is a noncanonical living formalization.",
            "- Canonical snapshots remain owned by the snapshot writer.",
            "",
            "END OF DRAFTSHOT",
            "",
        ]
    )
    return "\n".join(lines)


def load_active_draftshot(data_root: Path, session_id: str | None = None) -> dict[str, Any] | None:
    state = _load_state(data_root)
    sessions = dict(state.get("active_sessions") or {})
    pointer: dict[str, Any] | None = None
    if session_id:
        current = sessions.get(session_id)
        if isinstance(current, dict) and str(current.get("status") or "").strip().upper() == "ACTIVE":
            pointer = dict(current)
    else:
        ordered = sorted(
            [
                dict(item)
                for item in sessions.values()
                if isinstance(item, dict) and str(item.get("status") or "").strip().upper() == "ACTIVE"
            ],
            key=lambda item: (str(item.get("refreshed_at") or ""), str(item.get("revision_path") or "")),
        )
        pointer = ordered[-1] if ordered else None
    if not pointer:
        return None
    payload = _load_revision(pointer.get("revision_path"))
    if payload is None:
        return None
    return payload


def list_draftshot_revisions(data_root: Path, session_id: str | None = None) -> list[dict[str, Any]]:
    root = draftshot_revision_root(data_root)
    if not root.exists():
        return []
    revisions: list[dict[str, Any]] = []
    for path in sorted(root.glob("DRAFTSHOT_REV__*.yaml")):
        payload = _load_revision(path)
        if payload is None:
            continue
        if session_id and str(payload.get("session_id") or "").strip() != str(session_id).strip():
            continue
        revisions.append(payload)
    return revisions


def draftshot_summary(
    data_root: Path,
    *,
    session_id: str | None = None,
    current_source_signature: str | None = None,
) -> dict[str, Any]:
    state = _load_state(data_root)
    active = load_active_draftshot(data_root, session_id=session_id)
    revisions = list_draftshot_revisions(data_root, session_id=session_id)
    active_sessions = dict(state.get("active_sessions") or {})
    stale = bool(active and current_source_signature and str(active.get("source_signature") or "") != current_source_signature)
    recent_details = [
        {
            "revision_id": item.get("revision_id"),
            "session_id": item.get("session_id"),
            "revision_number": item.get("revision_number"),
            "status": item.get("status"),
            "refreshed_at": item.get("refreshed_at"),
            "body_path": item.get("body_path"),
        }
        for item in revisions[-5:]
    ]
    active_count = sum(
        1
        for item in active_sessions.values()
        if isinstance(item, dict) and str(item.get("status") or "").strip().upper() == "ACTIVE"
    )
    return {
        "draftshot_schema_version": DRAFTSHOT_SCHEMA_VERSION,
        "active_draftshot_count": active_count,
        "current_active_draftshot_family_id": active.get("draftshot_family_id") if active else None,
        "current_active_draftshot_revision_id": active.get("revision_id") if active else None,
        "current_active_draftshot_path": active.get("body_path") if active else None,
        "current_active_draftshot_status": active.get("status") if active else None,
        "current_active_draftshot_session_id": active.get("session_id") if active else None,
        "last_draftshot_refreshed_at": active.get("refreshed_at") if active else None,
        "draftshot_stale": stale,
        "recent_draftshot_details": recent_details,
        "state_path": str(draftshot_state_path(data_root).resolve()),
    }


def refresh_draftshot(
    *,
    subject: str,
    data_root: Path,
    session_id: str,
    run_id: str | None = None,
    synthesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(session_id or "").strip():
        raise DraftshotError("refresh_draftshot requires a non-empty session_id.")
    ensure_draftshot_scaffold(data_root)
    if synthesis is None:
        from synapse_runtime.synthesis_refresh import refresh_synthesis

        synthesis = refresh_synthesis(subject=subject, data_root=data_root)

    source_refs = draftshot_source_refs_from_synthesis(synthesis)
    if not source_refs:
        return {
            "status": "noop",
            "reason": "no_material_sources",
            "session_id": session_id,
            "draftshot": draftshot_summary(data_root, session_id=session_id),
        }

    summary_lines = draftshot_detail_lines_from_synthesis(synthesis)
    source_signature = draftshot_source_signature(source_refs)
    state = _load_state(data_root)
    family_id = _family_id(subject, session_id)
    sessions = dict(state.get("active_sessions") or {})
    current_pointer = sessions.get(session_id) if isinstance(sessions.get(session_id), dict) else None
    current_active = _load_revision(current_pointer.get("revision_path")) if current_pointer else None
    if current_active and str(current_active.get("source_signature") or "") == source_signature:
        return {
            "status": "noop",
            "reason": "unchanged_source_signature",
            "session_id": session_id,
            "draftshot": draftshot_summary(data_root, session_id=session_id, current_source_signature=source_signature),
        }

    revision_number = int(current_active.get("revision_number") or 0) + 1 if current_active else 1
    revision_id = _revision_id(subject, session_id, revision_number)
    refreshed_at = str(synthesis.get("refreshed_at") or _now_iso())
    title_seed = summary_lines[0] if summary_lines else f"{subject} session"
    body_path = draftshots_body_root(data_root) / _body_filename(
        refreshed_at=refreshed_at,
        title=f"{session_id}-{title_seed}",
        revision_number=revision_number,
    )
    for other_session_id, pointer in list(sessions.items()):
        if other_session_id == session_id or not isinstance(pointer, dict):
            continue
        if str(pointer.get("status") or "").strip().upper() != "ACTIVE":
            continue
        other_body = Path(str(pointer.get("body_path") or ""))
        if other_body.exists():
            _update_body_status(other_body, "REVISED")
        other_revision = _load_revision(pointer.get("revision_path"))
        if other_revision is not None:
            other_revision["status"] = "REVISED"
            _write_yaml(Path(str(other_revision["path"])), other_revision)
        sessions[other_session_id] = {
            **pointer,
            "status": "REVISED",
        }
    if current_active and current_active.get("body_path"):
        _update_body_status(Path(str(current_active["body_path"])), "REVISED")
        current_active["status"] = "REVISED"
        _write_yaml(Path(str(current_active["path"])), current_active)

    body_text = _draftshot_body(
        subject=subject,
        session_id=session_id,
        run_id=run_id,
        revision_number=revision_number,
        refreshed_at=refreshed_at,
        summary_lines=summary_lines,
        source_refs=source_refs,
    )
    body_path.write_text(body_text, encoding="utf-8")
    revision_path = _revision_path(data_root, revision_id)
    revision_payload = {
        "schema_version": DRAFTSHOT_SCHEMA_VERSION,
        "subject": subject,
        "session_id": session_id,
        "run_id": run_id,
        "draftshot_family_id": family_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "status": "ACTIVE",
        "created_at": refreshed_at,
        "refreshed_at": refreshed_at,
        "body_path": str(body_path.resolve()),
        "source_signature": source_signature,
        "source_ref_count": len(source_refs),
        "source_refs": source_refs,
        "summary_lines": summary_lines,
        "previous_revision_id": current_active.get("revision_id") if current_active else None,
        "previous_revision_path": current_active.get("path") if current_active else None,
    }
    _write_yaml(revision_path, revision_payload)

    sessions[session_id] = {
        "draftshot_family_id": family_id,
        "revision_id": revision_id,
        "revision_path": str(revision_path.resolve()),
        "body_path": str(body_path.resolve()),
        "status": "ACTIVE",
        "refreshed_at": refreshed_at,
        "session_id": session_id,
        "run_id": run_id,
        "source_signature": source_signature,
    }
    state.update(
        {
            "schema_version": DRAFTSHOT_SCHEMA_VERSION,
            "active_sessions": sessions,
            "latest_revision": {
                "revision_id": revision_id,
                "revision_path": str(revision_path.resolve()),
                "body_path": str(body_path.resolve()),
                "refreshed_at": refreshed_at,
                "session_id": session_id,
            },
        }
    )
    _save_state(data_root, state)
    return {
        "status": "updated" if current_active else "written",
        "session_id": session_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "body_path": str(body_path.resolve()),
        "revision_path": str(revision_path.resolve()),
        "source_signature": source_signature,
        "source_ref_count": len(source_refs),
        "draftshot": draftshot_summary(data_root, session_id=session_id, current_source_signature=source_signature),
    }


def mark_draftshot_consumed(
    *,
    data_root: Path,
    session_id: str,
    snapshot_path: str,
    consumed_at: str | None = None,
) -> dict[str, Any] | None:
    active = load_active_draftshot(data_root, session_id=session_id)
    if active is None:
        return None
    consumed_at_text = str(consumed_at or _now_iso())
    body_path = Path(str(active.get("body_path") or ""))
    if body_path.exists():
        _update_body_status(body_path, "CONSUMED")
    revision_path = Path(str(active.get("path") or ""))
    payload = dict(active)
    payload["status"] = "CONSUMED"
    payload["consumed_at"] = consumed_at_text
    payload["consumed_by_snapshot_path"] = str(snapshot_path)
    _write_yaml(revision_path, payload)

    state = _load_state(data_root)
    sessions = dict(state.get("active_sessions") or {})
    if session_id in sessions:
        sessions[session_id] = {
            **dict(sessions[session_id]),
            "status": "CONSUMED",
            "consumed_at": consumed_at_text,
            "consumed_by_snapshot_path": str(snapshot_path),
        }
    state["active_sessions"] = sessions
    _save_state(data_root, state)
    return {**payload, "path": str(revision_path.resolve())}

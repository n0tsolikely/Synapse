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
_DATE_LINE = re.compile(r"(?im)^(?:-\s*)?Date:\s*(\d{4}-\d{2}-\d{2})\s*$")
_REVISION_LINE = re.compile(r"(?im)^(?:-\s*)?Revision:\s*(REV\d+)\s*$")

_SECTION_HEADINGS = {
    "CAPTURE_INDEX": "B) Capture Index",
    "DECISIONS": "C) Decisions",
    "FINDINGS": "D) Findings / Observations",
    "TODO": "E) TODO / Follow-ups",
    "RISKS": "F) Risks / Blockers",
    "OPEN_QUESTIONS": "G) Open Questions",
    "RUNNING_LOG": "H) Running Log",
}

_CAPTURE_PREFIX = {
    "DECISIONS": "DECISION",
    "FINDINGS": "DISCOVERY_CAPTURE",
    "TODO": "FOLLOWUP_CAPTURE",
    "RISKS": "RISK_CAPTURE",
    "OPEN_QUESTIONS": "QUESTION_CAPTURE",
}


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
        "imported_continuity_delta",
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
        ("Imported Continuity", synthesis.get("imported_continuity_delta")),
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


def _body_filename(*, refreshed_at: str, context_token: str, revision_number: int) -> str:
    date_token = str(refreshed_at or "").split("T", 1)[0] or _now().date().isoformat()
    slug = _slugify(context_token)[:64] or "general"
    return f"DRAFTSHOT__{date_token}__{slug}__REV{revision_number}.txt"


def _family_id(subject: str, session_id: str) -> str:
    return stable_kernel_id("DRAFTFAM", subject, session_id)


def _revision_id(subject: str, session_id: str, revision_number: int) -> str:
    return stable_kernel_id("DRAFTREV", subject, session_id, revision_number)


def _revision_path(data_root: Path, revision_id: str) -> Path:
    return draftshot_revision_root(data_root) / f"DRAFTSHOT_REV__{revision_id}.yaml"


def _parse_body_status(text: str) -> str | None:
    match = _STATUS_LINE.search(text)
    return match.group(1).strip().upper() if match else None


def _parse_body_revision_label(text: str, path: Path) -> str:
    match = _REVISION_LINE.search(text)
    if match:
        return match.group(1).strip().upper()
    filename_match = re.search(r"(?i)__?(REV\d+)\b", path.name)
    if filename_match:
        return filename_match.group(1).strip().upper()
    return "REV?"


def _body_contract_issues(text: str) -> list[str]:
    issues: list[str] = []
    if not _STATUS_LINE.search(text):
        issues.append("missing_header_status")
    if not _DATE_LINE.search(text):
        issues.append("missing_header_date")
    if not _REVISION_LINE.search(text):
        issues.append("missing_header_revision")
    for key, heading in _SECTION_HEADINGS.items():
        if re.search(rf"(?m)^{re.escape(heading)}\s*$", text) is None:
            issues.append(f"missing_section_{key.lower()}")
    return issues


def _body_integrity(*, path: Path, expected_status: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {
            "integrity_ok": False,
            "integrity_issues": ["missing_body_file"],
            "body_status": None,
            "revision_label": "REV?",
        }
    text = path.read_text(encoding="utf-8")
    issues = _body_contract_issues(text)
    body_status = _parse_body_status(text)
    if expected_status and body_status and body_status != str(expected_status).strip().upper():
        issues.append(f"status_mismatch:{body_status}!={str(expected_status).strip().upper()}")
    return {
        "integrity_ok": not issues,
        "integrity_issues": issues,
        "body_status": body_status,
        "revision_label": _parse_body_revision_label(text, path),
    }


def _load_revision(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = _read_yaml(Path(str(path)))
    if not payload:
        return None
    payload["path"] = str(Path(str(path)).resolve())
    return payload


def _load_revision_by_body_path(data_root: Path, body_path: Path) -> dict[str, Any] | None:
    needle = str(body_path.resolve())
    for revision in list_draftshot_revisions(data_root):
        if str(revision.get("body_path") or "") == needle:
            return revision
    return None


def _legacy_body_payload(data_root: Path, path: Path) -> dict[str, Any]:
    integrity = _body_integrity(path=path)
    return {
        "schema_version": DRAFTSHOT_SCHEMA_VERSION,
        "body_path": str(path.resolve()),
        "status": integrity.get("body_status") or "UNKNOWN",
        "revision_label": integrity.get("revision_label"),
        "integrity_ok": integrity.get("integrity_ok"),
        "integrity_issues": list(integrity.get("integrity_issues") or []),
        "index_backed": False,
        "rel_path": _rel_to_data_root(data_root, path),
    }


def _rel_to_data_root(data_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except Exception:
        return str(path)


def _consume_body_for_snapshot(path: Path, *, snapshot_path: Path, consumed_at_iso: str) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")

    if re.search(r"(?im)^(?:-\s*)?Status:\s*CONSUMED\s*$", text):
        return

    replaced, count = re.subn(
        r"(?im)^(?:-\s*)?Status:\s*ACTIVE\s*$",
        "- Status: CONSUMED",
        text,
        count=1,
    )
    if count == 0:
        wrapper = (
            "================================================================================\n"
            "DRAFTSHOT CONSUMPTION WRAPPER (AI11)\n"
            f"- Status: CONSUMED\n"
            f"- Consumed At: {consumed_at_iso}\n"
            f"- Consumed By Snapshot: {snapshot_path.name}\n"
            "================================================================================\n\n"
        )
        replaced = wrapper + text

    marker = (
        "\n\n================================================================================\n"
        "DRAFTSHOT CONSUMPTION MARKER (AI11)\n"
        f"- Consumed At: {consumed_at_iso}\n"
        f"- Consumed By Snapshot: {snapshot_path.name}\n"
        "- Rule: Draftshot ACTIVE → CONSUMED on Snapshot mint\n"
        "================================================================================\n"
    )
    if "DRAFTSHOT CONSUMPTION MARKER (AI11)" not in replaced:
        replaced = replaced.rstrip("\n") + marker + "\n"
    path.write_text(replaced, encoding="utf-8")


def _capture_id(section_key: str, *parts: Any) -> str:
    return stable_kernel_id(_CAPTURE_PREFIX.get(section_key, "DRAFT_CAPTURE"), *parts)


def _append_capture_entry(
    *,
    section_key: str,
    summary: str,
    source_refs: Iterable[dict[str, Any]],
    sections: dict[str, list[dict[str, Any]]],
    capture_entries: list[dict[str, Any]],
    seen_ids: set[str],
    basis_parts: Iterable[Any],
) -> None:
    text = " ".join(str(summary or "").split()).strip()
    if not text:
        return
    normalized_refs = _normalize_source_refs(source_refs)
    capture_id = _capture_id(
        section_key,
        section_key,
        *basis_parts,
        *(
            f"{ref.get('kind')}|{ref.get('id')}|{ref.get('path')}"
            for ref in normalized_refs
        ),
    )
    if capture_id in seen_ids:
        return
    seen_ids.add(capture_id)
    entry = {
        "capture_id": capture_id,
        "section": section_key,
        "summary": text,
        "source_refs": normalized_refs,
    }
    sections.setdefault(section_key, []).append(entry)
    capture_entries.append(entry)


def _load_recent_family_records(data_root: Path, family: str, *, limit: int = 5) -> list[dict[str, Any]]:
    from synapse_runtime.promotion_engine import load_working_records

    records = [item for item in load_working_records(data_root, family) if isinstance(item, dict)]
    return records[-limit:]


def _open_question_lines(data_root: Path) -> list[str]:
    from synapse_runtime.sidecar_store import load_open_questions_text

    text = load_open_questions_text(data_root)
    if not text.strip():
        return []
    questions: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        question = line[1:].strip()
        if not question or question.lower() == "none yet.":
            continue
        questions.append(question)
    return _normalize_lines(questions)


def _entries_from_delta(
    *,
    section_key: str,
    delta_key: str,
    payload: dict[str, Any] | None,
    sections: dict[str, list[dict[str, Any]]],
    capture_entries: list[dict[str, Any]],
    seen_ids: set[str],
) -> None:
    if not isinstance(payload, dict):
        return
    summary = str(payload.get("summary") or "").strip()
    source_refs = list(payload.get("source_refs") or [])
    if summary:
        _append_capture_entry(
            section_key=section_key,
            summary=summary,
            source_refs=source_refs,
            sections=sections,
            capture_entries=capture_entries,
            seen_ids=seen_ids,
            basis_parts=(delta_key, "summary"),
        )
    for index, line in enumerate(list(payload.get("detail_lines") or [])[:6], start=1):
        _append_capture_entry(
            section_key=section_key,
            summary=str(line),
            source_refs=source_refs,
            sections=sections,
            capture_entries=capture_entries,
            seen_ids=seen_ids,
            basis_parts=(delta_key, "detail", index),
        )


def _entries_from_records(
    *,
    data_root: Path,
    family: str,
    section_key: str,
    sections: dict[str, list[dict[str, Any]]],
    capture_entries: list[dict[str, Any]],
    seen_ids: set[str],
) -> None:
    for record in _load_recent_family_records(data_root, family):
        summary = str(record.get("summary") or record.get("title") or "").strip()
        if not summary:
            continue
        _append_capture_entry(
            section_key=section_key,
            summary=summary,
            source_refs=[
                {
                    "kind": "governed_working_record",
                    "id": str(record.get("record_id") or record.get("family_id") or summary),
                    "path": str(record.get("path") or ""),
                    "family": record.get("family"),
                }
            ],
            sections=sections,
            capture_entries=capture_entries,
            seen_ids=seen_ids,
            basis_parts=(family, str(record.get("record_id") or record.get("family_id") or summary)),
        )


def _build_draftshot_sections(*, data_root: Path, synthesis: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    sections: dict[str, list[dict[str, Any]]] = {
        "DECISIONS": [],
        "FINDINGS": [],
        "TODO": [],
        "RISKS": [],
        "OPEN_QUESTIONS": [],
    }
    capture_entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    _entries_from_records(
        data_root=data_root,
        family="DECISION_GRAPH",
        section_key="DECISIONS",
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="FINDINGS",
        delta_key="ACTIVE_SCOPE",
        payload=synthesis.get("active_scope_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="FINDINGS",
        delta_key="ARCHITECTURE",
        payload=synthesis.get("architecture_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="FINDINGS",
        delta_key="IDENTITY",
        payload=synthesis.get("identity_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="FINDINGS",
        delta_key="NARRATIVE",
        payload=synthesis.get("narrative_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="FINDINGS",
        delta_key="IMPORTED_CONTINUITY",
        payload=synthesis.get("imported_continuity_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="TODO",
        delta_key="ACTIVE_PLAN",
        payload=synthesis.get("active_plan_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_delta(
        section_key="RISKS",
        delta_key="OPEN_OBLIGATIONS",
        payload=synthesis.get("obligation_delta"),
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    _entries_from_records(
        data_root=data_root,
        family="FAILURE_CHAINS",
        section_key="RISKS",
        sections=sections,
        capture_entries=capture_entries,
        seen_ids=seen_ids,
    )
    if bool(dict(synthesis.get("imported_continuity_delta") or {}).get("metadata", {}).get("requires_import_review")):
        _entries_from_delta(
            section_key="RISKS",
            delta_key="IMPORTED_CONTINUITY_REVIEW",
            payload=synthesis.get("imported_continuity_delta"),
            sections=sections,
            capture_entries=capture_entries,
            seen_ids=seen_ids,
        )

    for index, question in enumerate(_open_question_lines(data_root), start=1):
        _append_capture_entry(
            section_key="OPEN_QUESTIONS",
            summary=question,
            source_refs=[],
            sections=sections,
            capture_entries=capture_entries,
            seen_ids=seen_ids,
            basis_parts=("OPEN_QUESTION", index, question),
        )

    return sections, capture_entries


def _format_section_lines(entries: list[dict[str, Any]]) -> list[str]:
    if not entries:
        return ["- none"]
    return [f"- [{item['capture_id']}] {item['summary']}" for item in entries]


def _draftshot_body(
    *,
    subject: str,
    session_id: str,
    run_id: str | None,
    revision_number: int,
    refreshed_at: str,
    draftshot_context: str,
    capture_entries: list[dict[str, Any]],
    sections: dict[str, list[dict[str, Any]]],
    running_log: list[dict[str, Any]],
) -> str:
    lines = [
        "================================================================================",
        "DRAFTSHOT",
        "================================================================================",
        "A) Header",
        "- Status: ACTIVE",
        f"- Date: {str(refreshed_at).split('T', 1)[0]}",
        f"- Revision: REV{revision_number}",
        f"- Session Context: {draftshot_context}",
        f"- Session ID: {session_id}",
        f"- Subject: {subject}",
        f"- Run ID: {run_id or 'none'}",
        "",
        _SECTION_HEADINGS["CAPTURE_INDEX"],
    ]
    if capture_entries:
        for entry in capture_entries:
            lines.append(f"- {entry['capture_id']} :: {entry['section']} :: {entry['summary']}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            _SECTION_HEADINGS["DECISIONS"],
            *_format_section_lines(sections.get("DECISIONS") or []),
            "",
            _SECTION_HEADINGS["FINDINGS"],
            *_format_section_lines(sections.get("FINDINGS") or []),
            "",
            _SECTION_HEADINGS["TODO"],
            *_format_section_lines(sections.get("TODO") or []),
            "",
            _SECTION_HEADINGS["RISKS"],
            *_format_section_lines(sections.get("RISKS") or []),
            "",
            _SECTION_HEADINGS["OPEN_QUESTIONS"],
            *_format_section_lines(sections.get("OPEN_QUESTIONS") or []),
            "",
            _SECTION_HEADINGS["RUNNING_LOG"],
        ]
    )
    if running_log:
        for entry in running_log:
            revision_label = str(entry.get("revision_label") or f"REV{revision_number}")
            refreshed_line = str(entry.get("refreshed_at") or refreshed_at)
            change_type = str(entry.get("change_type") or "updated")
            summary = str(entry.get("summary") or "").strip()
            source_ref_count = int(entry.get("source_ref_count") or 0)
            lines.append(
                f"- {revision_label} @ {refreshed_line} :: {change_type} :: {source_ref_count} source refs :: {summary}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "END OF DRAFTSHOT", ""])
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
    integrity = _body_integrity(path=Path(str(payload.get("body_path") or "")), expected_status=str(payload.get("status") or ""))
    payload["integrity_ok"] = integrity.get("integrity_ok")
    payload["integrity_issues"] = list(integrity.get("integrity_issues") or [])
    payload["revision_label"] = integrity.get("revision_label") or f"REV{payload.get('revision_number') or '?'}"
    payload["rel_path"] = _rel_to_data_root(data_root, Path(str(payload.get("body_path") or "")))
    payload["index_backed"] = True
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
        "draftshot_integrity_ok": bool(active.get("integrity_ok")) if active else True,
        "draftshot_integrity_issues": list(active.get("integrity_issues") or []) if active else [],
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
    if current_active is not None:
        integrity = _body_integrity(
            path=Path(str(current_active.get("body_path") or "")),
            expected_status=str(current_active.get("status") or ""),
        )
        if not integrity.get("integrity_ok"):
            raise DraftshotError(
                "active Draftshot integrity issue: " + ", ".join(str(item) for item in integrity.get("integrity_issues") or [])
            )
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
    draftshot_context = "GENERAL"
    sections, capture_entries = _build_draftshot_sections(data_root=data_root, synthesis=synthesis)
    headline = summary_lines[0] if summary_lines else "No material continuity delta captured."
    running_log = list(current_active.get("running_log") or []) if current_active else []
    running_log.append(
        {
            "revision_label": f"REV{revision_number}",
            "refreshed_at": refreshed_at,
            "change_type": "updated" if current_active else "written",
            "summary": headline,
            "source_ref_count": len(source_refs),
        }
    )
    context_token = f"{draftshot_context}-{session_id}"
    body_path = draftshots_body_root(data_root) / _body_filename(
        refreshed_at=refreshed_at,
        context_token=context_token,
        revision_number=revision_number,
    )
    body_text = _draftshot_body(
        subject=subject,
        session_id=session_id,
        run_id=run_id,
        revision_number=revision_number,
        refreshed_at=refreshed_at,
        draftshot_context=draftshot_context,
        capture_entries=capture_entries,
        sections=sections,
        running_log=running_log,
    )
    body_path.write_text(body_text, encoding="utf-8")
    integrity = _body_integrity(path=body_path, expected_status="ACTIVE")
    revision_path = _revision_path(data_root, revision_id)
    revision_payload = {
        "schema_version": DRAFTSHOT_SCHEMA_VERSION,
        "subject": subject,
        "session_id": session_id,
        "run_id": run_id,
        "draftshot_family_id": family_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "revision_label": f"REV{revision_number}",
        "status": "ACTIVE",
        "created_at": refreshed_at,
        "refreshed_at": refreshed_at,
        "draftshot_context": draftshot_context,
        "body_path": str(body_path.resolve()),
        "source_signature": source_signature,
        "source_ref_count": len(source_refs),
        "source_refs": source_refs,
        "summary_lines": summary_lines,
        "capture_index": capture_entries,
        "running_log": running_log,
        "integrity_ok": integrity.get("integrity_ok"),
        "integrity_issues": list(integrity.get("integrity_issues") or []),
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


def resolve_snapshot_draftshot(*, data_root: Path, explicit: str | None = None) -> dict[str, Any] | None:
    ensure_draftshot_scaffold(data_root)
    if explicit:
        body_path = Path(explicit).expanduser()
        if not body_path.is_absolute():
            body_path = (data_root / body_path).resolve()
        if not body_path.exists():
            raise DraftshotError(f"Draftshot not found: {body_path}")
        return _load_revision_by_body_path(data_root, body_path) or _legacy_body_payload(data_root, body_path)

    state = _load_state(data_root)
    active_payloads: list[dict[str, Any]] = []
    for pointer in dict(state.get("active_sessions") or {}).values():
        if not isinstance(pointer, dict):
            continue
        if str(pointer.get("status") or "").strip().upper() != "ACTIVE":
            continue
        payload = _load_revision(pointer.get("revision_path"))
        if payload:
            active_payloads.append(payload)
    if active_payloads:
        if len(active_payloads) > 1:
            raise DraftshotError(
                "multiple ACTIVE Draftshots found across sessions; pass --draftshot explicitly."
            )
        return active_payloads[0]

    active_bodies: list[dict[str, Any]] = []
    for path in sorted(draftshots_body_root(data_root).glob("DRAFTSHOT__*.txt")):
        legacy = _legacy_body_payload(data_root, path)
        if str(legacy.get("status") or "").strip().upper() == "ACTIVE":
            active_bodies.append(legacy)
    if not active_bodies:
        return None
    if len(active_bodies) > 1:
        raise DraftshotError(
            "multiple ACTIVE Draftshots found without runtime index support; pass --draftshot explicitly."
        )
    return active_bodies[0]


def consume_draftshot_for_snapshot(
    *,
    data_root: Path,
    explicit: str | None,
    snapshot_path: str,
    consumed_at_iso: str | None = None,
) -> dict[str, Any] | None:
    payload = resolve_snapshot_draftshot(data_root=data_root, explicit=explicit)
    if payload is None:
        return None
    body_path = Path(str(payload.get("body_path") or "")).resolve()
    consumed_at_text = str(consumed_at_iso or _now_iso())
    _consume_body_for_snapshot(body_path, snapshot_path=Path(snapshot_path), consumed_at_iso=consumed_at_text)

    if not bool(payload.get("index_backed", True)):
        return {
            **payload,
            "status": "CONSUMED",
            "consumed_at": consumed_at_text,
            "consumed_by_snapshot_path": str(snapshot_path),
        }

    revision_path = Path(str(payload.get("path") or ""))
    updated = dict(payload)
    updated["status"] = "CONSUMED"
    updated["consumed_at"] = consumed_at_text
    updated["consumed_by_snapshot_path"] = str(snapshot_path)
    integrity = _body_integrity(path=body_path, expected_status="CONSUMED")
    updated["integrity_ok"] = integrity.get("integrity_ok")
    updated["integrity_issues"] = list(integrity.get("integrity_issues") or [])
    _write_yaml(revision_path, updated)

    state = _load_state(data_root)
    sessions = dict(state.get("active_sessions") or {})
    session_id = str(payload.get("session_id") or "").strip()
    if session_id and session_id in sessions:
        sessions[session_id] = {
            **dict(sessions[session_id]),
            "status": "CONSUMED",
            "consumed_at": consumed_at_text,
            "consumed_by_snapshot_path": str(snapshot_path),
        }
        state["active_sessions"] = sessions
        _save_state(data_root, state)

    return {**updated, "path": str(revision_path.resolve())}


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
    return consume_draftshot_for_snapshot(
        data_root=data_root,
        explicit=str(active.get("body_path") or ""),
        snapshot_path=snapshot_path,
        consumed_at_iso=consumed_at,
    )

"""Noncanonical truth draft storage for compiled current-state truth inputs."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.kernel_types import stable_kernel_id
from synapse_runtime.live_memory_common import _slugify
from synapse_runtime.sidecar_store import live_root
from synapse_runtime.truth_statements import StatementKind, TruthLayer, normalize_confidence, normalize_summary_text, normalize_topic_key

TRUTH_DRAFT_SCHEMA_VERSION = 1


class TruthDraftError(RuntimeError):
    """Raised when truth drafts cannot be stored safely."""


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).astimezone().isoformat()


def truth_drafts_root(data_root: Path) -> Path:
    return live_root(data_root) / "TRUTH" / "DRAFTS"


def truth_draft_index_path(data_root: Path) -> Path:
    return truth_drafts_root(data_root) / "INDEX.yaml"


def ensure_truth_draft_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    root = truth_drafts_root(data_root)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        created.append(str(root.resolve()))
    index_path = truth_draft_index_path(data_root)
    if not index_path.exists():
        index_path.write_text(yaml.safe_dump(_default_index(), sort_keys=False), encoding="utf-8")
        created.append(str(index_path.resolve()))
    return created


def _default_index() -> dict[str, Any]:
    return {
        "schema_version": TRUTH_DRAFT_SCHEMA_VERSION,
        "current": {},
        "updated_at": None,
    }


def _read_yaml(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        return default
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if payload is None else payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _load_index(data_root: Path) -> dict[str, Any]:
    ensure_truth_draft_scaffold(data_root)
    payload = _read_yaml(truth_draft_index_path(data_root), default={})
    if not isinstance(payload, dict):
        return _default_index()
    merged = _default_index()
    merged.update(payload)
    merged["current"] = dict(payload.get("current") or {})
    return merged


def _write_index(data_root: Path, payload: dict[str, Any]) -> Path:
    normalized = dict(payload)
    normalized["schema_version"] = TRUTH_DRAFT_SCHEMA_VERSION
    normalized["updated_at"] = _now_iso()
    path = truth_draft_index_path(data_root)
    _write_yaml(path, normalized)
    return path


def _family_id(subject: str, family_key: str) -> str:
    return stable_kernel_id("TRUTHDRAFT", subject, family_key)


def _revision_id(subject: str, family_id: str, revision_number: int) -> str:
    return stable_kernel_id("TRUTHDRAFTREV", subject, family_id, f"REV{revision_number:03d}")


def _draft_path(data_root: Path, family_id: str, revision_number: int) -> Path:
    return truth_drafts_root(data_root) / f"TRUTH_DRAFT__{family_id}__REV{revision_number}.yaml"


def _normalize_source_refs(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        ref_id = str(item.get("id") or item.get("source_id") or "").strip()
        path = str(item.get("path") or item.get("body_path") or item.get("source_path") or "").strip()
        key = (kind, ref_id, path)
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return normalized


def _normalize_statement(statement: dict[str, Any], *, position: int) -> dict[str, Any]:
    if not isinstance(statement, dict):
        raise TruthDraftError("Truth draft statements must be objects.")
    statement_kind = StatementKind(str(statement.get("statement_kind") or "").strip())
    summary = normalize_summary_text(statement.get("summary"))
    truth_layer = TruthLayer(str(statement.get("truth_layer") or TruthLayer.PARTIAL.value).strip())
    topic_seed = statement.get("topic_key") or statement.get("topic") or summary
    return {
        "statement_kind": statement_kind.value,
        "summary": summary,
        "detail": " ".join(str(statement.get("detail") or "").split()).strip(),
        "truth_layer": truth_layer.value,
        "confidence": normalize_confidence(statement.get("confidence") or "medium"),
        "operator_confirmed": bool(statement.get("operator_confirmed")),
        "needs_expansion": bool(statement.get("needs_expansion")),
        "topic_key": normalize_topic_key(topic_seed),
        "statement_ref": str(statement.get("statement_ref") or f"STATEMENT-{position:03d}"),
    }


def _source_signature(
    *,
    family_key: str,
    title: str,
    summary: str,
    statements: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> str:
    statement_tokens = [
        "|".join(
            [
                item["statement_kind"],
                item["topic_key"],
                item["summary"],
                item["detail"],
                item["truth_layer"],
                item["confidence"],
                "1" if item["operator_confirmed"] else "0",
                "1" if item["needs_expansion"] else "0",
            ]
        )
        for item in statements
    ]
    ref_tokens = [
        "|".join(
            [
                str(item.get("kind") or ""),
                str(item.get("id") or item.get("source_id") or ""),
                str(item.get("path") or item.get("body_path") or item.get("source_path") or ""),
            ]
        )
        for item in source_refs
    ]
    return stable_kernel_id("TRUTHDRAFTSIG", family_key, title, summary, *statement_tokens, *ref_tokens)


def write_truth_draft(
    *,
    subject: str,
    data_root: Path,
    title: str,
    statements: Iterable[dict[str, Any]],
    summary: str | None = None,
    family_key: str | None = None,
    source_refs: Iterable[dict[str, Any]] | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_title = normalize_summary_text(title)
    normalized_summary = " ".join(str(summary or normalized_title).split()).strip() or normalized_title
    normalized_family_key = _slugify(family_key or normalized_title) or "truth-draft"
    normalized_statements = [_normalize_statement(item, position=index + 1) for index, item in enumerate(list(statements))]
    if not normalized_statements:
        raise TruthDraftError("Truth drafts require at least one statement.")
    normalized_refs = _normalize_source_refs(source_refs or [])

    draft_family_id = _family_id(subject, normalized_family_key)
    source_signature = _source_signature(
        family_key=normalized_family_key,
        title=normalized_title,
        summary=normalized_summary,
        statements=normalized_statements,
        source_refs=normalized_refs,
    )

    index_payload = _load_index(data_root)
    current = dict(index_payload.get("current") or {}).get(draft_family_id) or {}
    current_path_text = str(current.get("draft_path") or current.get("path") or "").strip()
    if current_path_text and str(current.get("source_signature") or "") == source_signature and Path(current_path_text).exists():
        return {
            "status": "noop",
            "reason": "unchanged_source_signature",
            "truth_draft_family_id": draft_family_id,
            "revision_id": current.get("revision_id"),
            "revision_number": current.get("revision_number"),
            "draft_path": current_path_text,
            "index_path": str(truth_draft_index_path(data_root).resolve()),
            "summary": truth_draft_summary(data_root),
        }

    revision_number = int(current.get("revision_number") or 0) + 1
    revision_id = _revision_id(subject, draft_family_id, revision_number)
    path = _draft_path(data_root, draft_family_id, revision_number)
    drafted_at = _now_iso()
    payload = {
        "schema_version": TRUTH_DRAFT_SCHEMA_VERSION,
        "truth_draft_family_id": draft_family_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "family_key": normalized_family_key,
        "subject": subject,
        "title": normalized_title,
        "summary": normalized_summary,
        "drafted_at": drafted_at,
        "noncanonical": True,
        "source_signature": source_signature,
        "source_refs": normalized_refs,
        "statement_count": len(normalized_statements),
        "statements": normalized_statements,
        "run_context": {
            "run_id": str((run_context or {}).get("run_id") or "").strip() or None,
            "session_id": str((run_context or {}).get("session_id") or "").strip() or None,
            "session_mode": str((run_context or {}).get("session_mode") or "").strip() or None,
        },
    }
    _write_yaml(path, payload)

    current_index = dict(index_payload.get("current") or {})
    current_index[draft_family_id] = {
        "truth_draft_family_id": draft_family_id,
        "family_key": normalized_family_key,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "title": normalized_title,
        "summary": normalized_summary,
        "drafted_at": drafted_at,
        "source_signature": source_signature,
        "draft_path": str(path.resolve()),
    }
    index_payload["current"] = current_index
    index_path = _write_index(data_root, index_payload)
    return {
        "status": "written",
        "truth_draft_family_id": draft_family_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "draft_path": str(path.resolve()),
        "index_path": str(index_path.resolve()),
        "summary": truth_draft_summary(data_root),
    }


def _load_truth_draft(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path, default={})
    if not isinstance(payload, dict):
        raise TruthDraftError(f"Malformed truth draft payload: {path}")
    payload["path"] = str(path.resolve())
    return payload


def list_truth_draft_revisions(data_root: Path) -> list[dict[str, Any]]:
    ensure_truth_draft_scaffold(data_root)
    drafts: list[dict[str, Any]] = []
    for path in sorted(truth_drafts_root(data_root).glob("TRUTH_DRAFT__*.yaml")):
        if path.name == "INDEX.yaml":
            continue
        drafts.append(_load_truth_draft(path))
    return drafts


def load_current_truth_drafts(data_root: Path) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    current = dict(_load_index(data_root).get("current") or {})
    for entry in current.values():
        draft_path = str(entry.get("draft_path") or "").strip()
        if not draft_path:
            continue
        path = Path(draft_path)
        if not path.exists():
            continue
        drafts.append(_load_truth_draft(path))
    drafts.sort(key=lambda item: str(item.get("drafted_at") or ""), reverse=True)
    return drafts


def truth_draft_summary(data_root: Path) -> dict[str, Any]:
    drafts = load_current_truth_drafts(data_root)
    details = [
        {
            "truth_draft_family_id": item.get("truth_draft_family_id"),
            "revision_id": item.get("revision_id"),
            "revision_number": item.get("revision_number"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "drafted_at": item.get("drafted_at"),
            "path": item.get("path"),
            "statement_count": int(item.get("statement_count") or 0),
            "source_ref_count": len(list(item.get("source_refs") or [])),
        }
        for item in drafts
    ]
    return {
        "truth_draft_schema_version": TRUTH_DRAFT_SCHEMA_VERSION,
        "truth_draft_count": len(drafts),
        "current_truth_draft_paths": [str(item.get("path")) for item in drafts if str(item.get("path") or "").strip()],
        "recent_truth_draft_details": details[:10],
        "index_path": str(truth_draft_index_path(data_root).resolve()),
    }

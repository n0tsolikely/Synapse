"""Semantic capture schema, raw storage, and projection helpers."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.governance_model import PromotionRecord, ProposalKind, ProposalState
from synapse_runtime.ledger_store import _append_ledger_entry, _entry_id
from synapse_runtime.live_memory_common import _slugify
from synapse_runtime.sidecar_store import _now_iso, live_root


OPEN_QUESTIONS_MANAGED_MARKER = "<!-- SYNAPSE_MANAGED_OPEN_QUESTIONS -->"
OPEN_QUESTIONS_SCAFFOLD = """# Open Questions

## Blocking
- None yet.

## Nonblocking
- None yet.
"""

_OPEN_QUESTIONS_MANAGED_TEMPLATE = """# Open Questions

<!-- SYNAPSE_MANAGED_OPEN_QUESTIONS -->

## Blocking
{blocking_lines}

## Nonblocking
{nonblocking_lines}
"""

_QUESTION_KINDS = {"question", "unknown"}
_BLOCKING_ALLOWED_KINDS = {"question", "unknown", "risk"}
_CONFIDENCE_VALUES = {"low", "medium", "high"}
_PROMOTION_REASON = {
    ProposalKind.QUEST: "Semantic capture batch surfaced work that should be tracked as a quest candidate.",
    ProposalKind.CODEX: "Semantic capture batch surfaced repo knowledge that should be consolidated into codex guidance.",
    ProposalKind.BUILD_MANUAL: "Semantic capture batch surfaced implementation detail that should be reflected in the build manual backlog.",
    ProposalKind.CONTROL_SYNC: "Semantic capture batch surfaced a provisional decision that should be resolved through control sync.",
    ProposalKind.DISCLOSURE: "Semantic capture batch surfaced blocking uncertainty or risk that should be escalated through disclosure handling.",
}


class SemanticIntakeError(RuntimeError):
    """Raised when semantic capture payloads or artifacts are invalid."""


class CaptureKind(str, Enum):
    IDEA = "idea"
    QUESTION = "question"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    UNKNOWN = "unknown"
    RISK = "risk"
    DEPENDENCY = "dependency"
    REPO_FACT = "repo_fact"
    MILESTONE = "milestone"
    NON_GOAL = "non_goal"


class CaptureSourceRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    IMPORTED = "imported"
    REPO_SCAN = "repo_scan"


def capture_batches_dir(data_root: Path) -> Path:
    return live_root(data_root) / "CAPTURES" / "BATCHES"


def capture_daily_ledger_path(data_root: Path, stamp: str | None = None) -> Path:
    day = stamp or dt.datetime.fromisoformat(_now_iso()).date().isoformat()
    return live_root(data_root) / "CAPTURES" / f"{day}.yaml"


def generate_capture_batch_id() -> str:
    return _entry_id("CAPTURE")


def capture_item_id(batch_id: str, index: int) -> str:
    return f"{batch_id}::ITEM-{index + 1:03d}"


def normalize_capture_source_role(value: str | CaptureSourceRole | None) -> CaptureSourceRole:
    if isinstance(value, CaptureSourceRole):
        return value
    try:
        return CaptureSourceRole(str(value or CaptureSourceRole.USER.value).strip())
    except ValueError as exc:
        raise SemanticIntakeError(f"Invalid capture source role: {value}") from exc


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise SemanticIntakeError("Capture tags must be a list of strings.")
    results: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if text and text not in results:
            results.append(text)
    return results


def _normalize_summary(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SemanticIntakeError(f"{field_name} must be non-empty.")
    return text


def normalize_related_paths(value: Any, *, engine_root: Path, data_root: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        raise SemanticIntakeError("related_paths must normalize to a list of strings.")
    results: list[str] = []
    seen: set[str] = set()
    engine_base = engine_root.resolve()
    data_base = data_root.resolve()
    for raw in candidates:
        text = str(raw).strip()
        if not text:
            continue
        normalized = _normalize_related_path(text, engine_base=engine_base, data_base=data_base)
        if normalized not in seen:
            results.append(normalized)
            seen.add(normalized)
    return results


def _normalize_related_path(raw: str, *, engine_base: Path, data_base: Path) -> str:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve(strict=False)
        except Exception:
            return raw
        try:
            return resolved.relative_to(engine_base).as_posix()
        except Exception:
            pass
        try:
            return resolved.relative_to(data_base).as_posix()
        except Exception:
            return str(resolved)

    engine_candidate = (engine_base / candidate).resolve(strict=False)
    if engine_candidate.exists():
        try:
            return engine_candidate.relative_to(engine_base).as_posix()
        except Exception:
            pass

    data_candidate = (data_base / candidate).resolve(strict=False)
    if data_candidate.exists():
        try:
            return data_candidate.relative_to(data_base).as_posix()
        except Exception:
            pass

    return raw


def normalize_capture_payload(payload: Any, *, engine_root: Path, data_root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SemanticIntakeError("Capture payload must be an object with a 'captures' list.")
    captures_raw = payload.get("captures")
    if not isinstance(captures_raw, list):
        raise SemanticIntakeError("Capture payload 'captures' must be a list.")
    if not captures_raw:
        raise SemanticIntakeError("Capture payload must contain at least one capture item.")

    captures: list[dict[str, Any]] = []
    for index, item in enumerate(captures_raw):
        if not isinstance(item, dict):
            raise SemanticIntakeError(f"Capture item {index + 1} must be an object.")
        captures.append(
            normalize_capture_item(
                item,
                engine_root=engine_root,
                data_root=data_root,
            )
        )

    title = payload.get("title")
    title_text = str(title).strip() if title is not None else None
    return {
        "title": title_text or None,
        "tags": _normalize_tags(payload.get("tags")),
        "captures": captures,
    }


def normalize_capture_item(item: dict[str, Any], *, engine_root: Path, data_root: Path) -> dict[str, Any]:
    raw_kind = item.get("kind")
    try:
        kind = CaptureKind(str(raw_kind).strip())
    except ValueError as exc:
        raise SemanticIntakeError(f"Invalid capture kind: {raw_kind}") from exc

    summary = _normalize_summary(item.get("summary"), field_name="Capture summary")
    detail = str(item.get("detail") or "").strip() or None
    tags = _normalize_tags(item.get("tags"))
    confidence_raw = item.get("confidence")
    confidence = None
    if confidence_raw is not None and str(confidence_raw).strip():
        confidence = str(confidence_raw).strip().lower()
        if confidence not in _CONFIDENCE_VALUES:
            raise SemanticIntakeError("Capture confidence must be one of: low, medium, high.")

    blocking_present = "blocking" in item
    blocking = bool(item.get("blocking")) if blocking_present else False
    if blocking_present and kind.value not in _BLOCKING_ALLOWED_KINDS:
        raise SemanticIntakeError(f"blocking is only allowed for question, unknown, or risk captures (got {kind.value}).")

    related_paths = normalize_related_paths(item.get("related_paths"), engine_root=engine_root, data_root=data_root)
    return {
        "kind": kind.value,
        "summary": summary,
        "detail": detail,
        "blocking": blocking,
        "confidence": confidence,
        "related_paths": related_paths,
        "tags": tags,
    }


def build_capture_batch(
    *,
    subject: str,
    run_data: dict[str, Any],
    raw_text: str,
    payload: Any,
    source_role: str | CaptureSourceRole | None,
    engine_root: Path,
    data_root: Path,
    title_override: str | None = None,
    capture_batch_id: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    raw = str(raw_text or "")
    if not raw.strip():
        raise SemanticIntakeError("Raw capture text must be non-empty.")
    run_id = str(run_data.get("run_id") or "").strip()
    session_id = str(run_data.get("session_id") or "").strip()
    session_mode = str(run_data.get("session_mode") or "").strip()
    session_mode_source = str(run_data.get("session_mode_source") or "").strip()
    session_mode_policy_version = run_data.get("session_mode_policy_version")
    if not run_id or not session_id or not session_mode or not session_mode_source or session_mode_policy_version is None:
        raise SemanticIntakeError(
            "capture-chunk requires a normalized active run with run_id, session_id, session_mode, "
            "session_mode_source, and session_mode_policy_version."
        )

    normalized_payload = normalize_capture_payload(payload, engine_root=engine_root, data_root=data_root)
    batch_id = capture_batch_id or generate_capture_batch_id()
    when = captured_at or _now_iso()
    title = str(title_override or normalized_payload.get("title") or "").strip() or None
    source = normalize_capture_source_role(source_role)

    captures: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_payload["captures"]):
        capture = dict(item)
        capture["capture_id"] = capture_item_id(batch_id, index)
        captures.append(capture)

    return {
        "capture_batch_id": batch_id,
        "captured_at": when,
        "subject": subject,
        "run_id": run_id,
        "session_id": session_id,
        "session_mode": session_mode,
        "session_mode_source": session_mode_source,
        "session_mode_policy_version": session_mode_policy_version,
        "source_role": source.value,
        "title": title,
        "tags": normalized_payload.get("tags") or [],
        "raw_text": raw,
        "captures": captures,
    }


def capture_artifact_path(data_root: Path, *, batch: dict[str, Any]) -> Path:
    captured_at = str(batch.get("captured_at") or "").strip()
    if not captured_at:
        raise SemanticIntakeError("Capture batch missing captured_at.")
    try:
        stamp = dt.datetime.fromisoformat(captured_at).strftime("%Y%m%d-%H%M%S")
    except ValueError as exc:
        raise SemanticIntakeError(f"Capture batch has invalid captured_at: {captured_at}") from exc
    slug_source = str(batch.get("title") or "").strip()
    if not slug_source:
        captures = batch.get("captures") or []
        if captures and isinstance(captures[0], dict):
            slug_source = str(captures[0].get("summary") or "").strip()
    slug = _slugify(slug_source or str(batch.get("capture_batch_id") or "capture"))[:48]
    return (capture_batches_dir(data_root) / f"CAPTURE__{stamp}__{slug}.yaml").resolve()


def write_capture_batch(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    run_data: dict[str, Any],
    raw_text: str,
    payload: Any,
    source_role: str | CaptureSourceRole | None = None,
    title_override: str | None = None,
) -> dict[str, Any]:
    batch = build_capture_batch(
        subject=subject,
        run_data=run_data,
        raw_text=raw_text,
        payload=payload,
        source_role=source_role,
        engine_root=engine_root,
        data_root=data_root,
        title_override=title_override,
    )
    artifact_path = capture_artifact_path(data_root, batch=batch)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(yaml.safe_dump(batch, sort_keys=False), encoding="utf-8")

    ledger_path = capture_daily_ledger_path(data_root, stamp=str(batch["captured_at"])[:10])
    ledger_entry = {
        "capture_batch_id": batch["capture_batch_id"],
        "captured_at": batch["captured_at"],
        "source_role": batch["source_role"],
        "title": batch.get("title"),
        "session_mode": batch.get("session_mode"),
        "run_id": batch.get("run_id"),
        "session_id": batch.get("session_id"),
        "capture_count": len(batch["captures"]),
        "capture_kinds": [str(item.get("kind")) for item in batch["captures"]],
        "artifact_path": str(artifact_path),
    }
    _append_ledger_entry(ledger_path, subject=subject, entry=ledger_entry)
    return {
        "batch": batch,
        "artifact_path": str(artifact_path),
        "ledger_path": str(ledger_path.resolve()),
        "ledger_entry": ledger_entry,
    }


def load_capture_batch(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SemanticIntakeError(f"Unable to load capture artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise SemanticIntakeError(f"Malformed capture artifact: {path}")
    if not payload.get("capture_batch_id") or not isinstance(payload.get("captures"), list):
        raise SemanticIntakeError(f"Malformed capture artifact: {path}")
    return payload


def semantic_detail_records(batch: dict[str, Any]) -> list[dict[str, Any]]:
    batch_id = str(batch.get("capture_batch_id") or "").strip()
    captured_at = str(batch.get("captured_at") or "").strip() or None
    source_role = str(batch.get("source_role") or "").strip() or None
    details: list[dict[str, Any]] = []
    for capture in batch.get("captures") or []:
        if not isinstance(capture, dict):
            continue
        details.append(
            {
                "capture_id": str(capture.get("capture_id") or "").strip() or None,
                "batch_id": batch_id,
                "kind": str(capture.get("kind") or "").strip() or None,
                "summary": str(capture.get("summary") or "").strip() or None,
                "detail": str(capture.get("detail") or "").strip() or None,
                "blocking": bool(capture.get("blocking")),
                "captured_at": captured_at,
                "source_role": source_role,
                "related_paths": list(capture.get("related_paths") or []),
            }
        )
    return [detail for detail in details if detail["capture_id"] and detail["kind"] and detail["summary"]]


def semantic_detail_lists(batch: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    details = semantic_detail_records(batch)
    return {
        "open_question_details": [detail for detail in details if detail["kind"] in _QUESTION_KINDS],
        "blocking_question_details": [
            detail for detail in details if detail["kind"] in _QUESTION_KINDS and bool(detail.get("blocking"))
        ],
        "recent_idea_details": [detail for detail in details if detail["kind"] == CaptureKind.IDEA.value],
        "recent_repo_fact_details": [detail for detail in details if detail["kind"] == CaptureKind.REPO_FACT.value],
        "recent_constraint_details": [detail for detail in details if detail["kind"] == CaptureKind.CONSTRAINT.value],
        "recent_risk_details": [detail for detail in details if detail["kind"] == CaptureKind.RISK.value],
        "recent_dependency_details": [detail for detail in details if detail["kind"] == CaptureKind.DEPENDENCY.value],
        "recent_non_goal_details": [detail for detail in details if detail["kind"] == CaptureKind.NON_GOAL.value],
        "recent_milestone_details": [detail for detail in details if detail["kind"] == CaptureKind.MILESTONE.value],
        "candidate_decision_details": [detail for detail in details if detail["kind"] == CaptureKind.DECISION.value],
    }


def merge_semantic_details(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
    *,
    cap: int = 10,
) -> list[dict[str, Any]]:
    combined = [detail for detail in (existing or []) if isinstance(detail, dict)] + [
        detail for detail in (incoming or []) if isinstance(detail, dict)
    ]
    ordered = sorted(
        combined,
        key=lambda detail: (
            str(detail.get("captured_at") or ""),
            str(detail.get("capture_id") or ""),
        ),
    )
    deduped: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for detail in ordered:
        deduped[_semantic_key(detail)] = detail
    return sorted(
        deduped.values(),
        key=lambda detail: (
            str(detail.get("captured_at") or ""),
            str(detail.get("capture_id") or ""),
        ),
        reverse=True,
    )[:cap]


def capture_kinds(batch: dict[str, Any]) -> list[str]:
    kinds: list[str] = []
    for capture in batch.get("captures") or []:
        if not isinstance(capture, dict):
            continue
        kind = str(capture.get("kind") or "").strip()
        if kind:
            kinds.append(kind)
    return kinds


def batch_uncertainty_present(batch: dict[str, Any]) -> bool:
    return any(kind in {"question", "unknown", "risk"} for kind in capture_kinds(batch))


def batch_disclosure_needed(batch: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict)
        and bool(item.get("blocking"))
        and str(item.get("kind") or "").strip() in {"question", "unknown", "risk"}
        for item in batch.get("captures") or []
    )


def derive_semantic_promotions(batch: dict[str, Any]) -> list[PromotionRecord]:
    kinds = set(capture_kinds(batch))
    blocking_uncertainty = batch_disclosure_needed(batch)
    title = str(batch.get("title") or "").strip() or "Semantic intake batch"
    summary = _promotion_summary(batch)
    evidence = (str(batch.get("capture_batch_id") or ""),)
    promotions: list[PromotionRecord] = []

    if kinds & {CaptureKind.IDEA.value, CaptureKind.MILESTONE.value}:
        promotions.append(_promotion(ProposalKind.QUEST, title=title, summary=summary, evidence=evidence))
    if kinds & {CaptureKind.REPO_FACT.value, CaptureKind.CONSTRAINT.value, CaptureKind.NON_GOAL.value, CaptureKind.DEPENDENCY.value}:
        promotions.append(_promotion(ProposalKind.CODEX, title=title, summary=summary, evidence=evidence))
    if kinds & {CaptureKind.DEPENDENCY.value, CaptureKind.MILESTONE.value, CaptureKind.CONSTRAINT.value}:
        promotions.append(_promotion(ProposalKind.BUILD_MANUAL, title=title, summary=summary, evidence=evidence))
    if CaptureKind.DECISION.value in kinds:
        promotions.append(_promotion(ProposalKind.CONTROL_SYNC, title=title, summary=summary, evidence=evidence))
    if blocking_uncertainty:
        promotions.append(_promotion(ProposalKind.DISCLOSURE, title=title, summary=summary, evidence=evidence))
    return promotions


def _promotion(kind: ProposalKind, *, title: str, summary: str, evidence: tuple[str, ...]) -> PromotionRecord:
    return PromotionRecord(
        kind=kind,
        state=ProposalState.AMBIENT,
        title=title,
        summary=summary,
        reason=_PROMOTION_REASON[kind],
        evidence=evidence,
    )


def _promotion_summary(batch: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for capture in batch.get("captures") or []:
        if not isinstance(capture, dict):
            continue
        kind = str(capture.get("kind") or "").strip()
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return "Semantic capture batch recorded without typed entries."
    parts = [f"{kind}={counts[kind]}" for kind in sorted(counts)]
    return f"Semantic capture batch recorded: {', '.join(parts)}."


def is_managed_open_questions_text(text: str) -> bool:
    return OPEN_QUESTIONS_MANAGED_MARKER in str(text or "")


def matches_open_questions_scaffold(text: str) -> bool:
    return str(text or "").rstrip() == OPEN_QUESTIONS_SCAFFOLD.rstrip()


def render_managed_open_questions(details: list[dict[str, Any]]) -> str:
    ordered = sorted(
        [detail for detail in details if str(detail.get("kind") or "") in _QUESTION_KINDS],
        key=lambda detail: str(detail.get("captured_at") or ""),
    )
    blocking: list[str] = []
    nonblocking: list[str] = []
    seen_blocking: set[tuple[str, str, bool]] = set()
    seen_nonblocking: set[tuple[str, str, bool]] = set()
    for detail in ordered:
        key = _semantic_key(detail)
        bucket = blocking if bool(detail.get("blocking")) else nonblocking
        seen = seen_blocking if bool(detail.get("blocking")) else seen_nonblocking
        if key in seen:
            continue
        seen.add(key)
        bucket.append(f"- {detail['summary']}")
    return _OPEN_QUESTIONS_MANAGED_TEMPLATE.format(
        blocking_lines="\n".join(blocking) if blocking else "- None yet.",
        nonblocking_lines="\n".join(nonblocking) if nonblocking else "- None yet.",
    )


def _semantic_key(detail: dict[str, Any]) -> tuple[str, str, bool]:
    kind = str(detail.get("kind") or "").strip().lower()
    summary = " ".join(str(detail.get("summary") or "").split()).lower()
    blocking = bool(detail.get("blocking"))
    return (kind, summary, blocking)

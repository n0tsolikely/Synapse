"""Normalized segmentation and semantic classification for the engaged kernel."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from synapse_runtime.kernel_types import (
    ConversationSegmentEnvelope,
    ExecutionSegmentEnvelope,
    KERNEL_SCHEMA_VERSION,
    PlanEventEnvelope,
    SEMANTIC_CLASSIFIER_VERSION,
    SemanticClassLabel,
    SemanticConfidenceBand,
    SemanticEventEnvelope,
    SemanticMaterialityBand,
    SegmentFamily,
    stable_kernel_id,
)


SEGMENTS_DIRNAME = "SEGMENTS"
SEMANTIC_EVENTS_DIRNAME = "SEMANTIC_EVENTS"
PLAN_EVENTS_DIRNAME = "PLAN_EVENTS"
AUTHORITATIVE_PLAN_STORE = ".synapse/PLANS/"
MAX_PREVIEW_CHARS = 240
MAX_RECENT_ITEMS = 10

_NOISE_TEXTS = {
    "ok",
    "okay",
    "cool",
    "sounds good",
    "sure",
    "thanks",
    "thank you",
    "got it",
    "lets do it",
    "let's do it",
}
_QUESTION_CUES = ("?", "how ", "what ", "why ", "when ", "where ", "who ")
_PLAN_CUES = ("plan", "milestone", "step", "steps", "we need to", "need to", "let's", "lets ", "implement")
_SCOPE_CUES = ("support", "must", "needs to", "need to", "should", "require", "i want", "we want", "goal")
_ARCHITECTURE_CUES = (
    "web app",
    "api",
    "database",
    "auth",
    "account",
    "accounts",
    "transcribe",
    "local only",
    "cloud",
    "installable",
    "desktop app",
)
_DECISION_CUES = ("decision:", "we decided", "decided", "going with", "will use", "lock in")
_RISK_CUES = ("risk", "unknown", "uncertain", "uncertainty", "blocked", "blocker")
_ERROR_CUES = ("error", "bug", "failing", "failed", "problem", "issue", "regression", "crash")
_VISION_CUES = ("vision", "mission", "portfolio", "investor", "story", "soul")
_VERIFICATION_CUES = ("pytest", "unittest", "test ", "tests ", "lint", "verify", "verification")
_REPO_FACT_CUES = ("exists", "already", "currently", "implemented", "in repo", "codebase")


class SemanticClassifierError(RuntimeError):
    """Raised when normalized semantic persistence or parsing fails."""


def semantic_root(data_root: Path) -> Path:
    return data_root / ".synapse"


def conversation_segments_dir(data_root: Path) -> Path:
    return semantic_root(data_root) / SEGMENTS_DIRNAME / "CONVERSATION"


def execution_segments_dir(data_root: Path) -> Path:
    return semantic_root(data_root) / SEGMENTS_DIRNAME / "EXECUTION"


def semantic_events_dir(data_root: Path) -> Path:
    return semantic_root(data_root) / SEMANTIC_EVENTS_DIRNAME


def plan_events_dir(data_root: Path) -> Path:
    return semantic_root(data_root) / PLAN_EVENTS_DIRNAME


def ensure_semantic_scaffold(data_root: Path) -> dict[str, Any]:
    created: list[str] = []
    existing: list[str] = []
    for path in (
        conversation_segments_dir(data_root),
        execution_segments_dir(data_root),
        semantic_events_dir(data_root),
        plan_events_dir(data_root),
    ):
        if path.exists():
            existing.append(str(path.resolve()))
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path.resolve()))
    return {"created": created, "existing": existing}


def _day_bucket(recorded_at: str) -> str:
    return str(recorded_at or "").split("T", 1)[0]


def _preview(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= MAX_PREVIEW_CHARS:
        return compact
    return compact[: MAX_PREVIEW_CHARS - 1] + "…"


def _record_path(root: Path, recorded_at: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_day_bucket(recorded_at)}.jsonl"


def _append_jsonl_unique(path: Path, *, record_id_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    record_id = str(payload.get(record_id_key) or "").strip()
    if not record_id:
        raise SemanticClassifierError(f"Normalized record missing required id key: {record_id_key}")
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    existing = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise SemanticClassifierError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
                if str(existing.get(record_id_key) or "").strip() == record_id:
                    return {"path": str(path.resolve()), "record_id": record_id, "written": False}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return {"path": str(path.resolve()), "record_id": record_id, "written": True}


def _source_ref_from_raw_record(raw_record: dict[str, Any], *, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": raw_record.get("raw_turn_id") or raw_record.get("raw_event_id"),
        "path": raw_record.get("raw_turn_path") or raw_record.get("raw_event_path"),
        "sha256": raw_record.get("raw_turn_sha256") or raw_record.get("raw_event_sha256"),
    }


def _source_ref_from_blob(blob: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(blob, dict):
        return None
    path = str(blob.get("path") or "").strip()
    sha256 = str(blob.get("sha256") or "").strip()
    if not path or not sha256:
        return None
    return {
        "kind": "raw_blob",
        "id": sha256,
        "path": path,
        "sha256": sha256,
        "mime_type": blob.get("mime_type"),
    }


def conversation_blocks(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks: list[str] = []
    for chunk in re.split(r"\n\s*\n+", normalized):
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) > 1 and all(re.match(r"^[-*]\s+", line) for line in lines):
            for line in lines:
                blocks.append(re.sub(r"^[-*]\s+", "", line).strip())
            continue
        blocks.append(" ".join(lines))
    return blocks or [normalized]


def conversation_segments_from_raw_turn(raw_turn: dict[str, Any], *, text: str) -> list[ConversationSegmentEnvelope]:
    recorded_at = str(raw_turn.get("recorded_at") or "").strip()
    subject = str(raw_turn.get("subject") or "").strip()
    source_turn_id = str(raw_turn.get("raw_turn_id") or "").strip()
    source_surface = str(raw_turn.get("source_surface") or "unknown").strip() or "unknown"
    role = str(raw_turn.get("role") or "user").strip() or "user"
    session_id = str(raw_turn.get("session_id") or "").strip() or None
    run_id = str(raw_turn.get("run_id") or "").strip() or None
    source_refs = [_source_ref_from_raw_record(raw_turn, kind="raw_conversation_turn")]
    blob_ref = _source_ref_from_blob(raw_turn.get("text_blob"))
    if blob_ref is not None:
        source_refs.append(blob_ref)

    segments: list[ConversationSegmentEnvelope] = []
    for index, block in enumerate(conversation_blocks(text)):
        segment_id = stable_kernel_id("SEGCONV", source_turn_id, index)
        segments.append(
            ConversationSegmentEnvelope(
                segment_id=segment_id,
                schema_version=KERNEL_SCHEMA_VERSION,
                classifier_version=SEMANTIC_CLASSIFIER_VERSION,
                recorded_at=recorded_at,
                subject=subject,
                segment_family=SegmentFamily.CONVERSATION.value,
                source_turn_id=source_turn_id,
                source_surface=source_surface,
                session_id=session_id,
                run_id=run_id,
                role=role,
                segment_index=index,
                text_preview=_preview(block),
                text_length=len(block),
                transient_noise=_is_noise(block),
                source_refs=source_refs,
            )
        )
    return segments


def execution_segment_from_raw_event(raw_event: dict[str, Any], *, payload_preview: str | None = None) -> ExecutionSegmentEnvelope:
    recorded_at = str(raw_event.get("recorded_at") or "").strip()
    subject = str(raw_event.get("subject") or "").strip()
    source_event_id = str(raw_event.get("raw_event_id") or "").strip()
    source_surface = str(raw_event.get("source_surface") or "unknown").strip() or "unknown"
    command_preview = str(raw_event.get("command") or "").strip() or (payload_preview or None)
    source_refs = [_source_ref_from_raw_record(raw_event, kind="raw_execution_event")]
    blob_ref = _source_ref_from_blob(raw_event.get("payload_blob"))
    if blob_ref is not None:
        source_refs.append(blob_ref)
    return ExecutionSegmentEnvelope(
        segment_id=stable_kernel_id("SEGEXEC", source_event_id),
        schema_version=KERNEL_SCHEMA_VERSION,
        classifier_version=SEMANTIC_CLASSIFIER_VERSION,
        recorded_at=recorded_at,
        subject=subject,
        segment_family=SegmentFamily.EXECUTION.value,
        source_event_id=source_event_id,
        source_surface=source_surface,
        session_id=str(raw_event.get("session_id") or "").strip() or None,
        run_id=str(raw_event.get("run_id") or "").strip() or None,
        event_family=str(raw_event.get("family") or "").strip(),
        phase=str(raw_event.get("phase") or "").strip() or None,
        tool_name=str(raw_event.get("tool_name") or "").strip() or None,
        status=str(raw_event.get("status") or "").strip() or None,
        changed_files=list(raw_event.get("changed_files") or []),
        command_preview=_preview(command_preview or "") if command_preview else None,
        transient_noise=not (command_preview or raw_event.get("changed_files") or raw_event.get("status")),
        source_refs=source_refs,
    )


def _is_noise(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return True
    if normalized in _NOISE_TEXTS:
        return True
    if len(normalized) <= 8 and normalized.isalpha():
        return True
    return False


def _band(value: str, enum_type: type[SemanticConfidenceBand] | type[SemanticMaterialityBand]) -> str:
    return enum_type(str(value)).value


def _cap_imported_confidence(band: str) -> str:
    if band == SemanticConfidenceBand.HIGH.value:
        return SemanticConfidenceBand.MEDIUM.value
    if band == SemanticConfidenceBand.MEDIUM.value:
        return SemanticConfidenceBand.LOW.value
    return band


def _emit_semantic_event(
    *,
    segment_id: str,
    subject: str,
    recorded_at: str,
    class_label: str,
    topic_key: str,
    confidence_band: str,
    materiality_band: str,
    summary: str,
    source_refs: list[dict[str, Any]],
    related_paths: list[str] | None = None,
    imported_limited: bool = False,
) -> SemanticEventEnvelope:
    confidence = _cap_imported_confidence(confidence_band) if imported_limited else confidence_band
    return SemanticEventEnvelope(
        semantic_event_id=stable_kernel_id(
            "SEM",
            segment_id,
            class_label,
            topic_key,
            summary,
            SEMANTIC_CLASSIFIER_VERSION,
        ),
        schema_version=KERNEL_SCHEMA_VERSION,
        classifier_version=SEMANTIC_CLASSIFIER_VERSION,
        recorded_at=recorded_at,
        subject=subject,
        class_label=class_label,
        topic_key=topic_key,
        confidence_band=confidence,
        materiality_band=materiality_band,
        summary=summary,
        transient_noise=class_label == SemanticClassLabel.TRANSIENT_NOISE.value,
        imported_limited=imported_limited,
        source_segment_ids=[segment_id],
        source_refs=list(source_refs),
        related_paths=list(related_paths or []),
    )


def classify_conversation_segment(
    segment: ConversationSegmentEnvelope,
    *,
    text: str,
    imported_limited: bool = False,
    related_paths: list[str] | None = None,
) -> list[SemanticEventEnvelope]:
    normalized = " ".join(str(text or "").split())
    lowered = normalized.lower()
    if _is_noise(normalized):
        return [
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.TRANSIENT_NOISE.value,
                topic_key="transient.noise",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.LOW.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        ]

    events: list[SemanticEventEnvelope] = []
    if any(lowered.startswith(prefix) or prefix in lowered for prefix in _QUESTION_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.QUESTION.value,
                topic_key="question.open",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.MEDIUM.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _PLAN_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.BUILD_PLAN_SIGNAL.value,
                topic_key="build.plan",
                confidence_band=SemanticConfidenceBand.MEDIUM.value if imported_limited else SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _SCOPE_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.SCOPE_STATEMENT.value,
                topic_key="project.scope",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _ARCHITECTURE_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.ARCHITECTURE_STATEMENT.value,
                topic_key="architecture.shape",
                confidence_band=SemanticConfidenceBand.MEDIUM.value if imported_limited else SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _DECISION_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.DECISION_SIGNAL.value,
                topic_key="decision.locked",
                confidence_band=SemanticConfidenceBand.MEDIUM.value if imported_limited else SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _RISK_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.RISK_SIGNAL.value,
                topic_key="risk.blocker",
                confidence_band=SemanticConfidenceBand.MEDIUM.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _ERROR_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.ERROR_SIGNAL.value,
                topic_key="execution.error",
                confidence_band=SemanticConfidenceBand.MEDIUM.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _VISION_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.VISION_STATEMENT.value,
                topic_key="project.vision",
                confidence_band=SemanticConfidenceBand.MEDIUM.value if imported_limited else SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.MEDIUM.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )
    if any(cue in lowered for cue in _REPO_FACT_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.REPO_FACT.value,
                topic_key="repo.fact",
                confidence_band=SemanticConfidenceBand.MEDIUM.value if imported_limited else SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.MEDIUM.value,
                summary=_preview(normalized),
                source_refs=segment.source_refs,
                related_paths=related_paths,
                imported_limited=imported_limited,
            )
        )

    deduped: dict[tuple[str, str, str], SemanticEventEnvelope] = {}
    for event in events:
        deduped[(event.class_label, event.topic_key, event.summary)] = event
    return list(deduped.values())


def classify_execution_segment(segment: ExecutionSegmentEnvelope) -> list[SemanticEventEnvelope]:
    summary_parts = [
        part
        for part in (
            segment.command_preview,
            segment.tool_name,
            segment.status,
        )
        if str(part or "").strip()
    ]
    summary = _preview(" | ".join(summary_parts) or f"{segment.event_family} event")
    events: list[SemanticEventEnvelope] = []

    if any(cue in str(segment.command_preview or "").lower() for cue in _VERIFICATION_CUES):
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.VERIFICATION_SIGNAL.value,
                topic_key="verification.command",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.MEDIUM.value,
                summary=summary,
                source_refs=segment.source_refs,
            )
        )
    if segment.status and segment.status.lower() in {"failed", "blocked"}:
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.ERROR_SIGNAL.value,
                topic_key="execution.failure",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.HIGH.value,
                summary=summary,
                source_refs=segment.source_refs,
                related_paths=segment.changed_files,
            )
        )
    elif segment.changed_files or segment.command_preview:
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.EXECUTION_SIGNAL.value,
                topic_key="execution.change",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.MEDIUM.value,
                summary=summary,
                source_refs=segment.source_refs,
                related_paths=segment.changed_files,
            )
        )

    if not events:
        events.append(
            _emit_semantic_event(
                segment_id=segment.segment_id,
                subject=segment.subject,
                recorded_at=segment.recorded_at,
                class_label=SemanticClassLabel.TRANSIENT_NOISE.value,
                topic_key="transient.noise",
                confidence_band=SemanticConfidenceBand.HIGH.value,
                materiality_band=SemanticMaterialityBand.LOW.value,
                summary=summary,
                source_refs=segment.source_refs,
            )
        )
    return events


def plan_events_from_semantic_events(
    semantic_events: list[Any],
    *,
    subject: str,
    recorded_at: str,
) -> list[PlanEventEnvelope]:
    plan_events: list[PlanEventEnvelope] = []
    for event in semantic_events:
        payload = event.to_dict() if isinstance(event, SemanticEventEnvelope) else dict(event)
        if str(payload.get("class_label") or "") != SemanticClassLabel.BUILD_PLAN_SIGNAL.value:
            continue
        if bool(payload.get("imported_source")):
            continue
        plan_events.append(
            PlanEventEnvelope(
                plan_event_id=stable_kernel_id("PLANEV", payload.get("semantic_event_id")),
                schema_version=KERNEL_SCHEMA_VERSION,
                classifier_version=SEMANTIC_CLASSIFIER_VERSION,
                recorded_at=recorded_at,
                subject=subject,
                topic_key=str(payload.get("topic_key") or ""),
                confidence_band=str(payload.get("confidence_band") or ""),
                materiality_band=str(payload.get("materiality_band") or ""),
                summary=str(payload.get("summary") or ""),
                source_segment_ids=list(payload.get("source_segment_ids") or []),
                source_semantic_event_ids=[str(payload.get("semantic_event_id") or "")],
                source_refs=list(payload.get("source_refs") or []),
                authoritative_plan_store=AUTHORITATIVE_PLAN_STORE,
            )
        )
    return plan_events


def persist_conversation_segments(data_root: Path, segments: list[ConversationSegmentEnvelope]) -> list[dict[str, Any]]:
    ensure_semantic_scaffold(data_root)
    receipts: list[dict[str, Any]] = []
    for segment in segments:
        payload = segment.to_dict()
        path = _record_path(conversation_segments_dir(data_root), payload["recorded_at"])
        receipts.append(_append_jsonl_unique(path, record_id_key="segment_id", payload=payload))
    return receipts


def persist_execution_segments(data_root: Path, segments: list[ExecutionSegmentEnvelope]) -> list[dict[str, Any]]:
    ensure_semantic_scaffold(data_root)
    receipts: list[dict[str, Any]] = []
    for segment in segments:
        payload = segment.to_dict()
        path = _record_path(execution_segments_dir(data_root), payload["recorded_at"])
        receipts.append(_append_jsonl_unique(path, record_id_key="segment_id", payload=payload))
    return receipts


def persist_semantic_events(data_root: Path, semantic_events: list[Any]) -> list[dict[str, Any]]:
    ensure_semantic_scaffold(data_root)
    receipts: list[dict[str, Any]] = []
    for event in semantic_events:
        payload = event.to_dict() if isinstance(event, SemanticEventEnvelope) else dict(event)
        path = _record_path(semantic_events_dir(data_root), payload["recorded_at"])
        receipts.append(_append_jsonl_unique(path, record_id_key="semantic_event_id", payload=payload))
    return receipts


def persist_plan_events(data_root: Path, plan_events: list[Any]) -> list[dict[str, Any]]:
    ensure_semantic_scaffold(data_root)
    receipts: list[dict[str, Any]] = []
    for event in plan_events:
        payload = event if isinstance(event, dict) else event.to_dict()
        path = _record_path(plan_events_dir(data_root), payload["recorded_at"])
        receipts.append(_append_jsonl_unique(path, record_id_key="plan_event_id", payload=payload))
    return receipts


def _load_jsonl_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in sorted(root.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    records.append(json.loads(text))
                except json.JSONDecodeError as exc:
                    raise SemanticClassifierError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
    return records


def normalized_semantic_summary(data_root: Path) -> dict[str, Any]:
    ensure_semantic_scaffold(data_root)
    conversation_segments = _load_jsonl_records(conversation_segments_dir(data_root))
    execution_segments = _load_jsonl_records(execution_segments_dir(data_root))
    semantic_events = _load_jsonl_records(semantic_events_dir(data_root))
    plan_events = _load_jsonl_records(plan_events_dir(data_root))

    non_transient_events = [item for item in semantic_events if not item.get("transient_noise")]
    recent_events = sorted(
        non_transient_events or semantic_events,
        key=lambda item: (
            str(item.get("recorded_at") or ""),
            str(item.get("semantic_event_id") or ""),
        ),
        reverse=True,
    )[:MAX_RECENT_ITEMS]
    return {
        "conversation_segment_count": len(conversation_segments),
        "execution_segment_count": len(execution_segments),
        "semantic_event_count": len(semantic_events),
        "transient_semantic_event_count": sum(1 for item in semantic_events if item.get("transient_noise")),
        "plan_event_count": len(plan_events),
        "last_conversation_segment_id": conversation_segments[-1].get("segment_id") if conversation_segments else None,
        "last_execution_segment_id": execution_segments[-1].get("segment_id") if execution_segments else None,
        "last_semantic_event_id": semantic_events[-1].get("semantic_event_id") if semantic_events else None,
        "last_semantic_event_at": semantic_events[-1].get("recorded_at") if semantic_events else None,
        "recent_conversation_segment_ids": [
            str(item.get("segment_id"))
            for item in sorted(
                conversation_segments,
                key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("segment_id") or "")),
                reverse=True,
            )[:MAX_RECENT_ITEMS]
            if str(item.get("segment_id") or "").strip()
        ],
        "recent_execution_segment_ids": [
            str(item.get("segment_id"))
            for item in sorted(
                execution_segments,
                key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("segment_id") or "")),
                reverse=True,
            )[:MAX_RECENT_ITEMS]
            if str(item.get("segment_id") or "").strip()
        ],
        "recent_semantic_event_details": [
            {
                "semantic_event_id": item.get("semantic_event_id"),
                "class_label": item.get("class_label"),
                "topic_key": item.get("topic_key"),
                "confidence_band": item.get("confidence_band"),
                "materiality_band": item.get("materiality_band"),
                "summary": item.get("summary"),
                "transient_noise": bool(item.get("transient_noise")),
                "source_segment_ids": list(item.get("source_segment_ids") or []),
            }
            for item in recent_events
        ],
        "recent_plan_event_ids": [
            str(item.get("plan_event_id"))
            for item in sorted(
                plan_events,
                key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("plan_event_id") or "")),
                reverse=True,
            )[:MAX_RECENT_ITEMS]
            if str(item.get("plan_event_id") or "").strip()
        ],
    }

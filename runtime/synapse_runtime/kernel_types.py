"""Shared engaged-kernel ids, enums, and normalized/raw envelope schemas."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
KERNEL_SCHEMA_VERSION = 1
LOCAL_CODEX_INTEGRATION_VERSION = 1
SEMANTIC_CLASSIFIER_VERSION = "v1-phase1"


class RawStoreFamily(str, Enum):
    CONVERSATION_TURNS = "CONVERSATION_TURNS"
    EXECUTION_EVENTS = "EXECUTION_EVENTS"
    TOOL_EVENTS = "TOOL_EVENTS"
    IMPORT_EVENTS = "IMPORT_EVENTS"
    BLOBS = "BLOBS"


class ConversationTurnRole(str, Enum):
    USER = "user"
    EXECUTOR = "executor"


class LocalIntegrationPosture(str, Enum):
    HOOKED = "hooked"
    DEGRADED = "degraded"


class LocalIntegrationHealth(str, Enum):
    INSTALLED = "installed"
    UPDATED = "updated"
    NOOP = "noop"
    MISSING = "missing"
    PARTIAL = "partial"
    STALE = "stale"


class SegmentFamily(str, Enum):
    CONVERSATION = "conversation"
    EXECUTION = "execution"


class SemanticConfidenceBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SemanticMaterialityBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SemanticClassLabel(str, Enum):
    TRANSIENT_NOISE = "transient_noise"
    QUESTION = "question"
    SCOPE_STATEMENT = "scope_statement"
    BUILD_PLAN_SIGNAL = "build_plan_signal"
    ARCHITECTURE_STATEMENT = "architecture_statement"
    DECISION_SIGNAL = "decision_signal"
    RISK_SIGNAL = "risk_signal"
    ERROR_SIGNAL = "error_signal"
    VISION_STATEMENT = "vision_statement"
    EXECUTION_SIGNAL = "execution_signal"
    VERIFICATION_SIGNAL = "verification_signal"
    REPO_FACT = "repo_fact"


class ImportedContinuityKind(str, Enum):
    TRANSCRIPT = "transcript"
    NOTE = "note"
    PDF = "pdf"


class ImportedContinuityParseStatus(str, Enum):
    PARSED = "parsed"
    LIMITED = "limited"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RawArtifactRef:
    raw_id: str
    family: str
    path: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_id": self.raw_id,
            "family": self.family,
            "path": self.path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class RawBlobRef:
    sha256: str
    path: str
    mime_type: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "path": self.path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class RawConversationTurnEnvelope:
    raw_turn_id: str
    schema_version: int
    recorded_at: str
    subject: str
    role: str
    source_surface: str
    session_id: str | None
    run_id: str | None
    text_preview: str
    text_blob: RawBlobRef
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_turn_id": self.raw_turn_id,
            "schema_version": self.schema_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "role": self.role,
            "source_surface": self.source_surface,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "text_preview": self.text_preview,
            "text_blob": self.text_blob.to_dict(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RawExecutionEnvelope:
    raw_event_id: str
    schema_version: int
    recorded_at: str
    subject: str
    family: str
    source_surface: str
    phase: str | None
    session_id: str | None
    run_id: str | None
    command: str | None
    tool_name: str | None
    status: str | None
    changed_files: list[str]
    payload_blob: RawBlobRef | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_event_id": self.raw_event_id,
            "schema_version": self.schema_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "family": self.family,
            "source_surface": self.source_surface,
            "phase": self.phase,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "command": self.command,
            "tool_name": self.tool_name,
            "status": self.status,
            "changed_files": list(self.changed_files),
            "payload_blob": self.payload_blob.to_dict() if self.payload_blob else None,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ConversationSegmentEnvelope:
    segment_id: str
    schema_version: int
    classifier_version: str
    recorded_at: str
    subject: str
    segment_family: str
    source_turn_id: str
    source_surface: str
    session_id: str | None
    run_id: str | None
    role: str
    segment_index: int
    text_preview: str
    text_length: int
    transient_noise: bool
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "schema_version": self.schema_version,
            "classifier_version": self.classifier_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "segment_family": self.segment_family,
            "source_turn_id": self.source_turn_id,
            "source_surface": self.source_surface,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "role": self.role,
            "segment_index": self.segment_index,
            "text_preview": self.text_preview,
            "text_length": self.text_length,
            "transient_noise": self.transient_noise,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class ExecutionSegmentEnvelope:
    segment_id: str
    schema_version: int
    classifier_version: str
    recorded_at: str
    subject: str
    segment_family: str
    source_event_id: str
    source_surface: str
    session_id: str | None
    run_id: str | None
    event_family: str
    phase: str | None
    tool_name: str | None
    status: str | None
    changed_files: list[str]
    command_preview: str | None
    transient_noise: bool
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "schema_version": self.schema_version,
            "classifier_version": self.classifier_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "segment_family": self.segment_family,
            "source_event_id": self.source_event_id,
            "source_surface": self.source_surface,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "event_family": self.event_family,
            "phase": self.phase,
            "tool_name": self.tool_name,
            "status": self.status,
            "changed_files": list(self.changed_files),
            "command_preview": self.command_preview,
            "transient_noise": self.transient_noise,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class SemanticEventEnvelope:
    semantic_event_id: str
    schema_version: int
    classifier_version: str
    recorded_at: str
    subject: str
    class_label: str
    topic_key: str
    confidence_band: str
    materiality_band: str
    summary: str
    transient_noise: bool
    imported_limited: bool
    source_segment_ids: list[str]
    source_refs: list[dict[str, Any]]
    related_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_event_id": self.semantic_event_id,
            "schema_version": self.schema_version,
            "classifier_version": self.classifier_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "class_label": self.class_label,
            "topic_key": self.topic_key,
            "confidence_band": self.confidence_band,
            "materiality_band": self.materiality_band,
            "summary": self.summary,
            "transient_noise": self.transient_noise,
            "imported_limited": self.imported_limited,
            "source_segment_ids": list(self.source_segment_ids),
            "source_refs": list(self.source_refs),
            "related_paths": list(self.related_paths),
        }


@dataclass(frozen=True)
class PlanEventEnvelope:
    plan_event_id: str
    schema_version: int
    classifier_version: str
    recorded_at: str
    subject: str
    topic_key: str
    confidence_band: str
    materiality_band: str
    summary: str
    source_segment_ids: list[str]
    source_semantic_event_ids: list[str]
    source_refs: list[dict[str, Any]]
    authoritative_plan_store: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_event_id": self.plan_event_id,
            "schema_version": self.schema_version,
            "classifier_version": self.classifier_version,
            "recorded_at": self.recorded_at,
            "subject": self.subject,
            "topic_key": self.topic_key,
            "confidence_band": self.confidence_band,
            "materiality_band": self.materiality_band,
            "summary": self.summary,
            "source_segment_ids": list(self.source_segment_ids),
            "source_semantic_event_ids": list(self.source_semantic_event_ids),
            "source_refs": list(self.source_refs),
            "authoritative_plan_store": self.authoritative_plan_store,
        }


@dataclass(frozen=True)
class ImportedContinuityEnvelope:
    import_id: str
    schema_version: int
    recorded_at: str
    source_path: str
    source_kind: str
    source_sha256: str
    size_bytes: int
    parser_status: str
    parser_name: str
    confidence_band: str
    text_preview: str
    extracted_text: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "schema_version": self.schema_version,
            "recorded_at": self.recorded_at,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_sha256": self.source_sha256,
            "size_bytes": self.size_bytes,
            "parser_status": self.parser_status,
            "parser_name": self.parser_name,
            "confidence_band": self.confidence_band,
            "text_preview": self.text_preview,
            "extracted_text": self.extracted_text,
            "warnings": list(self.warnings),
        }


def kernel_now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def kernel_now_iso() -> str:
    return kernel_now().isoformat()


def raw_id(prefix: str) -> str:
    normalized = str(prefix or "RAW").strip().upper()
    return f"{normalized}-{uuid.uuid4().hex[:16].upper()}"


def stable_kernel_id(prefix: str, *parts: Any) -> str:
    normalized = str(prefix or "KERNEL").strip().upper()
    digest = uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(part or "") for part in parts)).hex[:16].upper()
    return f"{normalized}-{digest}"

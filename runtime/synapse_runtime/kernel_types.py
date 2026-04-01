"""Shared Phase 0 engaged-kernel ids, enums, and raw envelope schemas."""

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


def kernel_now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def kernel_now_iso() -> str:
    return kernel_now().isoformat()


def raw_id(prefix: str) -> str:
    normalized = str(prefix or "RAW").strip().upper()
    return f"{normalized}-{uuid.uuid4().hex[:16].upper()}"

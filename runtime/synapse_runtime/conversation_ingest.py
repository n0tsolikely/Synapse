"""Raw conversation-turn ingestion for the engaged-kernel Phase 0 scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.kernel_types import (
    ConversationTurnRole,
    KERNEL_SCHEMA_VERSION,
    RawBlobRef,
    RawConversationTurnEnvelope,
    kernel_now_iso,
    raw_id,
)
from synapse_runtime.raw_store import RawStoreFamily, write_blob, write_raw_record


class ConversationIngestError(RuntimeError):
    """Raised when raw turn capture input is invalid."""


MAX_PREVIEW_CHARS = 240



def _normalize_role(role: str) -> ConversationTurnRole:
    text = str(role or "").strip().lower()
    try:
        return ConversationTurnRole(text)
    except ValueError as exc:
        raise ConversationIngestError(f"Invalid turn role: {role}") from exc



def _preview(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= MAX_PREVIEW_CHARS:
        return compact
    return compact[: MAX_PREVIEW_CHARS - 1] + "…"



def record_raw_turn(
    *,
    subject: str,
    data_root: Path,
    role: str,
    text: str,
    source_surface: str,
    session_id: str | None = None,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = str(text or "")
    if not body.strip():
        raise ConversationIngestError("Raw turn text cannot be empty.")
    role_value = _normalize_role(role)
    recorded_at = kernel_now_iso()
    raw_turn_id = raw_id("TURN")
    blob = write_blob(data_root=data_root, payload=body, mime_type="text/plain")
    envelope = RawConversationTurnEnvelope(
        raw_turn_id=raw_turn_id,
        schema_version=KERNEL_SCHEMA_VERSION,
        recorded_at=recorded_at,
        subject=str(subject).strip(),
        role=role_value.value,
        source_surface=str(source_surface or "unknown").strip() or "unknown",
        session_id=str(session_id).strip() if str(session_id or "").strip() else None,
        run_id=str(run_id).strip() if str(run_id or "").strip() else None,
        text_preview=_preview(body),
        text_blob=RawBlobRef(**blob),
        metadata=dict(metadata or {}),
    )
    record = write_raw_record(
        data_root=data_root,
        family=RawStoreFamily.CONVERSATION_TURNS,
        record_id=raw_turn_id,
        recorded_at=recorded_at,
        payload=envelope.to_dict(),
    )
    return {
        **envelope.to_dict(),
        "raw_turn_path": record["path"],
        "raw_turn_sha256": record["sha256"],
    }

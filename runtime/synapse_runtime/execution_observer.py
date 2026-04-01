"""Raw execution and tool-event capture for the engaged-kernel Phase 0 scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from synapse_runtime.kernel_types import KERNEL_SCHEMA_VERSION, RawBlobRef, RawExecutionEnvelope, kernel_now_iso, raw_id
from synapse_runtime.live_memory_common import _normalize_relpaths
from synapse_runtime.raw_store import RawStoreFamily, write_blob, write_raw_record


class ExecutionObserverError(RuntimeError):
    """Raised when raw execution capture input is invalid."""



def _normalize_family(value: str) -> RawStoreFamily:
    text = str(value or "").strip().lower()
    if text == "execution":
        return RawStoreFamily.EXECUTION_EVENTS
    if text == "tool":
        return RawStoreFamily.TOOL_EVENTS
    if text == "import":
        return RawStoreFamily.IMPORT_EVENTS
    raise ExecutionObserverError(f"Invalid raw execution family: {value}")



def record_raw_execution(
    *,
    subject: str,
    data_root: Path,
    family: str,
    source_surface: str,
    phase: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    command: str | None = None,
    tool_name: str | None = None,
    status: str | None = None,
    changed_files: list[str] | None = None,
    payload: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    family_value = _normalize_family(family)
    recorded_at = kernel_now_iso()
    if family_value == RawStoreFamily.EXECUTION_EVENTS:
        raw_event_id = raw_id("EXEC")
    elif family_value == RawStoreFamily.IMPORT_EVENTS:
        raw_event_id = raw_id("IMPORT")
    else:
        raw_event_id = raw_id("TOOL")
    payload_blob: RawBlobRef | None = None
    if payload not in (None, "", [], {}):
        mime_type = "application/json" if not isinstance(payload, str) else "text/plain"
        blob = write_blob(data_root=data_root, payload=payload, mime_type=mime_type)
        payload_blob = RawBlobRef(**blob)
    normalized_files = _normalize_relpaths(data_root, changed_files or [])
    envelope = RawExecutionEnvelope(
        raw_event_id=raw_event_id,
        schema_version=KERNEL_SCHEMA_VERSION,
        recorded_at=recorded_at,
        subject=str(subject).strip(),
        family=family_value.value,
        source_surface=str(source_surface or "unknown").strip() or "unknown",
        phase=str(phase).strip() if str(phase or "").strip() else None,
        session_id=str(session_id).strip() if str(session_id or "").strip() else None,
        run_id=str(run_id).strip() if str(run_id or "").strip() else None,
        command=str(command).strip() if str(command or "").strip() else None,
        tool_name=str(tool_name).strip() if str(tool_name or "").strip() else None,
        status=str(status).strip() if str(status or "").strip() else None,
        changed_files=normalized_files,
        payload_blob=payload_blob,
        metadata=dict(metadata or {}),
    )
    record = write_raw_record(
        data_root=data_root,
        family=family_value,
        record_id=raw_event_id,
        recorded_at=recorded_at,
        payload=envelope.to_dict(),
    )
    return {
        **envelope.to_dict(),
        "raw_event_path": record["path"],
        "raw_event_sha256": record["sha256"],
    }


def load_raw_execution_event(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ExecutionObserverError(f"Unable to load raw execution record: {path}") from exc
    if not isinstance(payload, dict) or not str(payload.get("raw_event_id") or "").strip():
        raise ExecutionObserverError(f"Malformed raw execution record: {path}")
    payload["raw_event_path"] = str(path.resolve())
    return payload


def load_raw_execution_payload(raw_event: dict[str, Any]) -> Any | None:
    blob = raw_event.get("payload_blob")
    if not isinstance(blob, dict):
        return None
    blob_path = Path(str(blob.get("path") or "")).expanduser()
    if not blob_path.exists():
        raise ExecutionObserverError(f"Raw execution payload blob does not exist: {blob_path}")
    mime_type = str(blob.get("mime_type") or "").strip().lower()
    if mime_type == "application/json":
        try:
            return json.loads(blob_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ExecutionObserverError(f"Unable to decode raw execution payload blob: {blob_path}") from exc
    try:
        return blob_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise ExecutionObserverError(f"Unable to read raw execution payload blob: {blob_path}") from exc

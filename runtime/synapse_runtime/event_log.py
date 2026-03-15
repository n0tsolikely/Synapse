"""Append-only runtime event log helpers for the Synapse sidecar."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
EVENTS_DIRNAME = "EVENTS"
EVENT_SCHEMA_VERSION = 1
REDUCER_VERSION = "v2.1-phase1"
VALID_STATUSES = {"ok", "blocked", "failed", "partial"}
REQUIRED_SIGNAL_DEFAULTS = {
    "plan_items": [],
    "commands": [],
    "changed_files": [],
    "verification_entries": [],
    "decisions": [],
    "discoveries": [],
    "disclosures": [],
    "related_quest_ids": [],
    "related_sidequest_ids": [],
    "accepted_context": {
        "current_accepted_quest_id": None,
        "governed_execution_ready": None,
        "active_order_ids": [],
    },
    "run_title": None,
    "run_goal": None,
    "run_summary": None,
}
REQUIRED_TRUTH_FLAG_DEFAULTS = {
    "governed": False,
    "canon_mutated": False,
    "derived_state_changed": False,
    "verification_present": False,
    "disclosure_open": False,
    "uncertainty_present": False,
}
REQUIRED_OUTPUT_DEFAULTS = {
    "written_artifacts": [],
    "formalized_artifacts": [],
    "accepted_quest_id": None,
    "audit_bundle_path": None,
    "errors": [],
}


class EventLogError(RuntimeError):
    """Raised when event envelopes or event log files are invalid."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _normalize_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_json(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_json(item) for item in value]
    return str(value)


def _merge_contract(defaults: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = _normalize_json(defaults)
    for key, value in _normalize_json(payload).items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
            continue
        merged[key] = value
    return merged


def events_root(data_root: Path) -> Path:
    return data_root / ".synapse" / EVENTS_DIRNAME


def ensure_events_dir(data_root: Path) -> Path:
    root = events_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def event_day(timestamp: str | None = None) -> str:
    if timestamp:
        try:
            return dt.datetime.fromisoformat(str(timestamp)).astimezone(DEFAULT_TIMEZONE).date().isoformat()
        except Exception:
            pass
    return _now().date().isoformat()


def event_log_path(data_root: Path, *, timestamp: str | None = None) -> Path:
    return ensure_events_dir(data_root) / f"{event_day(timestamp)}.jsonl"


def semantic_fingerprint(
    *,
    action_name: str,
    summary: str,
    run_id: str | None,
    changed_files: Iterable[str],
    related_quest_ids: Iterable[str],
    related_sidequest_ids: Iterable[str],
    verification_entries: Iterable[str],
    accepted_context: dict[str, Any] | None,
) -> str:
    payload = {
        "action_name": str(action_name).strip(),
        "summary": str(summary or "").strip(),
        "run_id": str(run_id or "").strip() or None,
        "changed_files": sorted(str(item).strip() for item in changed_files if str(item).strip()),
        "related_quest_ids": sorted(str(item).strip() for item in related_quest_ids if str(item).strip()),
        "related_sidequest_ids": sorted(str(item).strip() for item in related_sidequest_ids if str(item).strip()),
        "verification_entries": sorted(str(item).strip() for item in verification_entries if str(item).strip()),
        "accepted_context": _normalize_json(accepted_context or {}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def default_actor() -> dict[str, str]:
    actor_id = (
        os.environ.get("SYNAPSE_ACTOR_ID")
        or os.environ.get("CODEX_ACTOR_ID")
        or os.environ.get("USER")
        or "unknown"
    )
    runtime = os.environ.get("SYNAPSE_RUNTIME_ID") or os.environ.get("CODEX_RUNTIME_ID") or "synapse-cli"
    return {
        "type": "executor",
        "id": actor_id,
        "runtime": runtime,
    }


def build_event(
    *,
    subject: str,
    action_name: str,
    summary: str,
    status: str,
    signals: dict[str, Any],
    truth_flags: dict[str, Any],
    outputs: dict[str, Any],
    session_id: str | None = None,
    run_id: str | None = None,
    actor: dict[str, Any] | None = None,
    notes: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or _now().isoformat()
    normalized_signals = _merge_contract(REQUIRED_SIGNAL_DEFAULTS, signals or {})
    normalized_truth = _merge_contract(REQUIRED_TRUTH_FLAG_DEFAULTS, truth_flags or {})
    normalized_outputs = _merge_contract(REQUIRED_OUTPUT_DEFAULTS, outputs or {})
    related_quest_ids = normalized_signals.get("related_quest_ids") or []
    related_sidequest_ids = normalized_signals.get("related_sidequest_ids") or []
    changed_files = normalized_signals.get("changed_files") or []
    verification_entries = normalized_signals.get("verification_entries") or []
    accepted_context = normalized_signals.get("accepted_context") or {}
    payload = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": f"EVT-{uuid.uuid4()}",
        "timestamp": ts,
        "subject": str(subject).strip(),
        "session_id": str(session_id).strip() if str(session_id or "").strip() else None,
        "actor": _normalize_json(actor or default_actor()),
        "action_name": str(action_name).strip(),
        "status": str(status).strip().lower(),
        "summary": str(summary or "").strip(),
        "signals": normalized_signals,
        "truth_flags": normalized_truth,
        "outputs": normalized_outputs,
        "semantic_fingerprint": semantic_fingerprint(
            action_name=action_name,
            summary=summary,
            run_id=run_id,
            changed_files=changed_files,
            related_quest_ids=related_quest_ids,
            related_sidequest_ids=related_sidequest_ids,
            verification_entries=verification_entries,
            accepted_context=accepted_context if isinstance(accepted_context, dict) else {},
        ),
        "reducer_version": REDUCER_VERSION,
    }
    if str(run_id or "").strip():
        payload["run_id"] = str(run_id).strip()
    if notes:
        payload["notes"] = str(notes).strip()
    return validate_event(payload)


def validate_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise EventLogError("Event payload must be a JSON object.")
    required_string_fields = (
        "event_id",
        "timestamp",
        "subject",
        "action_name",
        "status",
        "summary",
        "semantic_fingerprint",
        "reducer_version",
    )
    for field in required_string_fields:
        value = event.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EventLogError(f"Event field '{field}' must be a non-empty string.")
    if event.get("status") not in VALID_STATUSES:
        raise EventLogError(f"Event field 'status' must be one of {sorted(VALID_STATUSES)}.")
    if not isinstance(event.get("actor"), dict):
        raise EventLogError("Event field 'actor' must be an object.")
    actor = event["actor"]
    for field in ("type", "id"):
        value = actor.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EventLogError(f"Event actor field '{field}' must be a non-empty string.")
    runtime = actor.get("runtime")
    if runtime is not None and not isinstance(runtime, str):
        raise EventLogError("Event actor field 'runtime' must be a string or null.")
    if not isinstance(event.get("signals"), dict):
        raise EventLogError("Event field 'signals' must be an object.")
    for field in REQUIRED_SIGNAL_DEFAULTS:
        if field not in event["signals"]:
            raise EventLogError(f"Event signals field '{field}' is required.")
    if not isinstance(event.get("truth_flags"), dict):
        raise EventLogError("Event field 'truth_flags' must be an object.")
    for field in REQUIRED_TRUTH_FLAG_DEFAULTS:
        if field not in event["truth_flags"]:
            raise EventLogError(f"Event truth_flags field '{field}' is required.")
    if not isinstance(event.get("outputs"), dict):
        raise EventLogError("Event field 'outputs' must be an object.")
    for field in REQUIRED_OUTPUT_DEFAULTS:
        if field not in event["outputs"]:
            raise EventLogError(f"Event outputs field '{field}' is required.")
    return event


def append_event(*, data_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    payload = validate_event(event)
    path = event_log_path(data_root, timestamp=str(payload.get("timestamp") or ""))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return {
        "path": str(path.resolve()),
        "event_id": payload["event_id"],
        "timestamp": payload["timestamp"],
        "semantic_fingerprint": payload["semantic_fingerprint"],
    }


def load_event_records(data_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = events_root(data_root)
    if not root.exists():
        return records
    for path in sorted(root.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise EventLogError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
                validate_event(payload)
                records.append(payload)
    return records


def validate_event_stream(data_root: Path) -> list[str]:
    problems: list[str] = []
    root = events_root(data_root)
    if not root.exists():
        return problems
    for path in sorted(root.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                    validate_event(payload)
                except Exception as exc:
                    problems.append(f"{path}:{line_number}: {exc}")
    return problems

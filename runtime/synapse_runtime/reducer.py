"""Phase 1 reducer facade for event-centered derived-state orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.event_log import REDUCER_VERSION
from synapse_runtime.live_memory import LiveMemoryError, ensure_live_scaffold, reduce_sidecar_from_event, render_rehydrate
from synapse_runtime.rehydration_pack import refresh_rehydration_pack


class ReducerError(RuntimeError):
    """Raised when reducer orchestration fails."""


def reducer_mode(env: dict[str, str] | None = None) -> str:
    value = str((env or os.environ).get("SYNAPSE_REDUCER_MODE") or "").strip().lower()
    return value or "active"


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _stamp_state_metadata(*, subject: str, data_root: Path, event: dict[str, Any]) -> None:
    state_path = data_root / ".synapse" / "STATE.yaml"
    state = _read_yaml(state_path)
    if not isinstance(state, dict):
        state = {
            "schema_version": 1,
            "subject": subject,
        }
    state["subject"] = subject
    state["last_event_id"] = str(event["event_id"])
    state["last_event_at"] = str(event["timestamp"])
    state["last_reduced_event_id"] = str(event["event_id"])
    state["reducer_version"] = REDUCER_VERSION
    _write_yaml(state_path, state)


def reduce_after_event(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    event: dict[str, Any],
    refresh_continuity: bool = True,
) -> dict[str, Any]:
    ensure_live_scaffold(subject, data_root)
    mode = reducer_mode()
    if mode == "legacy":
        return {
            "mode": mode,
            "reducer_version": REDUCER_VERSION,
            "event_id": str(event["event_id"]),
            "sidecar": None,
            "rehydrate": None,
            "continuity": None,
        }

    try:
        sidecar = reduce_sidecar_from_event(subject=subject, data_root=data_root, event=event)
        _stamp_state_metadata(subject=subject, data_root=data_root, event=event)
        rehydrate = render_rehydrate(subject=subject, data_root=data_root)
        continuity = None
        if refresh_continuity:
            continuity = refresh_rehydration_pack(subject=subject, data_root=data_root, engine_root=engine_root)
    except Exception as exc:
        raise ReducerError(str(exc)) from exc

    return {
        "mode": mode,
        "reducer_version": REDUCER_VERSION,
        "event_id": str(event["event_id"]),
        "sidecar": sidecar,
        "rehydrate": rehydrate,
        "continuity": continuity,
    }

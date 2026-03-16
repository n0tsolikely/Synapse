"""Daily ledger and run-ledger helpers for the live sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.sidecar_store import (
    _default_daily_ledger,
    _now,
    _now_iso,
    _read_yaml,
    _write_yaml,
    live_root,
)


def _daily_ledger_path(data_root: Path, ledger_name: str, stamp: str | None = None) -> Path:
    day = stamp or _now().date().isoformat()
    return live_root(data_root) / ledger_name / f"{day}.yaml"


def _append_ledger_entry(path: Path, *, subject: str, entry: dict[str, Any]) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        data = _default_daily_ledger(subject, path.stem)
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    data["subject"] = subject
    data["date"] = path.stem
    data["entries"].append(entry)
    _write_yaml(path, data)
    return data


def _entry_id(prefix: str) -> str:
    return f"{prefix}-{_now().strftime('%Y%m%d-%H%M%S-%f')}"


def _run_ledger_path(live: Path, run_data: dict[str, Any], *, slugify) -> Path:
    existing = str(run_data.get("ledger_path") or "").strip()
    if existing:
        return Path(existing)
    run_id = str(run_data.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("Cannot derive run ledger path without run_id.")
    slug = slugify(str(run_data.get("title") or run_id))
    return live / "RUNS" / f"{run_id}__{slug}.yaml"


def _sync_run_ledger(live: Path, run_data: dict[str, Any], *, slugify) -> str | None:
    run_id = str(run_data.get("run_id") or "").strip()
    if not run_id:
        return None
    ledger_path = _run_ledger_path(live, run_data, slugify=slugify)
    run_data["ledger_path"] = str(ledger_path)
    _write_yaml(ledger_path, run_data)
    return str(ledger_path)


def _read_ledger_entries(path: Path) -> list[dict[str, Any]]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return []
    entries = data.get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _read_ledger_entries_strict(path: Path) -> list[dict[str, Any]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LiveMemoryError(f"Malformed canonical sidecar ledger: {path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise LiveMemoryError(f"Malformed canonical sidecar ledger: {path}")
    return [entry for entry in raw["entries"] if isinstance(entry, dict)]


def _classify_verification_status(entries: Iterable[str]) -> str | None:
    status: str | None = None
    for raw in entries:
        text = str(raw).strip().lower()
        if not text:
            continue
        if any(token in text for token in ("blocked", "unable", "unverified")):
            status = "BLOCKED"
        if any(token in text for token in ("fail", "failed", "error")):
            return "FAIL"
        if any(token in text for token in ("pass", "passed", "ok", "success")) and status is None:
            status = "PASS"
    return status


def _load_recent_daily_entries(data_root: Path, ledger_name: str, limit: int, *, strict: bool = False) -> list[dict[str, Any]]:
    ledger_dir = live_root(data_root) / ledger_name
    paths = sorted(ledger_dir.glob("*.yaml"))
    entries: list[dict[str, Any]] = []
    for path in reversed(paths):
        loader = _read_ledger_entries_strict if strict else _read_ledger_entries
        entries.extend(reversed(loader(path)))
        if len(entries) >= limit:
            break
    return list(reversed(entries[-limit:]))

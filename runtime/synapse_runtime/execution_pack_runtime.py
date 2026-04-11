"""Bounded Execution Pack lifecycle runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.live_memory_common import LiveMemoryError, _normalize_relpaths, _slugify, _unique_strings
from synapse_runtime.rehydration_pack import inspect_execution_pack_state, refresh_rehydration_pack


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
REQUIRED_PACK_FILES = ("PACK.yaml", "INDEX.md", "RUNBOOK.md")
REQUIRED_PACK_FIELDS = (
    "pack_id",
    "pack_key",
    "subject",
    "status",
    "trigger",
    "objective",
    "out_of_scope",
    "warrant_reason",
    "scope_refs",
    "prerequisites",
    "boundaries",
    "verification",
    "archive_condition",
    "created_at",
    "updated_at",
    "material_signature",
)


class ExecutionPackRuntimeError(LiveMemoryError):
    """Raised when Execution Pack lifecycle work cannot proceed safely."""


class ExecutionPackDecision(str, Enum):
    CREATE_ACTIVE_PACK = "create_active_pack"
    REFRESH_ACTIVE_PACK = "refresh_active_pack"
    ARCHIVE_ACTIVE_PACK = "archive_active_pack"
    NOOP = "noop"
    BLOCK = "block"


class ExecutionPackWarrantPosture(str, Enum):
    WARRANTED = "warranted"
    NOT_WARRANTED = "not_warranted"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ExecutionPackEvaluation:
    decision: str
    warrant_posture: str
    reason: str
    pack_key: str | None
    pack_id: str | None
    scope_refs: tuple[str, ...]
    material_signature: str | None
    pointer_refresh_required: bool
    supersedes_active_pack: bool
    archive_targets: tuple[str, ...]
    active_source_path: str | None
    active_pointer_path: str | None


def execution_pack_active_root(data_root: Path) -> Path:
    return data_root / "Docs" / "Execution Packs" / "Active"


def execution_pack_archived_root(data_root: Path) -> Path:
    return data_root / "Docs" / "Execution Packs" / "Archived"


def ensure_execution_pack_runtime_scaffold(data_root: Path) -> None:
    execution_pack_active_root(data_root).mkdir(parents=True, exist_ok=True)
    execution_pack_archived_root(data_root).mkdir(parents=True, exist_ok=True)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _today() -> str:
    return _now().date().isoformat()


def _now_iso() -> str:
    return _now().isoformat()


def _canonical_rel(data_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _pack_key(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).upper()
    text = re.sub(r"_+", "_", text).strip("_")
    return text or None


def _derived_pack_key(*, objective: str, pack_key: str | None) -> str:
    explicit = _pack_key(pack_key)
    if explicit:
        return explicit
    derived = _pack_key(_slugify(objective).replace("-", "_"))
    return derived or "EXECUTION_WINDOW"


def _request_payload(
    *,
    data_root: Path,
    trigger: str,
    objective: str,
    out_of_scope: list[str],
    scope_refs: list[str],
    prerequisites: list[str],
    boundaries: list[str],
    verification: list[str],
    archive_condition: str,
    pack_key: str,
    bounded_window: bool,
    drift_sensitive: bool,
    handoff_sensitive: bool,
    force_warrant: bool,
) -> dict[str, Any]:
    return {
        "trigger": trigger,
        "objective": objective.strip(),
        "out_of_scope": _unique_strings(out_of_scope),
        "scope_refs": _normalize_relpaths(data_root, scope_refs),
        "prerequisites": _unique_strings(prerequisites),
        "boundaries": _unique_strings(boundaries),
        "verification": _unique_strings(verification),
        "archive_condition": archive_condition.strip(),
        "pack_key": pack_key,
        "bounded_window": bool(bounded_window),
        "drift_sensitive": bool(drift_sensitive),
        "handoff_sensitive": bool(handoff_sensitive),
        "force_warrant": bool(force_warrant),
    }


def _material_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _pack_prefix(subject: str, pack_key: str) -> str:
    return f"EXEC_PACK__{subject.upper()}__{pack_key}__"


def _pack_dirname(subject: str, pack_key: str, day: str, revision: int) -> str:
    return f"{_pack_prefix(subject, pack_key)}{day}__v{revision}"


def _next_pack_revision(*, subject: str, pack_key: str, data_root: Path, day: str) -> int:
    prefix = _pack_prefix(subject, pack_key)
    candidates = []
    for root in (execution_pack_active_root(data_root), execution_pack_archived_root(data_root)):
        if not root.exists():
            continue
        for path in root.glob(f"{prefix}{day}__v*"):
            match = re.search(r"__v(\d+)$", path.name)
            if match:
                candidates.append(int(match.group(1)))
    return max(candidates or [0]) + 1


def _load_pack_yaml(source_path: Path) -> dict[str, Any]:
    pack_yaml = source_path / "PACK.yaml"
    if not pack_yaml.exists():
        raise ExecutionPackRuntimeError(f"Execution Pack missing PACK.yaml: {source_path}")
    payload = yaml.safe_load(pack_yaml.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ExecutionPackRuntimeError(f"Execution Pack PACK.yaml is invalid: {pack_yaml}")
    return payload


def validate_execution_pack_source(source_path: Path) -> tuple[bool, str | None]:
    if not source_path.exists():
        return False, "active_source_missing"
    if not source_path.is_dir():
        return False, "runtime_owned_source_must_be_directory"
    missing_files = [name for name in REQUIRED_PACK_FILES if not (source_path / name).exists()]
    if missing_files:
        return False, f"missing_required_files:{','.join(missing_files)}"
    try:
        payload = _load_pack_yaml(source_path)
    except ExecutionPackRuntimeError as exc:
        return False, str(exc)
    missing_fields = [field for field in REQUIRED_PACK_FIELDS if payload.get(field) in (None, "", [])]
    if missing_fields:
        return False, f"missing_required_fields:{','.join(missing_fields)}"
    return True, None


def _render_index(pack_id: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# {pack_id}",
        "",
        f"Objective: {payload['objective']}",
        f"Trigger: {payload['trigger']}",
        "",
        "## Read Order",
        "1. PACK.yaml",
        "2. INDEX.md",
        "3. RUNBOOK.md",
        "",
        "## Scope Refs",
    ]
    scope_refs = payload.get("scope_refs") or []
    if scope_refs:
        lines.extend(f"- {item}" for item in scope_refs)
    else:
        lines.append("- None recorded.")
    lines.extend([
        "",
        "## Archive Condition",
        payload["archive_condition"],
        "",
    ])
    return "\n".join(lines)


def _render_runbook(payload: dict[str, Any]) -> str:
    def section(title: str, items: list[str]) -> list[str]:
        lines = [f"## {title}"]
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None recorded.")
        lines.append("")
        return lines

    lines = [
        "# Runbook",
        "",
        "## Objective",
        payload["objective"],
        "",
    ]
    lines.extend(section("Out Of Scope", payload["out_of_scope"]))
    lines.extend(section("Prerequisites", payload["prerequisites"]))
    lines.extend(section("Execution Boundaries", payload["boundaries"]))
    lines.extend(section("Verification", payload["verification"]))
    lines.extend([
        "## Stop / Archive Condition",
        payload["archive_condition"],
        "",
    ])
    return "\n".join(lines)


def _write_pack_directory(*, source_dir: Path, pack_id: str, subject: str, payload: dict[str, Any], status: str, created_at: str | None = None) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    pack_yaml = {
        "schema_version": 1,
        "pack_id": pack_id,
        "pack_key": payload["pack_key"],
        "subject": subject,
        "status": status,
        "trigger": payload["trigger"],
        "objective": payload["objective"],
        "out_of_scope": list(payload["out_of_scope"]),
        "warrant_reason": "explicit_force_warrant" if payload["force_warrant"] else "bounded_and_sensitive_window",
        "scope_refs": list(payload["scope_refs"]),
        "prerequisites": list(payload["prerequisites"]),
        "boundaries": list(payload["boundaries"]),
        "verification": list(payload["verification"]),
        "archive_condition": payload["archive_condition"],
        "created_at": created_at or _now_iso(),
        "updated_at": _now_iso(),
        "material_signature": _material_signature(payload),
    }
    (source_dir / "PACK.yaml").write_text(yaml.safe_dump(pack_yaml, sort_keys=False), encoding="utf-8")
    (source_dir / "INDEX.md").write_text(_render_index(pack_id, payload), encoding="utf-8")
    (source_dir / "RUNBOOK.md").write_text(_render_runbook(payload), encoding="utf-8")


def _unique_archive_destination(root: Path, name: str) -> Path:
    candidate = root / name
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        alt = root / f"{name}__ARCHIVED__{suffix:02d}"
        if not alt.exists():
            return alt
        suffix += 1


def _archive_source(source_path: Path, archived_root: Path, *, archive_reason: str) -> Path:
    if not source_path.exists():
        raise ExecutionPackRuntimeError(f"Cannot archive missing Execution Pack source: {source_path}")
    archived_root.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir() and (source_path / "PACK.yaml").exists():
        payload = yaml.safe_load((source_path / "PACK.yaml").read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["status"] = "ARCHIVED"
            payload["archive_reason"] = archive_reason
            payload["archived_at"] = _now_iso()
            (source_path / "PACK.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    destination = _unique_archive_destination(archived_root, source_path.name)
    shutil.move(str(source_path), str(destination))
    return destination.resolve()


def _load_existing_source_metadata(source_path: Path) -> dict[str, Any]:
    payload = _load_pack_yaml(source_path)
    payload["material_signature"] = str(payload.get("material_signature") or "").strip()
    payload["pack_key"] = _pack_key(str(payload.get("pack_key") or "")) or None
    return payload


def _current_state(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    return inspect_execution_pack_state(subject=subject, data_root=data_root, engine_root=engine_root)


def evaluate_execution_pack(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    trigger: str,
    objective: str,
    out_of_scope: list[str],
    scope_refs: list[str],
    prerequisites: list[str],
    boundaries: list[str],
    verification: list[str],
    archive_condition: str,
    pack_key: str | None = None,
    bounded_window: bool = False,
    drift_sensitive: bool = False,
    handoff_sensitive: bool = False,
    force_warrant: bool = False,
) -> dict[str, Any]:
    ensure_execution_pack_runtime_scaffold(data_root)
    state = _current_state(subject=subject, data_root=data_root, engine_root=engine_root)
    active_source = Path(str(state.get("active_source_path"))) if state.get("active_source_path") else None
    active_pointer = Path(str(state.get("active_pointer_path"))) if state.get("active_pointer_path") else None

    normalized_objective = str(objective or "").strip()
    derived_key = _derived_pack_key(objective=normalized_objective, pack_key=pack_key)
    payload = _request_payload(
        data_root=data_root,
        trigger=trigger,
        objective=normalized_objective,
        out_of_scope=out_of_scope,
        scope_refs=scope_refs,
        prerequisites=prerequisites,
        boundaries=boundaries,
        verification=verification,
        archive_condition=archive_condition,
        pack_key=derived_key,
        bounded_window=bounded_window,
        drift_sensitive=drift_sensitive,
        handoff_sensitive=handoff_sensitive,
        force_warrant=force_warrant,
    )
    material_signature = _material_signature(payload) if normalized_objective else None

    if active_source is not None:
        valid, reason = validate_execution_pack_source(active_source)
        if not valid:
            return {
                "decision": ExecutionPackDecision.BLOCK.value,
                "warrant_posture": ExecutionPackWarrantPosture.BLOCKED.value,
                "reason": f"invalid_active_source:{reason}",
                "pack_key": derived_key,
                "pack_id": None,
                "scope_refs": payload["scope_refs"],
                "material_signature": material_signature,
                "pointer_refresh_required": False,
                "supersedes_active_pack": False,
                "archive_targets": [],
                "active_source_path": str(active_source.resolve()),
                "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
            }

    if not normalized_objective:
        return {
            "decision": ExecutionPackDecision.BLOCK.value,
            "warrant_posture": ExecutionPackWarrantPosture.BLOCKED.value,
            "reason": "missing_objective",
            "pack_key": derived_key,
            "pack_id": None,
            "scope_refs": payload["scope_refs"],
            "material_signature": None,
            "pointer_refresh_required": False,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": str(active_source.resolve()) if active_source else None,
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }

    warranted = bool(force_warrant or (bounded_window and (drift_sensitive or handoff_sensitive)))
    if not warranted:
        return {
            "decision": ExecutionPackDecision.BLOCK.value,
            "warrant_posture": ExecutionPackWarrantPosture.NOT_WARRANTED.value,
            "reason": "pack_not_warranted",
            "pack_key": derived_key,
            "pack_id": None,
            "scope_refs": payload["scope_refs"],
            "material_signature": material_signature,
            "pointer_refresh_required": False,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": str(active_source.resolve()) if active_source else None,
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }

    missing_fields: list[str] = []
    if not payload["out_of_scope"]:
        missing_fields.append("out_of_scope")
    if not payload["prerequisites"]:
        missing_fields.append("prerequisites")
    if not payload["boundaries"]:
        missing_fields.append("boundaries")
    if not payload["verification"]:
        missing_fields.append("verification")
    if not payload["archive_condition"]:
        missing_fields.append("archive_condition")
    if missing_fields:
        return {
            "decision": ExecutionPackDecision.BLOCK.value,
            "warrant_posture": ExecutionPackWarrantPosture.BLOCKED.value,
            "reason": f"missing_mvep_fields:{','.join(missing_fields)}",
            "pack_key": derived_key,
            "pack_id": None,
            "scope_refs": payload["scope_refs"],
            "material_signature": material_signature,
            "pointer_refresh_required": False,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": str(active_source.resolve()) if active_source else None,
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }

    if active_source is None:
        revision = _next_pack_revision(subject=subject, pack_key=derived_key, data_root=data_root, day=_today())
        pack_id = _pack_dirname(subject, derived_key, _today(), revision)
        return {
            "decision": ExecutionPackDecision.CREATE_ACTIVE_PACK.value,
            "warrant_posture": ExecutionPackWarrantPosture.WARRANTED.value,
            "reason": "no_active_pack_exists",
            "pack_key": derived_key,
            "pack_id": pack_id,
            "scope_refs": payload["scope_refs"],
            "material_signature": material_signature,
            "pointer_refresh_required": True,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": None,
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }

    current_meta = _load_existing_source_metadata(active_source)
    current_signature = str(current_meta.get("material_signature") or state.get("source_signature") or "").strip()
    current_key = _pack_key(str(current_meta.get("pack_key") or ""))
    if current_key != derived_key:
        revision = _next_pack_revision(subject=subject, pack_key=derived_key, data_root=data_root, day=_today())
        pack_id = _pack_dirname(subject, derived_key, _today(), revision)
        return {
            "decision": ExecutionPackDecision.CREATE_ACTIVE_PACK.value,
            "warrant_posture": ExecutionPackWarrantPosture.WARRANTED.value,
            "reason": "active_pack_scope_changed",
            "pack_key": derived_key,
            "pack_id": pack_id,
            "scope_refs": payload["scope_refs"],
            "material_signature": material_signature,
            "pointer_refresh_required": True,
            "supersedes_active_pack": True,
            "archive_targets": [str(active_source.resolve())],
            "active_source_path": str(active_source.resolve()),
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }
    if current_signature == material_signature:
        return {
            "decision": ExecutionPackDecision.NOOP.value,
            "warrant_posture": ExecutionPackWarrantPosture.WARRANTED.value,
            "reason": "active_pack_already_matches_request",
            "pack_key": derived_key,
            "pack_id": active_source.name,
            "scope_refs": payload["scope_refs"],
            "material_signature": material_signature,
            "pointer_refresh_required": False,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": str(active_source.resolve()),
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        }
    return {
        "decision": ExecutionPackDecision.REFRESH_ACTIVE_PACK.value,
        "warrant_posture": ExecutionPackWarrantPosture.WARRANTED.value,
        "reason": "active_pack_material_change_detected",
        "pack_key": derived_key,
        "pack_id": active_source.name,
        "scope_refs": payload["scope_refs"],
        "material_signature": material_signature,
        "pointer_refresh_required": True,
        "supersedes_active_pack": False,
        "archive_targets": [],
        "active_source_path": str(active_source.resolve()),
        "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
    }


def refresh_execution_pack(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    trigger: str,
    objective: str,
    out_of_scope: list[str],
    scope_refs: list[str],
    prerequisites: list[str],
    boundaries: list[str],
    verification: list[str],
    archive_condition: str,
    pack_key: str | None = None,
    bounded_window: bool = False,
    drift_sensitive: bool = False,
    handoff_sensitive: bool = False,
    force_warrant: bool = False,
) -> dict[str, Any]:
    ensure_execution_pack_runtime_scaffold(data_root)
    evaluation = evaluate_execution_pack(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        trigger=trigger,
        objective=objective,
        out_of_scope=out_of_scope,
        scope_refs=scope_refs,
        prerequisites=prerequisites,
        boundaries=boundaries,
        verification=verification,
        archive_condition=archive_condition,
        pack_key=pack_key,
        bounded_window=bounded_window,
        drift_sensitive=drift_sensitive,
        handoff_sensitive=handoff_sensitive,
        force_warrant=force_warrant,
    )
    decision = str(evaluation["decision"])
    if decision in {ExecutionPackDecision.BLOCK.value, ExecutionPackDecision.NOOP.value}:
        return {
            **evaluation,
            "changed": False,
            "archived_source_paths": [],
            "state": _current_state(subject=subject, data_root=data_root, engine_root=engine_root),
        }

    payload = _request_payload(
        data_root=data_root,
        trigger=trigger,
        objective=objective,
        out_of_scope=out_of_scope,
        scope_refs=scope_refs,
        prerequisites=prerequisites,
        boundaries=boundaries,
        verification=verification,
        archive_condition=archive_condition,
        pack_key=str(evaluation["pack_key"]),
        bounded_window=bounded_window,
        drift_sensitive=drift_sensitive,
        handoff_sensitive=handoff_sensitive,
        force_warrant=force_warrant,
    )
    active_root = execution_pack_active_root(data_root)
    archived_root = execution_pack_archived_root(data_root)
    archived_sources: list[str] = []
    state_before = _current_state(subject=subject, data_root=data_root, engine_root=engine_root)
    active_source_before = Path(str(state_before.get("active_source_path"))) if state_before.get("active_source_path") else None

    if decision == ExecutionPackDecision.CREATE_ACTIVE_PACK.value and active_source_before is not None:
        archived_sources.append(str(_archive_source(active_source_before, archived_root, archive_reason="superseded").resolve()))

    if decision == ExecutionPackDecision.CREATE_ACTIVE_PACK.value:
        pack_id = str(evaluation["pack_id"])
        target = active_root / pack_id
        _write_pack_directory(source_dir=target, pack_id=pack_id, subject=subject, payload=payload, status="ACTIVE")
        artifact_path = target.resolve()
    elif decision == ExecutionPackDecision.REFRESH_ACTIVE_PACK.value:
        if active_source_before is None:
            raise ExecutionPackRuntimeError("Cannot refresh an Execution Pack when no active source exists.")
        existing = _load_existing_source_metadata(active_source_before)
        _write_pack_directory(
            source_dir=active_source_before,
            pack_id=active_source_before.name,
            subject=subject,
            payload=payload,
            status="ACTIVE",
            created_at=str(existing.get("created_at") or _now_iso()),
        )
        artifact_path = active_source_before.resolve()
    else:
        raise ExecutionPackRuntimeError(f"Unsupported refresh decision: {decision}")

    continuity = refresh_rehydration_pack(subject=subject, data_root=data_root, engine_root=engine_root)
    return {
        **evaluation,
        "changed": True,
        "artifact_path": str(artifact_path),
        "archived_source_paths": archived_sources,
        "continuity": continuity,
        "state": _current_state(subject=subject, data_root=data_root, engine_root=engine_root),
    }


def archive_execution_pack(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    archive_reason: str = "archive_requested",
) -> dict[str, Any]:
    ensure_execution_pack_runtime_scaffold(data_root)
    state_before = _current_state(subject=subject, data_root=data_root, engine_root=engine_root)
    active_source = Path(str(state_before.get("active_source_path"))) if state_before.get("active_source_path") else None
    active_pointer = Path(str(state_before.get("active_pointer_path"))) if state_before.get("active_pointer_path") else None
    if active_source is None:
        return {
            "decision": ExecutionPackDecision.NOOP.value,
            "warrant_posture": ExecutionPackWarrantPosture.NOT_WARRANTED.value,
            "reason": "no_active_pack_to_archive",
            "pack_key": None,
            "pack_id": None,
            "scope_refs": [],
            "material_signature": None,
            "pointer_refresh_required": False,
            "supersedes_active_pack": False,
            "archive_targets": [],
            "active_source_path": None,
            "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
            "changed": False,
            "archived_source_paths": [],
            "state": state_before,
        }

    archived_path = _archive_source(active_source, execution_pack_archived_root(data_root), archive_reason=archive_reason)
    continuity = refresh_rehydration_pack(subject=subject, data_root=data_root, engine_root=engine_root)
    return {
        "decision": ExecutionPackDecision.ARCHIVE_ACTIVE_PACK.value,
        "warrant_posture": ExecutionPackWarrantPosture.WARRANTED.value,
        "reason": archive_reason,
        "pack_key": None,
        "pack_id": active_source.name,
        "scope_refs": [],
        "material_signature": None,
        "pointer_refresh_required": True,
        "supersedes_active_pack": False,
        "archive_targets": [str(active_source.resolve())],
        "active_source_path": str(active_source.resolve()),
        "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        "changed": True,
        "archived_source_paths": [str(archived_path)],
        "continuity": continuity,
        "state": _current_state(subject=subject, data_root=data_root, engine_root=engine_root),
    }


def execution_pack_status(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    state = _current_state(subject=subject, data_root=data_root, engine_root=engine_root)
    active_source = Path(str(state.get("active_source_path"))) if state.get("active_source_path") else None
    valid, reason = (True, None)
    pack_yaml: dict[str, Any] | None = None
    if active_source is not None:
        valid, reason = validate_execution_pack_source(active_source)
        if valid:
            pack_yaml = _load_pack_yaml(active_source)
    return {
        **state,
        "active_pack_valid": valid,
        "active_pack_invalid_reason": reason,
        "pack_yaml": pack_yaml,
    }

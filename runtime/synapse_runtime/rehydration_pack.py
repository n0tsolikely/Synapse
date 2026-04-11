"""Deterministic continuity and rehydration-pack refresh helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
MATERIAL_SIG_LABEL = "MATERIAL SIGNATURE:"
BOOTSTRAP_TOKEN = "BOOTSTRAP_PROMPT"
CONTINUITY_TOKEN = "CONTINUITY_LOCK"
EXECUTION_PACK_POINTER_PREFIX = "ACTIVE_EXECUTION_PACK"
EXECUTION_PACK_DIRNAME = "Execution Pack"
ACTIVE_EXECUTION_PACK_GLOB = "EXEC_PACK__*"


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _today() -> str:
    return _now().date().isoformat()


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _recent_entries(path: Path, key: str, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    for ledger in sorted(path.glob("*.yaml"), reverse=True):
        data = _read_yaml(ledger)
        if not isinstance(data, dict):
            continue
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            continue
        for item in reversed(raw_entries):
            if isinstance(item, dict):
                entries.append(item)
            if len(entries) >= limit:
                return list(reversed(entries[-limit:]))
    return list(reversed(entries[-limit:]))


def _latest_text_file(path: Path) -> Path | None:
    files = sorted(item for item in path.glob("*.txt") if item.is_file())
    return files[-1] if files else None


def _latest_snapshot(data_root: Path, category: str) -> Path | None:
    return _latest_text_file(data_root / "Snapshots" / category)


def _rel(data_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _open_questions(threads_path: Path) -> list[str]:
    if not threads_path.exists():
        return []
    lines: list[str] = []
    for raw in threads_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in {"- None yet.", "None yet."}:
            continue
        lines.append(line)
    return lines[:8]


def _accepted_quests(data_root: Path) -> list[str]:
    accepted = data_root / "Quest Board" / "Accepted"
    if not accepted.exists():
        return []
    return [path.name for path in sorted(accepted.glob("*.txt"))[:8]]


def _active_orders(data_root: Path) -> list[str]:
    active = data_root / "Guild Orders" / "ACTIVE"
    if not active.exists():
        return []
    return [path.name for path in sorted(active.glob("*")) if path.is_file()][:8]


def _resume_point(
    *,
    active_run: dict[str, Any],
    pending_proposals: list[dict[str, Any]],
    disclosures: list[dict[str, Any]],
    accepted_quests: list[str],
) -> str:
    run_id = str(active_run.get("run_id") or "").strip()
    if run_id:
        items = active_run.get("plan", {}).get("items", [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").upper()
                if status not in {"DONE", "COMPLETED", "SKIPPED", "CANCELED", "ABANDONED"}:
                    return f"Continue {run_id}: {item.get('id')} - {item.get('text')}"
        title = str(active_run.get("title") or run_id)
        return f"Resume active run {run_id}: {title}"

    if disclosures:
        latest = disclosures[-1]
        return f"Resolve disclosure {latest.get('disclosure_id')}: {latest.get('decision_needed')}"

    if pending_proposals:
        latest = pending_proposals[-1]
        return f"Review pending formalization {latest.get('proposal_id')}: {latest.get('title')}"

    if accepted_quests:
        return f"Open Control Sync and choose the next accepted quest: {accepted_quests[0]}"

    return "Open Control Sync and determine the next governed scope."


def _load_subject_state(subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    path = data_root / "SUBJECT_STATE.yaml"
    data = _read_yaml(path)
    if not isinstance(data, dict):
        data = {
            "schema_version": 1,
            "subject": {"name": subject, "key": subject},
            "roots": {"data_root": str(data_root), "engine_root": str(engine_root)},
            "pointers": {},
        }
    data.setdefault("schema_version", 1)
    data.setdefault("subject", {"name": subject, "key": subject})
    data.setdefault("roots", {"data_root": str(data_root), "engine_root": str(engine_root)})
    data.setdefault("pointers", {})
    return data


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path_signature(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(b"F")
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
        return digest.hexdigest()
    if path.is_dir():
        digest.update(b"D")
        digest.update(path.name.encode("utf-8"))
        for child in sorted(path.rglob("*")):
            rel = child.relative_to(path).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"D" if child.is_dir() else b"F")
            if child.is_file():
                digest.update(child.read_bytes())
        return digest.hexdigest()
    digest.update(str(path).encode("utf-8"))
    return digest.hexdigest()


def _extract_material_signature(text: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(MATERIAL_SIG_LABEL)}\s*([0-9a-f]{{64}})\s*$", text)
    return match.group(1) if match else None


def _extract_day_token(name: str) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return match.group(1) if match else None


def _extract_revision(name: str, day: str) -> int:
    match = re.search(rf"{re.escape(day)}__(\d{{2}})\.[^.]+$", name)
    if not match:
        return 1
    return int(match.group(1))


def _artifact_filename(subject: str, token: str, day: str, revision: int) -> str:
    if revision <= 1:
        return f"{subject}_{token}__{day}.txt"
    return f"{subject}_{token}__{day}__{revision:02d}.txt"


def _execution_pointer_filename(day: str, revision: int) -> str:
    if revision <= 1:
        return f"{EXECUTION_PACK_POINTER_PREFIX}__{day}.yaml"
    return f"{EXECUTION_PACK_POINTER_PREFIX}__{day}__{revision:02d}.yaml"


def _rehydration_pointer(subject_state: dict[str, Any], key: str) -> Path | None:
    latest_pack = subject_state.get("pointers", {}).get("latest_rehydration_pack", {})
    if not isinstance(latest_pack, dict):
        return None
    entry = latest_pack.get(key)
    if not isinstance(entry, dict):
        return None
    raw = str(entry.get("path") or "").strip()
    if not raw:
        return None
    return Path(raw)


def _resolve_active_text_artifact(
    *,
    data_root: Path,
    directory: Path,
    token: str,
    pointer_path: Path | None,
) -> Path | None:
    candidates = sorted(path for path in directory.glob(f"*{token}*") if path.is_file())
    if pointer_path is not None:
        resolved = (data_root / pointer_path).resolve()
        if resolved in {item.resolve() for item in candidates}:
            return resolved
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        return None
    raise RuntimeError(f"Ambiguous active {token}: {', '.join(str(item) for item in candidates)}")


def _archive_directory_entries(directory: Path, archive_dir: Path, keep: set[Path]) -> list[str]:
    archived: list[str] = []
    if not directory.exists():
        return archived
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(directory.iterdir()):
        if path.resolve() in keep:
            continue
        target = archive_dir / path.name
        if target.exists():
            stamp = _now().strftime("%Y%m%d-%H%M%S")
            suffix = "".join(path.suffixes)
            stem = path.name[: -len(suffix)] if suffix else path.name
            target = archive_dir / f"{stem}__ARCHIVED_AT__{stamp}{suffix}"
        shutil.move(str(path), str(target))
        archived.append(str(target.resolve()))
    return archived


def _text_artifact_revision(day: str, directory: Path, current_path: Path | None) -> int:
    revisions = []
    if current_path is not None and current_path.exists() and _extract_day_token(current_path.name) == day:
        revisions.append(_extract_revision(current_path.name, day))
    for candidate in directory.glob(f"*{day}*.txt"):
        if candidate.is_file():
            revisions.append(_extract_revision(candidate.name, day))
    return (max(revisions) if revisions else 0) + 1


def _execution_pointer_revision(day: str, directory: Path, current_path: Path | None) -> int:
    revisions = []
    if current_path is not None and current_path.exists() and _extract_day_token(current_path.name) == day:
        revisions.append(_extract_revision(current_path.name, day))
    for candidate in directory.glob(f"*{day}*.yaml"):
        if candidate.is_file():
            revisions.append(_extract_revision(candidate.name, day))
    return (max(revisions) if revisions else 0) + 1


def _render_text_artifact(lines: list[str], signature: str) -> str:
    materialized: list[str] = []
    inserted = False
    for line in lines:
        materialized.append(line)
        if not inserted and line.startswith("Version:"):
            materialized.append(f"{MATERIAL_SIG_LABEL} {signature}")
            inserted = True
    if not inserted:
        materialized.insert(0, f"{MATERIAL_SIG_LABEL} {signature}")
    return "\n".join(materialized).rstrip() + "\n"


def _execution_pack_roots(data_root: Path) -> tuple[Path, Path, Path, Path]:
    active_root = data_root / "Docs" / "Execution Packs" / "Active"
    archived_root = data_root / "Docs" / "Execution Packs" / "Archived"
    mirror_root = data_root / "Latest Rehydration Pack" / EXECUTION_PACK_DIRNAME
    mirror_archive_root = data_root / "Archive" / "Latest Rehydration Pack" / EXECUTION_PACK_DIRNAME
    return active_root, archived_root, mirror_root, mirror_archive_root


def _resolve_active_execution_pack_source(subject_state: dict[str, Any], data_root: Path) -> Path | None:
    active_root, _archived_root, _mirror_root, _mirror_archive_root = _execution_pack_roots(data_root)
    if not active_root.exists():
        return None
    candidates = sorted(path for path in active_root.glob(ACTIVE_EXECUTION_PACK_GLOB) if path.is_file() or path.is_dir())
    latest_pack = subject_state.get("pointers", {}).get("latest_rehydration_pack", {})
    if isinstance(latest_pack, dict):
        execution_pack = latest_pack.get("execution_pack", {})
        if isinstance(execution_pack, dict):
            source_rel = str(execution_pack.get("source_path") or "").strip()
            if source_rel:
                source_path = (data_root / source_rel).resolve()
                if source_path in {item.resolve() for item in candidates}:
                    return source_path
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        return None
    raise RuntimeError(
        "Ambiguous active Execution Pack state; multiple candidates exist without an authoritative pointer."
    )


def _resolve_active_execution_pointer(subject_state: dict[str, Any], data_root: Path, mirror_root: Path) -> Path | None:
    latest_pack = subject_state.get("pointers", {}).get("latest_rehydration_pack", {})
    if isinstance(latest_pack, dict):
        execution_pack = latest_pack.get("execution_pack", {})
        if isinstance(execution_pack, dict):
            pointer_rel = str(execution_pack.get("path") or "").strip()
            if pointer_rel:
                pointer_path = (data_root / pointer_rel).resolve()
                if pointer_path.exists():
                    return pointer_path
    candidates = sorted(path for path in mirror_root.glob(f"{EXECUTION_PACK_POINTER_PREFIX}*.yaml") if path.is_file())
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        return None
    raise RuntimeError(
        "Ambiguous active Execution Pack pointer state; multiple rehydration-pack execution pointers exist."
    )


def _sync_execution_pack_pointer(subject_state: dict[str, Any], data_root: Path) -> dict[str, Any]:
    active_root, archived_root, mirror_root, mirror_archive_root = _execution_pack_roots(data_root)
    active_root.mkdir(parents=True, exist_ok=True)
    archived_root.mkdir(parents=True, exist_ok=True)
    mirror_root.mkdir(parents=True, exist_ok=True)
    mirror_archive_root.mkdir(parents=True, exist_ok=True)

    active_source = _resolve_active_execution_pack_source(subject_state, data_root)
    current_pointer = _resolve_active_execution_pointer(subject_state, data_root, mirror_root)
    archived_paths: list[str] = []

    if active_source is None:
        if current_pointer is not None:
            archived_paths.extend(_archive_directory_entries(mirror_root, mirror_archive_root, keep=set()))
        return {
            "pointer_path": None,
            "source_path": None,
            "source_signature": None,
            "changed": bool(archived_paths),
            "archived_paths": archived_paths,
        }

    source_signature = _path_signature(active_source)
    desired_payload = {
        "schema_version": 1,
        "subject": data_root.name.removesuffix("_Data"),
        "included_at": _now_iso(),
        "source_path": _rel(data_root, active_source),
        "source_signature": source_signature,
        "source_type": "directory" if active_source.is_dir() else "file",
        "status": "ACTIVE",
    }

    pointer_changed = True
    pointer_path = current_pointer
    if current_pointer is not None:
        current_payload = _read_yaml(current_pointer)
        if isinstance(current_payload, dict):
            current_day = _extract_day_token(current_pointer.name)
            if (
                current_day == _today()
                and str(current_payload.get("source_path") or "") == desired_payload["source_path"]
                and str(current_payload.get("source_signature") or "") == source_signature
            ):
                pointer_changed = False

    if pointer_changed:
        revision = _execution_pointer_revision(_today(), mirror_root, current_pointer)
        pointer_path = mirror_root / _execution_pointer_filename(_today(), revision)
        _write_yaml(pointer_path, desired_payload)

    keep = {pointer_path.resolve()} if pointer_path is not None else set()
    archived_paths.extend(_archive_directory_entries(mirror_root, mirror_archive_root, keep=keep))
    return {
        "pointer_path": pointer_path.resolve() if pointer_path is not None else None,
        "source_path": active_source.resolve(),
        "source_signature": source_signature,
        "changed": pointer_changed or bool(archived_paths),
        "archived_paths": archived_paths,
    }


def inspect_execution_pack_state(*, subject: str, data_root: Path, engine_root: Path | None = None) -> dict[str, Any]:
    """Return the current active execution-pack source/pointer state without mutation."""

    resolved_data_root = data_root.resolve()
    resolved_engine_root = (engine_root or resolved_data_root.parent).resolve()
    subject_state = _load_subject_state(subject, resolved_data_root, resolved_engine_root)
    active_root, archived_root, mirror_root, mirror_archive_root = _execution_pack_roots(resolved_data_root)
    active_source = _resolve_active_execution_pack_source(subject_state, resolved_data_root)
    active_pointer = _resolve_active_execution_pointer(subject_state, resolved_data_root, mirror_root)
    return {
        "active_root": str(active_root.resolve()),
        "archived_root": str(archived_root.resolve()),
        "mirror_root": str(mirror_root.resolve()),
        "mirror_archive_root": str(mirror_archive_root.resolve()),
        "active_source_path": str(active_source.resolve()) if active_source else None,
        "active_pointer_path": str(active_pointer.resolve()) if active_pointer else None,
        "source_signature": _path_signature(active_source) if active_source else None,
    }


def _bootstrap_lines(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    state: dict[str, Any],
    control_sync_snapshot: Path | None,
    eod_snapshot: Path | None,
    general_snapshot: Path | None,
    build_manual_path: Path,
    rehydrate_path: Path,
    buff_execution: Path,
    buff_map: Path,
    buff_start: Path,
    continuity_ref: str,
    bootstrap_ref: str,
    resume_point: str,
    execution_pack_pointer_ref: str | None,
    execution_pack_source_ref: str | None,
) -> list[str]:
    lines = [
        "BOOTSTRAP PROMPT",
        "Version: v1.3",
        f"Last Updated: {_today()}",
        "",
        f"SUBJECT: {subject}",
        f"DATA_ROOT: {data_root}",
        f"ENGINE_ROOT: {engine_root}",
        "",
        "AUTHORITY ORDER:",
        "1) Locks and governance law",
        "2) Canonical subject-state artifacts under DATA_ROOT",
        "3) Canonical ambient sidecar under DATA_ROOT/.synapse",
        "4) Conversation as intent only",
        "",
        "CURRENT WORLD STATE:",
        f"- {state.get('world_state') or 'unknown'}",
        "",
        "READ FIRST:",
        f"- {buff_execution}",
        f"- {buff_map}",
        f"- {buff_start}",
        f"- {continuity_ref}",
        f"- {bootstrap_ref}",
    ]
    if execution_pack_pointer_ref is not None:
        lines.append(f"- {execution_pack_pointer_ref}")
    for item in (control_sync_snapshot, eod_snapshot, general_snapshot):
        if item is not None:
            lines.append(f"- {item}")
    lines.append(f"- {rehydrate_path}")
    if build_manual_path.exists():
        lines.append(f"- {build_manual_path}")
    lines.extend(
        [
            "",
            "EXECUTION POSTURE:",
            "- Treat Continuity Lock as authoritative state.",
            "- Treat REHYDRATE.md as the concise operator surface, not the final authority.",
            "- Do not claim PASS/verification without receipts.",
            "- Trigger Disclosure Gate instead of guessing through ambiguity.",
        ]
    )
    if execution_pack_source_ref is not None:
        lines.extend(
            [
                f"- Active Execution Pack source: {execution_pack_source_ref}",
                "- If the Execution Pack exists, obey it before improvising in drift-sensitive areas.",
            ]
        )
    else:
        lines.append("- No active Execution Pack is currently binding.")
    lines.extend(["", "FIRST ACTION:", f"- {resume_point}", ""])
    return lines


def _continuity_lines(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    state: dict[str, Any],
    decisions: list[dict[str, Any]],
    disclosures: list[dict[str, Any]],
    pending_proposals: list[dict[str, Any]],
    open_questions: list[str],
    active_run: dict[str, Any],
    accepted_quests: list[str],
    active_orders: list[str],
    buff_execution: Path,
    buff_map: Path,
    buff_start: Path,
    continuity_ref: str,
    bootstrap_ref: str,
    control_sync_snapshot: Path | None,
    eod_snapshot: Path | None,
    general_snapshot: Path | None,
    rehydrate_path: Path,
    build_manual_path: Path,
    resume_point: str,
    execution_pack_pointer_ref: str | None,
    execution_pack_source_ref: str | None,
) -> list[str]:
    lines = [
        "CONTINUITY LOCK",
        "Version: v1.3",
        f"Last Updated: {_today()}",
        "",
        f"SUBJECT: {subject}",
        f"DATE: {_today()}",
        f"WORLD STATE: {(state.get('world_state') or 'unknown').upper()}",
        f"CURRENT PHASE: {state.get('active_phase') or 'idle'}",
        "",
        "BINDING DECISIONS (LAW):",
        f"- ENGINE_ROOT is fixed to: {engine_root}",
        f"- DATA_ROOT is fixed to: {data_root}",
        "- Canonical continuity artifacts live under DATA_ROOT.",
        "- Canonical ambient sidecar state lives under DATA_ROOT/.synapse.",
        "- External session locks are convenience cursors only.",
    ]
    if execution_pack_source_ref is not None:
        lines.append(f"- Execution Pack is binding at: {execution_pack_source_ref}")
    if decisions:
        for entry in decisions[-5:]:
            lines.append(f"- {entry.get('decision_id')}: {entry.get('title')} -> {entry.get('summary')}")
    else:
        lines.append("- No additional binding decisions recorded yet.")

    lines.extend(["", "DEFERRED / REJECTED / UNKNOWN:"])
    if disclosures:
        for entry in disclosures[-5:]:
            labels = ", ".join(entry.get("status_labels") or []) or "UNKNOWN"
            lines.append(f"- UNKNOWN [{labels}]: {entry.get('trigger')} -> {entry.get('decision_needed')}")
    if open_questions:
        for question in open_questions:
            lines.append(f"- OPEN QUESTION: {question}")
    blocked = [item for item in pending_proposals if str(item.get("state") or "") in {"blocked", "escalated"}]
    for item in blocked[-5:]:
        lines.append(f"- DEFERRED: {item.get('proposal_id')} ({item.get('kind')}) -> {item.get('title')}")
    if len(lines) > 0 and lines[-1] == "DEFERRED / REJECTED / UNKNOWN:":
        lines.append("- NONE recorded.")

    lines.extend(["", "ACTIVE SCOPE / COMMITMENTS:"])
    run_id = str(active_run.get("run_id") or "").strip()
    if run_id:
        lines.append(f"- ACTIVE RUN: {run_id} - {active_run.get('title')}")
    else:
        lines.append("- ACTIVE RUN: NONE")
    if accepted_quests:
        lines.extend(f"- ACTIVE QUEST: {item}" for item in accepted_quests)
    else:
        lines.append("- ACTIVE QUESTS: NONE")
    if active_orders:
        lines.extend(f"- ACTIVE ORDER: {item}" for item in active_orders)
    else:
        lines.append("- ACTIVE ORDERS: NONE")
    if execution_pack_pointer_ref is not None and execution_pack_source_ref is not None:
        lines.append(f"- ACTIVE EXECUTION PACK POINTER: {execution_pack_pointer_ref}")
        lines.append(f"- ACTIVE EXECUTION PACK SOURCE: {execution_pack_source_ref}")
    else:
        lines.append("- ACTIVE EXECUTION PACK: NONE")

    lines.extend(["", "REQUIRED READ FIRST:"])
    for item in (buff_execution, buff_map, buff_start, continuity_ref, bootstrap_ref):
        lines.append(f"- {item}")
    if execution_pack_pointer_ref is not None:
        lines.append(f"- {execution_pack_pointer_ref}")
    for item in (control_sync_snapshot, eod_snapshot, general_snapshot):
        if item is not None:
            lines.append(f"- {item}")
    lines.append(f"- {rehydrate_path}")
    if build_manual_path.exists():
        lines.append(f"- {build_manual_path}")

    lines.extend(["", "RESUME POINT:", f"- {resume_point}", ""])
    return lines


def refresh_rehydration_pack(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    if not data_root.exists() or not data_root.is_dir():
        raise RuntimeError(f"DATA_ROOT does not exist or is not a directory: {data_root}")
    if not engine_root.exists() or not engine_root.is_dir():
        raise RuntimeError(f"ENGINE_ROOT does not exist or is not a directory: {engine_root}")

    live = data_root / ".synapse"
    rehydration_dir = data_root / "Latest Rehydration Pack"
    archive_dir = data_root / "Archive" / "Latest Rehydration Pack"
    rehydration_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    state = _read_yaml(live / "STATE.yaml")
    active_run = _read_yaml(live / "ACTIVE_RUN.yaml")
    state = state if isinstance(state, dict) else {}
    active_run = active_run if isinstance(active_run, dict) else {}

    decisions = _recent_entries(live / "DECISIONS", "decision_id", 5)
    disclosures = _recent_entries(live / "DISCLOSURES", "disclosure_id", 5)
    proposals_root = live / "PROPOSALS"
    pending_proposals: list[dict[str, Any]] = []
    if proposals_root.exists():
        for proposal_path in sorted(proposals_root.rglob("*.yaml")):
            payload = _read_yaml(proposal_path)
            if not isinstance(payload, dict):
                continue
            if str(payload.get("state") or "") in {"proposed", "ready", "blocked", "escalated"}:
                pending_proposals.append(payload)
    pending_proposals = pending_proposals[-8:]

    control_sync_snapshot = _latest_snapshot(data_root, "Control Sync")
    eod_snapshot = _latest_snapshot(data_root, "End of Day")
    general_snapshot = _latest_snapshot(data_root, "General")
    rehydrate_path = live / "REHYDRATE.md"
    build_manual_path = data_root / "Build_Manual" / "BUILD_MANUAL.md"
    threads_path = live / "THREADS" / "open_questions.md"
    accepted_quests = _accepted_quests(data_root)
    active_orders = _active_orders(data_root)
    open_questions = _open_questions(threads_path)

    buff_prefix = subject.upper()
    buff_execution = data_root / "Buffs" / f"{buff_prefix}_EXECUTION_PROTOCOL.txt"
    buff_map = data_root / "Buffs" / f"{buff_prefix}_DATA_DIRECTORY_MAP.txt"
    buff_start = data_root / "Buffs" / f"{buff_prefix}_SESSION_START_CHECK.txt"

    subject_state = _load_subject_state(subject, data_root, engine_root)
    current_bootstrap = _resolve_active_text_artifact(
        data_root=data_root,
        directory=rehydration_dir,
        token=BOOTSTRAP_TOKEN,
        pointer_path=_rehydration_pointer(subject_state, "bootstrap_prompt"),
    )
    current_continuity = _resolve_active_text_artifact(
        data_root=data_root,
        directory=rehydration_dir,
        token=CONTINUITY_TOKEN,
        pointer_path=_rehydration_pointer(subject_state, "continuity_lock"),
    )

    execution_pack = _sync_execution_pack_pointer(subject_state, data_root)
    execution_pack_pointer = execution_pack.get("pointer_path")
    execution_pack_source = execution_pack.get("source_path")
    execution_pack_pointer_ref = _rel(data_root, execution_pack_pointer) if execution_pack_pointer else None
    execution_pack_source_ref = _rel(data_root, execution_pack_source) if execution_pack_source else None

    resume_point = _resume_point(
        active_run=active_run,
        pending_proposals=pending_proposals,
        disclosures=disclosures,
        accepted_quests=accepted_quests,
    )

    continuity_placeholder = "__ACTIVE_CONTINUITY_LOCK__"
    bootstrap_placeholder = "__ACTIVE_BOOTSTRAP_PROMPT__"
    bootstrap_template = _bootstrap_lines(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        state=state,
        control_sync_snapshot=control_sync_snapshot,
        eod_snapshot=eod_snapshot,
        general_snapshot=general_snapshot,
        build_manual_path=build_manual_path,
        rehydrate_path=rehydrate_path,
        buff_execution=buff_execution,
        buff_map=buff_map,
        buff_start=buff_start,
        continuity_ref=continuity_placeholder,
        bootstrap_ref=bootstrap_placeholder,
        resume_point=resume_point,
        execution_pack_pointer_ref=execution_pack_pointer_ref,
        execution_pack_source_ref=execution_pack_source_ref,
    )
    continuity_template = _continuity_lines(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        state=state,
        decisions=decisions,
        disclosures=disclosures,
        pending_proposals=pending_proposals,
        open_questions=open_questions,
        active_run=active_run,
        accepted_quests=accepted_quests,
        active_orders=active_orders,
        buff_execution=buff_execution,
        buff_map=buff_map,
        buff_start=buff_start,
        continuity_ref=continuity_placeholder,
        bootstrap_ref=bootstrap_placeholder,
        control_sync_snapshot=control_sync_snapshot,
        eod_snapshot=eod_snapshot,
        general_snapshot=general_snapshot,
        rehydrate_path=rehydrate_path,
        build_manual_path=build_manual_path,
        resume_point=resume_point,
        execution_pack_pointer_ref=execution_pack_pointer_ref,
        execution_pack_source_ref=execution_pack_source_ref,
    )

    bootstrap_signature = _sha256_text("\n".join(bootstrap_template))
    continuity_signature = _sha256_text("\n".join(continuity_template))
    today = _today()
    same_day = bool(
        current_bootstrap is not None
        and current_continuity is not None
        and _extract_day_token(current_bootstrap.name) == today
        and _extract_day_token(current_continuity.name) == today
    )
    current_bootstrap_signature = _extract_material_signature(_read_text(current_bootstrap)) if current_bootstrap else None
    current_continuity_signature = _extract_material_signature(_read_text(current_continuity)) if current_continuity else None
    day_rollover = _extract_day_token(current_bootstrap.name if current_bootstrap else "") != today
    day_rollover = day_rollover or _extract_day_token(current_continuity.name if current_continuity else "") != today
    lifecycle_changed = bool(execution_pack.get("changed")) or day_rollover
    material_change = (
        current_bootstrap is None
        or current_continuity is None
        or current_bootstrap_signature != bootstrap_signature
        or current_continuity_signature != continuity_signature
        or lifecycle_changed
    )

    if not material_change:
        bootstrap_path = current_bootstrap
        continuity_path = current_continuity
        if bootstrap_path is None or continuity_path is None:
            raise RuntimeError("Continuity lifecycle state is incomplete; active pack members are missing.")
        archived_paths = _archive_directory_entries(
            rehydration_dir,
            archive_dir,
            keep={bootstrap_path.resolve(), continuity_path.resolve(), (rehydration_dir / EXECUTION_PACK_DIRNAME).resolve()},
        )
        bootstrap_changed = False
        continuity_changed = False
    else:
        revision = _text_artifact_revision(today, rehydration_dir, current_bootstrap)
        bootstrap_path = rehydration_dir / _artifact_filename(subject, BOOTSTRAP_TOKEN, today, revision)
        continuity_path = rehydration_dir / _artifact_filename(subject, CONTINUITY_TOKEN, today, revision)
        bootstrap_ref = str(bootstrap_path.resolve())
        continuity_ref = str(continuity_path.resolve())
        bootstrap_text = _render_text_artifact(
            [line.replace(continuity_placeholder, continuity_ref).replace(bootstrap_placeholder, bootstrap_ref) for line in bootstrap_template],
            bootstrap_signature,
        )
        continuity_text = _render_text_artifact(
            [line.replace(continuity_placeholder, continuity_ref).replace(bootstrap_placeholder, bootstrap_ref) for line in continuity_template],
            continuity_signature,
        )
        bootstrap_path.write_text(bootstrap_text, encoding="utf-8")
        continuity_path.write_text(continuity_text, encoding="utf-8")
        archived_paths = _archive_directory_entries(
            rehydration_dir,
            archive_dir,
            keep={bootstrap_path.resolve(), continuity_path.resolve(), (rehydration_dir / EXECUTION_PACK_DIRNAME).resolve()},
        )
        bootstrap_changed = True
        continuity_changed = True

    subject_state = _load_subject_state(subject, data_root, engine_root)
    pointers = subject_state.setdefault("pointers", {})
    latest_pack = {
        "dir": "Latest Rehydration Pack",
        "bootstrap_prompt": {
            "path": _rel(data_root, bootstrap_path),
            "filename_contains_any": [BOOTSTRAP_TOKEN],
            "pick": "single_required",
            "material_signature": bootstrap_signature,
        },
        "continuity_lock": {
            "path": _rel(data_root, continuity_path),
            "filename_contains_any": [CONTINUITY_TOKEN],
            "pick": "single_required",
            "material_signature": continuity_signature,
        },
    }
    if execution_pack_pointer is not None and execution_pack_source is not None:
        latest_pack["execution_pack"] = {
            "dir": EXECUTION_PACK_DIRNAME,
            "path": execution_pack_pointer_ref,
            "source_path": execution_pack_source_ref,
            "source_signature": execution_pack.get("source_signature"),
        }
    pointers["latest_rehydration_pack"] = latest_pack
    pointers["latest_snapshots"] = {
        "control_sync": _rel(data_root, control_sync_snapshot) or "NONE",
        "end_of_day": _rel(data_root, eod_snapshot) or "NONE",
        "general": _rel(data_root, general_snapshot) or "NONE",
    }
    pointers["active_rehydrate"] = {"path": _rel(data_root, rehydrate_path) or ".synapse/REHYDRATE.md"}
    if build_manual_path.exists():
        pointers["build_manual"] = {"path": _rel(data_root, build_manual_path)}
    subject_state["updated_at"] = _now_iso()
    _write_yaml(data_root / "SUBJECT_STATE.yaml", subject_state)

    return {
        "bootstrap_prompt_path": str(bootstrap_path.resolve()),
        "continuity_lock_path": str(continuity_path.resolve()),
        "bootstrap_changed": bootstrap_changed,
        "continuity_changed": continuity_changed,
        "archived_paths": archived_paths,
        "resume_point": resume_point,
        "subject_state_path": str((data_root / "SUBJECT_STATE.yaml").resolve()),
        "execution_pack_pointer_path": str(execution_pack_pointer.resolve()) if execution_pack_pointer else None,
        "execution_pack_source_path": str(execution_pack_source.resolve()) if execution_pack_source else None,
        "execution_pack_changed": bool(execution_pack.get("changed")),
        "execution_pack_archived_paths": execution_pack.get("archived_paths") or [],
    }

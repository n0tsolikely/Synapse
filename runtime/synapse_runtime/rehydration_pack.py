"""Deterministic continuity and rehydration-pack refresh helpers."""

from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


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


def _archive_superseded(active_dir: Path, archive_dir: Path, keep: set[Path]) -> list[str]:
    archived: list[str] = []
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(active_dir.iterdir()):
        if not path.is_file():
            continue
        if "BOOTSTRAP_PROMPT" not in path.name and "CONTINUITY_LOCK" not in path.name:
            continue
        if path.resolve() in keep:
            continue
        target = archive_dir / path.name
        if target.exists():
            stamp = _now().strftime("%Y%m%d-%H%M%S")
            target = archive_dir / f"{path.stem}__ARCHIVED_AT__{stamp}{path.suffix}"
        shutil.move(str(path), str(target))
        archived.append(str(target.resolve()))
    return archived


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

    today = _today()
    state = _read_yaml(live / "STATE.yaml")
    manifold = _read_yaml(live / "MANIFOLD.yaml")
    active_run = _read_yaml(live / "ACTIVE_RUN.yaml")
    state = state if isinstance(state, dict) else {}
    manifold = manifold if isinstance(manifold, dict) else {}
    active_run = active_run if isinstance(active_run, dict) else {}

    decisions = _recent_entries(live / "DECISIONS", "decision_id", 5)
    discoveries = _recent_entries(live / "DISCOVERIES", "discovery_id", 5)
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

    resume_point = _resume_point(
        active_run=active_run,
        pending_proposals=pending_proposals,
        disclosures=disclosures,
        accepted_quests=accepted_quests,
    )

    bootstrap_path = rehydration_dir / f"{subject}_BOOTSTRAP_PROMPT__{today}.txt"
    continuity_path = rehydration_dir / f"{subject}_CONTINUITY_LOCK__{today}.txt"

    bootstrap_lines = [
        "BOOTSTRAP PROMPT",
        "Version: v1.2",
        f"Last Updated: {today}",
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
        f"- {continuity_path}",
        f"- {bootstrap_path}",
    ]
    for item in (control_sync_snapshot, eod_snapshot, general_snapshot):
        if item is not None:
            bootstrap_lines.append(f"- {item}")
    bootstrap_lines.append(f"- {rehydrate_path}")
    if build_manual_path.exists():
        bootstrap_lines.append(f"- {build_manual_path}")
    bootstrap_lines.extend(
        [
            "",
            "EXECUTION POSTURE:",
            "- Treat Continuity Lock as authoritative state.",
            "- Treat REHYDRATE.md as the concise operator surface, not the final authority.",
            "- Do not claim PASS/verification without receipts.",
            "- Trigger Disclosure Gate instead of guessing through ambiguity.",
            "",
            "FIRST ACTION:",
            f"- {resume_point}",
            "",
        ]
    )
    bootstrap_path.write_text("\n".join(bootstrap_lines), encoding="utf-8")

    continuity_lines = [
        "CONTINUITY LOCK",
        "Version: v1.2",
        f"Last Updated: {today}",
        "",
        f"SUBJECT: {subject}",
        f"DATE: {today}",
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
    if decisions:
        for entry in decisions[-5:]:
            continuity_lines.append(f"- {entry.get('decision_id')}: {entry.get('title')} -> {entry.get('summary')}")
    else:
        continuity_lines.append("- No additional binding decisions recorded yet.")

    continuity_lines.extend(["", "DEFERRED / REJECTED / UNKNOWN:"])
    if disclosures:
        for entry in disclosures[-5:]:
            labels = ", ".join(entry.get("status_labels") or []) or "UNKNOWN"
            continuity_lines.append(f"- UNKNOWN [{labels}]: {entry.get('trigger')} -> {entry.get('decision_needed')}")
    if open_questions:
        for question in open_questions:
            continuity_lines.append(f"- OPEN QUESTION: {question}")
    blocked = [item for item in pending_proposals if str(item.get("state") or "") in {"blocked", "escalated"}]
    for item in blocked[-5:]:
        continuity_lines.append(f"- DEFERRED: {item.get('proposal_id')} ({item.get('kind')}) -> {item.get('title')}")
    if len(continuity_lines) > 0 and continuity_lines[-1] == "DEFERRED / REJECTED / UNKNOWN:":
        continuity_lines.append("- NONE recorded.")

    continuity_lines.extend(["", "ACTIVE SCOPE / COMMITMENTS:"])
    run_id = str(active_run.get("run_id") or "").strip()
    if run_id:
        continuity_lines.append(f"- ACTIVE RUN: {run_id} - {active_run.get('title')}")
    else:
        continuity_lines.append("- ACTIVE RUN: NONE")
    if accepted_quests:
        continuity_lines.extend(f"- ACTIVE QUEST: {item}" for item in accepted_quests)
    else:
        continuity_lines.append("- ACTIVE QUESTS: NONE")
    if active_orders:
        continuity_lines.extend(f"- ACTIVE ORDER: {item}" for item in active_orders)
    else:
        continuity_lines.append("- ACTIVE ORDERS: NONE")

    continuity_lines.extend(["", "REQUIRED READ FIRST:"])
    for item in (buff_execution, buff_map, buff_start, continuity_path, bootstrap_path):
        continuity_lines.append(f"- {item}")
    for item in (control_sync_snapshot, eod_snapshot, general_snapshot):
        if item is not None:
            continuity_lines.append(f"- {item}")
    continuity_lines.append(f"- {rehydrate_path}")
    if build_manual_path.exists():
        continuity_lines.append(f"- {build_manual_path}")

    continuity_lines.extend(["", "RESUME POINT:", f"- {resume_point}", ""])
    continuity_path.write_text("\n".join(continuity_lines), encoding="utf-8")

    archived = _archive_superseded(rehydration_dir, archive_dir, {bootstrap_path.resolve(), continuity_path.resolve()})

    subject_state = _load_subject_state(subject, data_root, engine_root)
    pointers = subject_state.setdefault("pointers", {})
    pointers["latest_rehydration_pack"] = {
        "dir": "Latest Rehydration Pack",
        "bootstrap_prompt": {
            "path": _rel(data_root, bootstrap_path),
            "filename_contains_any": ["BOOTSTRAP_PROMPT"],
            "pick": "single_required",
        },
        "continuity_lock": {
            "path": _rel(data_root, continuity_path),
            "filename_contains_any": ["CONTINUITY_LOCK"],
            "pick": "single_required",
        },
    }
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
        "archived_paths": archived,
        "resume_point": resume_point,
        "subject_state_path": str((data_root / "SUBJECT_STATE.yaml").resolve()),
    }

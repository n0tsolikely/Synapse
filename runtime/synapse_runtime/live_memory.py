"""Live subject-memory sidecar helpers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

LIVE_DIRNAME = ".synapse"
DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


class LiveMemoryError(RuntimeError):
    """Raised when live-memory operations fail."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "run"


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def live_root(data_root: Path) -> Path:
    return data_root / LIVE_DIRNAME


def _default_state(subject: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "status": "idle",
        "current_capabilities": [],
        "active_constraints": [],
        "current_priorities": [],
        "recent_changes": [],
        "open_threads": [],
        "active_run_id": None,
        "last_run_id": None,
        "last_decision_id": None,
        "last_rehydrate_at": None,
    }


def _default_active_run(subject: str) -> dict[str, Any]:
    return {
        "active": False,
        "run_id": None,
        "subject": subject,
        "title": None,
        "goal": None,
        "started_at": None,
        "updated_at": _now_iso(),
        "status": "idle",
        "plan": {"items": []},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "result_summary": None,
    }


def ensure_live_scaffold(subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    decisions_dir = live / "DECISIONS"
    runs_dir = live / "RUNS"
    threads_dir = live / "THREADS"

    decisions_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    threads_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    existing: list[str] = []

    vision_path = live / "VISION.md"
    vision_template = """# Vision (Live)

This is the concise, living identity for the subject.
Keep it short, truthful, and current.

## Project
- Name:
- One-line summary:

## Purpose
- Why this exists:

## Core experience / feel
- What it should feel like to use or operate:

## What exists now
- Known capabilities:

## What does not exist yet
- Explicit gaps:

## Non-negotiables
- Principles that must not be violated:

## Recent important shifts
- Changes in direction or scope:
"""
    if _write_if_missing(vision_path, vision_template):
        created.append(str(vision_path))
    else:
        existing.append(str(vision_path))

    state_path = live / "STATE.yaml"
    if not state_path.exists():
        _write_yaml(state_path, _default_state(subject))
        created.append(str(state_path))
    else:
        existing.append(str(state_path))

    rehydrate_path = live / "REHYDRATE.md"
    rehydrate_template = """# Rehydrate

Run `python3 runtime/synapse.py render-rehydrate` to refresh this file.
"""
    if _write_if_missing(rehydrate_path, rehydrate_template):
        created.append(str(rehydrate_path))
    else:
        existing.append(str(rehydrate_path))

    active_run_path = live / "ACTIVE_RUN.yaml"
    if not active_run_path.exists():
        _write_yaml(active_run_path, _default_active_run(subject))
        created.append(str(active_run_path))
    else:
        existing.append(str(active_run_path))

    open_questions_path = threads_dir / "open_questions.md"
    open_questions_template = """# Open Questions

## Blocking
- None yet.

## Nonblocking
- None yet.
"""
    if _write_if_missing(open_questions_path, open_questions_template):
        created.append(str(open_questions_path))
    else:
        existing.append(str(open_questions_path))

    return {
        "live_root": str(live),
        "created": created,
        "existing": existing,
    }


def _append_recent_change(state: dict[str, Any], note: str) -> None:
    entries = state.get("recent_changes")
    if not isinstance(entries, list):
        entries = []
    entries.append(f"{_now_iso()} - {note}")
    state["recent_changes"] = entries[-10:]


def _load_state(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_state(subject)
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    defaults = _default_state(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def _load_active_run(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_active_run(subject)
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    if "plan" not in data or not isinstance(data["plan"], dict):
        data["plan"] = {"items": []}
    if "items" not in data["plan"] or not isinstance(data["plan"]["items"], list):
        data["plan"]["items"] = []
    return data


def _next_item_id(items: list[dict[str, Any]]) -> str:
    ids = [item.get("id", "") for item in items if isinstance(item, dict)]
    numbers = []
    for item_id in ids:
        match = re.search(r"(\d+)$", str(item_id))
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers or [0]) + 1
    return f"ITEM-{next_num:03d}"


def _normalize_items(items: Iterable[str], existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    existing_items = existing or []
    results: list[dict[str, Any]] = []
    for text in items:
        item_text = str(text).strip()
        if not item_text:
            continue
        item_id = _next_item_id(existing_items + results)
        results.append({"id": item_id, "text": item_text, "status": "TODO"})
    return results


def _parse_status_updates(entries: Iterable[str]) -> list[tuple[str, str]]:
    updates: list[tuple[str, str]] = []
    for entry in entries:
        raw = str(entry).strip()
        if not raw:
            continue
        if ":" in raw:
            key, status = raw.split(":", 1)
        elif "=" in raw:
            key, status = raw.split("=", 1)
        else:
            raise LiveMemoryError(f"Invalid status format '{raw}'. Use ITEM-###:STATUS")
        updates.append((key.strip(), status.strip().upper()))
    return updates


def _is_terminal_status(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().upper() in {"DONE", "COMPLETED", "SKIPPED", "CANCELED", "ABANDONED"}


def _extract_run_id(filename: str) -> str:
    return filename.split("__", 1)[0]


def _extract_decision_id(filename: str) -> str:
    return filename.split(".", 1)[0]


def run_start(
    *,
    subject: str,
    data_root: Path,
    title: str,
    goal: str | None,
    items: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    scaffold = ensure_live_scaffold(subject, data_root)

    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"

    state = _load_state(state_path, subject)
    existing_run = _load_active_run(run_path, subject)

    run_id = f"RUN-{_now().strftime('%Y%m%d-%H%M%S')}"
    plan_items = _normalize_items(items, existing_run.get("plan", {}).get("items", []))

    run_data = {
        "active": True,
        "run_id": run_id,
        "subject": subject,
        "title": title,
        "goal": goal,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "active",
        "plan": {"items": plan_items},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "result_summary": None,
    }

    _write_yaml(run_path, run_data)

    state["active_run_id"] = run_id
    state["last_run_id"] = run_id
    state["status"] = "active"
    _append_recent_change(state, f"Run started: {title}")
    _write_yaml(state_path, state)

    return {
        "run_path": str(run_path),
        "run_id": run_id,
        "title": title,
        "goal": goal,
        "items": plan_items,
        "scaffold": scaffold,
    }


def run_update(
    *,
    subject: str,
    data_root: Path,
    add_items: list[str],
    status_updates: list[str],
    commands: list[str],
    files_touched: list[str],
    notes: list[str],
    verification: list[str],
    related_sidequests: list[str],
    status: str | None,
    summary: str | None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"

    run_data = _load_active_run(run_path, subject)
    if not run_data.get("run_id"):
        raise LiveMemoryError("No ACTIVE_RUN found. Run `python3 runtime/synapse.py run-start` first.")

    plan_items = run_data.get("plan", {}).get("items", [])
    if not isinstance(plan_items, list):
        plan_items = []

    new_items = _normalize_items(add_items, plan_items)
    plan_items.extend(new_items)

    updates = _parse_status_updates(status_updates)
    for item_id, status_value in updates:
        matched = False
        for item in plan_items:
            if str(item.get("id")) == item_id:
                item["status"] = status_value
                matched = True
        if not matched:
            raise LiveMemoryError(f"No plan item with id '{item_id}'.")

    run_data["plan"] = {"items": plan_items}

    if commands:
        run_data.setdefault("commands", [])
        run_data["commands"].extend(commands)
    if files_touched:
        run_data.setdefault("files_touched", [])
        run_data["files_touched"].extend(files_touched)
    if notes:
        run_data.setdefault("notes", [])
        run_data["notes"].extend(notes)
    if verification:
        run_data.setdefault("verification", [])
        run_data["verification"].extend(verification)
    if related_sidequests:
        run_data.setdefault("related_sidequests", [])
        run_data["related_sidequests"].extend(related_sidequests)
    if status:
        run_data["status"] = status
    if summary:
        run_data["result_summary"] = summary

    run_data["updated_at"] = _now_iso()

    _write_yaml(run_path, run_data)

    state = _load_state(state_path, subject)
    state["active_run_id"] = run_data.get("run_id")
    state["status"] = "active"
    change_note = "Run updated"
    if summary:
        change_note = f"Run updated: {summary}"
    _append_recent_change(state, change_note)
    _write_yaml(state_path, state)

    return {
        "run_path": str(run_path),
        "run_id": run_data.get("run_id"),
        "added_items": new_items,
        "status_updates": updates,
    }


def run_finalize(
    *,
    subject: str,
    data_root: Path,
    status: str,
    summary: str | None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"

    run_data = _load_active_run(run_path, subject)
    run_id = run_data.get("run_id")
    if not run_id:
        raise LiveMemoryError("No ACTIVE_RUN found to finalize.")

    if status.strip().lower() == "completed":
        plan_items = run_data.get("plan", {}).get("items", [])
        open_items = [
            item
            for item in plan_items
            if not _is_terminal_status(str(item.get("status") or ""))
        ]
        if open_items:
            details = ", ".join(f"{item.get('id')}={item.get('status')}" for item in open_items)
            raise LiveMemoryError(f"Cannot finalize as completed with open plan items: {details}")

    run_data["active"] = False
    run_data["status"] = status
    run_data["result_summary"] = summary or run_data.get("result_summary")
    run_data["updated_at"] = _now_iso()
    run_data["finalized_at"] = _now_iso()

    runs_dir = live / "RUNS"
    runs_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(run_data.get("title") or run_id)
    archive_name = f"{run_id}__{slug}.yaml"
    archive_path = runs_dir / archive_name
    if archive_path.exists():
        raise LiveMemoryError(f"Archived run already exists: {archive_path}")

    _write_yaml(archive_path, run_data)

    _write_yaml(run_path, _default_active_run(subject))

    state = _load_state(state_path, subject)
    state["active_run_id"] = None
    state["last_run_id"] = run_id
    state["status"] = "idle"
    _append_recent_change(state, f"Run finalized: {run_data.get('title')}")
    _write_yaml(state_path, state)

    return {
        "archive_path": str(archive_path),
        "run_id": run_id,
    }


def log_decision(
    *,
    subject: str,
    data_root: Path,
    title: str,
    summary: str,
    why: str | None,
    constraints: list[str],
    tradeoffs: list[str],
    related_runs: list[str],
    related_quests: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    decisions_dir = live / "DECISIONS"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(title)
    filename = f"DECISION__{timestamp}__{slug}.md"
    path = decisions_dir / filename
    if path.exists():
        raise LiveMemoryError(f"Decision already exists: {path}")

    lines = [
        f"# {title}",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {_now_iso()}",
        "",
        "## Summary",
        summary.strip(),
        "",
    ]

    if why:
        lines.extend(["## Rationale", why.strip(), ""])

    if constraints:
        lines.append("## Constraints")
        lines.extend([f"- {c}" for c in constraints])
        lines.append("")

    if tradeoffs:
        lines.append("## Tradeoffs")
        lines.extend([f"- {t}" for t in tradeoffs])
        lines.append("")

    if related_runs or related_quests:
        lines.append("## Related")
        for run in related_runs:
            lines.append(f"- Run: {run}")
        for quest in related_quests:
            lines.append(f"- Quest: {quest}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    state_path = live / "STATE.yaml"
    state = _load_state(state_path, subject)
    state["last_decision_id"] = _extract_decision_id(path.name)
    _append_recent_change(state, f"Decision logged: {title}")
    _write_yaml(state_path, state)

    return {"decision_path": str(path)}


def render_rehydrate(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    rehydrate_path = live / "REHYDRATE.md"

    state = _load_state(state_path, subject)
    active_run = _load_active_run(run_path, subject)

    decisions_dir = live / "DECISIONS"
    runs_dir = live / "RUNS"
    threads_path = live / "THREADS" / "open_questions.md"

    recent_decisions = sorted(decisions_dir.glob("DECISION__*.md"))[-5:]
    recent_runs = sorted(runs_dir.glob("RUN-*.yaml"))[-3:]

    active_run_id = active_run.get("run_id")
    state["active_run_id"] = active_run_id
    state["status"] = "active" if active_run_id else "idle"
    if not state.get("last_run_id") and recent_runs:
        state["last_run_id"] = _extract_run_id(recent_runs[-1].name)
    if not state.get("last_decision_id") and recent_decisions:
        state["last_decision_id"] = _extract_decision_id(recent_decisions[-1].name)

    lines = [
        "# Rehydrate",
        "",
        f"Subject: {subject}",
        f"Last updated: {_now_iso()}",
        "",
        "## What this project is",
        "See VISION.md for the current concise identity.",
        "",
        "## Current state",
        f"- Status: {state.get('status')}",
    ]

    if active_run_id:
        lines.append(f"- Active run: {active_run_id}")
    else:
        lines.append("- Active run: none")

    if state.get("last_run_id"):
        lines.append(f"- Last run: {state.get('last_run_id')}")

    if state.get("last_decision_id"):
        lines.append(f"- Last decision: {state.get('last_decision_id')}")

    lines.append("")

    if active_run_id:
        lines.append("## Active run")
        lines.append(f"- Run: {active_run_id} — {active_run.get('title')}")
        if active_run.get("goal"):
            lines.append(f"- Goal: {active_run.get('goal')}")
        items = active_run.get("plan", {}).get("items", [])
        if items:
            lines.append("- Plan items:")
            for item in items:
                lines.append(f"  - [{item.get('status')}] {item.get('id')}: {item.get('text')}")
        lines.append("")

    if state.get("recent_changes"):
        lines.append("## Recent changes")
        for entry in state.get("recent_changes", [])[-5:]:
            lines.append(f"- {entry}")
        lines.append("")

    if recent_decisions:
        lines.append("## Recent decisions")
        for decision in recent_decisions:
            lines.append(f"- {decision.name}")
        lines.append("")

    if recent_runs:
        lines.append("## Recent runs")
        for run in recent_runs:
            lines.append(f"- {run.name}")
        lines.append("")

    if threads_path.exists():
        lines.append("## Open questions")
        lines.append(threads_path.read_text(encoding="utf-8").strip())
        lines.append("")

    lines.append("## Files")
    lines.append(f"- {live / 'VISION.md'}")
    lines.append(f"- {state_path}")
    lines.append(f"- {run_path}")
    lines.append(f"- {decisions_dir}")
    lines.append(f"- {runs_dir}")

    rehydrate_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    state["last_rehydrate_at"] = _now_iso()
    _write_yaml(state_path, state)

    return {"rehydrate_path": str(rehydrate_path)}

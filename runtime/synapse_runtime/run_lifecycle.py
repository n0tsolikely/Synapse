"""Active run lifecycle helpers for the live sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.governance_model import AmbientSignal, current_session_id, infer_interaction_mode
from synapse_runtime.ledger_store import _append_ledger_entry, _daily_ledger_path, _entry_id, _sync_run_ledger
from synapse_runtime.live_memory_common import (
    LiveMemoryError,
    _is_terminal_status,
    _normalize_items,
    _normalize_relpaths,
    _parse_status_updates,
    _slugify,
)
from synapse_runtime.sidecar_projection import _append_recent_change, _sync_sidecar
from synapse_runtime.sidecar_store import (
    _default_active_run,
    _load_active_run,
    _load_state,
    _now,
    _now_iso,
    _write_yaml,
    ensure_live_scaffold,
    live_root,
)


def load_active_run_record(*, subject: str, data_root: Path) -> dict[str, Any]:
    ensure_live_scaffold(subject, data_root)
    return _load_active_run(live_root(data_root) / "ACTIVE_RUN.yaml", subject)


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
    session_id = current_session_id()
    signal = AmbientSignal(
        source="run-start",
        subject=subject,
        title=title,
        summary=goal,
        notes=tuple(items),
        status="active",
    )

    run_data = {
        "schema_version": 1,
        "active": True,
        "run_id": run_id,
        "subject": subject,
        "session_id": session_id,
        "title": title,
        "goal": goal,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "active",
        "interaction_mode": infer_interaction_mode(signal).value,
        "plan": {"items": plan_items},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "related_quests": [],
        "pending_questions": [],
        "result_summary": None,
    }

    _write_yaml(run_path, run_data)
    ledger_path = _sync_run_ledger(live, run_data, slugify=_slugify)
    _write_yaml(run_path, run_data)

    state["active_run_id"] = run_id
    state["last_run_id"] = run_id
    state["status"] = "active"
    _append_recent_change(state, f"Run started: {title}")
    _write_yaml(state_path, state)
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, signal=signal)

    return {
        "run_path": str(run_path),
        "run_id": run_id,
        "title": title,
        "goal": goal,
        "items": plan_items,
        "ledger_path": ledger_path,
        "scaffold": scaffold,
        "sidecar": sidecar,
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
    related_quests: list[str],
    status: str | None,
    summary: str | None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    discoveries_path = _daily_ledger_path(data_root, "DISCOVERIES")

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
        run_data["files_touched"].extend(_normalize_relpaths(data_root, files_touched))
    if notes:
        run_data.setdefault("notes", [])
        run_data["notes"].extend(notes)
    if verification:
        run_data.setdefault("verification", [])
        run_data["verification"].extend(verification)
    if related_sidequests:
        run_data.setdefault("related_sidequests", [])
        run_data["related_sidequests"].extend(related_sidequests)
    if related_quests:
        run_data.setdefault("related_quests", [])
        run_data["related_quests"].extend(related_quests)
    if status:
        run_data["status"] = status
    if summary:
        run_data["result_summary"] = summary

    signal = AmbientSignal(
        source="run-update",
        subject=subject,
        title=str(run_data.get("title") or ""),
        summary=summary or run_data.get("result_summary"),
        notes=tuple(notes),
        commands=tuple(commands),
        files_touched=tuple(run_data.get("files_touched", [])),
        verification=tuple(verification),
        related_sidequests=tuple(related_sidequests),
        related_quests=tuple(related_quests),
        status=status or str(run_data.get("status") or ""),
    )
    run_data["interaction_mode"] = infer_interaction_mode(signal).value
    run_data["updated_at"] = _now_iso()

    _write_yaml(run_path, run_data)
    ledger_path = _sync_run_ledger(live, run_data, slugify=_slugify)
    _write_yaml(run_path, run_data)

    state = _load_state(state_path, subject)
    state["active_run_id"] = run_data.get("run_id")
    state["status"] = "active"
    change_note = "Run updated"
    if summary:
        change_note = f"Run updated: {summary}"
    _append_recent_change(state, change_note)
    _write_yaml(state_path, state)

    discovery_entries: list[dict[str, Any]] = []
    for note in list(notes) + ([summary] if summary else []):
        if not note:
            continue
        discovery_entries.append(
            {
                "discovery_id": _entry_id("DISCOVERY"),
                "logged_at": _now_iso(),
                "kind": run_data["interaction_mode"],
                "summary": note,
                "evidence": {
                    "run_id": run_data.get("run_id"),
                    "files_touched": run_data.get("files_touched", []),
                    "commands": commands,
                    "verification": verification,
                },
            }
        )
    for entry in discovery_entries:
        _append_ledger_entry(discoveries_path, subject=subject, entry=entry)

    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        discoveries_path=discoveries_path,
    )

    return {
        "run_path": str(run_path),
        "run_id": run_data.get("run_id"),
        "added_items": new_items,
        "status_updates": updates,
        "ledger_path": ledger_path,
        "discoveries_path": str(discoveries_path),
        "sidecar": sidecar,
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
    existing_ledger = str(run_data.get("ledger_path") or "").strip()
    same_ledger = existing_ledger and Path(existing_ledger).resolve() == archive_path.resolve()
    if archive_path.exists() and not same_ledger:
        raise LiveMemoryError(f"Archived run already exists: {archive_path}")

    run_data["ledger_path"] = str(archive_path)
    _write_yaml(archive_path, run_data)
    signal = AmbientSignal(
        source="run-finalize",
        subject=subject,
        title=str(run_data.get("title") or ""),
        summary=run_data.get("result_summary"),
        notes=tuple([summary] if summary else []),
        commands=tuple(run_data.get("commands", [])),
        files_touched=tuple(run_data.get("files_touched", [])),
        verification=tuple(run_data.get("verification", [])),
        related_sidequests=tuple(run_data.get("related_sidequests", [])),
        related_quests=tuple(run_data.get("related_quests", [])),
        status=status,
    )
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, signal=signal)

    _write_yaml(run_path, _default_active_run(subject))

    state = _load_state(state_path, subject)
    state["active_run_id"] = None
    state["last_run_id"] = run_id
    state["status"] = "idle"
    _append_recent_change(state, f"Run finalized: {run_data.get('title')}")
    _write_yaml(state_path, state)
    _sync_sidecar(subject=subject, data_root=data_root, active_run=_default_active_run(subject))

    return {
        "archive_path": str(archive_path),
        "run_id": run_id,
        "sidecar": sidecar,
    }

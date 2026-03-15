"""Decision, disclosure, and quest-acceptance journaling for the live sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.accepted_execution_view import _record_disclosure_in_quest_audits
from synapse_runtime.governance_model import AmbientSignal
from synapse_runtime.ledger_store import _append_ledger_entry, _daily_ledger_path, _entry_id, _sync_run_ledger
from synapse_runtime.live_memory_common import LiveMemoryError, _extract_decision_id, _normalize_relpaths, _slugify
from synapse_runtime.sidecar_projection import _append_recent_change, _sync_sidecar
from synapse_runtime.sidecar_store import (
    _load_active_run,
    _load_state,
    _now,
    _now_iso,
    _write_yaml,
    ensure_live_scaffold,
    live_root,
)


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
    decisions_path = _daily_ledger_path(data_root, "DECISIONS")
    run_data = _load_active_run(live / "ACTIVE_RUN.yaml", subject)

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

    ledger_entry = {
        "decision_id": _extract_decision_id(path.name),
        "logged_at": _now_iso(),
        "title": title,
        "summary": summary,
        "why": why,
        "constraints": constraints,
        "tradeoffs": tradeoffs,
        "related_runs": related_runs,
        "related_quests": related_quests,
        "artifact_path": str(path),
        "binding": True,
    }
    _append_ledger_entry(decisions_path, subject=subject, entry=ledger_entry)

    state_path = live / "STATE.yaml"
    state = _load_state(state_path, subject)
    state["last_decision_id"] = _extract_decision_id(path.name)
    _append_recent_change(state, f"Decision logged: {title}")
    _write_yaml(state_path, state)
    signal = AmbientSignal(
        source="log-decision",
        subject=subject,
        title=title,
        summary=summary,
        notes=tuple((why,) if why else ()),
        files_touched=tuple(_normalize_relpaths(data_root, [str(path)])),
        related_quests=tuple(related_quests),
        related_sidequests=(),
        status="binding",
    )
    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        decisions_path=decisions_path,
    )

    return {
        "decision_path": str(path),
        "decisions_ledger_path": str(decisions_path),
        "sidecar": sidecar,
    }


def log_disclosure(
    *,
    subject: str,
    data_root: Path,
    trigger: str,
    expected: str,
    provable: str,
    status_labels: list[str],
    impact: str,
    safe_options: list[str],
    decision_needed: str,
    related_runs: list[str],
    related_quests: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    disclosures_dir = live / "DISCLOSURES"
    disclosures_dir.mkdir(parents=True, exist_ok=True)
    disclosures_path = _daily_ledger_path(data_root, "DISCLOSURES")
    run_data = _load_active_run(live / "ACTIVE_RUN.yaml", subject)

    timestamp = _now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(trigger)
    filename = f"DISCLOSURE__{timestamp}__{slug}.md"
    path = disclosures_dir / filename
    if path.exists():
        raise LiveMemoryError(f"Disclosure already exists: {path}")

    labels = [label.strip().upper() for label in status_labels if str(label).strip()]
    options = [option.strip() for option in safe_options if str(option).strip()]
    if not options:
        options = ["HALT until Brains chooses the next legal action."]
    disclosure_id = _extract_decision_id(path.name)
    disclosure_block = "\n".join(
        [
            "DISCLOSURE GATE -- EVENT",
            "",
            "Trigger:",
            trigger.strip(),
            "Expected:",
            expected.strip(),
            "Provable:",
            provable.strip(),
            "Status Labels:",
            *[f"- {label}" for label in labels],
            "Impact:",
            impact.strip(),
            "Safe Options:",
            *[f"- {option}" for option in options],
            "Decision Needed From Brains:",
            decision_needed.strip(),
        ]
    )

    lines = [
        "DISCLOSURE GATE -- EVENT",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {_now_iso()}",
        "",
        "Trigger:",
        trigger.strip(),
        "",
        "Expected:",
        expected.strip(),
        "",
        "Provable:",
        provable.strip(),
        "",
        "Status Labels:",
        *(f"- {label}" for label in labels),
        "",
        "Impact:",
        impact.strip(),
        "",
        "Safe Options:",
        *(f"- {option}" for option in options),
        "",
        "Decision Needed From Brains:",
        decision_needed.strip(),
        "",
    ]
    if related_runs or related_quests:
        lines.extend(
            ["Related:", *(f"- Run: {run}" for run in related_runs), *(f"- Quest: {quest}" for quest in related_quests), ""]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    audit_touches = _record_disclosure_in_quest_audits(
        subject=subject,
        data_root=data_root,
        related_quests=related_quests,
        disclosure_id=disclosure_id,
        disclosure_block=disclosure_block,
        trigger=trigger,
        status_labels=labels,
    )

    ledger_entry = {
        "disclosure_id": disclosure_id,
        "logged_at": _now_iso(),
        "trigger": trigger,
        "expected": expected,
        "provable": provable,
        "status_labels": labels,
        "impact": impact,
        "safe_options": options,
        "decision_needed": decision_needed,
        "related_runs": related_runs,
        "related_quests": related_quests,
        "artifact_path": str(path),
        "audit_paths": audit_touches,
    }
    _append_ledger_entry(disclosures_path, subject=subject, entry=ledger_entry)

    state_path = live / "STATE.yaml"
    state = _load_state(state_path, subject)
    _append_recent_change(state, f"Disclosure logged: {trigger}")
    _write_yaml(state_path, state)
    signal = AmbientSignal(
        source="log-disclosure",
        subject=subject,
        title=trigger,
        summary=impact,
        notes=tuple([expected, provable, decision_needed, *options]),
        files_touched=tuple(_normalize_relpaths(data_root, [str(path), *audit_touches])),
        related_quests=tuple(related_quests),
        related_sidequests=(),
        status="blocked" if any(label in {"BLOCKED", "UNVERIFIED", "UNKNOWN"} for label in labels) else "unknown",
    )
    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        disclosures_path=disclosures_path,
    )

    return {
        "disclosure_path": str(path),
        "disclosures_ledger_path": str(disclosures_path),
        "sidecar": sidecar,
    }


def record_quest_acceptance(
    *,
    subject: str,
    data_root: Path,
    quest_id: str,
    quest_title: str,
    accepted_path: Path,
    audit_bundle_path: Path,
    control_sync_state_path: Path,
) -> dict[str, Any]:
    live = live_root(data_root)
    ensure_live_scaffold(subject, data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    discoveries_path = _daily_ledger_path(data_root, "DISCOVERIES")
    run_data = _load_active_run(run_path, subject)

    if run_data.get("run_id"):
        related = list(run_data.get("related_quests") or [])
        if quest_id not in related:
            related.append(quest_id)
            run_data["related_quests"] = related
            run_data["updated_at"] = _now_iso()
            _write_yaml(run_path, run_data)
            _sync_run_ledger(live, run_data, slugify=_slugify)
            _write_yaml(run_path, run_data)

    discovery_entry = {
        "discovery_id": _entry_id("DISCOVERY"),
        "logged_at": _now_iso(),
        "kind": "governed_execution_readiness",
        "summary": f"Quest accepted for governed execution: {quest_id} - {quest_title}",
        "evidence": {
            "accepted_path": str(accepted_path.resolve()),
            "audit_bundle_path": str(audit_bundle_path.resolve()),
            "control_sync_state_path": str(control_sync_state_path.resolve()),
        },
    }
    _append_ledger_entry(discoveries_path, subject=subject, entry=discovery_entry)

    state = _load_state(state_path, subject)
    _append_recent_change(state, f"Quest accepted: {quest_id}")
    _write_yaml(state_path, state)
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, discoveries_path=discoveries_path)
    return {
        "discoveries_path": str(discoveries_path),
        "sidecar": sidecar,
    }

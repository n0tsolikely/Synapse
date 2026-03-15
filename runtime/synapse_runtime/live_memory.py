"""Live subject-memory sidecar helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.governance_model import (
    AmbientSignal,
    ProposalState,
)
from synapse_runtime.accepted_execution_view import _record_disclosure_in_quest_audits
from synapse_runtime.ledger_store import (
    _append_ledger_entry,
    _daily_ledger_path,
    _entry_id,
    _load_recent_daily_entries,
    _read_ledger_entries,
    _sync_run_ledger,
)
from synapse_runtime.live_memory_common import (
    LiveMemoryError,
    _extract_decision_id,
    _extract_run_id,
    _normalize_relpaths,
    _slugify,
)
from synapse_runtime.quest_candidates import _auto_formalize_ready_quest_candidates, _load_proposal_records, _sync_candidate_backlog, list_proposals, mark_proposal_state
from synapse_runtime.run_lifecycle import load_active_run_record, run_finalize, run_start, run_update
from synapse_runtime.sidecar_projection import _append_recent_change, _sync_sidecar, reduce_sidecar_from_event
from synapse_runtime.sidecar_store import (
    _load_active_run,
    _load_manifold,
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
        lines.extend(["Related:", *(f"- Run: {run}" for run in related_runs), *(f"- Quest: {quest}" for quest in related_quests), ""])
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


def render_rehydrate(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    rehydrate_path = live / "REHYDRATE.md"

    auto_formalizations = _auto_formalize_ready_quest_candidates(subject=subject, data_root=data_root)

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    active_run = _load_active_run(run_path, subject)

    decisions_dir = live / "DECISIONS"
    discoveries_dir = live / "DISCOVERIES"
    disclosures_dir = live / "DISCLOSURES"
    runs_dir = live / "RUNS"
    threads_path = live / "THREADS" / "open_questions.md"
    build_manual_path = data_root / "Build_Manual" / "BUILD_MANUAL.md"
    proposals = _load_proposal_records(live)

    recent_decisions = sorted(decisions_dir.glob("DECISION__*.md"))[-5:]
    recent_runs = sorted(runs_dir.glob("RUN-*.yaml"))[-3:]
    recent_decision_entries = _load_recent_daily_entries(data_root, "DECISIONS", 5)
    recent_discovery_entries = _load_recent_daily_entries(data_root, "DISCOVERIES", 5)
    recent_disclosure_entries = _load_recent_daily_entries(data_root, "DISCLOSURES", 5)
    _sync_candidate_backlog(manifold, proposals)
    quest_candidate_details = list(manifold.get("quest_candidate_details") or [])
    pending_proposals = [
        proposal
        for proposal in proposals
        if str(proposal.get("state") or "") in {
            ProposalState.PROPOSED.value,
            ProposalState.READY.value,
            ProposalState.BLOCKED.value,
            ProposalState.ESCALATED.value,
        }
    ][-8:]

    active_run_id = active_run.get("run_id")
    state["active_run_id"] = active_run_id
    state["status"] = "active" if active_run_id else "idle"
    if not state.get("last_run_id") and recent_runs:
        state["last_run_id"] = _extract_run_id(recent_runs[-1].name)
    if not state.get("last_decision_id") and recent_decisions:
        state["last_decision_id"] = _extract_decision_id(recent_decisions[-1].name)
    for item in auto_formalizations:
        _append_recent_change(state, f"Quest auto-formalized: {item.get('quest_id')}")

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
        f"- World state: {state.get('world_state')}",
        f"- Active phase: {state.get('active_phase')}",
        f"- Active modes: {', '.join(state.get('active_modes') or []) or 'none'}",
        f"- Governed execution ready: {'YES' if manifold.get('governed_execution_ready') else 'NO'}",
    ]
    if manifold.get("current_verification_status"):
        lines.append(f"- Verification status: {manifold.get('current_verification_status')}")
    if manifold.get("accepted_quest_ids"):
        lines.append(f"- Accepted quests: {', '.join(manifold.get('accepted_quest_ids') or [])}")

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

    if pending_proposals:
        lines.append("## Pending formalizations")
        for proposal in pending_proposals:
            lines.append(
                f"- [{proposal.get('state')}] {proposal.get('kind')}: {proposal.get('proposal_id')} - {proposal.get('title')}"
            )
        lines.append("")

    if quest_candidate_details:
        lines.append("## Quest candidates")
        for item in quest_candidate_details[:8]:
            lines.append(
                f"- [{item.get('state')}] {item.get('kind')} :: {item.get('title')} "
                f"({item.get('proposal_id')})"
            )
            lines.append(
                f"  scope={item.get('scope_classification')} "
                f"signals={item.get('signal_count')} "
                f"evidence={', '.join(item.get('evidence_sources') or []) or 'none'}"
            )
            if item.get("formalized_artifact_path"):
                lines.append(f"  board_artifact={item.get('formalized_artifact_path')}")
        lines.append("")

    if manifold.get("current_accepted_quest_id"):
        lines.append("## Governed execution")
        lines.append(
            f"- Current accepted quest: {manifold.get('current_accepted_quest_id')}"
            f" - {next((item.get('title') for item in manifold.get('accepted_quest_details', []) if item.get('quest_id') == manifold.get('current_accepted_quest_id')), '')}"
        )
        if manifold.get("current_accepted_quest_path"):
            lines.append(f"- Accepted quest path: {manifold.get('current_accepted_quest_path')}")
        if manifold.get("current_accepted_audit_bundle_path"):
            lines.append(f"- Audit bundle: {manifold.get('current_accepted_audit_bundle_path')}")
        lines.append(
            f"- Ready to execute: {'YES' if manifold.get('governed_execution_ready') else 'NO'}"
        )
        extra = [
            item.get("quest_id")
            for item in manifold.get("accepted_quest_details", [])
            if item.get("quest_id") != manifold.get("current_accepted_quest_id")
        ]
        if extra:
            lines.append(f"- Additional accepted quests: {', '.join(str(item) for item in extra)}")
        lines.append("")

    if recent_decision_entries:
        lines.append("## Recent binding decisions")
        for entry in recent_decision_entries:
            lines.append(f"- {entry.get('decision_id')}: {entry.get('title')} - {entry.get('summary')}")
        lines.append("")

    if recent_discovery_entries:
        lines.append("## Recent discoveries")
        for entry in recent_discovery_entries:
            lines.append(f"- {entry.get('discovery_id')}: {entry.get('summary')}")
        lines.append("")

    if manifold.get("latest_verification_entries"):
        lines.append("## Recent verification")
        for entry in list(manifold.get("latest_verification_entries") or [])[-5:]:
            lines.append(f"- {entry}")
        lines.append("")

    if recent_disclosure_entries:
        lines.append("## Recent disclosures")
        for entry in recent_disclosure_entries:
            labels = ", ".join(entry.get("status_labels") or []) or "UNSPECIFIED"
            lines.append(f"- {entry.get('disclosure_id')}: [{labels}] {entry.get('trigger')} -> {entry.get('decision_needed')}")
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
    lines.append(f"- {manifold_path}")
    lines.append(f"- {run_path}")
    lines.append(f"- {decisions_dir}")
    lines.append(f"- {discoveries_dir}")
    lines.append(f"- {disclosures_dir}")
    lines.append(f"- {runs_dir}")
    if build_manual_path.exists():
        lines.append(f"- {build_manual_path}")

    rehydrate_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    state["last_rehydrate_at"] = _now_iso()
    manifold["current_decision_ledger_path"] = str(_daily_ledger_path(data_root, "DECISIONS"))
    manifold["current_discovery_ledger_path"] = str(_daily_ledger_path(data_root, "DISCOVERIES"))
    manifold["current_disclosure_ledger_path"] = str(_daily_ledger_path(data_root, "DISCLOSURES"))
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(state_path, state)
    _write_yaml(manifold_path, manifold)

    return {
        "rehydrate_path": str(rehydrate_path),
        "auto_formalizations": auto_formalizations,
        "pending_formalization_count": len(pending_proposals),
        "recent_decision_count": len(recent_decision_entries),
        "recent_discovery_count": len(recent_discovery_entries),
        "recent_disclosure_count": len(recent_disclosure_entries),
    }

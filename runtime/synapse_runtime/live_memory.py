"""Live subject-memory sidecar helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.governance_model import (
    AmbientSignal,
    ArtifactType,
    DraftshotState,
    ProposalKind,
    PromotionRecord,
    ProposalState,
    current_session_id,
    derive_world_state,
    evaluate_promotion,
    infer_interaction_mode,
)
from synapse_runtime.accepted_execution_view import (
    _load_accepted_quest_details,
    _record_disclosure_in_quest_audits,
    _select_current_accepted_quest,
)
from synapse_runtime.ledger_store import (
    _append_ledger_entry,
    _classify_verification_status,
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
    _is_terminal_status,
    _normalize_items,
    _normalize_relpaths,
    _parse_status_updates,
    _slugify,
)
from synapse_runtime.quest_candidates import (
    QUEST_PROPOSAL_KINDS,
    _auto_formalize_ready_quest_candidates,
    _candidate_summary,
    _candidate_title,
    _load_proposal_records,
    _open_plan_items,
    _proposal_id,
    _sync_candidate_backlog,
    _upsert_quest_candidate,
    _write_proposals,
    list_proposals,
    mark_proposal_state,
)
from synapse_runtime.sidecar_store import (
    _default_active_run,
    _load_active_run,
    _load_manifold,
    _load_state,
    _now,
    _now_iso,
    _write_yaml,
    ensure_live_scaffold,
    live_root,
)

def _append_recent_change(state: dict[str, Any], note: str) -> None:
    entries = state.get("recent_changes")
    if not isinstance(entries, list):
        entries = []
    entries.append(f"{_now_iso()} - {note}")
    state["recent_changes"] = entries[-10:]


def _sync_sidecar(
    *,
    subject: str,
    data_root: Path,
    active_run: dict[str, Any],
    signal: AmbientSignal | None = None,
    decisions_path: Path | None = None,
    discoveries_path: Path | None = None,
    disclosures_path: Path | None = None,
    mutate_proposals: bool = True,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    world_state = derive_world_state(data_root)
    inferred_mode = infer_interaction_mode(signal) if signal is not None else active_run.get("interaction_mode") or "maintenance"
    interaction_mode = str(getattr(inferred_mode, "value", inferred_mode) or "maintenance")
    session_id = active_run.get("session_id") or current_session_id()
    run_id = active_run.get("run_id")
    accepted_details = _load_accepted_quest_details(subject, data_root)
    current_accepted = _select_current_accepted_quest(accepted_details)
    governed_execution_ready = bool(
        current_accepted
        and current_accepted.get("execution_ready")
        and world_state.value == "fog_lifted"
    )

    state["world_state"] = world_state.value
    state["active_phase"] = "execute" if run_id else ("incubation" if world_state.value == "fog_of_war" else "idle")
    state["active_modes"] = ["ambient", interaction_mode]
    state["active_run_id"] = run_id
    state["status"] = "active" if active_run.get("active") else "idle"
    state["governed_execution_ready"] = governed_execution_ready
    state["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    state["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    if decisions_path is not None:
        state["last_decision_id"] = decisions_path.stem
    _write_yaml(state_path, state)

    manifold["world_state"] = world_state.value
    manifold["active_phase"] = state["active_phase"]
    manifold["active_modes"] = state["active_modes"]
    manifold["active_run_ids"] = [run_id] if run_id else []
    manifold["accepted_quest_ids"] = [str(item.get("quest_id")) for item in accepted_details if item.get("quest_id")]
    manifold["accepted_quest_details"] = accepted_details
    manifold["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    manifold["current_accepted_quest_path"] = current_accepted.get("path") if current_accepted else None
    manifold["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    manifold["governed_execution_ready"] = governed_execution_ready
    if session_id:
        manifold["active_session_ids"] = [session_id]
    if decisions_path is not None:
        manifold["current_decision_ledger_path"] = str(decisions_path)
    if discoveries_path is not None:
        manifold["current_discovery_ledger_path"] = str(discoveries_path)
    if disclosures_path is not None:
        manifold["current_disclosure_ledger_path"] = str(disclosures_path)

    proposal_paths: list[str] = []
    build_manual_candidates = list(manifold.get("current_build_manual_candidate_backlog") or [])
    talent_candidates = list(manifold.get("current_talent_candidate_backlog") or [])
    codex_candidates = list(manifold.get("current_codex_shard_backlog") or [])
    disclosure_candidates = list(manifold.get("current_disclosure_candidate_backlog") or [])
    order_candidates = list(manifold.get("active_order_candidates") or [])
    build_manual_candidate_path = manifold.get("current_build_manual_candidate_path")
    disclosure_candidate_path = manifold.get("current_disclosure_candidate_path")
    snapshot_candidate_path = manifold.get("current_snapshot_candidate_path")
    verification_entries = list(manifold.get("latest_verification_entries") or [])
    verification_status = manifold.get("current_verification_status")
    if signal is not None:
        if signal.verification:
            verification_entries.extend(str(item) for item in signal.verification if str(item).strip())
            verification_entries = verification_entries[-10:]
            verification_status = _classify_verification_status(verification_entries) or verification_status
    if signal is not None and mutate_proposals:
        promotions = evaluate_promotion(signal, data_root)
        if not any(promotion.kind in QUEST_PROPOSAL_KINDS for promotion in promotions):
            if signal.source in {"run-start", "run-update", "run-finalize"} and (
                _open_plan_items(active_run)
                or signal.commands
                or signal.files_touched
                or signal.notes
                or signal.summary
            ):
                promotions.append(
                    PromotionRecord(
                        kind=ProposalKind.QUEST,
                        state=ProposalState.AMBIENT,
                        title=_candidate_title(signal, active_run),
                        summary=_candidate_summary(signal, active_run, _candidate_title(signal, active_run)),
                        reason="Active run signals indicate a bounded work unit that should be tracked as a quest candidate.",
                    )
                )
        promotion_payloads: list[dict[str, Any]] = []
        quest_candidate_paths: list[str] = []
        for promotion in promotions:
            source_id = run_id or "NO_RUN"
            if promotion.kind in QUEST_PROPOSAL_KINDS:
                candidate = _upsert_quest_candidate(
                    live=live,
                    subject=subject,
                    data_root=data_root,
                    source_id=source_id,
                    interaction_mode=interaction_mode,
                    active_run=active_run,
                    signal=signal,
                    promotion=promotion,
                    current_accepted=current_accepted,
                )
                if candidate is not None:
                    quest_candidate_paths.append(str(candidate["path"]))
                continue

            proposal_id = _proposal_id(promotion.kind, source_id, promotion.title)
            promotion_payloads.append(
                {
                    "proposal_id": proposal_id,
                    "kind": promotion.kind.value,
                    "state": promotion.state.value,
                    "title": promotion.title,
                    "summary": promotion.summary,
                    "reason": promotion.reason,
                    "blockers": list(promotion.blockers),
                    "evidence": list(promotion.evidence),
                    "codex_implications": list(promotion.codex_implications),
                    "created_at": _now_iso(),
                }
            )
            if promotion.state in {ProposalState.PROPOSED, ProposalState.READY, ProposalState.BLOCKED, ProposalState.ESCALATED}:
                pass
            if promotion.kind == ProposalKind.GUILD_ORDERS:
                if proposal_id not in order_candidates:
                    order_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.TALENT:
                if proposal_id not in talent_candidates:
                    talent_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.CODEX:
                if proposal_id not in codex_candidates:
                    codex_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.BUILD_MANUAL:
                if proposal_id not in build_manual_candidates:
                    build_manual_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.DISCLOSURE:
                if proposal_id not in disclosure_candidates:
                    disclosure_candidates.append(proposal_id)
        proposal_paths = quest_candidate_paths + _write_proposals(
            live=live,
            subject=subject,
            source_id=run_id or "NO_RUN",
            interaction_mode=interaction_mode,
            promotions=promotion_payloads,
        )

    proposal_records = _load_proposal_records(live)
    _sync_candidate_backlog(manifold, proposal_records)

    manifold["active_order_candidates"] = order_candidates
    manifold["current_build_manual_candidate_backlog"] = build_manual_candidates
    manifold["current_talent_candidate_backlog"] = talent_candidates
    manifold["current_codex_shard_backlog"] = codex_candidates
    manifold["current_disclosure_candidate_backlog"] = disclosure_candidates
    if signal is not None:
        build_manual_candidate_path = next(
            (path for path in proposal_paths if "/build_manual/" in path),
            build_manual_candidate_path,
        )
        disclosure_candidate_path = next(
            (path for path in proposal_paths if "/disclosures/" in path),
            disclosure_candidate_path,
        )
        snapshot_candidate_path = next((path for path in proposal_paths if "/snapshots/" in path), snapshot_candidate_path)
    manifold["current_build_manual_candidate_path"] = build_manual_candidate_path
    manifold["current_disclosure_candidate_path"] = disclosure_candidate_path
    manifold["current_snapshot_candidate_path"] = snapshot_candidate_path
    manifold["current_verification_status"] = verification_status
    manifold["latest_verification_entries"] = verification_entries
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)

    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        "proposal_paths": proposal_paths,
        "interaction_mode": interaction_mode,
        "world_state": world_state.value,
    }


def _event_notes(signals: dict[str, Any]) -> tuple[str, ...]:
    raw_notes: list[str] = []
    for key in ("notes", "plan_items", "decisions", "discoveries", "disclosures"):
        value = signals.get(key)
        if isinstance(value, list):
            raw_notes.extend(str(item).strip() for item in value if str(item).strip())
    return tuple(raw_notes)


def _ambient_signal_from_event(subject: str, event: dict[str, Any], active_run: dict[str, Any]) -> AmbientSignal | None:
    action_name = str(event.get("action_name") or "").strip()
    if action_name not in {
        "attach-or-init",
        "live-bootstrap",
        "session-start",
        "run-start",
        "run-update",
        "session-tick",
        "run-finalize",
        "log-decision",
        "log-disclosure",
        "formalize",
        "accept-quest",
    }:
        return None

    signals = event.get("signals")
    if not isinstance(signals, dict):
        signals = {}

    title = (
        str(signals.get("run_title") or "").strip()
        or str(signals.get("decision_title") or "").strip()
        or str(signals.get("disclosure_trigger") or "").strip()
        or str(active_run.get("title") or "").strip()
        or None
    )
    summary = (
        str(signals.get("run_goal") or "").strip()
        or str(signals.get("run_summary") or "").strip()
        or str(event.get("summary") or "").strip()
        or None
    )
    status = (
        str(signals.get("final_status") or "").strip()
        or str(signals.get("run_status") or "").strip()
        or str(event.get("status") or "").strip()
        or None
    )
    return AmbientSignal(
        source=action_name,
        subject=subject,
        title=title,
        summary=summary,
        notes=_event_notes(signals),
        commands=tuple(str(item).strip() for item in signals.get("commands") or [] if str(item).strip()),
        files_touched=tuple(
            str(item).strip()
            for item in (active_run.get("files_touched") or signals.get("changed_files") or [])
            if str(item).strip()
        ),
        verification=tuple(
            str(item).strip() for item in signals.get("verification_entries") or [] if str(item).strip()
        ),
        related_sidequests=tuple(
            str(item).strip() for item in signals.get("related_sidequest_ids") or [] if str(item).strip()
        ),
        related_quests=tuple(
            str(item).strip() for item in signals.get("related_quest_ids") or [] if str(item).strip()
        ),
        status=status,
    )


def reduce_sidecar_from_event(*, subject: str, data_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    ensure_live_scaffold(subject, data_root)
    live = live_root(data_root)
    active_run = _load_active_run(live / "ACTIVE_RUN.yaml", subject)
    signal = _ambient_signal_from_event(subject, event, active_run)
    outputs = event.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    def maybe_path(value: Any) -> Path | None:
        text = str(value or "").strip()
        return Path(text) if text else None

    return _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=active_run,
        signal=signal,
        decisions_path=maybe_path(outputs.get("decisions_ledger_path")),
        discoveries_path=maybe_path(outputs.get("discoveries_path")),
        disclosures_path=maybe_path(outputs.get("disclosures_ledger_path")),
        mutate_proposals=False,
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

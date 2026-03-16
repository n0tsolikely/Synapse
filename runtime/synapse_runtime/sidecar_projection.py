"""Sidecar projection and event-to-sidecar reduction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.accepted_execution_view import (
    load_accepted_quest_details,
    load_completed_quest_details,
    select_current_accepted_quest,
    select_latest_completed_quest,
)
from synapse_runtime.governance_model import (
    AmbientSignal,
    PromotionRecord,
    ProposalKind,
    ProposalState,
    current_session_id,
    derive_world_state,
    evaluate_promotion,
    infer_interaction_mode,
)
from synapse_runtime.ledger_store import _classify_verification_status
from synapse_runtime.quest_candidates import (
    QUEST_PROPOSAL_KINDS,
    _candidate_summary,
    _candidate_title,
    _load_proposal_records,
    _open_plan_items,
    _proposal_id,
    _sync_candidate_backlog,
    _upsert_quest_candidate,
    _write_proposals,
)
from synapse_runtime.sidecar_store import (
    _load_active_run,
    _load_manifold,
    _load_state,
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


def _apply_quest_lifecycle_projection(
    *,
    subject: str,
    data_root: Path,
    state: dict[str, Any],
    manifold: dict[str, Any],
    world_state: Any,
) -> dict[str, Any]:
    accepted_details = load_accepted_quest_details(subject, data_root)
    current_accepted = select_current_accepted_quest(accepted_details)
    completed_details = load_completed_quest_details(subject, data_root)
    latest_completed = select_latest_completed_quest(completed_details)
    governed_execution_ready = bool(
        current_accepted
        and current_accepted.get("execution_ready")
        and world_state.value == "fog_lifted"
    )

    state["governed_execution_ready"] = governed_execution_ready
    state["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    state["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    state["last_completed_quest_id"] = latest_completed.get("quest_id") if latest_completed else None
    state["last_completed_quest_path"] = latest_completed.get("path") if latest_completed else None
    state["last_completed_audit_bundle_path"] = (
        latest_completed.get("audit_bundle_path") if latest_completed else None
    )

    manifold["accepted_quest_ids"] = [str(item.get("quest_id")) for item in accepted_details if item.get("quest_id")]
    manifold["accepted_quest_details"] = accepted_details
    manifold["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    manifold["current_accepted_quest_path"] = current_accepted.get("path") if current_accepted else None
    manifold["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    manifold["completed_quest_ids"] = [str(item.get("quest_id")) for item in completed_details if item.get("quest_id")]
    manifold["completed_quest_details"] = completed_details
    manifold["last_completed_quest_id"] = latest_completed.get("quest_id") if latest_completed else None
    manifold["last_completed_quest_path"] = latest_completed.get("path") if latest_completed else None
    manifold["last_completed_audit_bundle_path"] = (
        latest_completed.get("audit_bundle_path") if latest_completed else None
    )
    manifold["governed_execution_ready"] = governed_execution_ready

    return {
        "accepted_details": accepted_details,
        "current_accepted": current_accepted,
        "completed_details": completed_details,
        "latest_completed": latest_completed,
        "governed_execution_ready": governed_execution_ready,
    }


def refresh_quest_lifecycle_projection(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    world_state = derive_world_state(data_root)
    projection = _apply_quest_lifecycle_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
        world_state=world_state,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        **projection,
    }


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

    state["world_state"] = world_state.value
    state["active_phase"] = "execute" if run_id else ("incubation" if world_state.value == "fog_of_war" else "idle")
    state["active_modes"] = ["ambient", interaction_mode]
    state["active_run_id"] = run_id
    state["status"] = "active" if active_run.get("active") else "idle"
    if decisions_path is not None:
        state["last_decision_id"] = decisions_path.stem

    manifold["world_state"] = world_state.value
    manifold["active_phase"] = state["active_phase"]
    manifold["active_modes"] = state["active_modes"]
    manifold["active_run_ids"] = [run_id] if run_id else []
    if session_id:
        manifold["active_session_ids"] = [session_id]
    if decisions_path is not None:
        manifold["current_decision_ledger_path"] = str(decisions_path)
    if discoveries_path is not None:
        manifold["current_discovery_ledger_path"] = str(discoveries_path)
    if disclosures_path is not None:
        manifold["current_disclosure_ledger_path"] = str(disclosures_path)

    accepted_details = load_accepted_quest_details(subject, data_root)
    current_accepted = select_current_accepted_quest(accepted_details)

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
    if signal is not None and signal.verification:
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
            if promotion.kind == ProposalKind.GUILD_ORDERS and proposal_id not in order_candidates:
                order_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.TALENT and proposal_id not in talent_candidates:
                talent_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.CODEX and proposal_id not in codex_candidates:
                codex_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.BUILD_MANUAL and proposal_id not in build_manual_candidates:
                build_manual_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.DISCLOSURE and proposal_id not in disclosure_candidates:
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
        snapshot_candidate_path = next(
            (path for path in proposal_paths if "/snapshots/" in path),
            snapshot_candidate_path,
        )
    manifold["current_build_manual_candidate_path"] = build_manual_candidate_path
    manifold["current_disclosure_candidate_path"] = disclosure_candidate_path
    manifold["current_snapshot_candidate_path"] = snapshot_candidate_path
    manifold["current_verification_status"] = verification_status
    manifold["latest_verification_entries"] = verification_entries
    projection = _apply_quest_lifecycle_projection(
        subject=subject,
        data_root=data_root,
        state=state,
        manifold=manifold,
        world_state=world_state,
    )
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)

    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        "proposal_paths": proposal_paths,
        "interaction_mode": interaction_mode,
        "world_state": world_state.value,
        "current_accepted_quest_id": projection["current_accepted"]["quest_id"] if projection["current_accepted"] else None,
        "last_completed_quest_id": projection["latest_completed"]["quest_id"] if projection["latest_completed"] else None,
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

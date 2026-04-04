"""Rehydrate rendering for the live sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synapse_runtime.governance_model import ProposalState
from synapse_runtime.ledger_store import _daily_ledger_path, _load_recent_daily_entries
from synapse_runtime.live_memory_common import _extract_decision_id, _extract_run_id
from synapse_runtime.quest_candidates import _auto_formalize_ready_quest_candidates, _load_proposal_records, _sync_candidate_backlog
from synapse_runtime.sidecar_projection import (
    _append_recent_change,
    refresh_onboarding_projection,
    refresh_provenance_projection,
    refresh_synthesis_projection,
    refresh_semantic_capture_projection,
    refresh_quest_lifecycle_projection,
    refresh_session_posture_projection,
)
from synapse_runtime.sidecar_store import _load_active_run, _load_manifold, _load_state, _now_iso, _write_yaml, live_root


def _render_delta_block(lines: list[str], title: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or not str(payload.get("summary") or "").strip():
        return
    lines.append(f"- {title}: {payload.get('summary')}")
    refreshed_at = str(payload.get("refreshed_at") or "").strip()
    if refreshed_at:
        lines.append(f"  refreshed_at={refreshed_at}")
    source_refs = list(payload.get("source_refs") or [])
    if source_refs:
        lines.append(f"  source_refs={len(source_refs)}")
        for ref in source_refs[:3]:
            path = str(ref.get("path") or "").strip()
            if path:
                lines.append(f"  source={path}")
    for item in list(payload.get("detail_lines") or [])[:4]:
        lines.append(f"  - {item}")


def render_rehydrate(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    rehydrate_path = live / "REHYDRATE.md"

    active_run = _load_active_run(run_path, subject)
    auto_formalizations = _auto_formalize_ready_quest_candidates(
        subject=subject,
        data_root=data_root,
        active_run=active_run,
    )
    refresh_semantic_capture_projection(subject=subject, data_root=data_root)
    refresh_onboarding_projection(subject=subject, data_root=data_root)
    refresh_session_posture_projection(subject=subject, data_root=data_root)
    refresh_quest_lifecycle_projection(subject=subject, data_root=data_root)
    refresh_synthesis_projection(subject=subject, data_root=data_root)
    refresh_provenance_projection(subject=subject, data_root=data_root)

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)

    decisions_dir = live / "DECISIONS"
    discoveries_dir = live / "DISCOVERIES"
    disclosures_dir = live / "DISCLOSURES"
    runs_dir = live / "RUNS"
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

    lines.append("## Repository readiness")
    lines.append(f"- Onboarding required: {'YES' if state.get('onboarding_required') else 'NO'}")
    lines.append(f"- Onboarding confirmed: {'YES' if state.get('onboarding_confirmed') else 'NO'}")
    if state.get("onboarding_requirement_reason"):
        lines.append(f"- Onboarding requirement reason: {state.get('onboarding_requirement_reason')}")
    lines.append(f"- Project identity ready: {'YES' if state.get('project_identity_ready') else 'NO'}")
    lines.append(f"- Continuity ready: {'YES' if state.get('continuity_ready') else 'NO'}")
    if state.get("onboarding_required"):
        if not state.get("published_project_model_path"):
            lines.append("- WARNING: project model missing")
        if not state.get("published_project_story_path"):
            lines.append("- WARNING: project story missing")
        if not state.get("published_vision_path"):
            lines.append("- WARNING: vision missing")
        lines.append("- WARNING: onboarding confirmation required before normal work")
    lines.append("")

    lines.append("## Automation status")
    lines.append(f"- Automation status: {state.get('automation_status') or 'unknown'}")
    lines.append(f"- Last activity at: {state.get('automation_last_activity_at') or 'none'}")
    lines.append(
        f"- Last continuity update at: {state.get('automation_last_continuity_update_at') or 'none'}"
    )
    lines.append(f"- Pending gate: {state.get('automation_pending_gate') or 'none'}")
    recent_automation = list(manifold.get("automation_recent_actions") or [])
    if recent_automation:
        lines.append(f"- Recent automation actions: {', '.join(recent_automation)}")
    else:
        lines.append("- Recent automation actions: none")
    lines.append("")

    lines.append("## Session posture")
    active_session_mode = str(manifold.get("active_session_mode") or "").strip()
    if active_session_mode:
        policy = manifold.get("active_session_mode_policy") or {}
        lines.append(f"- Current session mode: {active_session_mode}")
        if policy.get("description"):
            lines.append(f"- Description: {policy.get('description')}")
        blocked_commands = list(policy.get("blocked_mutation_commands") or [])
        lines.append(
            f"- Blocked mutation commands: {', '.join(blocked_commands) if blocked_commands else 'none'}"
        )
        allowed_next_modes = list(policy.get("allowed_next_modes") or [])
        lines.append(f"- Allowed next modes: {', '.join(allowed_next_modes) if allowed_next_modes else 'none'}")
    else:
        lines.append("- Current session mode: none")
        if state.get("last_session_mode"):
            lines.append(f"- Last session mode: {state.get('last_session_mode')}")
            if state.get("last_session_mode_ended_at"):
                lines.append(f"- Last session mode ended at: {state.get('last_session_mode_ended_at')}")
    lines.append("")

    lines.append("## Draftshot state")
    lines.append(f"- Active Draftshot count: {manifold.get('active_draftshot_count') or 0}")
    if manifold.get("current_active_draftshot_path"):
        lines.append(f"- Active Draftshot path: {manifold.get('current_active_draftshot_path')}")
        lines.append(f"- Active Draftshot status: {manifold.get('current_active_draftshot_status') or 'unknown'}")
        lines.append(f"- Active Draftshot session: {manifold.get('current_active_draftshot_session_id') or 'unknown'}")
        lines.append(f"- Last refreshed at: {manifold.get('last_draftshot_refreshed_at') or 'unknown'}")
        lines.append(f"- Stale against current synthesis: {'YES' if manifold.get('draftshot_stale') else 'NO'}")
        integrity_issues = list(manifold.get("draftshot_integrity_issues") or [])
        if integrity_issues:
            lines.append(f"- Integrity: ISSUE ({len(integrity_issues)})")
            for issue in integrity_issues[:5]:
                lines.append(f"  - {issue}")
        else:
            lines.append("- Integrity: OK")
    else:
        lines.append("- Active Draftshot path: none")
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

    lines.append("## Onboarding status")
    onboarding_state = str(state.get("onboarding_state") or "").strip()
    if onboarding_state:
        lines.append(f"- Active onboarding id: {state.get('active_onboarding_id')}")
        lines.append(f"- State: {onboarding_state}")
        lines.append(f"- Workplan id: {state.get('current_workplan_id') or 'missing'}")
        lines.append(f"- Draft stale: {'YES' if manifold.get('draft_is_stale') else 'NO'}")
        if manifold.get("unincorporated_capture_batch_ids"):
            lines.append(
                "- Unincorporated clarification batches: "
                + ", ".join(str(item) for item in manifold.get("unincorporated_capture_batch_ids") or [])
            )
        blocking_steps = [
            step_id
            for step_id, status in dict(manifold.get("workplan_step_statuses") or {}).items()
            if str(status or "").strip() not in {"complete", "completed"}
        ]
        lines.append(f"- Blocking workplan steps: {', '.join(blocking_steps) if blocking_steps else 'none'}")
    else:
        lines.append("- Active onboarding id: none")
        if state.get("latest_confirmed_onboarding_id"):
            lines.append(f"- Latest confirmed onboarding id: {state.get('latest_confirmed_onboarding_id')}")
    lines.append("")

    lines.append("## Published project identity")
    if (
        state.get("published_project_model_path")
        or state.get("published_project_story_path")
        or state.get("published_vision_path")
        or state.get("published_codex_current_path")
        or state.get("published_codex_future_path")
    ):
        lines.append(f"- Project model path: {state.get('published_project_model_path') or 'missing'}")
        lines.append(f"- Project story path: {state.get('published_project_story_path') or 'missing'}")
        lines.append(f"- Vision path: {state.get('published_vision_path') or 'missing'}")
        lines.append(f"- Current codex path: {state.get('published_codex_current_path') or 'missing'}")
        lines.append(f"- Future codex path: {state.get('published_codex_future_path') or 'missing'}")
    else:
        lines.append("- Project model path: missing")
        lines.append("- Project story path: missing")
        lines.append("- Vision path: missing")
        lines.append("- Current codex path: missing")
        lines.append("- Future codex path: missing")
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

    completed_quest_details = list(manifold.get("completed_quest_details") or [])
    if completed_quest_details:
        lines.append("## Completed quests")
        for item in completed_quest_details[:3]:
            lines.append(f"- {item.get('quest_id')}: {item.get('title')}")
            lines.append(f"  path={item.get('path')}")
            if item.get("audit_bundle_path"):
                lines.append(f"  audit_bundle={item.get('audit_bundle_path')}")
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

    lines.append("## Provenance / Trust")
    lines.append(f"- Provenance status: {state.get('provenance_status') or 'unknown'}")
    lines.append(
        "- Trust note: clear means no current warnings or blockers under Phase 5 checks; "
        "it does not prove universal mediation or perfect provenance."
    )
    lines.append(f"- Wrapper proof status: {state.get('current_wrapper_proof_status') or 'unknown'}")
    lines.append(f"- Git hooks status: {state.get('git_hooks_status') or 'unknown'}")
    lines.append(f"- Integration posture: {state.get('integration_posture') or 'unknown'}")
    lines.append(f"- Local integration health: {state.get('local_integration_health') or 'unknown'}")
    lines.append(f"- Open continuity obligations: {state.get('open_continuity_obligation_count') or 0}")
    lines.append(f"- Blocker continuity obligations: {state.get('blocker_continuity_obligation_count') or 0}")
    if state.get("degraded_mode"):
        lines.append(f"- Degraded-mode note: {manifold.get('degraded_mode_reason') or 'turn-bound enforcement is not guaranteed'}")
    blockers = list(manifold.get("provenance_blockers") or [])
    warnings = list(manifold.get("provenance_warnings") or [])
    continuity_blockers = list(manifold.get("continuity_blockers") or [])
    continuity_warnings = list(manifold.get("continuity_warnings") or [])
    if blockers:
        lines.append("- Current blockers:")
        for item in blockers:
            lines.append(f"  - {item.get('kind')}: {item.get('message')}")
    else:
        lines.append("- Current blockers: none")
    if continuity_blockers:
        lines.append("- Continuity blockers:")
        for item in continuity_blockers[:5]:
            lines.append(f"  - {item.get('obligation_kind')}: {item.get('summary')}")
    else:
        lines.append("- Continuity blockers: none")
    if warnings:
        lines.append("- Current warnings:")
        for item in warnings:
            lines.append(f"  - {item.get('kind')}: {item.get('message')}")
    else:
        lines.append("- Current warnings: none")
    if continuity_warnings:
        lines.append("- Continuity warnings:")
        for item in continuity_warnings[:5]:
            lines.append(f"  - {item.get('obligation_kind')}: {item.get('summary')}")
    else:
        lines.append("- Continuity warnings: none")
    recent_anomalies = list(manifold.get("recent_provenance_anomalies") or [])
    if recent_anomalies:
        lines.append("- Recent anomalies:")
        for item in recent_anomalies[:5]:
            lines.append(f"  - [{item.get('severity')}] {item.get('kind')}: {item.get('message')}")
    else:
        lines.append("- Recent anomalies: none")
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

    blocking_questions = list(manifold.get("blocking_question_details") or [])
    nonblocking_questions = [
        detail
        for detail in list(manifold.get("open_question_details") or [])
        if not bool(detail.get("blocking"))
    ]
    if blocking_questions or nonblocking_questions:
        lines.append("## Open questions")
        lines.append("- Blocking:")
        if blocking_questions:
            for detail in blocking_questions:
                lines.append(f"  - {detail.get('summary')}")
        else:
            lines.append("  - None yet.")
        lines.append("- Nonblocking:")
        if nonblocking_questions:
            for detail in nonblocking_questions:
                lines.append(f"  - {detail.get('summary')}")
        else:
            lines.append("  - None yet.")
        lines.append("")

    if state.get("published_project_model_path"):
        lines.append("## Published project model")
        if state.get("project_summary"):
            lines.append(f"- Summary: {state.get('project_summary')}")
        if manifold.get("project_purpose_summary"):
            lines.append(f"- Purpose: {manifold.get('project_purpose_summary')}")
        if manifold.get("project_capability_summary"):
            lines.append("- Capabilities:")
            for item in manifold.get("project_capability_summary") or []:
                lines.append(f"  - {item}")
        if manifold.get("project_constraint_summary"):
            lines.append("- Constraints:")
            for item in manifold.get("project_constraint_summary") or []:
                lines.append(f"  - {item}")
        if manifold.get("project_history_summary"):
            lines.append("- History / supersession:")
            for item in manifold.get("project_history_summary") or []:
                lines.append(f"  - {item}")
        lines.append(f"- Project model path: {state.get('published_project_model_path')}")
        lines.append(f"- Project story path: {state.get('published_project_story_path')}")
        lines.append(f"- Vision path: {state.get('published_vision_path')}")
        lines.append("")

    if manifold.get("project_open_question_details"):
        lines.append("## Open project questions")
        for item in manifold.get("project_open_question_details") or []:
            lines.append(f"- [{item.get('priority')}] {item.get('prompt')}")
        lines.append("")

    derived_deltas = [
        ("Active plan delta", dict(manifold.get("current_active_plan_delta") or {})),
        ("Active scope delta", dict(manifold.get("current_active_scope_delta") or {})),
        ("Obligation delta", dict(manifold.get("current_obligation_delta") or {})),
        ("Architecture delta", dict(manifold.get("current_architecture_delta") or {})),
        ("Identity delta", dict(manifold.get("current_identity_delta") or {})),
        ("Narrative delta", dict(manifold.get("current_narrative_delta") or {})),
    ]
    if any(str(payload.get("summary") or "").strip() for _, payload in derived_deltas):
        lines.append("## Derived synthesis")
        refreshed_at = str(manifold.get("last_synthesis_refresh_at") or "").strip()
        lines.append(f"- Last synthesis refresh: {refreshed_at or 'none'}")
        for title, payload in derived_deltas:
            _render_delta_block(lines, title, payload)
        lines.append("")

    codex_packets = list(manifold.get("recent_codex_packet_details") or [])
    if codex_packets:
        lines.append("## Codex section packets")
        lines.append(
            f"- Packet count: {manifold.get('codex_packet_count') or len(codex_packets)}"
        )
        last_refreshed = str(manifold.get("last_codex_packet_refreshed_at") or "").strip()
        lines.append(f"- Last packet refresh: {last_refreshed or 'none'}")
        for item in codex_packets[:6]:
            lines.append(
                f"- {item.get('section_title') or item.get('section_key')}: {item.get('summary')}"
            )
            if item.get("path"):
                lines.append(f"  packet={item.get('path')}")
        lines.append("")

    semantic_sections = [
        ("Ideas", manifold.get("recent_idea_details") or []),
        ("Constraints", manifold.get("recent_constraint_details") or []),
        ("Risks", manifold.get("recent_risk_details") or []),
        ("Dependencies", manifold.get("recent_dependency_details") or []),
        ("Non-goals", manifold.get("recent_non_goal_details") or []),
        ("Milestones", manifold.get("recent_milestone_details") or []),
        ("Provisional decisions", manifold.get("candidate_decision_details") or []),
        ("Repo facts", manifold.get("recent_repo_fact_details") or []),
    ]
    if any(details for _, details in semantic_sections):
        lines.append("## Recent semantic captures")
        for label, details in semantic_sections:
            if not details:
                continue
            lines.append(f"- {label}:")
            for detail in details:
                lines.append(f"  - {detail.get('summary')}")
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

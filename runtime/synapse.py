#!/usr/bin/env python3
"""Synapse runtime CLI."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.automation_orchestrator import (
    AutomationAction,
    automation_summary,
    automation_policy_for_context,
    classify_runtime_activity,
    plan_automation_side_effects,
    ready_state_gate_for_mode,
)
from synapse_runtime.artifact_router import (
    GOVERNANCE_PROPOSAL_DISPATCH_KEY,
    NOOP_DISPATCH_KEY,
    PUBLICATION_DISPATCH_KEY,
    QUEST_DISPATCH_KEY,
    SNAPSHOT_DISPATCH_KEY,
    ArtifactRoutingContext,
    ArtifactRoutingResult,
    build_artifact_routing_context,
    evaluate_artifact_routing,
    promotion_record_from_payload,
)
from synapse_runtime.continuity_model_adapter import configured_continuity_observer_backend
from synapse_runtime.continuity_observer import ContinuityObserverError, observe_continuity
from synapse_runtime.continuity_obligations import open_obligation, resolve_matching_obligations
from synapse_runtime.conversation_ingest import ConversationIngestError, record_raw_turn
from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.draftshots import DraftshotError, load_active_draftshot, refresh_draftshot
from synapse_runtime.doctor import run_doctor
from synapse_runtime.event_log import (
    EventLogError,
    REDUCER_VERSION,
    append_event,
    build_event,
    load_event_records,
    raw_artifact_ref,
    raw_capture_signals,
)
from synapse_runtime.execution_observer import ExecutionObserverError, record_raw_execution
from synapse_runtime.governance_pack import resolve_governance_asset, resolve_governance_root, resolve_synapse_root
from synapse_runtime.governance_inventory import build_governance_inventory, write_governance_inventory
from synapse_runtime.governance_model import AmbientSignal, ProposalKind, ProposalState
from synapse_runtime.guild_orders_runtime import formalize_guild_orders_from_proposal
from synapse_runtime.live_journal import log_decision, log_disclosure, record_quest_acceptance
from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.imported_continuity import (
    ImportedContinuityError,
    imported_confidence_profile,
    parse_imported_continuity_source,
)
from synapse_runtime.kernel_types import kernel_now_iso
from synapse_runtime.persona import resolve_persona
from synapse_runtime.git_hooks import GitHooksError, install_managed_hooks, inspect_git_hooks, write_hooks_receipt
from synapse_runtime.provenance import (
    GitHooksStatus,
    ProvenanceStatus,
    compute_current_provenance_summary,
    run_provenance_watch_cycle,
)
from synapse_runtime.project_model import ProjectModelError
from synapse_runtime.repo_archaeology import RepoArchaeologyError
from synapse_runtime.repo_onboarding import (
    RepoOnboardingError,
    current_onboarding_session,
    mark_adopted_existing_repo,
    onboard_repo,
    onboarding_abandon,
    onboarding_confirm,
    register_onboarding_continuity_capture,
    onboarding_respond,
    onboarding_status_payload,
    onboarding_update,
    publish_publication_candidate,
)
from synapse_runtime.quest_candidates import (
    list_proposals,
    mark_proposal_state,
    upsert_operational_proposal_from_promotion,
    upsert_quest_candidate_from_promotion,
)
from synapse_runtime.reducer import ReducerError, reduce_after_event, reducer_mode
from synapse_runtime.rehydration_pack import refresh_rehydration_pack
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.run_lifecycle import load_active_run_record, run_finalize, run_start, run_update
from synapse_runtime.repo_state import (
    acknowledge_head,
    drift_commands,
    drift_status,
    enforce_execution_gate,
    inspect_engaged_kernel_posture,
    load_state,
    set_mode,
    state_path,
)
from synapse_runtime.session_modes import (
    SESSION_MODE_POLICY_VERSION,
    SessionMode,
    default_mode_for_command,
    policy_for_run,
    policy_summary,
    session_mode_signal_fields,
    validate_transition,
)
from synapse_runtime.semantic_intake import (
    CaptureSourceRole,
    SemanticIntakeError,
    batch_disclosure_needed,
    batch_uncertainty_present,
    capture_kinds as semantic_capture_kinds,
    normalize_capture_source_role,
    write_capture_batch,
)
from synapse_runtime.sidecar_projection import _sync_sidecar, refresh_provenance_projection, refresh_synthesis_projection
from synapse_runtime.sidecar_store import _read_yaml, ensure_live_scaffold
from synapse_runtime.snapshot_candidates import (
    CONTROL_SYNC_KIND,
    EOD_KIND,
    SNAPSHOT_CANDIDATE_KINDS,
    SnapshotCandidateError,
    refresh_snapshot_candidates,
    snapshot_candidate_summary,
)
from synapse_runtime.snapshot_checkpoint_policy import (
    evaluate_snapshot_checkpoint,
    materialize_snapshot_checkpoint_decision,
)
from synapse_runtime.subject_bootstrap import initialize_subject_state, repo_subject_defaults
from synapse_runtime.subject_bridge import ensure_subject_repo_bridges, install_local_codex_integration
from synapse_runtime.quest_acceptance import QuestAcceptanceError, accept_quest, parse_quest_document
from synapse_runtime.quest_completion import QuestCompletionError, complete_quest
from synapse_runtime.quest_board import (
    draft_quest_from_proposal,
    fill_quest_template as _fill_quest_template_impl,
    load_quest_template as _load_quest_template_impl,
    next_quest_number as _next_quest_number_impl,
    today_toronto as _today_toronto_impl,
    write_quest_document,
)
from synapse_runtime.publication_candidates import (
    PUBLICATION_CANDIDATE_KINDS,
    PublicationCandidateError,
    publication_candidate_summary,
    refresh_publication_candidates,
    resolve_publication_candidate,
)
from synapse_runtime.quest_plans import derive_canonical_dungeon_plan_inputs, persist_execution_plan
from synapse_runtime.subject_resolver import (
    SubjectResolutionError,
    detect_subject_candidates,
    is_placeholder_subject,
    load_active_focus_lock,
    resolve_subject,
    session_focus_lock_path,
    write_focus_lock,
)
from synapse_runtime.truth_compiler import (
    TruthCompilerError,
    TruthCompilerPartialError,
    compile_current_state,
    refresh_truth_status,
)
from synapse_runtime.truth_sources import TruthSourceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse")
    subparsers = parser.add_subparsers(dest="command", required=True)
    session_mode_choices = [mode.value for mode in SessionMode]

    doctor_parser = subparsers.add_parser("doctor", help="Run deterministic governance checks")
    doctor_parser.add_argument(
        "--governance-root",
        help="Path to governance root (relative to SYNAPSE_ROOT or absolute path)",
    )
    doctor_parser.add_argument(
        "--subject",
        help="Explicit subject key override (must match active lock unless switching via focus)",
    )
    doctor_parser.add_argument(
        "--no-subject",
        action="store_true",
        help="Skip subject resolution gates (governance-only checks)",
    )

    gov_map_parser = subparsers.add_parser("governance-map", help="Build machine-readable governance inventory")
    gov_map_parser.add_argument(
        "--governance-root",
        required=True,
        help="Path to governance root (relative to SYNAPSE_ROOT or absolute path)",
    )
    gov_map_parser.add_argument("--output", help="Optional output path (.yaml or .json)")
    gov_map_parser.add_argument("--json", action="store_true", help="Print JSON output")

    engage_parser = subparsers.add_parser("engage", help="Resolve or select subject context for the current session")
    engage_parser.add_argument("--subject", help="Subject key to set directly")
    engage_parser.add_argument("--data-root", help="Override data root path")
    engage_parser.add_argument("--engine-root", help="Override engine root path")
    engage_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    engage_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    engage_parser.add_argument("--shell", action="store_true", help="Print shell assignments")
    engage_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    engage_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    engage_parser.add_argument(
        "--continue-active",
        action="store_true",
        help="Non-interactive only: explicitly continue the active subject lock",
    )
    engage_parser.add_argument(
        "--adopt-current-repo",
        action="store_true",
        help="Set focus lock from current repo roots (ENGINE_ROOT=<git root>, DATA_ROOT=<git-root-parent>/<repo>_Data)",
    )

    attach_existing_repo_parser = subparsers.add_parser(
        "attach-existing-repo",
        help="Adopt the current repo, run onboarding bootstrap, and return continuity readiness truth",
    )
    attach_existing_repo_parser.add_argument("--subject", help="Optional subject override")
    attach_existing_repo_parser.add_argument("--data-root", help="Override data root path")
    attach_existing_repo_parser.add_argument("--engine-root", help="Override engine root path")
    attach_existing_repo_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    attach_existing_repo_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    attach_existing_repo_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    attach_existing_repo_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")

    attach_parser = subparsers.add_parser(
        "attach-or-init",
        help="Attach to existing subject or adopt/init current repo subject automatically",
    )
    attach_parser.add_argument("--subject", help="Subject key to set directly")
    attach_parser.add_argument("--data-root", help="Override data root path")
    attach_parser.add_argument("--engine-root", help="Override engine root path")
    attach_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    attach_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    attach_parser.add_argument("--shell", action="store_true", help="Print shell assignments")
    attach_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    attach_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")

    focus_parser = subparsers.add_parser("focus", help="Select and persist active subject focus lock")
    focus_parser.add_argument("--subject", help="Subject key to set directly (non-interactive)")
    focus_parser.add_argument("--data-root", help="Override data root path")
    focus_parser.add_argument("--engine-root", help="Override engine root path")
    focus_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    focus_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    focus_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")

    res_parser = subparsers.add_parser("resolve-subject", help=argparse.SUPPRESS)
    res_parser.add_argument("--subject", help="Explicit subject key")
    res_parser.add_argument("--data-root", help="Explicit data root")
    res_parser.add_argument("--engine-root", help="Explicit engine root")
    res_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    res_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    res_parser.add_argument("--shell", action="store_true", help="Print shell assignments")
    res_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")

    persona_parser = subparsers.add_parser("persona", help="Resolve optional Synapse-managed persona overlay")
    persona_parser.add_argument("--json", action="store_true", help="Print JSON output")
    persona_parser.add_argument("--shell", action="store_true", help="Print shell assignments")

    mode_parser = subparsers.add_parser("mode", help="Get/set elastic governance mode")
    mode_parser.add_argument("--set", dest="set_mode", choices=["INCUBATION", "PLAN", "EXECUTE"], help="Set active mode")

    drift_parser = subparsers.add_parser("drift", help="Show governance drift status and diff commands")
    drift_parser.add_argument("--json", action="store_true", help="Print JSON output")

    subparsers.add_parser("acknowledge", help="Acknowledge current governance HEAD commit")

    gate_parser = subparsers.add_parser("enforce", help=argparse.SUPPRESS)
    gate_parser.add_argument("--risk", default="R1", help="Risk class (R0/R1/R2/...)")
    gate_parser.add_argument("--tool", default="synapse", help="Tool name for receipt context")
    gate_parser.add_argument("--action", default="operation", help="Action name for receipt context")

    scaffold_parser = subparsers.add_parser(
        "scaffold-subject",
        help="Create incubation + codex scaffolding in active subject data root",
    )
    scaffold_parser.add_argument("--subject", help="Optional subject override")
    scaffold_parser.add_argument("--incubation-only", action="store_true", help="Only scaffold Incubation artifacts")
    scaffold_parser.add_argument("--codex-only", action="store_true", help="Only scaffold Codex artifacts")
    scaffold_parser.add_argument("--force", action="store_true", help="Overwrite existing template files")

    plan_parser = subparsers.add_parser(
        "plan-quests",
        help="Persist an execution-ready plan and draft outcome-based quest files on BOARD",
    )
    plan_parser.add_argument("--item", action="append", default=[], help="Plan item (repeatable)")
    plan_parser.add_argument("--items-file", help="Text file with one plan item per line")
    plan_parser.add_argument("--title", help="Optional plan title override")
    plan_parser.add_argument("--goal", help="Optional scope / objective override")
    plan_parser.add_argument("--coherent-outcome", help="Override the bounded coherent outcome statement")
    plan_parser.add_argument("--closure-statement", help="Override the quest closure statement")
    plan_parser.add_argument("--split-trigger", action="append", default=[], help="Split trigger (repeatable)")
    plan_parser.add_argument("--separate-outcome", action="append", default=[], help="Explicit independently closable outcome (repeatable)")
    plan_parser.add_argument("--dependency", action="append", default=[], help="Dependency (repeatable)")
    plan_parser.add_argument("--out-of-scope", help="Explicit out-of-scope statement")
    plan_parser.add_argument("--verification-plan", help="Concrete verification plan text")
    plan_parser.add_argument("--guild-orders-ref", help="Optional parent guild-orders reference")
    plan_parser.add_argument("--guild-orders-artifact", help="Canonical Guild Orders artifact path for dungeon-derived planning")
    plan_parser.add_argument("--dungeon-ref", help="Optional parent dungeon reference")
    plan_parser.add_argument("--dungeon-id", help="Dungeon ID inside the canonical Guild Orders artifact")
    plan_parser.add_argument(
        "--dungeon-coverage",
        choices=["FULL_DUNGEON", "PARTIAL_DUNGEON", "N/A"],
        default="N/A",
        help="Dungeon coverage for the drafted quest(s)",
    )
    plan_parser.add_argument("--plan-id", help="Append a revision to an existing persisted plan id")
    plan_parser.add_argument("--subject", help="Optional subject override")
    plan_parser.add_argument("--data-root", help="Override data root path")
    plan_parser.add_argument("--engine-root", help="Override engine root path")
    plan_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    plan_parser.add_argument(
        "--quest-prefix",
        choices=["SIDE-QUEST", "QUEST"],
        default="SIDE-QUEST",
        help="Quest ID prefix (default: SIDE-QUEST)",
    )
    plan_parser.add_argument("--priority", choices=["P0", "P1", "P2"], default="P1")
    plan_parser.add_argument("--risk", default="R0", help="Risk class (R0/R1/R2)")
    plan_parser.add_argument(
        "--change-class",
        choices=["TRIVIAL", "FEATURE", "STRUCTURAL"],
        default="STRUCTURAL",
        help="Quest Change Class (default: STRUCTURAL)",
    )
    plan_parser.add_argument(
        "--vision-delta",
        choices=["ALIGNED", "VARIATION", "SHIFT"],
        default="ALIGNED",
        help="Quest Vision Delta (default: ALIGNED)",
    )
    plan_parser.add_argument("--door-impact", default="NONE", help="Door Impact (default: NONE)")
    plan_parser.add_argument(
        "--testing-level",
        default="TL2",
        help="Testing Level value (default: TL2)",
    )
    plan_parser.add_argument("--origin", help="Override Origin field")
    plan_parser.add_argument("--anchor", action="append", default=[], help="Codex anchor (repeatable)")
    plan_parser.add_argument("--constraint", action="append", default=[], help="Codex constraint (repeatable)")
    plan_parser.add_argument("--dry-run", action="store_true", help="Show planned quests without writing files")
    plan_parser.add_argument("--json", action="store_true", help="Print JSON output")

    plan_sidequests_parser = subparsers.add_parser(
        "plan-sidequests",
        help="Compatibility alias for plan-quests",
    )
    for action in plan_parser._actions[1:]:
        if not action.option_strings:
            continue
        plan_sidequests_parser._add_action(action)

    live_parser = subparsers.add_parser("live-bootstrap", help="Scaffold live subject-memory sidecar")
    live_parser.add_argument("--subject", help="Optional subject override")
    live_parser.add_argument("--data-root", help="Override data root path")
    live_parser.add_argument("--engine-root", help="Override engine root path")
    live_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    live_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    live_parser.add_argument("--json", action="store_true", help="Print JSON output")

    run_start_parser = subparsers.add_parser("run-start", help="Start or replace the active run record")
    run_start_parser.add_argument("--title", required=True, help="Short run title/summary")
    run_start_parser.add_argument("--goal", help="Optional mission or goal")
    run_start_parser.add_argument("--plan-item", action="append", default=[], help="Plan item (repeatable)")
    run_start_parser.add_argument("--items-file", help="Text file with one plan item per line")
    run_start_parser.add_argument("--subject", help="Optional subject override")
    run_start_parser.add_argument("--data-root", help="Override data root path")
    run_start_parser.add_argument("--engine-root", help="Override engine root path")
    run_start_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    run_start_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    run_start_parser.add_argument("--session-mode", choices=session_mode_choices, help="Explicit session posture for the new run")
    run_start_parser.add_argument("--json", action="store_true", help="Print JSON output")

    session_start_parser = subparsers.add_parser("session-start", help="Auto-attach/init subject and start an ambient session run")
    session_start_parser.add_argument("--title", help="Short run title/summary")
    session_start_parser.add_argument("--goal", help="Optional mission or goal")
    session_start_parser.add_argument("--plan-item", action="append", default=[], help="Plan item (repeatable)")
    session_start_parser.add_argument("--items-file", help="Text file with one plan item per line")
    session_start_parser.add_argument("--subject", help="Optional subject override")
    session_start_parser.add_argument("--data-root", help="Override data root path")
    session_start_parser.add_argument("--engine-root", help="Override engine root path")
    session_start_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    session_start_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    session_start_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    session_start_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    session_start_parser.add_argument("--session-mode", choices=session_mode_choices, help="Explicit session posture for a newly created session run")
    session_start_parser.add_argument("--json", action="store_true", help="Print JSON output")

    run_update_parser = subparsers.add_parser("run-update", help="Update the active run record")
    run_update_parser.add_argument("--add-item", action="append", default=[], help="Plan item to add (repeatable)")
    run_update_parser.add_argument("--items-file", help="Text file with one plan item per line")
    run_update_parser.add_argument(
        "--set-item-status",
        action="append",
        default=[],
        help="Update item status (ITEM-###:STATUS)",
    )
    run_update_parser.add_argument(
        "--command",
        dest="commands",
        action="append",
        default=[],
        help="Command executed (repeatable)",
    )
    run_update_parser.add_argument("--file", action="append", default=[], help="File touched (repeatable)")
    run_update_parser.add_argument("--note", action="append", default=[], help="Note or observation (repeatable)")
    run_update_parser.add_argument(
        "--verification",
        action="append",
        default=[],
        help="Verification result or check (repeatable)",
    )
    run_update_parser.add_argument(
        "--related-sidequest",
        action="append",
        default=[],
        help="Related SIDE-QUEST id (repeatable)",
    )
    run_update_parser.add_argument(
        "--related-quest",
        action="append",
        default=[],
        help="Related QUEST id (repeatable)",
    )
    run_update_parser.add_argument("--status", help="Update overall run status")
    run_update_parser.add_argument("--summary", help="Short summary of the update")
    run_update_parser.add_argument("--subject", help="Optional subject override")
    run_update_parser.add_argument("--data-root", help="Override data root path")
    run_update_parser.add_argument("--engine-root", help="Override engine root path")
    run_update_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    run_update_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    run_update_parser.add_argument("--json", action="store_true", help="Print JSON output")

    session_tick_parser = subparsers.add_parser("session-tick", help="Capture ambient session activity and refresh the sidecar")
    session_tick_parser.add_argument("--title", help="Session title if a run must be created")
    session_tick_parser.add_argument("--goal", help="Session goal if a run must be created")
    session_tick_parser.add_argument("--plan-item", action="append", default=[], help="Plan item (repeatable)")
    session_tick_parser.add_argument("--items-file", help="Text file with one plan item per line")
    session_tick_parser.add_argument("--command", dest="commands", action="append", default=[], help="Command executed (repeatable)")
    session_tick_parser.add_argument("--file", action="append", default=[], help="File touched (repeatable)")
    session_tick_parser.add_argument("--note", action="append", default=[], help="Note or observation (repeatable)")
    session_tick_parser.add_argument("--discovery", action="append", default=[], help="Discovery entry (repeatable)")
    session_tick_parser.add_argument("--verification", action="append", default=[], help="Verification result or check (repeatable)")
    session_tick_parser.add_argument("--related-sidequest", action="append", default=[], help="Related SIDE-QUEST id (repeatable)")
    session_tick_parser.add_argument("--related-quest", action="append", default=[], help="Related QUEST id (repeatable)")
    session_tick_parser.add_argument("--status", help="Update overall run status")
    session_tick_parser.add_argument("--summary", help="Short summary of the tick")
    session_tick_parser.add_argument("--decision-title", help="Optional binding decision title to log during the tick")
    session_tick_parser.add_argument("--decision-summary", help="Optional binding decision summary to log during the tick")
    session_tick_parser.add_argument("--decision-why", help="Optional rationale for the binding decision")
    session_tick_parser.add_argument("--capture-git", action="store_true", help="Capture current git status file list into the tick")
    session_tick_parser.add_argument("--subject", help="Optional subject override")
    session_tick_parser.add_argument("--data-root", help="Override data root path")
    session_tick_parser.add_argument("--engine-root", help="Override engine root path")
    session_tick_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    session_tick_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    session_tick_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    session_tick_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    session_tick_parser.add_argument("--session-mode", choices=session_mode_choices, help="Validate or set posture only when creating a new run")
    session_tick_parser.add_argument("--json", action="store_true", help="Print JSON output")

    capture_chunk_parser = subparsers.add_parser("capture-chunk", help="Record one raw semantic capture batch against the active run")
    capture_chunk_text = capture_chunk_parser.add_mutually_exclusive_group(required=True)
    capture_chunk_text.add_argument("--text", help="Raw text chunk to capture")
    capture_chunk_text.add_argument("--text-file", help="Path to raw text file (cwd-relative unless absolute)")
    capture_chunk_payload = capture_chunk_parser.add_mutually_exclusive_group(required=True)
    capture_chunk_payload.add_argument("--captures-json", help="Structured capture payload as JSON")
    capture_chunk_payload.add_argument("--captures-file", help="Path to structured capture payload file (cwd-relative unless absolute)")
    capture_chunk_parser.add_argument("--title", help="Optional batch title override")
    capture_chunk_parser.add_argument(
        "--source-role",
        choices=[role.value for role in CaptureSourceRole],
        default="user",
        help="Who produced the capture batch (default: user)",
    )
    capture_chunk_parser.add_argument("--subject", help="Optional subject override")
    capture_chunk_parser.add_argument("--data-root", help="Override data root path")
    capture_chunk_parser.add_argument("--engine-root", help="Override engine root path")
    capture_chunk_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    capture_chunk_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    capture_chunk_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboard_repo_parser = subparsers.add_parser("onboard-repo", help="Run deterministic repo archaeology and bootstrap or resume onboarding")
    onboard_repo_parser.add_argument("--subject", help="Optional subject override")
    onboard_repo_parser.add_argument("--data-root", help="Override data root path")
    onboard_repo_parser.add_argument("--engine-root", help="Override engine root path")
    onboard_repo_parser.add_argument("--depth", choices=["quick", "deep"], default="deep", help="Archaeology depth (default: deep)")
    onboard_repo_parser.add_argument("--allow-switch", action="store_true", help="Allow explicit posture transition to onboarding_existing_repo")
    onboard_repo_parser.add_argument("--rescan", action="store_true", help="Append a new scan to the current onboarding session")
    onboard_repo_parser.add_argument("--restart", action="store_true", help="Abandon current onboarding session and start a new one")
    onboard_repo_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboarding_status_parser = subparsers.add_parser("onboarding-status", help="Inspect the current or latest confirmed onboarding session")
    onboarding_status_parser.add_argument("--subject", help="Optional subject override")
    onboarding_status_parser.add_argument("--data-root", help="Override data root path")
    onboarding_status_parser.add_argument("--engine-root", help="Override engine root path")
    onboarding_status_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboarding_update_parser = subparsers.add_parser("onboarding-update", help="Submit a draft project model and question set")
    onboarding_update_parser.add_argument("--draft-file", help="Path to draft project model YAML/JSON")
    onboarding_update_parser.add_argument("--draft-json", help="Inline draft project model JSON")
    onboarding_update_parser.add_argument("--questions-file", help="Path to question-set YAML/JSON")
    onboarding_update_parser.add_argument("--questions-json", help="Inline question-set JSON")
    onboarding_update_parser.add_argument("--subject", help="Optional subject override")
    onboarding_update_parser.add_argument("--data-root", help="Override data root path")
    onboarding_update_parser.add_argument("--engine-root", help="Override engine root path")
    onboarding_update_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboarding_respond_parser = subparsers.add_parser("onboarding-respond", help="Capture onboarding clarification canonically without proposal emission")
    onboarding_respond_text = onboarding_respond_parser.add_mutually_exclusive_group(required=True)
    onboarding_respond_text.add_argument("--text", help="Inline clarification text")
    onboarding_respond_text.add_argument("--text-file", help="Path to clarification text file")
    onboarding_respond_payload = onboarding_respond_parser.add_mutually_exclusive_group(required=True)
    onboarding_respond_payload.add_argument("--captures-json", help="Inline structured captures JSON")
    onboarding_respond_payload.add_argument("--captures-file", help="Path to structured captures YAML/JSON file")
    onboarding_respond_parser.add_argument("--title", help="Optional response title")
    onboarding_respond_parser.add_argument(
        "--source-role",
        choices=[role.value for role in CaptureSourceRole],
        default="user",
        help="Who produced the response capture batch (default: user)",
    )
    onboarding_respond_question_ids = onboarding_respond_parser.add_mutually_exclusive_group()
    onboarding_respond_question_ids.add_argument("--question-ids-json", help="Inline JSON list of linked onboarding question ids")
    onboarding_respond_question_ids.add_argument("--question-ids-file", help="Path to JSON/YAML list of linked onboarding question ids")
    onboarding_respond_parser.add_argument("--subject", help="Optional subject override")
    onboarding_respond_parser.add_argument("--data-root", help="Override data root path")
    onboarding_respond_parser.add_argument("--engine-root", help="Override engine root path")
    onboarding_respond_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboarding_confirm_parser = subparsers.add_parser("onboarding-confirm", help="Confirm and publish the current onboarding session")
    onboarding_confirm_parser.add_argument("--yes-i-confirm", action="store_true", help="Required explicit confirmation flag")
    onboarding_confirm_parser.add_argument("--subject", help="Optional subject override")
    onboarding_confirm_parser.add_argument("--data-root", help="Override data root path")
    onboarding_confirm_parser.add_argument("--engine-root", help="Override engine root path")
    onboarding_confirm_parser.add_argument("--json", action="store_true", help="Print JSON output")

    onboarding_abandon_parser = subparsers.add_parser("onboarding-abandon", help="Abandon the current onboarding session explicitly")
    onboarding_abandon_parser.add_argument("--reason", help="Reason for abandoning the current onboarding session")
    onboarding_abandon_parser.add_argument("--subject", help="Optional subject override")
    onboarding_abandon_parser.add_argument("--data-root", help="Override data root path")
    onboarding_abandon_parser.add_argument("--engine-root", help="Override engine root path")
    onboarding_abandon_parser.add_argument("--json", action="store_true", help="Print JSON output")

    session_mode_parser = subparsers.add_parser("session-mode", help="Inspect or explicitly transition the active session posture")
    session_mode_parser.add_argument("--set", dest="target_session_mode", choices=session_mode_choices, help="Target session posture")
    session_mode_parser.add_argument("--reason", help="Reason for the posture transition")
    session_mode_parser.add_argument("--subject", help="Optional subject override")
    session_mode_parser.add_argument("--data-root", help="Override data root path")
    session_mode_parser.add_argument("--engine-root", help="Override engine root path")
    session_mode_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    session_mode_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    session_mode_parser.add_argument("--json", action="store_true", help="Print JSON output")

    run_finalize_parser = subparsers.add_parser("run-finalize", help="Archive and close the active run record")
    run_finalize_parser.add_argument("--status", default="completed", help="Final run status (default: completed)")
    run_finalize_parser.add_argument("--summary", help="Final summary or outcome")
    run_finalize_parser.add_argument("--subject", help="Optional subject override")
    run_finalize_parser.add_argument("--data-root", help="Override data root path")
    run_finalize_parser.add_argument("--engine-root", help="Override engine root path")
    run_finalize_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    run_finalize_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    run_finalize_parser.add_argument("--json", action="store_true", help="Print JSON output")

    decision_parser = subparsers.add_parser("log-decision", help="Log a project decision (live memory)")
    decision_parser.add_argument("--title", required=True, help="Decision title")
    decision_parser.add_argument("--summary", required=True, help="Decision summary")
    decision_parser.add_argument("--why", help="Rationale or why")
    decision_parser.add_argument("--constraint", action="append", default=[], help="Constraint (repeatable)")
    decision_parser.add_argument("--tradeoff", action="append", default=[], help="Tradeoff (repeatable)")
    decision_parser.add_argument("--related-run", action="append", default=[], help="Related run id (repeatable)")
    decision_parser.add_argument("--related-quest", action="append", default=[], help="Related quest id (repeatable)")
    decision_parser.add_argument("--subject", help="Optional subject override")
    decision_parser.add_argument("--data-root", help="Override data root path")
    decision_parser.add_argument("--engine-root", help="Override engine root path")
    decision_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    decision_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    decision_parser.add_argument("--json", action="store_true", help="Print JSON output")

    disclosure_parser = subparsers.add_parser("log-disclosure", help="Log a Disclosure Gate event (live memory)")
    disclosure_parser.add_argument("--trigger", required=True, help="What caused Disclosure Gate to trigger")
    disclosure_parser.add_argument("--expected", required=True, help="What was expected to be true")
    disclosure_parser.add_argument("--provable", required=True, help="What is actually provable now")
    disclosure_parser.add_argument("--status-label", action="append", default=[], help="Truth Gate status label (repeatable)")
    disclosure_parser.add_argument("--impact", required=True, help="What cannot safely proceed and why")
    disclosure_parser.add_argument("--safe-option", action="append", default=[], help="Legal next action under current state (repeatable)")
    disclosure_parser.add_argument("--decision-needed", required=True, help="Minimal Brains decision required to continue")
    disclosure_parser.add_argument("--related-run", action="append", default=[], help="Related run id (repeatable)")
    disclosure_parser.add_argument("--related-quest", action="append", default=[], help="Related quest id (repeatable)")
    disclosure_parser.add_argument("--subject", help="Optional subject override")
    disclosure_parser.add_argument("--data-root", help="Override data root path")
    disclosure_parser.add_argument("--engine-root", help="Override engine root path")
    disclosure_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    disclosure_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    disclosure_parser.add_argument("--json", action="store_true", help="Print JSON output")

    rehydrate_parser = subparsers.add_parser("render-rehydrate", help="Render concise REHYDRATE.md")
    rehydrate_parser.add_argument("--subject", help="Optional subject override")
    rehydrate_parser.add_argument("--data-root", help="Override data root path")
    rehydrate_parser.add_argument("--engine-root", help="Override engine root path")
    rehydrate_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    rehydrate_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    rehydrate_parser.add_argument("--json", action="store_true", help="Print JSON output")

    continuity_parser = subparsers.add_parser("refresh-continuity", help="Seal current sidecar truth into the active rehydration pack")
    continuity_parser.add_argument("--subject", help="Optional subject override")
    continuity_parser.add_argument("--data-root", help="Override data root path")
    continuity_parser.add_argument("--engine-root", help="Override engine root path")
    continuity_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    continuity_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    continuity_parser.add_argument("--json", action="store_true", help="Print JSON output")

    compile_truth_parser = subparsers.add_parser("compile-current-state", help="Compile deterministic current-state truth from runtime evidence")
    compile_truth_parser.add_argument("--subject", help="Optional subject override")
    compile_truth_parser.add_argument("--data-root", help="Override data root path")
    compile_truth_parser.add_argument("--engine-root", help="Override engine root path")
    compile_truth_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    compile_truth_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    compile_truth_parser.add_argument("--json", action="store_true", help="Print JSON output")

    accept_parser = subparsers.add_parser(
        "accept-quest",
        help="Validate a BOARD quest and move it into ACCEPTED governed execution readiness",
    )
    accept_parser.add_argument("quest", help="Quest ID or path to a BOARD quest file")
    accept_parser.add_argument("--subject", help="Optional subject override")
    accept_parser.add_argument("--data-root", help="Override data root path")
    accept_parser.add_argument("--engine-root", help="Override engine root path")
    accept_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    accept_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    accept_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    accept_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    accept_parser.add_argument("--json", action="store_true", help="Print JSON output")

    complete_parser = subparsers.add_parser(
        "complete-quest",
        help="Record a completion audit attempt and only complete the quest on a clean PASS",
    )
    complete_parser.add_argument("quest", help="Quest ID or path to an ACCEPTED/COMPLETED quest file")
    complete_parser.add_argument("--milestone-status", action="append", default=[], help="Milestone status entry KEY:STATUS[:DETAIL]")
    complete_parser.add_argument("--check", action="append", default=[], help="Check result entry KEY:PASS|FAIL|BLOCKED[:DETAIL]")
    complete_parser.add_argument("--command-run", dest="command_runs", action="append", default=[], help="Command actually run (repeatable)")
    complete_parser.add_argument("--changed-file", action="append", default=[], help="Changed file or artifact path (repeatable)")
    complete_parser.add_argument("--receipt-ref", action="append", default=[], help="Receipt reference path or note (repeatable)")
    complete_parser.add_argument("--skipped-item", action="append", default=[], help="Skipped in-scope item (repeatable)")
    complete_parser.add_argument("--unresolved-gap", action="append", default=[], help="Unresolved gap in quest scope (repeatable)")
    complete_parser.add_argument("--known-bug", action="append", default=[], help="Known bug/regression still in quest scope (repeatable)")
    complete_parser.add_argument("--blocker", action="append", default=[], help="Blocker preventing clean closure (repeatable)")
    complete_parser.add_argument("--disclosure", action="append", default=[], help="Disclosure event note (repeatable)")
    complete_parser.add_argument("--note", action="append", default=[], help="Freeform completion audit note (repeatable)")
    complete_parser.add_argument("--subject", help="Optional subject override")
    complete_parser.add_argument("--data-root", help="Override data root path")
    complete_parser.add_argument("--engine-root", help="Override engine root path")
    complete_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    complete_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    complete_parser.add_argument("--json", action="store_true", help="Print JSON output")

    formalize_parser = subparsers.add_parser("formalize", help="Formalize ambient proposals into canonical artifacts")
    formalize_parser.add_argument("--proposal-id", help="Proposal id to formalize")
    formalize_parser.add_argument(
        "--candidate-handle",
        help="Publication candidate handle to publish canonically (story, vision, codex, or a candidate revision/family id)",
    )
    formalize_parser.add_argument(
        "--kind",
        choices=[kind.value for kind in ProposalKind],
        help="Optional proposal kind filter",
    )
    formalize_parser.add_argument(
        "--state",
        choices=[state.value for state in ProposalState],
        help="Optional proposal state filter when listing",
    )
    formalize_parser.add_argument("--list", action="store_true", help="List proposals instead of formalizing one")
    formalize_parser.add_argument("--dry-run", action="store_true", help="Preview formalization without mutating canon")
    formalize_parser.add_argument("--topic", help="Optional topic override for snapshot or guild-order formalization")
    formalize_parser.add_argument("--subject", help="Optional subject override")
    formalize_parser.add_argument("--data-root", help="Override data root path")
    formalize_parser.add_argument("--engine-root", help="Override engine root path")
    formalize_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    formalize_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    formalize_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    formalize_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    formalize_parser.add_argument("--json", action="store_true", help="Print JSON output")

    watch_parser = subparsers.add_parser("watch", help="Poll local state and continuously update the ambient sidecar")
    watch_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds (default: 2.0)")
    watch_parser.add_argument("--iterations", type=int, default=1, help="Number of polls to run (default: 1)")
    watch_parser.add_argument("--capture-git", action="store_true", help="Capture git working-tree changes on each poll")
    watch_parser.add_argument("--title", help="Session title if a run must be created")
    watch_parser.add_argument("--goal", help="Session goal if a run must be created")
    watch_parser.add_argument("--subject", help="Optional subject override")
    watch_parser.add_argument("--data-root", help="Override data root path")
    watch_parser.add_argument("--engine-root", help="Override engine root path")
    watch_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    watch_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    watch_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    watch_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    watch_parser.add_argument("--no-provenance", action="store_true", help="Disable Phase 5 provenance observation during watch")
    watch_parser.add_argument("--json", action="store_true", help="Print JSON output")

    provenance_parser = subparsers.add_parser("provenance-status", help="Inspect current provenance and trust posture")
    provenance_parser.add_argument("--strict", action="store_true", help="Exit 2 when current provenance status is blocked")
    provenance_parser.add_argument("--subject", help="Optional subject override")
    provenance_parser.add_argument("--data-root", help="Override data root path")
    provenance_parser.add_argument("--engine-root", help="Override engine root path")
    provenance_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    provenance_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    provenance_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    provenance_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    provenance_parser.add_argument("--json", action="store_true", help="Print JSON output")

    install_hooks_parser = subparsers.add_parser("install-hooks", help="Install managed Synapse git hooks into the engine repo")
    install_hooks_parser.add_argument("--force", action="store_true", help="Back up and replace unmanaged existing hooks")
    install_hooks_parser.add_argument("--subject", help="Optional subject override")
    install_hooks_parser.add_argument("--data-root", help="Override data root path")
    install_hooks_parser.add_argument("--engine-root", help="Override engine root path")
    install_hooks_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    install_hooks_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    install_hooks_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    install_hooks_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    install_hooks_parser.add_argument("--json", action="store_true", help="Print JSON output")

    verify_hooks_parser = subparsers.add_parser("verify-hooks", help="Inspect managed Synapse git hooks in the engine repo")
    verify_hooks_parser.add_argument("--subject", help="Optional subject override")
    verify_hooks_parser.add_argument("--data-root", help="Override data root path")
    verify_hooks_parser.add_argument("--engine-root", help="Override engine root path")
    verify_hooks_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    verify_hooks_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    verify_hooks_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    verify_hooks_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    verify_hooks_parser.add_argument("--json", action="store_true", help="Print JSON output")

    raw_turn_parser = subparsers.add_parser(
        "record-raw-turn",
        help="Append one raw user/executor conversation turn into the Phase 0 raw evidence store",
    )
    raw_turn_parser.add_argument("--role", choices=["user", "executor"], required=True, help="Raw turn role")
    raw_turn_parser.add_argument("--text", help="Literal turn text")
    raw_turn_parser.add_argument("--text-file", help="Path to a text file containing the turn body")
    raw_turn_parser.add_argument("--stdin", action="store_true", help="Read the turn body from stdin")
    raw_turn_parser.add_argument("--source-surface", default="cli", help="Source surface label (default: cli)")
    raw_turn_parser.add_argument("--run-id", help="Optional run id")
    raw_turn_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    raw_turn_parser.add_argument("--metadata-json", help="Optional JSON metadata object")
    raw_turn_parser.add_argument("--subject", help="Optional subject override")
    raw_turn_parser.add_argument("--data-root", help="Override data root path")
    raw_turn_parser.add_argument("--engine-root", help="Override engine root path")
    raw_turn_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    raw_turn_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    raw_turn_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    raw_turn_parser.add_argument("--json", action="store_true", help="Print JSON output")

    raw_execution_parser = subparsers.add_parser(
        "record-raw-execution",
        help="Append one raw execution/tool/import receipt into the Phase 0 raw evidence store",
    )
    raw_execution_parser.add_argument("--family", choices=["execution", "tool", "import"], required=True, help="Raw execution family")
    raw_execution_parser.add_argument("--source-surface", default="cli", help="Source surface label (default: cli)")
    raw_execution_parser.add_argument("--phase", help="Optional phase label")
    raw_execution_parser.add_argument("--command-text", help="Optional command summary")
    raw_execution_parser.add_argument("--tool-name", help="Optional tool name")
    raw_execution_parser.add_argument("--status", help="Optional status label")
    raw_execution_parser.add_argument("--changed-file", action="append", default=[], help="Changed file (repeatable)")
    raw_execution_parser.add_argument("--payload", help="Literal payload string")
    raw_execution_parser.add_argument("--payload-json", help="Inline JSON payload")
    raw_execution_parser.add_argument("--payload-file", help="Path to payload file (.json parses as JSON)")
    raw_execution_parser.add_argument("--metadata-json", help="Optional JSON metadata object")
    raw_execution_parser.add_argument("--run-id", help="Optional run id")
    raw_execution_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    raw_execution_parser.add_argument("--subject", help="Optional subject override")
    raw_execution_parser.add_argument("--data-root", help="Override data root path")
    raw_execution_parser.add_argument("--engine-root", help="Override engine root path")
    raw_execution_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    raw_execution_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    raw_execution_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    raw_execution_parser.add_argument("--json", action="store_true", help="Print JSON output")

    close_turn_parser = subparsers.add_parser(
        "close-turn",
        help="Validate close-turn continuity and surface blocker obligations at an honest boundary",
    )
    close_turn_parser.add_argument("--boundary", default="close_turn", help="Boundary label for the validation receipt")
    close_turn_parser.add_argument("--strict", action="store_true", help="Exit 2 when the close-turn boundary is blocked")
    close_turn_parser.add_argument("--subject", help="Optional subject override")
    close_turn_parser.add_argument("--data-root", help="Override data root path")
    close_turn_parser.add_argument("--engine-root", help="Override engine root path")
    close_turn_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    close_turn_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    close_turn_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    close_turn_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    close_turn_parser.add_argument("--json", action="store_true", help="Print JSON output")

    import_continuity_parser = subparsers.add_parser(
        "import-continuity",
        help="Parse a transcript/note/PDF into a noncanonical imported-continuity envelope and record it as raw import evidence",
    )
    import_continuity_parser.add_argument("--source-file", required=True, help="Path to the transcript, note, or PDF source")
    import_continuity_parser.add_argument("--kind", choices=["auto", "transcript", "note", "pdf"], default="auto", help="Imported continuity source kind")
    import_continuity_parser.add_argument("--source-surface", default="cli_import", help="Source surface label (default: cli_import)")
    import_continuity_parser.add_argument("--run-id", help="Optional run id")
    import_continuity_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    import_continuity_parser.add_argument("--subject", help="Optional subject override")
    import_continuity_parser.add_argument("--data-root", help="Override data root path")
    import_continuity_parser.add_argument("--engine-root", help="Override engine root path")
    import_continuity_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    import_continuity_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    import_continuity_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    import_continuity_parser.add_argument("--json", action="store_true", help="Print JSON output")

    local_integration_parser = subparsers.add_parser(
        "install-local-integration",
        help="Install or refresh optional local .codex integration assets for the resolved subject repo",
    )
    local_integration_parser.add_argument("--subject", help="Optional subject override")
    local_integration_parser.add_argument("--data-root", help="Override data root path")
    local_integration_parser.add_argument("--engine-root", help="Override engine root path")
    local_integration_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    local_integration_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    local_integration_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    local_integration_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    local_integration_parser.add_argument(
        "--observer-backend",
        help="Persist the selected continuity observer backend for this repo-local integration (for example: openai_responses, gemini_generate_content, noop)",
    )
    local_integration_parser.add_argument("--json", action="store_true", help="Print JSON output")

    draftshot_parser = subparsers.add_parser(
        "refresh-draftshot",
        help="Create or revise the active noncanonical Draftshot for the current session when continuity sources changed",
    )
    draftshot_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    draftshot_parser.add_argument("--subject", help="Optional subject override")
    draftshot_parser.add_argument("--data-root", help="Override data root path")
    draftshot_parser.add_argument("--engine-root", help="Override engine root path")
    draftshot_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    draftshot_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    draftshot_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    draftshot_parser.add_argument("--json", action="store_true", help="Print JSON output")

    snapshot_candidates_parser = subparsers.add_parser(
        "refresh-snapshot-candidates",
        help="Create or revise typed noncanonical EOD and Control Sync snapshot candidates when continuity sources changed",
    )
    snapshot_candidates_parser.add_argument("--session-id", help="Session-scoped lock id (or use SYNAPSE_SESSION_ID)")
    snapshot_candidates_parser.add_argument("--subject", help="Optional subject override")
    snapshot_candidates_parser.add_argument("--data-root", help="Override data root path")
    snapshot_candidates_parser.add_argument("--engine-root", help="Override engine root path")
    snapshot_candidates_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    snapshot_candidates_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    snapshot_candidates_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    snapshot_candidates_parser.add_argument("--json", action="store_true", help="Print JSON output")

    publication_candidates_parser = subparsers.add_parser(
        "refresh-publication-candidates",
        help="Create or revise noncanonical story, vision, and codex publication candidates when continuity sources changed",
    )
    publication_candidates_parser.add_argument("--subject", help="Optional subject override")
    publication_candidates_parser.add_argument("--data-root", help="Override data root path")
    publication_candidates_parser.add_argument("--engine-root", help="Override engine root path")
    publication_candidates_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    publication_candidates_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    publication_candidates_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")
    publication_candidates_parser.add_argument("--json", action="store_true", help="Print JSON output")

    return parser


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _print_subject_receipt(receipt: dict[str, Any]) -> None:
    print("=== RESOLVED SUBJECT RECEIPT ===")
    print(f"subject: {receipt.get('subject')}")
    print(f"data_root: {receipt.get('data_root')}")
    print(f"engine_root: {receipt.get('engine_root')}")
    print(f"selected_at: {receipt.get('selected_at')}")
    print(f"selected_by: {receipt.get('selected_by')}")
    print(f"selection_method: {receipt.get('selection_method')}")
    print(f"source_detail: {receipt.get('source_detail')}")
    if receipt.get("session_id"):
        print(f"session_id: {receipt.get('session_id')}")


def _print_mode_receipt(mode: str) -> None:
    print("=== MODE RECEIPT ===")
    print(f"mode: {mode}")
    print(f"state_path: {state_path().resolve()}")


def _subject_receipt_to_shell(receipt: dict[str, Any]) -> None:
    print(f"SUBJECT={receipt['subject']}")
    print(f"DATA_ROOT={receipt['data_root']}")
    print(f"ENGINE_ROOT={receipt['engine_root']}")
    print(f"SELECTION_METHOD={receipt['selection_method']}")
    print(f"SOURCE_DETAIL={receipt['source_detail']}")
    if receipt.get("session_id"):
        print(f"SESSION_ID={receipt['session_id']}")


def _resolve_subject_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    try:
        return resolve_subject(
            subject_flag=getattr(args, "subject", None),
            data_root_flag=getattr(args, "data_root", None),
            engine_root_flag=getattr(args, "engine_root", None),
            allow_switch=getattr(args, "allow_switch", False),
            session_id=getattr(args, "session_id", None),
        )
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        print("Hint: run `python3 runtime/synapse.py engage` first.")
        return None


def _emit_subject_output(receipt: dict[str, Any], *, json_mode: bool, shell_mode: bool) -> None:
    if shell_mode:
        _subject_receipt_to_shell(receipt)
        return
    if json_mode:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    _print_subject_receipt(receipt)


def _resolved_session_id(args: argparse.Namespace) -> str | None:
    raw = str(getattr(args, "session_id", None) or os.environ.get("SYNAPSE_SESSION_ID") or "").strip()
    return raw or None


def _normalize_session_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _generated_session_id() -> str:
    return f"syn-{uuid.uuid4().hex[:16]}"


def _ensure_generated_session_id(args: argparse.Namespace) -> str:
    session_id = _resolved_session_id(args)
    if session_id:
        args.session_id = session_id
        return session_id
    session_id = _generated_session_id()
    args.session_id = session_id
    return session_id


def _repair_active_run_session_id(
    *,
    data_root: Path,
    active_run: dict[str, Any],
    session_id: str | None,
) -> dict[str, Any]:
    repaired_session_id = _normalize_session_id(session_id)
    if not active_run.get("run_id") or _normalize_session_id(active_run.get("session_id")) or not repaired_session_id:
        return active_run

    repaired_run = dict(active_run)
    repaired_run["session_id"] = repaired_session_id
    run_path = data_root / ".synapse" / "ACTIVE_RUN.yaml"
    run_path.write_text(yaml.safe_dump(repaired_run, sort_keys=False), encoding="utf-8")
    return repaired_run


def _load_active_run_with_session_repair(ctx: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = load_active_run_record(subject=ctx["subject"], data_root=data_root)
    return _repair_active_run_session_id(
        data_root=data_root,
        active_run=active_run,
        session_id=ctx.get("session_id"),
    )


def _effective_session_id(
    ctx: dict[str, Any],
    *,
    active_run: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str | None:
    return (
        _normalize_session_id(session_id)
        or _normalize_session_id(ctx.get("session_id"))
        or _normalize_session_id((active_run or {}).get("session_id"))
    )


def _session_run_overlay_path(session_id: str) -> Path:
    return session_focus_lock_path(session_id, Path.home().resolve()).parent / "ACTIVE_RUN.json"


def _write_session_run_overlay(session_id: str, payload: dict[str, Any]) -> str:
    path = _session_run_overlay_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path.resolve())


def _clear_session_run_overlay(session_id: str) -> str:
    path = _session_run_overlay_path(session_id)
    if path.exists():
        path.unlink()
    return str(path.resolve())


def _render_and_refresh_continuity(subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    try:
        rehydrate = render_rehydrate(subject=subject, data_root=data_root)
        refresh_provenance_projection(subject=subject, data_root=data_root, engine_root=engine_root)
        continuity = refresh_rehydration_pack(subject=subject, data_root=data_root, engine_root=engine_root)
        return {"rehydrate": rehydrate, "continuity": continuity}
    except Exception as exc:
        raise LiveMemoryError(str(exc)) from exc


def _readiness_payload(data_root: Path) -> dict[str, Any]:
    summary = automation_summary(data_root)
    return {
        "onboarding_required": bool(summary.get("onboarding_required")),
        "onboarding_requirement_reason": summary.get("onboarding_requirement_reason"),
        "onboarding_confirmed": bool(summary.get("onboarding_confirmed")),
        "project_identity_ready": bool(summary.get("project_identity_ready")),
        "continuity_ready": bool(summary.get("continuity_ready")),
        "automation_status": summary.get("automation_status"),
        "automation_pending_gate": summary.get("automation_pending_gate"),
        "active_onboarding_id": summary.get("active_onboarding_id"),
        "latest_confirmed_onboarding_id": summary.get("latest_confirmed_onboarding_id"),
        "published_project_model_path": summary.get("published_project_model_path"),
        "published_project_story_path": summary.get("published_project_story_path"),
        "published_vision_path": summary.get("published_vision_path"),
        "missing_publication_fields": list(summary.get("missing_publication_fields") or []),
        "automation_last_activity_at": summary.get("automation_last_activity_at"),
        "automation_last_continuity_update_at": summary.get("automation_last_continuity_update_at"),
        "automation_recent_actions": list(summary.get("automation_recent_actions") or []),
    }


def _kernel_posture_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    return inspect_engaged_kernel_posture(
        repo_root=Path(str(ctx["engine_root"])),
        data_root=Path(str(ctx["data_root"])),
        synapse_root=resolve_synapse_root(),
    )


def _load_json_text(raw: str | None, *, label: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveMemoryError(f"{label} must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LiveMemoryError(f"{label} must decode to a JSON object.")
    return payload


def _read_text_input(
    *,
    literal: str | None = None,
    file_path: str | None = None,
    read_stdin: bool = False,
    label: str,
) -> str:
    sources = [bool(str(literal or "").strip()), bool(str(file_path or "").strip()), bool(read_stdin)]
    if sum(1 for item in sources if item) > 1:
        raise LiveMemoryError(f"Provide only one of --text, --text-file, or --stdin for {label}.")
    if str(literal or "").strip():
        return str(literal)
    if str(file_path or "").strip():
        path = Path(str(file_path)).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise LiveMemoryError(f"{label} file does not exist: {path}")
        return path.read_text(encoding="utf-8")
    if read_stdin:
        return sys.stdin.read()
    if not _stdin_is_interactive():
        return sys.stdin.read()
    raise LiveMemoryError(f"{label} requires --text, --text-file, or piped stdin.")


def _read_payload_input(
    *,
    literal: str | None = None,
    json_text: str | None = None,
    file_path: str | None = None,
    label: str,
) -> Any:
    sources = [
        bool(str(literal or "").strip()),
        bool(str(json_text or "").strip()),
        bool(str(file_path or "").strip()),
    ]
    if sum(1 for item in sources if item) > 1:
        raise LiveMemoryError(f"Provide only one of --payload, --payload-json, or --payload-file for {label}.")
    if str(json_text or "").strip():
        try:
            return json.loads(str(json_text))
        except json.JSONDecodeError as exc:
            raise LiveMemoryError(f"{label} JSON payload is invalid: {exc.msg}") from exc
    if str(file_path or "").strip():
        path = Path(str(file_path)).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise LiveMemoryError(f"{label} file does not exist: {path}")
        if path.suffix.lower() == ".json":
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise LiveMemoryError(f"{label} JSON file is invalid: {exc.msg}") from exc
        return path.read_text(encoding="utf-8")
    if str(literal or "").strip():
        return str(literal)
    return None


def _onboarding_gate_message(*, target_mode: str, gate: dict[str, Any]) -> str:
    missing = ", ".join(gate.get("missing_publication_fields") or []) or (
        "latest_confirmed_onboarding_id, published_project_model_path, "
        "published_project_story_path, published_vision_path"
    )
    return (
        f"Cannot enter session mode '{target_mode}' because this repo was adopted as an existing repo and "
        "has not been confirmed through onboarding yet. "
        "Current project identity/story/vision are not ready. "
        f"Missing continuity readiness fields: {missing}. "
        "Continue with onboarding (onboard-repo, onboarding-update, onboarding-respond, onboarding-confirm) first."
    )


def _assert_ready_state_mode_allowed(ctx: dict[str, Any], target_mode: SessionMode | str | None) -> None:
    gate = ready_state_gate_for_mode(
        data_root=Path(ctx["data_root"]),
        target_mode=target_mode,
    )
    if gate.get("blocked"):
        raise LiveMemoryError(
            _onboarding_gate_message(
                target_mode=str(gate.get("target_mode") or target_mode or "unknown"),
                gate=gate,
            )
        )


def _current_onboarding_session_for_automation(
    *,
    ctx: dict[str, Any],
    data_root: Path,
) -> dict[str, Any] | None:
    try:
        return current_onboarding_session(
            subject=ctx["subject"],
            data_root=data_root,
            require_current=False,
        )
    except Exception:
        return None


def _recent_automation_fingerprints(
    *,
    data_root: Path,
    limit: int = 25,
) -> set[str]:
    try:
        records = load_event_records(data_root)
    except EventLogError:
        return set()
    fingerprints: set[str] = set()
    for payload in reversed(records[-limit:]):
        signals = payload.get("signals")
        if not isinstance(signals, dict):
            continue
        automation_context = signals.get("automation_context")
        if not isinstance(automation_context, dict):
            continue
        fingerprint = str(automation_context.get("automation_fingerprint") or "").strip()
        if fingerprint:
            fingerprints.add(fingerprint)
    return fingerprints


def _execute_automation_side_effects(
    *,
    ctx: dict[str, Any],
    active_run: dict[str, Any],
    activity_source: str,
    activity_kind: str,
    summary: str | None,
    changed_files: list[str] | None = None,
    notes: list[str] | None = None,
    decision_boundary: bool = False,
    uncertainty_present: bool = False,
    explicit_decision_logged: bool = False,
    explicit_disclosure_logged: bool = False,
    explicit_capture_written: bool = False,
    onboarding_response: bool = False,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    session_mode = str(active_run.get("session_mode") or "").strip() or None
    onboarding_session = _current_onboarding_session_for_automation(ctx=ctx, data_root=data_root)
    policy = automation_policy_for_context(data_root=data_root)
    activity = classify_runtime_activity(
        activity_source=activity_source,
        activity_kind=activity_kind,
        session_mode=session_mode,
        onboarding_id=str((onboarding_session or {}).get("onboarding_id") or "").strip() or None,
        run_id=str(active_run.get("run_id") or "").strip() or None,
        session_id=_effective_session_id(ctx, active_run=active_run),
        subject=ctx["subject"],
        changed_files=list(changed_files or []),
        summary=summary,
        notes=list(notes or []),
        decision_boundary=decision_boundary,
        uncertainty_present=uncertainty_present,
        explicit_decision_logged=explicit_decision_logged,
        explicit_disclosure_logged=explicit_disclosure_logged,
        explicit_capture_written=explicit_capture_written,
        onboarding_response=onboarding_response,
    )
    actions = plan_automation_side_effects(
        policy=policy,
        activity=activity,
        recent_capture_fingerprints=_recent_automation_fingerprints(data_root=data_root),
    )
    result: dict[str, Any] = {
        "automation_context": {
            "activity_source": activity.get("activity_source"),
            "activity_kind": activity.get("activity_kind"),
            "session_mode": activity.get("session_mode"),
            "onboarding_id": activity.get("onboarding_id"),
            "run_id": activity.get("run_id"),
            "session_id": activity.get("session_id"),
            "subject": activity.get("subject"),
            "changed_files": list(activity.get("changed_files") or []),
            "summary": activity.get("summary"),
            "decision_boundary": bool(activity.get("decision_boundary")),
            "uncertainty_present": bool(activity.get("uncertainty_present")),
            "meaningful_activity": bool(activity.get("meaningful_activity")),
            "automation_fingerprint": activity.get("automation_fingerprint"),
        },
        "automation_triggered": bool(actions),
        "automation_action_kinds": [],
        "continuity_side_effects": [],
        "written_artifacts": [],
        "capture_batch_id": None,
        "capture_artifact_path": None,
        "capture_ledger_path": None,
        "capture_ids": [],
        "decision_path": None,
        "decisions_ledger_path": None,
        "disclosure_path": None,
        "disclosures_ledger_path": None,
        "error_code": None,
        "error_message": None,
    }

    for action in actions:
        action_kind = str(action.get("action") or "").strip()
        if not action_kind:
            continue
        try:
            if action_kind == AutomationAction.SEMANTIC_CAPTURE.value:
                capture_payload = action.get("capture_payload")
                raw_text = str(action.get("raw_text") or "").strip()
                extra_context = {
                    "capture_context": "automation_activity",
                    "suppress_proposals": True,
                }
                if onboarding_session:
                    extra_context["onboarding_id"] = onboarding_session.get("onboarding_id")
                    extra_context["question_set_id"] = onboarding_session.get("current_question_set_id")
                receipt = write_capture_batch(
                    subject=ctx["subject"],
                    data_root=data_root,
                    engine_root=engine_root,
                    run_data=active_run,
                    raw_text=raw_text or str(summary or activity_kind),
                    payload=capture_payload,
                    source_role=CaptureSourceRole.AGENT,
                    title_override=action.get("capture_payload", {}).get("title"),
                    extra_context=extra_context,
                )
                batch = receipt["batch"]
                batch_id = str(batch.get("capture_batch_id") or "").strip() or None
                if (
                    onboarding_session
                    and session_mode == SessionMode.ONBOARDING_EXISTING_REPO.value
                    and batch_id
                ):
                    onboarding_session = register_onboarding_continuity_capture(
                        data_root=data_root,
                        session=onboarding_session,
                        capture_batch_id=batch_id,
                    )
                capture_ids = [
                    str(item.get("capture_id"))
                    for item in batch.get("captures") or []
                    if str(item.get("capture_id") or "").strip()
                ]
                result["capture_batch_id"] = batch_id
                result["capture_artifact_path"] = receipt["artifact_path"]
                result["capture_ledger_path"] = receipt["ledger_path"]
                result["capture_ids"] = capture_ids
                result["written_artifacts"].extend([receipt["artifact_path"], receipt["ledger_path"]])
                result["continuity_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "capture_batch_id": batch_id,
                        "capture_artifact_path": receipt["artifact_path"],
                        "capture_ledger_path": receipt["ledger_path"],
                    }
                )
            elif action_kind == AutomationAction.DECISION_LOG.value:
                decision_receipt = log_decision(
                    subject=ctx["subject"],
                    data_root=data_root,
                    title=str(action.get("title") or summary or "Automation decision").strip(),
                    summary=str(action.get("summary") or summary or "").strip(),
                    why=str(action.get("why") or "").strip() or None,
                    constraints=[],
                    tradeoffs=[],
                    related_runs=[str(active_run.get("run_id") or "").strip()] if str(active_run.get("run_id") or "").strip() else [],
                    related_quests=[],
                    source_refs=list(action.get("source_refs") or []),
                )
                result["decision_path"] = decision_receipt.get("decision_path")
                result["decisions_ledger_path"] = decision_receipt.get("decisions_ledger_path")
                if decision_receipt.get("decision_path"):
                    result["written_artifacts"].append(decision_receipt["decision_path"])
                result["continuity_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "decision_path": decision_receipt.get("decision_path"),
                        "decisions_ledger_path": decision_receipt.get("decisions_ledger_path"),
                    }
                )
            elif action_kind == AutomationAction.DISCLOSURE_LOG.value:
                disclosure_receipt = log_disclosure(
                    subject=ctx["subject"],
                    data_root=data_root,
                    trigger=str(action.get("trigger") or summary or "Automation surfaced uncertainty.").strip(),
                    expected=str(action.get("expected") or "Continuity should remain truthful.").strip(),
                    provable=str(action.get("provable") or "Automation classification surfaced uncertainty or risk.").strip(),
                    status_labels=list(action.get("status_labels") or []),
                    impact=str(action.get("impact") or summary or "Automation surfaced uncertainty during executor work.").strip(),
                    safe_options=list(action.get("safe_options") or []),
                    decision_needed=str(action.get("decision_needed") or "Clarify the uncertain path before binding canon or governed execution.").strip(),
                    related_runs=[str(active_run.get("run_id") or "").strip()] if str(active_run.get("run_id") or "").strip() else [],
                    related_quests=[],
                    source_refs=list(action.get("source_refs") or []),
                )
                result["disclosure_path"] = disclosure_receipt.get("disclosure_path")
                result["disclosures_ledger_path"] = disclosure_receipt.get("disclosures_ledger_path")
                if disclosure_receipt.get("disclosure_path"):
                    result["written_artifacts"].append(disclosure_receipt["disclosure_path"])
                result["continuity_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "disclosure_path": disclosure_receipt.get("disclosure_path"),
                        "disclosures_ledger_path": disclosure_receipt.get("disclosures_ledger_path"),
                    }
                )
            else:
                result["continuity_side_effects"].append({"action": action_kind, "status": "ok"})
            result["automation_action_kinds"].append(action_kind)
        except Exception as exc:
            result["error_code"] = "AUTOMATION_SIDE_EFFECT_FAILED"
            result["error_message"] = f"{action_kind} failed: {exc}"
            result["continuity_side_effects"].append(
                {
                    "action": action_kind,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            break

    return result


def _apply_automation_event_metadata(
    *,
    signals: dict[str, Any],
    outputs: dict[str, Any],
    truth_flags: dict[str, Any],
    automation: dict[str, Any],
) -> None:
    changed_files = list(signals.get("changed_files") or [])
    for path in automation.get("written_artifacts") or []:
        text = str(path or "").strip()
        if text and text not in changed_files:
            changed_files.append(text)
    signals["changed_files"] = changed_files
    signals["automation_triggered"] = bool(automation.get("automation_triggered"))
    signals["automation_action_kinds"] = list(automation.get("automation_action_kinds") or [])
    signals["automation_context"] = dict(automation.get("automation_context") or {})
    outputs["continuity_side_effects"] = list(automation.get("continuity_side_effects") or [])
    for key in (
        "capture_batch_id",
        "capture_artifact_path",
        "capture_ledger_path",
        "decision_path",
        "decisions_ledger_path",
        "disclosure_path",
        "disclosures_ledger_path",
    ):
        value = automation.get(key)
        if value and not outputs.get(key):
            outputs[key] = value
    truth_flags["uncertainty_present"] = bool(
        truth_flags.get("uncertainty_present") or automation.get("automation_context", {}).get("uncertainty_present")
    )
    if automation.get("disclosure_path"):
        truth_flags["disclosure_open"] = True


def _apply_automation_partial_status(
    *,
    event_info: dict[str, Any],
    automation: dict[str, Any],
) -> dict[str, Any]:
    if not automation.get("error_message"):
        return event_info
    return _apply_follow_on_partial_status(
        event_info=event_info,
        error_code=automation.get("error_code") or "AUTOMATION_SIDE_EFFECT_FAILED",
        error_message=str(automation.get("error_message")),
        recovery_hint=(
            "Primary work was committed and recorded, but an automatic continuity side effect failed. "
            "Inspect the event continuity_side_effects metadata and rerun the relevant continuity command if needed."
        ),
    )


def _extract_observer_source_ids(source_refs: list[dict[str, Any]] | None) -> tuple[list[str], list[str]]:
    segment_ids: list[str] = []
    semantic_event_ids: list[str] = []
    for item in list(source_refs or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        ref_id = str(item.get("id") or item.get("raw_id") or "").strip()
        if not ref_id:
            continue
        if kind in {"conversation_segment", "segment"} and ref_id not in segment_ids:
            segment_ids.append(ref_id)
        elif kind in {"semantic_event", "semantic"} and ref_id not in semantic_event_ids:
            semantic_event_ids.append(ref_id)
    return segment_ids, semantic_event_ids


def _normalized_observer_capture_run(active_run: dict[str, Any]) -> dict[str, Any] | None:
    run_id = str(active_run.get("run_id") or "").strip()
    session_id = str(active_run.get("session_id") or "").strip()
    session_mode = str(active_run.get("session_mode") or "").strip()
    session_mode_source = str(active_run.get("session_mode_source") or "").strip()
    session_mode_policy_version = active_run.get("session_mode_policy_version")
    if not run_id or not session_id or not session_mode or not session_mode_source or session_mode_policy_version is None:
        return None
    return dict(active_run)


def _execute_continuity_observer(
    *,
    ctx: dict[str, Any],
    active_run: dict[str, Any],
    trigger: str,
    summary: str | None,
    notes: list[str] | None = None,
    changed_files: list[str] | None = None,
    boundary: str | None = None,
    decision_boundary: bool = False,
    uncertainty_present: bool = False,
    source_refs: list[dict[str, Any]] | None = None,
    accepted_context: dict[str, Any] | None = None,
    session_mode_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    backend = configured_continuity_observer_backend()
    result: dict[str, Any] = {
        "observer_status": "degraded",
        "observer_backend": backend,
        "observer_provider_status": "unknown",
        "observer_degraded": True,
        "observer_degraded_reason": None,
        "observer_triggered": False,
        "observer_action_kinds": [],
        "observer_context": {},
        "observer_side_effects": [],
        "observer_capture_batch_id": None,
        "observer_capture_artifact_path": None,
        "observer_capture_ledger_path": None,
        "observer_decision_path": None,
        "observer_decisions_ledger_path": None,
        "observer_disclosure_path": None,
        "observer_disclosures_ledger_path": None,
        "observer_obligation_path": None,
        "written_artifacts": [],
        "error_code": None,
        "error_message": None,
    }
    try:
        observer = observe_continuity(
            subject=ctx["subject"],
            data_root=data_root,
            trigger=trigger,
            summary=summary,
            notes=list(notes or []),
            changed_files=list(changed_files or []),
            session_id=_effective_session_id(ctx, active_run=active_run),
            run_id=str(active_run.get("run_id") or "").strip() or None,
            boundary=boundary,
            decision_boundary=decision_boundary,
            uncertainty_present=uncertainty_present,
            source_refs=list(source_refs or []),
            accepted_context=accepted_context,
            session_mode_fields=session_mode_fields,
        )
    except Exception as exc:
        result["error_code"] = "CONTINUITY_OBSERVER_FAILED"
        result["error_message"] = str(exc)
        result["observer_degraded_reason"] = "observer_execution_failed"
        result["observer_side_effects"].append(
            {
                "action": "observer",
                "status": "failed",
                "error": str(exc),
            }
        )
        return result

    result.update(
        {
            "observer_status": observer.get("observer_status"),
            "observer_backend": observer.get("backend"),
            "observer_provider_status": observer.get("provider_status"),
            "observer_degraded": bool(observer.get("degraded")),
            "observer_degraded_reason": observer.get("degraded_reason"),
            "observer_triggered": bool(observer.get("observer_triggered")),
            "observer_action_kinds": [],
            "observer_context": dict(observer.get("observer_context") or {}),
        }
    )

    for intent in list(observer.get("observer_intents") or []):
        requested_action_kind = str(intent.get("artifact_family") or "").strip()
        if not requested_action_kind or requested_action_kind == "noop":
            continue
        confidence = str(intent.get("confidence") or "medium").strip().lower() or "medium"
        payload = dict(intent.get("payload") or {})
        action_kind = requested_action_kind
        if confidence == "low" and requested_action_kind not in {"semantic_capture", "open_obligation"}:
            action_kind = "open_obligation"
            payload = {
                "obligation_kind": "observer.review.required",
                "severity": "warn",
                "summary": str(
                    payload.get("summary")
                    or summary
                    or f"Low-confidence observer intent for {requested_action_kind} requires review."
                ).strip(),
                "required_record_families": ["semantic_capture"],
                "metadata": {
                    **dict(payload.get("metadata") or {}),
                    "observer_requested_action_kind": requested_action_kind,
                    "observer_confidence": confidence,
                    "observer_downgraded": True,
                },
            }
        try:
            if action_kind == "semantic_capture":
                capture_run = _normalized_observer_capture_run(active_run)
                if capture_run is None:
                    result["observer_side_effects"].append(
                        {
                            "action": action_kind,
                            "status": "skipped",
                            "reason": "missing_normalized_session_context",
                        }
                    )
                    continue
                captures = list(payload.get("captures") or [])
                if not captures:
                    capture_summary = str(payload.get("title") or summary or trigger).strip()
                    captures = [{"kind": "repo_fact", "summary": capture_summary}]
                receipt = write_capture_batch(
                    subject=ctx["subject"],
                    data_root=data_root,
                    engine_root=engine_root,
                    run_data=capture_run,
                    raw_text=str(payload.get("raw_text") or summary or trigger).strip(),
                    payload={"title": str(payload.get("title") or summary or trigger).strip(), "captures": captures},
                    source_role=CaptureSourceRole.AGENT,
                    title_override=str(payload.get("title") or "").strip() or None,
                    extra_context={
                        "capture_context": "continuity_observer",
                        "observer_trigger": trigger,
                        "observer_packet_fingerprint": result["observer_context"].get("packet_fingerprint"),
                        "suppress_proposals": True,
                    },
                )
                batch = dict(receipt.get("batch") or {})
                result["observer_capture_batch_id"] = str(batch.get("capture_batch_id") or "").strip() or None
                result["observer_capture_artifact_path"] = receipt.get("artifact_path")
                result["observer_capture_ledger_path"] = receipt.get("ledger_path")
                result["written_artifacts"].extend(
                    [item for item in [receipt.get("artifact_path"), receipt.get("ledger_path")] if item]
                )
                result["observer_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "capture_batch_id": result["observer_capture_batch_id"],
                        "capture_artifact_path": result["observer_capture_artifact_path"],
                        "capture_ledger_path": result["observer_capture_ledger_path"],
                    }
                )
            elif action_kind == "decision_log":
                decision_receipt = log_decision(
                    subject=ctx["subject"],
                    data_root=data_root,
                    title=str(payload.get("title") or summary or "Observer decision").strip(),
                    summary=str(payload.get("summary") or summary or "Observer identified a decision boundary.").strip(),
                    why=str(payload.get("why") or "").strip() or None,
                    constraints=[],
                    tradeoffs=[],
                    related_runs=[str(active_run.get("run_id") or "").strip()] if str(active_run.get("run_id") or "").strip() else [],
                    related_quests=[],
                    source_refs=list(intent.get("source_refs") or []),
                    intended_directions=list(payload.get("intended_directions") or []),
                    unresolved_items=list(payload.get("unresolved_items") or []),
                )
                result["observer_decision_path"] = decision_receipt.get("decision_path")
                result["observer_decisions_ledger_path"] = decision_receipt.get("decisions_ledger_path")
                result["written_artifacts"].extend(
                    [item for item in [decision_receipt.get("decision_path"), decision_receipt.get("decisions_ledger_path")] if item]
                )
                result["observer_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "decision_path": result["observer_decision_path"],
                        "decisions_ledger_path": result["observer_decisions_ledger_path"],
                    }
                )
            elif action_kind == "disclosure_log":
                disclosure_receipt = log_disclosure(
                    subject=ctx["subject"],
                    data_root=data_root,
                    trigger=str(payload.get("trigger") or summary or "Observer surfaced uncertainty.").strip(),
                    expected=str(payload.get("expected") or "Continuity should remain truthful.").strip(),
                    provable=str(payload.get("provable") or "Observer detected uncertainty in the bounded continuity packet.").strip(),
                    status_labels=list(payload.get("status_labels") or ["UNCERTAINTY"]),
                    impact=str(payload.get("impact") or summary or "Observer surfaced uncertainty during a governed boundary.").strip(),
                    safe_options=list(payload.get("safe_options") or []),
                    decision_needed=str(payload.get("decision_needed") or "Clarify the uncertain path before stronger canon changes.").strip(),
                    related_runs=[str(active_run.get("run_id") or "").strip()] if str(active_run.get("run_id") or "").strip() else [],
                    related_quests=[],
                    source_refs=list(intent.get("source_refs") or []),
                )
                result["observer_disclosure_path"] = disclosure_receipt.get("disclosure_path")
                result["observer_disclosures_ledger_path"] = disclosure_receipt.get("disclosures_ledger_path")
                result["written_artifacts"].extend(
                    [item for item in [disclosure_receipt.get("disclosure_path"), disclosure_receipt.get("disclosures_ledger_path")] if item]
                )
                result["observer_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "disclosure_path": result["observer_disclosure_path"],
                        "disclosures_ledger_path": result["observer_disclosures_ledger_path"],
                    }
                )
            elif action_kind == "open_obligation":
                segment_ids, semantic_event_ids = _extract_observer_source_ids(intent.get("source_refs"))
                obligation_receipt = open_obligation(
                    subject=ctx["subject"],
                    data_root=data_root,
                    recorded_at=kernel_now_iso(),
                    obligation_kind=str(payload.get("obligation_kind") or "observer.review.required").strip(),
                    severity=str(payload.get("severity") or "warn").strip().lower() or "warn",
                    summary=str(payload.get("summary") or summary or "Observer requested a continuity review obligation.").strip(),
                    required_record_families=list(payload.get("required_record_families") or ["semantic_capture"]),
                    source_segment_ids=segment_ids,
                    source_semantic_event_ids=semantic_event_ids,
                    source_refs=list(intent.get("source_refs") or []),
                    metadata={
                        "observer_trigger": trigger,
                        "observer_packet_fingerprint": result["observer_context"].get("packet_fingerprint"),
                        **dict(payload.get("metadata") or {}),
                    },
                )
                result["observer_obligation_path"] = obligation_receipt.get("path")
                if obligation_receipt.get("path"):
                    result["written_artifacts"].append(obligation_receipt["path"])
                result["observer_side_effects"].append(
                    {
                        "action": action_kind,
                        "status": "ok",
                        "obligation_path": result["observer_obligation_path"],
                        "obligation_kind": obligation_receipt.get("obligation_kind"),
                        "downgraded_from": requested_action_kind if requested_action_kind != action_kind else None,
                    }
                )
            result["observer_action_kinds"].append(action_kind)
        except Exception as exc:
            result["error_code"] = "CONTINUITY_OBSERVER_SIDE_EFFECT_FAILED"
            result["error_message"] = f"{action_kind} failed: {exc}"
            result["observer_side_effects"].append(
                {
                    "action": action_kind,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            break

    result["observer_action_kinds"] = [str(item) for item in result.get("observer_action_kinds") or [] if str(item).strip()]
    result["observer_triggered"] = bool(result["observer_action_kinds"])
    return result


def _apply_observer_event_metadata(
    *,
    signals: dict[str, Any],
    outputs: dict[str, Any],
    truth_flags: dict[str, Any],
    observer: dict[str, Any],
) -> None:
    changed_files = list(signals.get("changed_files") or [])
    for path in observer.get("written_artifacts") or []:
        text = str(path or "").strip()
        if text and text not in changed_files:
            changed_files.append(text)
    signals["changed_files"] = changed_files
    signals["observer_triggered"] = bool(observer.get("observer_triggered"))
    signals["observer_action_kinds"] = list(observer.get("observer_action_kinds") or [])
    signals["observer_context"] = dict(observer.get("observer_context") or {})
    outputs["observer_status"] = observer.get("observer_status")
    outputs["observer_backend"] = observer.get("observer_backend")
    outputs["observer_provider_status"] = observer.get("observer_provider_status")
    outputs["observer_degraded"] = bool(observer.get("observer_degraded"))
    outputs["observer_degraded_reason"] = observer.get("observer_degraded_reason")
    outputs["observer_side_effects"] = list(observer.get("observer_side_effects") or [])
    for source_key, target_key in (
        ("observer_capture_batch_id", "capture_batch_id"),
        ("observer_capture_artifact_path", "capture_artifact_path"),
        ("observer_capture_ledger_path", "capture_ledger_path"),
        ("observer_decision_path", "decision_path"),
        ("observer_decisions_ledger_path", "decisions_ledger_path"),
        ("observer_disclosure_path", "disclosure_path"),
        ("observer_disclosures_ledger_path", "disclosures_ledger_path"),
    ):
        value = observer.get(source_key)
        if value and not outputs.get(target_key):
            outputs[target_key] = value
    if observer.get("observer_obligation_path"):
        outputs["observer_obligation_path"] = observer.get("observer_obligation_path")
    truth_flags["uncertainty_present"] = bool(
        truth_flags.get("uncertainty_present") or observer.get("observer_context", {}).get("uncertainty_present")
    )
    if observer.get("observer_disclosure_path"):
        truth_flags["disclosure_open"] = True


def _apply_observer_partial_status(
    *,
    event_info: dict[str, Any],
    observer: dict[str, Any],
) -> dict[str, Any]:
    if not observer.get("error_message"):
        return event_info
    return _apply_follow_on_partial_status(
        event_info=event_info,
        error_code=observer.get("error_code") or "CONTINUITY_OBSERVER_FAILED",
        error_message=str(observer.get("error_message")),
        recovery_hint=(
            "Primary work was committed and recorded, but a continuity-observer side effect failed. "
            "Inspect the observer_side_effects metadata and rerun the relevant continuity boundary if needed."
        ),
    )


def _apply_follow_on_partial_status(
    *,
    event_info: dict[str, Any],
    error_code: str,
    error_message: str,
    recovery_hint: str,
) -> dict[str, Any]:
    runtime_status = event_info.get("runtime_status")
    if not isinstance(runtime_status, dict):
        return event_info
    if str(runtime_status.get("operation_status") or "").lower() == "partial":
        return event_info
    updated = dict(event_info)
    updated_runtime_status = dict(runtime_status)
    updated_runtime_status["operation_status"] = "partial"
    updated_runtime_status["error_code"] = error_code
    updated_runtime_status["error_message"] = error_message
    updated_runtime_status["recovery_hint"] = recovery_hint
    updated["runtime_status"] = updated_runtime_status
    return updated


def _refresh_truth_status_after_mutation(
    *,
    ctx: dict[str, Any],
    event_info: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        refreshed = refresh_truth_status(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            engine_root=Path(ctx["engine_root"]),
        )
    except Exception as exc:
        return (
            _apply_follow_on_partial_status(
                event_info=event_info,
                error_code="TRUTH_STATUS_REFRESH_FAILED",
                error_message=str(exc),
                recovery_hint=(
                    "Primary mutation committed, but lightweight truth-status refresh failed. "
                    "Rerun `python3 runtime/synapse.py compile-current-state` or repair the truth compiler path."
                ),
            ),
            None,
        )
    return event_info, refreshed


def _compile_current_state_event_payload(
    *,
    ctx: dict[str, Any],
    compile_result: dict[str, Any],
    session_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    publication_paths = dict(compile_result.get("publication_paths") or {})
    changed_files = [
        compile_result.get("statement_store_path"),
        compile_result.get("compiler_report_path"),
        *publication_paths.values(),
    ]
    signals = {
        "compile_cycle_id": compile_result.get("compile_cycle_id"),
        "changed_files": [str(item) for item in changed_files if str(item or "").strip()],
        "verification_entries": [],
        "related_quest_ids": [],
        "related_sidequest_ids": [],
    }
    outputs = {
        "compile_cycle_id": compile_result.get("compile_cycle_id"),
        "statement_store_path": compile_result.get("statement_store_path"),
        "compiler_report_path": compile_result.get("compiler_report_path"),
        "publication_paths": publication_paths,
        "statement_count": compile_result.get("statement_count"),
        "active_statement_count": compile_result.get("active_statement_count"),
        "superseded_count": compile_result.get("superseded_count"),
        "contradiction_count": compile_result.get("contradiction_count"),
        "stale_active_run_detected": compile_result.get("stale_active_run_detected"),
        "truth_compile_stale": compile_result.get("truth_compile_stale"),
    }
    return signals, outputs


def _run_truth_compile(
    *,
    ctx: dict[str, Any],
    session_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, TruthCompilerError | None]:
    try:
        result = compile_current_state(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            engine_root=Path(ctx["engine_root"]),
        )
    except TruthCompilerError as exc:
        return None, None, exc
    except TruthSourceError as exc:
        return None, None, TruthCompilerError(str(exc))
    except RuntimeError as exc:
        return None, None, TruthCompilerError(str(exc))
    signals, outputs = _compile_current_state_event_payload(ctx=ctx, compile_result=result, session_id=session_id)
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="compile-current-state",
        summary=f"Compiled current-state truth for {ctx['subject']}.",
        session_id=session_id,
        signals=signals,
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": bool(result.get("contradiction_count")),
        },
        outputs=outputs,
    )
    result = {
        **result,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }
    return result, event_info, None


def _merge_truth_compile_follow_on(
    *,
    ctx: dict[str, Any],
    session_id: str | None,
    event_info: dict[str, Any],
    primary_action_label: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    truth_compile = None
    compile_result, compile_event_info, compile_error = _run_truth_compile(ctx=ctx, session_id=session_id)
    if compile_error is not None:
        truth_compile = dict(getattr(compile_error, "payload", {}) or {})
        return (
            _apply_follow_on_partial_status(
                event_info=event_info,
                error_code="TRUTH_COMPILE_PARTIAL" if isinstance(compile_error, TruthCompilerPartialError) else "TRUTH_COMPILE_FAILED",
                error_message=str(compile_error),
                recovery_hint=(
                    f"{primary_action_label} committed, but automatic truth compilation did not complete cleanly. "
                    "Rerun `python3 runtime/synapse.py compile-current-state` after repairing the truth compiler path."
                ),
            ),
            truth_compile,
        )
    truth_compile = compile_result
    compile_runtime_status = compile_event_info.get("runtime_status") if isinstance(compile_event_info, dict) else None
    if isinstance(compile_runtime_status, dict) and str(compile_runtime_status.get("operation_status") or "").lower() == "partial":
        event_info = _apply_follow_on_partial_status(
            event_info=event_info,
            error_code=str(compile_runtime_status.get("error_code") or "TRUTH_COMPILE_EVENT_PARTIAL"),
            error_message=str(compile_runtime_status.get("error_message") or "Automatic truth compile recorded a partial reducer/event result."),
            recovery_hint=str(
                compile_runtime_status.get("recovery_hint")
                or "Automatic truth compilation committed, but its event/reducer flow is stale. Repair continuity and rerun compile-current-state."
            ),
        )
    return event_info, truth_compile


def _current_provenance_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    return compute_current_provenance_summary(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        engine_root=Path(ctx["engine_root"]),
        write_projection=False,
    )


def _close_turn_validation_payload(ctx: dict[str, Any], *, boundary: str) -> dict[str, Any]:
    summary = _current_provenance_summary(ctx)
    return {
        "boundary": boundary,
        "validation_status": summary.get("provenance_status"),
        "continuation_required": summary.get("provenance_status") == ProvenanceStatus.BLOCKED.value,
        "integration_posture": summary.get("integration_posture"),
        "local_integration_health": summary.get("local_integration_health"),
        "local_integration_missing_assets": list(summary.get("local_integration_missing_assets") or []),
        "degraded_mode": bool(summary.get("degraded_mode")),
        "degraded_mode_reason": summary.get("degraded_mode_reason"),
        "strict_boundary_status": summary.get("strict_boundary_status"),
        "open_continuity_obligation_count": summary.get("open_continuity_obligation_count") or 0,
        "blocker_continuity_obligation_count": summary.get("blocker_continuity_obligation_count") or 0,
        "import_review_required_count": summary.get("import_review_required_count") or 0,
        "recent_open_continuity_obligation_details": list(summary.get("recent_open_continuity_obligation_details") or []),
        "recent_import_review_details": list(summary.get("recent_import_review_details") or []),
        "continuity_blockers": list(summary.get("continuity_blockers") or []),
        "continuity_warnings": list(summary.get("continuity_warnings") or []),
        "provenance_blockers": list(summary.get("blockers") or []),
        "provenance_warnings": list(summary.get("warnings") or []),
        "summary": summary,
    }


def _routing_signal_for_boundary(context: ArtifactRoutingContext) -> AmbientSignal | None:
    if not any((context.summary, context.notes, context.changed_files)):
        return None
    return AmbientSignal(
        source=context.trigger,
        subject=context.subject,
        title=context.summary,
        summary=context.summary,
        notes=context.notes,
        files_touched=context.changed_files,
    )


def _routing_current_accepted(accepted_context: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(accepted_context or {})
    quest_id = str(payload.get("current_accepted_quest_id") or "").strip()
    if not quest_id:
        return None
    return {"quest_id": quest_id}


def _routing_changed_paths(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    summary = dict(payload.get("summary") or {})
    for key in (
        "current_eod_candidate_path",
        "current_control_sync_candidate_path",
        "current_snapshot_candidate_path",
        "current_story_candidate_path",
        "current_vision_candidate_path",
    ):
        text = str(summary.get(key) or "").strip()
        if text and text not in paths:
            paths.append(text)
    for item in summary.get("current_codex_candidate_paths") or []:
        text = str(item or "").strip()
        if text and text not in paths:
            paths.append(text)
    return paths


def _apply_artifact_routing_result(
    *,
    ctx: dict[str, Any],
    active_run: dict[str, Any],
    accepted_context: dict[str, Any],
    routing_context: ArtifactRoutingContext,
    routing_result: ArtifactRoutingResult,
) -> dict[str, Any]:
    dispatch_results: list[dict[str, Any]] = []
    changed_artifact_paths: list[str] = []
    snapshot_candidate_result: dict[str, Any] | None = None
    publication_candidate_result: dict[str, Any] | None = None
    proposal_results: list[dict[str, Any]] = []
    proposal_mutated = False

    signal = _routing_signal_for_boundary(routing_context)
    current_accepted = _routing_current_accepted(accepted_context)
    source_id = str(active_run.get("run_id") or "NO_RUN").strip() or "NO_RUN"
    interaction_mode = str(active_run.get("interaction_mode") or "").strip().lower() or "maintenance"

    for intent in routing_result.intents:
        receipt: dict[str, Any] = {
            "intent_kind": intent.intent_kind,
            "target_family": intent.target_family,
            "target_owner": intent.target_owner,
            "target_posture": intent.target_posture,
            "dispatch_key": intent.dispatch_key,
            "blocking_reason": intent.blocking_reason,
            "required_prerequisites": list(intent.required_prerequisites),
        }
        if intent.dispatch_key == NOOP_DISPATCH_KEY:
            receipt["status"] = "noop"
            receipt["reason"] = str(intent.metadata.get("reason") or "no_routable_artifact_family")
            dispatch_results.append(receipt)
            continue
        if intent.dispatch_key == "blocked":
            receipt["status"] = "blocked"
            receipt["metadata"] = dict(intent.metadata or {})
            dispatch_results.append(receipt)
            continue
        if intent.dispatch_key == SNAPSHOT_DISPATCH_KEY:
            snapshot_candidate_result = _refresh_snapshot_candidate_boundary(
                ctx=ctx,
                boundary=routing_context.boundary or routing_context.trigger,
                candidate_kinds=list(intent.metadata.get("candidate_kinds") or []),
                target_day=str(intent.metadata.get("target_day") or "").strip() or None,
                prefer_latest_active_draftshot=bool(intent.metadata.get("prefer_latest_active_draftshot")),
                obligation_fallback=bool(intent.metadata.get("obligation_fallback", True)),
                session_id_override=str(active_run.get("session_id") or "").strip() or None,
                run_id_override=str(active_run.get("run_id") or "").strip() or None,
            )
            receipt["status"] = "applied"
            receipt["result"] = snapshot_candidate_result
            for path in _routing_changed_paths(snapshot_candidate_result):
                if path not in changed_artifact_paths:
                    changed_artifact_paths.append(path)
            dispatch_results.append(receipt)
            continue
        if intent.dispatch_key == PUBLICATION_DISPATCH_KEY:
            publication_candidate_result = _refresh_publication_candidate_boundary(
                ctx=ctx,
                boundary=routing_context.boundary or routing_context.trigger,
                candidate_kinds=list(intent.metadata.get("candidate_kinds") or []),
            )
            receipt["status"] = "applied"
            receipt["result"] = publication_candidate_result
            for path in _routing_changed_paths(publication_candidate_result):
                if path not in changed_artifact_paths:
                    changed_artifact_paths.append(path)
            dispatch_results.append(receipt)
            continue
        if intent.dispatch_key == QUEST_DISPATCH_KEY:
            if signal is None:
                receipt["status"] = "blocked"
                receipt["blocking_reason"] = "missing_signal"
                dispatch_results.append(receipt)
                continue
            proposal_receipt = upsert_quest_candidate_from_promotion(
                subject=ctx["subject"],
                data_root=Path(ctx["data_root"]),
                source_id=source_id,
                interaction_mode=interaction_mode,
                active_run=active_run,
                signal=signal,
                promotion=promotion_record_from_payload(dict(intent.metadata.get("promotion") or {})),
                current_accepted=current_accepted,
            )
            receipt["status"] = "applied" if proposal_receipt is not None else "noop"
            receipt["result"] = proposal_receipt
            if proposal_receipt is not None:
                proposal_mutated = True
                proposal_results.append(proposal_receipt)
                path = str(proposal_receipt.get("path") or "").strip()
                if path and path not in changed_artifact_paths:
                    changed_artifact_paths.append(path)
            dispatch_results.append(receipt)
            continue
        if intent.dispatch_key == GOVERNANCE_PROPOSAL_DISPATCH_KEY:
            proposal_receipt = upsert_operational_proposal_from_promotion(
                subject=ctx["subject"],
                data_root=Path(ctx["data_root"]),
                source_id=source_id,
                interaction_mode=interaction_mode,
                active_run=active_run,
                signal=signal,
                promotion=promotion_record_from_payload(dict(intent.metadata.get("promotion") or {})),
            )
            receipt["status"] = str(proposal_receipt.get("status") or "written")
            receipt["result"] = proposal_receipt
            proposal_mutated = proposal_mutated or receipt["status"] != "blocked"
            proposal_results.append(proposal_receipt)
            path = str(proposal_receipt.get("path") or "").strip()
            if path and path not in changed_artifact_paths:
                changed_artifact_paths.append(path)
            dispatch_results.append(receipt)
            continue
        receipt["status"] = "blocked"
        receipt["blocking_reason"] = f"unknown_dispatch_key:{intent.dispatch_key}"
        dispatch_results.append(receipt)

    projection = None
    if proposal_mutated:
        projection = _sync_sidecar(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            active_run=_load_active_run_with_session_repair(ctx),
            mutate_proposals=False,
        )

    status = "applied"
    if dispatch_results and all(item.get("status") == "noop" for item in dispatch_results):
        status = "noop"
    elif dispatch_results and all(item.get("status") == "blocked" for item in dispatch_results):
        status = "blocked"

    return {
        "status": status,
        "dispatch_results": dispatch_results,
        "changed_artifact_paths": changed_artifact_paths,
        "snapshot_candidates": snapshot_candidate_result,
        "publication_candidates": publication_candidate_result,
        "proposal_results": proposal_results,
        "projection": projection,
    }


def _route_artifact_boundary(
    *,
    ctx: dict[str, Any],
    trigger: str,
    invoke_reason: str,
    active_run: dict[str, Any],
    accepted_context: dict[str, Any],
    summary: str | None = None,
    notes: list[str] | None = None,
    changed_files: list[str] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    observer_action_kinds: list[str] | None = None,
    requested_snapshot_kinds: list[str] | None = None,
    requested_publication_candidate_kinds: list[str] | None = None,
    requested_missing_owner_families: list[str] | None = None,
    boundary: str | None = None,
    target_day: str | None = None,
    prefer_latest_active_draftshot: bool = False,
    obligation_fallback: bool = True,
    import_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routing_context = build_artifact_routing_context(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        engine_root=Path(ctx["engine_root"]),
        trigger=trigger,
        boundary=boundary,
        invoke_reason=invoke_reason,
        active_run=active_run,
        accepted_context=accepted_context,
        summary=summary,
        notes=list(notes or []),
        changed_files=list(changed_files or []),
        source_refs=list(source_refs or []),
        observer_action_kinds=list(observer_action_kinds or []),
        requested_snapshot_kinds=requested_snapshot_kinds,
        requested_publication_candidate_kinds=requested_publication_candidate_kinds,
        requested_missing_owner_families=requested_missing_owner_families,
        target_day=target_day,
        prefer_latest_active_draftshot=prefer_latest_active_draftshot,
        obligation_fallback=obligation_fallback,
        import_profile=import_profile,
    )
    routing_result = evaluate_artifact_routing(routing_context)
    applied = _apply_artifact_routing_result(
        ctx=ctx,
        active_run=active_run,
        accepted_context=accepted_context,
        routing_context=routing_context,
        routing_result=routing_result,
    )
    return {
        "context": routing_context.to_dict(),
        "result": routing_result.to_dict(),
        "dispatch": applied,
    }


def _snapshot_candidate_required_kinds(ctx: dict[str, Any]) -> list[str]:
    data_root = Path(ctx["data_root"])
    active_run = _load_active_run_with_session_repair(ctx)
    has_session_anchor = bool(_effective_session_id(ctx, active_run=active_run)) or load_active_draftshot(data_root, session_id=None) is not None
    if not has_session_anchor:
        return []

    manifold = _read_yaml(data_root / ".synapse" / "MANIFOLD.yaml")
    if not isinstance(manifold, dict):
        manifold = {}

    def has_summary(key: str) -> bool:
        payload = manifold.get(key)
        return bool(str(dict(payload or {}).get("summary") or "").strip())

    imported_delta = dict(manifold.get("current_imported_continuity_delta") or {})
    imported_snapshot_eligible = bool(dict(imported_delta.get("metadata") or {}).get("snapshot_candidate_eligible"))

    required: list[str] = []
    if any(
        has_summary(key)
        for key in (
            "current_active_plan_delta",
            "current_active_scope_delta",
            "current_obligation_delta",
            "current_architecture_delta",
        )
    ) or imported_snapshot_eligible:
        required.append(EOD_KIND)
    if str(manifold.get("active_session_mode") or "").strip() == SessionMode.CONTROL_SYNC.value or any(
        has_summary(key)
        for key in (
            "current_active_scope_delta",
            "current_architecture_delta",
            "current_identity_delta",
            "current_narrative_delta",
            "current_obligation_delta",
        )
    ):
        required.append(CONTROL_SYNC_KIND)
    return required


def _snapshot_candidate_marker(kind: str, target_day: str) -> str:
    return f"SNAPSHOT_CANDIDATE::{kind}::{target_day}"


def _snapshot_candidate_obligation_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    return f"snapshot.candidate.{normalized}.required"


def _snapshot_candidate_path_key(kind: str) -> str:
    return "current_eod_candidate_path" if kind == EOD_KIND else "current_control_sync_candidate_path"


def _snapshot_candidate_target_day_key(kind: str) -> str:
    return "current_eod_candidate_target_day" if kind == EOD_KIND else "current_control_sync_candidate_target_day"


def _candidate_kind_satisfied(summary: dict[str, Any], *, kind: str, target_day: str | None = None) -> bool:
    path = str(summary.get(_snapshot_candidate_path_key(kind)) or "").strip()
    if not path:
        return False
    if target_day:
        return str(summary.get(_snapshot_candidate_target_day_key(kind)) or "").strip() == str(target_day).strip()
    return True


def _sync_snapshot_candidate_obligations(
    *,
    ctx: dict[str, Any],
    required_kinds: list[str],
    target_day: str,
    summary: dict[str, Any],
    boundary: str,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    recorded_at = kernel_now_iso()
    opened: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    active_draftshot = load_active_draftshot(data_root, session_id=None)
    source_refs = []
    if active_draftshot:
        source_refs.append(
            {
                "kind": "draftshot_revision",
                "id": active_draftshot.get("revision_id"),
                "path": active_draftshot.get("path"),
                "body_path": active_draftshot.get("body_path"),
                "session_id": active_draftshot.get("session_id"),
            }
        )

    for kind in required_kinds:
        marker = _snapshot_candidate_marker(kind, target_day)
        obligation_kind = _snapshot_candidate_obligation_kind(kind)
        if _candidate_kind_satisfied(summary, kind=kind, target_day=target_day):
            resolution_ids = []
            path_key = _snapshot_candidate_path_key(kind)
            if summary.get(path_key):
                resolution_ids.append(str(summary.get(path_key)))
            resolved.extend(
                resolve_matching_obligations(
                    data_root=data_root,
                    recorded_at=recorded_at,
                    source_segment_ids=[marker],
                    source_semantic_event_ids=[marker],
                    resolution_record_ids=resolution_ids,
                    obligation_kinds=[obligation_kind],
                )
            )
            continue
        opened.append(
            open_obligation(
                subject=ctx["subject"],
                data_root=data_root,
                recorded_at=recorded_at,
                obligation_kind=obligation_kind,
                severity="blocker",
                summary=f"{kind} snapshot candidate is required at the {boundary} boundary but could not be drafted lawfully.",
                required_record_families=[f"snapshot_candidate_{str(kind).lower()}"],
                source_segment_ids=[marker],
                source_semantic_event_ids=[marker],
                source_refs=source_refs,
                metadata={
                    "candidate_kind": kind,
                    "target_day": target_day,
                    "boundary": boundary,
                },
            )
        )
    return {"opened_obligations": opened, "resolved_obligations": resolved}


def _refresh_snapshot_candidate_boundary(
    *,
    ctx: dict[str, Any],
    boundary: str,
    candidate_kinds: list[str] | None = None,
    target_day: str | None = None,
    prefer_latest_active_draftshot: bool = False,
    refresh_draftshot_first: bool = True,
    obligation_fallback: bool = True,
    session_id_override: str | None = None,
    run_id_override: str | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = _load_active_run_with_session_repair(ctx)
    run_id = str(run_id_override or active_run.get("run_id") or "").strip() or None
    session_id = _continuity_session_anchor(
        ctx,
        active_run=active_run,
        session_id=session_id_override,
        run_id=run_id,
    )
    draftshot_result: dict[str, Any] | None = None
    draftshot_error: str | None = None

    if refresh_draftshot_first and session_id:
        try:
            draftshot_result = refresh_draftshot(
                subject=ctx["subject"],
                data_root=data_root,
                session_id=session_id,
                run_id=run_id,
            )
        except DraftshotError as exc:
            draftshot_error = str(exc)

    refresh_synthesis_projection(subject=ctx["subject"], data_root=data_root)
    summary_before = snapshot_candidate_summary(data_root)
    if candidate_kinds is None:
        required_kinds = list(_snapshot_candidate_required_kinds(ctx))
    else:
        required_kinds = list(candidate_kinds)
    current_draftshot = load_active_draftshot(data_root, session_id=session_id) if session_id else None
    if current_draftshot is None and prefer_latest_active_draftshot:
        current_draftshot = load_active_draftshot(data_root, session_id=None)
    checkpoint_decision = evaluate_snapshot_checkpoint(
        boundary=boundary,
        requested_candidate_kinds=required_kinds,
        target_day_hint=target_day,
        current_summary=summary_before,
        draftshot=current_draftshot,
        session_anchor_present=bool(session_id),
    )
    if checkpoint_decision.blocked_reason == "missing_session_anchor":
        return _snapshot_candidate_boundary_noop(
            data_root=data_root,
            boundary=boundary,
            reason="missing_session_id",
            decision=checkpoint_decision.to_dict(),
        )
    if checkpoint_decision.blocked_reason == "no_active_draftshot":
        return _snapshot_candidate_boundary_noop(
            data_root=data_root,
            boundary=boundary,
            reason="no_active_draftshot",
            decision=checkpoint_decision.to_dict(),
        )
    if not checkpoint_decision.required_candidate_kinds:
        return _snapshot_candidate_boundary_noop(
            data_root=data_root,
            boundary=boundary,
            reason="no_required_candidate_kinds",
            decision=checkpoint_decision.to_dict(),
        )
    payload = refresh_snapshot_candidates(
        subject=ctx["subject"],
        data_root=data_root,
        session_id=session_id,
        candidate_kinds=list(checkpoint_decision.required_candidate_kinds),
        target_day=checkpoint_decision.target_day,
        prefer_latest_active_draftshot=prefer_latest_active_draftshot,
    )
    projection = _sync_sidecar(
        subject=ctx["subject"],
        data_root=data_root,
        active_run=_load_active_run_with_session_repair(ctx),
        mutate_proposals=False,
    )
    summary = dict(payload.get("summary") or snapshot_candidate_summary(data_root))
    obligation_result = {"opened_obligations": [], "resolved_obligations": []}
    effective_target_day = (
        str(checkpoint_decision.target_day or payload.get("target_day") or "").strip() or None
    )
    if obligation_fallback and checkpoint_decision.required_candidate_kinds and not effective_target_day:
        effective_target_day = kernel_now_iso().split("T", 1)[0]
    if obligation_fallback and checkpoint_decision.required_candidate_kinds and effective_target_day:
        obligation_result = _sync_snapshot_candidate_obligations(
            ctx=ctx,
            required_kinds=list(checkpoint_decision.required_candidate_kinds),
            target_day=effective_target_day,
            summary=summary,
            boundary=boundary,
        )
        if obligation_result["opened_obligations"] or obligation_result["resolved_obligations"]:
            projection = _sync_sidecar(
                subject=ctx["subject"],
                data_root=data_root,
                active_run=_load_active_run_with_session_repair(ctx),
                mutate_proposals=False,
            )
            summary = snapshot_candidate_summary(data_root)

    decision_payload = materialize_snapshot_checkpoint_decision(
        checkpoint_decision,
        snapshot_candidate_payload=payload,
        target_day=effective_target_day,
        draftshot_error=draftshot_error,
    )
    return {
        "boundary": boundary,
        "required_kinds": list(checkpoint_decision.required_candidate_kinds),
        "target_day": effective_target_day,
        "decision": decision_payload,
        "draftshot_result": draftshot_result,
        "draftshot_error": draftshot_error,
        "snapshot_candidates": payload,
        "summary": summary,
        "projection": projection,
        **obligation_result,
    }


def _refresh_publication_candidate_boundary(
    *,
    ctx: dict[str, Any],
    boundary: str,
    candidate_kinds: list[str] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    refresh_synthesis_projection(subject=ctx["subject"], data_root=data_root)
    payload = refresh_publication_candidates(
        subject=ctx["subject"],
        data_root=data_root,
        candidate_kinds=candidate_kinds,
    )
    projection = _sync_sidecar(
        subject=ctx["subject"],
        data_root=data_root,
        active_run=_load_active_run_with_session_repair(ctx),
        mutate_proposals=False,
    )
    summary = dict(payload.get("summary") or publication_candidate_summary(data_root))
    return {
        "boundary": boundary,
        "publication_candidates": payload,
        "summary": summary,
        "projection": projection,
    }


def _publication_candidate_boundary_noop(
    *,
    data_root: Path,
    boundary: str,
    reason: str,
) -> dict[str, Any]:
    summary = publication_candidate_summary(data_root)
    return {
        "boundary": boundary,
        "publication_candidates": {
            "status": "noop",
            "reason": reason,
            "summary": summary,
            "candidates": [],
        },
        "summary": summary,
        "projection": None,
    }


def _orchestrate_import_continuity_followup(
    *,
    ctx: dict[str, Any],
    parsed: dict[str, Any],
    raw_payload: dict[str, Any],
    session_id_override: str | None = None,
    run_id_override: str | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    import_profile = imported_confidence_profile(parsed)
    import_review_obligations: list[dict[str, Any]] = []
    if import_profile.get("requires_review") and not str(parsed.get("extracted_text") or "").strip():
        import_review_obligations.append(
            open_obligation(
                subject=ctx["subject"],
                data_root=data_root,
                recorded_at=kernel_now_iso(),
                obligation_kind="import.review.required",
                severity="warn",
                summary="Imported continuity source could not be parsed confidently enough for automatic drafting and requires review.",
                required_record_families=["IMPORTED_EVIDENCE"],
                source_segment_ids=[],
                source_semantic_event_ids=[],
                source_refs=[
                    {
                        "kind": "raw_import_event",
                        "id": raw_payload["raw_event_id"],
                        "path": raw_payload["raw_event_path"],
                        "source_kind": parsed.get("source_kind"),
                        "parser_status": import_profile.get("parser_status"),
                        "confidence_band": import_profile.get("confidence_band"),
                    }
                ],
                metadata={
                    "parser_status": import_profile.get("parser_status"),
                    "confidence_band": import_profile.get("confidence_band"),
                    "source_kind": parsed.get("source_kind"),
                    "contradiction_refs": [],
                },
            )
        )
    artifact_routing = None
    if import_profile.get("snapshot_candidate_eligible"):
        active_run = _load_active_run_with_session_repair(ctx)
        accepted_context = _accepted_context_snapshot(Path(ctx["data_root"]))
        artifact_routing = _route_artifact_boundary(
            ctx=ctx,
            trigger="import-continuity",
            boundary="import-continuity",
            invoke_reason="import_continuity_boundary",
            active_run={**active_run, "session_id": session_id_override or active_run.get("session_id"), "run_id": run_id_override or active_run.get("run_id")},
            accepted_context=accepted_context,
            summary=f"Imported {parsed.get('source_kind')} continuity evidence for {ctx['subject']}.",
            notes=list(parsed.get("warnings") or []),
            source_refs=[
                {
                    "kind": "raw_import_event",
                    "id": raw_payload["raw_event_id"],
                    "path": raw_payload["raw_event_path"],
                    "source_kind": parsed.get("source_kind"),
                    "parser_status": import_profile.get("parser_status"),
                    "confidence_band": import_profile.get("confidence_band"),
                }
            ],
            requested_snapshot_kinds=None,
            requested_publication_candidate_kinds=list(PUBLICATION_CANDIDATE_KINDS)
            if import_profile.get("publication_candidate_eligible")
            else [],
            import_profile=import_profile,
        )
        snapshot_candidate_result = artifact_routing["dispatch"].get("snapshot_candidates") or _snapshot_candidate_boundary_noop(
            data_root=data_root,
            boundary="import-continuity",
            reason="router_no_snapshot_dispatch",
        )
    elif import_profile.get("draftshot_eligible"):
        snapshot_candidate_result = _refresh_snapshot_candidate_boundary(
            ctx=ctx,
            boundary="import-continuity",
            candidate_kinds=[],
            obligation_fallback=False,
            session_id_override=session_id_override,
            run_id_override=run_id_override,
        )
    else:
        snapshot_candidate_result = _snapshot_candidate_boundary_noop(
            data_root=data_root,
            boundary="import-continuity",
            reason="import_confidence_not_permitted",
        )
    if artifact_routing is not None:
        publication_candidate_result = artifact_routing["dispatch"].get("publication_candidates") or _publication_candidate_boundary_noop(
            data_root=data_root,
            boundary="import-continuity",
            reason="router_no_publication_dispatch",
        )
    elif import_profile.get("publication_candidate_eligible"):
        publication_candidate_result = _refresh_publication_candidate_boundary(ctx=ctx, boundary="import-continuity")
    else:
        publication_candidate_result = _publication_candidate_boundary_noop(
            data_root=data_root,
            boundary="import-continuity",
            reason="import_confidence_not_permitted",
        )
    projection = _sync_sidecar(
        subject=ctx["subject"],
        data_root=data_root,
        active_run=_load_active_run_with_session_repair(ctx),
        mutate_proposals=False,
    )
    return {
        "import_profile": import_profile,
        "artifact_routing": artifact_routing,
        "snapshot_candidates": snapshot_candidate_result,
        "publication_candidates": publication_candidate_result,
        "opened_import_review_obligations": import_review_obligations,
        "projection": projection,
    }


def _snapshot_candidate_boundary_noop(
    *,
    data_root: Path,
    boundary: str,
    reason: str,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = snapshot_candidate_summary(data_root)
    return {
        "boundary": boundary,
        "required_kinds": [],
        "target_day": None,
        "decision": dict(decision or {}),
        "draftshot_result": None,
        "draftshot_error": None,
        "snapshot_candidates": {
            "status": "noop",
            "reason": reason,
            "summary": summary,
            "candidates": [],
        },
        "summary": summary,
        "projection": None,
        "opened_obligations": [],
        "resolved_obligations": [],
    }


def _verify_hooks_receipt(ctx: dict[str, Any]) -> dict[str, Any]:
    engine_root = Path(ctx["engine_root"])
    data_root = Path(ctx["data_root"])
    synapse_root = Path(__file__).resolve().parents[1]
    inspection = inspect_git_hooks(engine_root=engine_root, synapse_root=synapse_root)
    if not inspection.get("engine_is_git_repo"):
        return {
            **inspection,
            "git_hooks_status": inspection.get("hooks_status"),
            "hooks_receipt_path": None,
            "projection": None,
            "summary": None,
        }
    now = dt.datetime.now(tz=ZoneInfo("America/Toronto")).isoformat()
    inspection["last_verified_at"] = now
    inspection["installed_at"] = None
    hooks_path = write_hooks_receipt(data_root=data_root, receipt=inspection)
    summary = compute_current_provenance_summary(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        write_projection=False,
    )
    projection = refresh_provenance_projection(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        summary=summary,
    )
    return {
        **inspection,
        "git_hooks_status": inspection.get("hooks_status"),
        "hooks_receipt_path": str(hooks_path.resolve()),
        "projection": projection,
        "summary": summary,
    }


def _install_hooks_receipt(ctx: dict[str, Any], *, force: bool) -> dict[str, Any]:
    engine_root = Path(ctx["engine_root"])
    data_root = Path(ctx["data_root"])
    synapse_root = Path(__file__).resolve().parents[1]
    receipt = install_managed_hooks(engine_root=engine_root, synapse_root=synapse_root, force=force)
    if not receipt.get("engine_is_git_repo"):
        return {
            **receipt,
            "git_hooks_status": receipt.get("hooks_status"),
            "hooks_receipt_path": None,
            "projection": None,
            "summary": None,
        }
    hooks_path = write_hooks_receipt(data_root=data_root, receipt=receipt)
    summary = compute_current_provenance_summary(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        write_projection=False,
    )
    projection = refresh_provenance_projection(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        summary=summary,
    )
    return {
        **receipt,
        "git_hooks_status": receipt.get("hooks_status"),
        "hooks_receipt_path": str(hooks_path.resolve()),
        "projection": projection,
        "summary": summary,
    }


def _safe_load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _accepted_context_snapshot(data_root: Path) -> dict[str, Any]:
    state = _safe_load_yaml_dict(data_root / ".synapse" / "STATE.yaml")
    manifold = _safe_load_yaml_dict(data_root / ".synapse" / "MANIFOLD.yaml")
    return {
        "current_accepted_quest_id": manifold.get("current_accepted_quest_id") or state.get("current_accepted_quest_id"),
        "governed_execution_ready": bool(
            manifold.get("governed_execution_ready")
            if "governed_execution_ready" in manifold
            else state.get("governed_execution_ready")
        ),
        "active_order_ids": list(manifold.get("active_order_candidates") or []),
    }


def _compact_plan_items(items: Any) -> list[str]:
    results: list[str] = []
    if not isinstance(items, list):
        return results
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                results.append(text)
                continue
        text = str(item).strip()
        if text:
            results.append(text)
    return results


def _runtime_status(
    *,
    operation_status: str,
    primary_mutation_committed: bool,
    event_recorded: bool,
    derived_state_current: bool,
    event_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    recovery_hint: str | None = None,
) -> dict[str, Any]:
    return {
        "operation_status": operation_status,
        "primary_mutation_committed": primary_mutation_committed,
        "event_recorded": event_recorded,
        "derived_state_current": derived_state_current,
        "event_id": event_id,
        "error_code": error_code,
        "error_message": error_message,
        "recovery_hint": recovery_hint,
    }


def _empty_reducer_receipt() -> dict[str, Any]:
    return {
        "mode": reducer_mode(),
        "reducer_version": REDUCER_VERSION,
        "event_id": None,
        "sidecar": None,
        "rehydrate": None,
        "continuity": None,
    }


def _print_partial_runtime_status(runtime_status: dict[str, Any], *, stream) -> None:
    print("PARTIAL:", file=stream)
    print(f"- primary_mutation_committed: {'YES' if runtime_status.get('primary_mutation_committed') else 'NO'}", file=stream)
    print(f"- event_recorded: {'YES' if runtime_status.get('event_recorded') else 'NO'}", file=stream)
    print(f"- derived_state_current: {'YES' if runtime_status.get('derived_state_current') else 'NO'}", file=stream)
    if runtime_status.get("event_id"):
        print(f"- event_id: {runtime_status.get('event_id')}", file=stream)
    if runtime_status.get("error_code"):
        print(f"- error_code: {runtime_status.get('error_code')}", file=stream)
    if runtime_status.get("error_message"):
        print(f"- error_message: {runtime_status.get('error_message')}", file=stream)
    if runtime_status.get("recovery_hint"):
        print(f"- recovery_hint: {runtime_status.get('recovery_hint')}", file=stream)


def _finalize_mutation_result(
    *,
    payload: dict[str, Any],
    event_info: dict[str, Any] | None,
    json_mode: bool,
    text_emitter,
    shell_mode: bool = False,
) -> int:
    runtime_status = event_info.get("runtime_status") if event_info else None
    if runtime_status is not None:
        payload["runtime_status"] = runtime_status
    exit_code = 3 if runtime_status and runtime_status.get("operation_status") == "partial" else 0
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code
    text_emitter(payload)
    if runtime_status and runtime_status.get("operation_status") == "partial":
        _print_partial_runtime_status(runtime_status, stream=sys.stderr if shell_mode else sys.stdout)
    return exit_code


def _partial_after_primary_mutation(
    *,
    error_code: str,
    error_message: str,
    recovery_hint: str,
) -> dict[str, Any]:
    return {
        "event": None,
        "reducer": _empty_reducer_receipt(),
        "runtime_status": _runtime_status(
            operation_status="partial",
            primary_mutation_committed=True,
            event_recorded=False,
            derived_state_current=False,
            error_code=error_code,
            error_message=error_message,
            recovery_hint=recovery_hint,
        ),
    }


def _event_pipeline(
    *,
    ctx: dict[str, Any],
    action_name: str,
    summary: str,
    signals: dict[str, Any],
    truth_flags: dict[str, Any],
    outputs: dict[str, Any],
    status: str = "ok",
    refresh_continuity: bool = True,
    session_id: str | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    session_id = _normalize_session_id(session_id) or _normalize_session_id(ctx.get("session_id"))
    run_id = str(outputs.get("run_id") or signals.get("run_id") or "").strip() or None
    base_reducer = _empty_reducer_receipt()
    try:
        event = build_event(
            subject=ctx["subject"],
            action_name=action_name,
            summary=summary,
            status=status,
            session_id=session_id,
            run_id=run_id,
            signals=signals,
            truth_flags=truth_flags,
            outputs=outputs,
        )
    except Exception as exc:
        return {
            "event": None,
            "reducer": base_reducer,
            "runtime_status": _runtime_status(
                operation_status="partial",
                primary_mutation_committed=True,
                event_recorded=False,
                derived_state_current=False,
                error_code="EVENT_APPEND_FAILED",
                error_message=str(exc),
                recovery_hint="Primary mutation committed, but no event was recorded. Repair the event spine, then rerun the relevant refresh or inspect the mutated artifact directly.",
            ),
        }
    try:
        append_receipt = append_event(data_root=data_root, event=event)
    except EventLogError as exc:
        return {
            "event": None,
            "reducer": base_reducer,
            "runtime_status": _runtime_status(
                operation_status="partial",
                primary_mutation_committed=True,
                event_recorded=False,
                derived_state_current=False,
                error_code="EVENT_APPEND_FAILED",
                error_message=str(exc),
                recovery_hint="Primary mutation committed, but event append failed. Repair the event log and rerun a refresh command so derived state catches up.",
            ),
        }

    mode = base_reducer["mode"]
    base_reducer["event_id"] = append_receipt["event_id"]
    if mode == "legacy":
        try:
            legacy_refresh = _render_and_refresh_continuity(ctx["subject"], data_root, engine_root)
        except LiveMemoryError as exc:
            return {
                "event": {"receipt": append_receipt, "payload": event},
                "reducer": base_reducer,
                "runtime_status": _runtime_status(
                    operation_status="partial",
                    primary_mutation_committed=True,
                    event_recorded=True,
                    derived_state_current=False,
                    event_id=append_receipt["event_id"],
                    error_code="REDUCER_REFRESH_FAILED",
                    error_message=str(exc),
                    recovery_hint="The event was recorded, but derived state/continuity refresh failed. Rerun render-rehydrate or repair the reducer path before continuing.",
                ),
            }
        return {
            "event": {"receipt": append_receipt, "payload": event},
            "reducer": {
                "mode": "legacy",
                "reducer_version": REDUCER_VERSION,
                "event_id": append_receipt["event_id"],
                "sidecar": None,
                "rehydrate": legacy_refresh["rehydrate"],
                "continuity": legacy_refresh["continuity"],
            },
            "runtime_status": _runtime_status(
                operation_status="ok",
                primary_mutation_committed=True,
                event_recorded=True,
                derived_state_current=True,
                event_id=append_receipt["event_id"],
            ),
        }

    try:
        reduction = reduce_after_event(
            subject=ctx["subject"],
            data_root=data_root,
            engine_root=engine_root,
            event=event,
            refresh_continuity=refresh_continuity,
        )
    except ReducerError as exc:
        return {
            "event": {"receipt": append_receipt, "payload": event},
            "reducer": base_reducer,
            "runtime_status": _runtime_status(
                operation_status="partial",
                primary_mutation_committed=True,
                event_recorded=True,
                derived_state_current=False,
                event_id=append_receipt["event_id"],
                error_code="REDUCER_REFRESH_FAILED",
                error_message=str(exc),
                recovery_hint="The event was recorded, but reducer-owned state is stale. Repair the reducer failure, then rerun render-rehydrate or the relevant refresh path.",
            ),
        }

    result = {
        "event": {"receipt": append_receipt, "payload": event},
        "reducer": reduction,
        "runtime_status": _runtime_status(
            operation_status="ok",
            primary_mutation_committed=True,
            event_recorded=True,
            derived_state_current=True,
            event_id=append_receipt["event_id"],
        ),
    }
    return result


def _core_subject_artifacts_present(receipt: dict[str, Any]) -> bool:
    subject = str(receipt["subject"])
    data_root = Path(str(receipt["data_root"])).expanduser().resolve()
    if not data_root.exists():
        return False
    if not (data_root / "SUBJECT_STATE.yaml").exists():
        return False
    buff_prefix = subject.upper()
    for name in (
        f"{buff_prefix}_EXECUTION_PROTOCOL.txt",
        f"{buff_prefix}_DATA_DIRECTORY_MAP.txt",
        f"{buff_prefix}_SESSION_START_CHECK.txt",
    ):
        if not (data_root / "Buffs" / name).exists():
            return False
    rehydration_dir = data_root / "Latest Rehydration Pack"
    if not rehydration_dir.exists():
        return False
    if not list(rehydration_dir.glob("*BOOTSTRAP_PROMPT*")):
        return False
    if not list(rehydration_dir.glob("*CONTINUITY_LOCK*")):
        return False
    return True


def _maybe_persist_subject_cursor(receipt: dict[str, Any], args: argparse.Namespace, *, source_detail: str) -> dict[str, Any]:
    selection_method = str(receipt.get("selection_method") or "").strip()
    should_persist = selection_method in {"flag", "env", "inferred"} or source_detail == "attach_or_init"
    if not should_persist:
        return receipt
    return write_focus_lock(
        subject=receipt["subject"],
        data_root=receipt["data_root"],
        engine_root=receipt["engine_root"],
        selected_by=getattr(args, "selected_by", "Brains"),
        selection_method=selection_method or "auto_attach",
        source_detail=source_detail,
        write_home_lock=not getattr(args, "no_home_lock", False),
        session_id=_resolved_session_id(args),
    )


def _resolve_or_attach_subject_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    home = Path.home().resolve()
    auto_initialized = False
    init_receipt = {"created": [], "existing": []}
    live_receipt = {"created": [], "existing": [], "live_root": "", "required_paths": {}}

    try:
        receipt = resolve_subject(
            subject_flag=getattr(args, "subject", None),
            data_root_flag=getattr(args, "data_root", None),
            engine_root_flag=getattr(args, "engine_root", None),
            allow_switch=getattr(args, "allow_switch", False),
            session_id=_resolved_session_id(args),
        )
        receipt = _maybe_persist_subject_cursor(receipt, args, source_detail="attach_or_resume")
    except SubjectResolutionError:
        cwt = detect_canonical_working_tree()
        if getattr(args, "subject", None):
            selection = _apply_root_overrides({"subject": str(args.subject).strip()}, args, home)
        else:
            selection = _apply_root_overrides(repo_subject_defaults(cwt), args, home)
        receipt = write_focus_lock(
            subject=selection["subject"],
            data_root=selection["data_root"],
            engine_root=selection["engine_root"],
            selected_by=getattr(args, "selected_by", "Brains"),
            selection_method="auto_attach",
            source_detail="attach_or_init",
            write_home_lock=not getattr(args, "no_home_lock", False),
            session_id=_resolved_session_id(args),
        )

    data_root = Path(str(receipt["data_root"])).expanduser().resolve()
    engine_root = Path(str(receipt["engine_root"])).expanduser().resolve()
    if not _core_subject_artifacts_present(receipt):
        init_receipt = initialize_subject_state(receipt["subject"], data_root, engine_root)
        auto_initialized = True
    live_receipt = ensure_live_scaffold(receipt["subject"], data_root)
    receipt["live_root"] = live_receipt.get("live_root")
    receipt["required_paths"] = live_receipt.get("required_paths", {})
    receipt["initialized_created"] = init_receipt.get("created", [])
    receipt["initialized_existing"] = init_receipt.get("existing", [])
    receipt["live_created"] = live_receipt.get("created", [])
    receipt["live_existing"] = live_receipt.get("existing", [])
    receipt["auto_initialized"] = auto_initialized
    return receipt


def _try_resolve_subject_without_attach(args: argparse.Namespace) -> dict[str, Any] | None:
    try:
        receipt = resolve_subject(
            subject_flag=getattr(args, "subject", None),
            data_root_flag=getattr(args, "data_root", None),
            engine_root_flag=getattr(args, "engine_root", None),
            allow_switch=getattr(args, "allow_switch", False),
            session_id=_resolved_session_id(args),
        )
    except SubjectResolutionError:
        return None
    return _maybe_persist_subject_cursor(receipt, args, source_detail="attach_or_resume")


def _git_status_changed_files(cwt: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=str(cwt),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        raw = line[3:].strip()
        if not raw:
            continue
        files.append(raw)
    return files


def _watch_without_subject(args: argparse.Namespace, *, iterations: int) -> int:
    payloads: list[dict[str, Any]] = []
    last_files: list[str] = []
    for idx in range(iterations):
        files = _git_status_changed_files(detect_canonical_working_tree()) if args.capture_git else []
        changed_files = [item for item in files if item not in last_files]
        payloads.append(
            {
                "iteration": idx + 1,
                "changed_files": changed_files,
                "provenance": {
                    "provenance_status": "not_applicable",
                },
            }
        )
        last_files = files
        if idx < iterations - 1:
            time.sleep(max(args.interval, 0.1))

    if args.json:
        print(json.dumps({"subject": None, "ticks": payloads}, indent=2, sort_keys=True))
        return 0

    print("=== WATCH RECEIPT ===")
    print(f"iterations: {iterations}")
    print(f"captured_ticks: {len(payloads)}")
    print("provenance_status: not_applicable")
    return 0


def _print_noninteractive_focus_help(command_name: str, candidates: list[dict[str, str]]) -> None:
    print(f"FAIL: `{command_name}` requires interactive selection when no `--subject` is provided.")
    if candidates:
        print("Detected subject candidates:")
        for item in candidates:
            print(f"- {item['subject']} [{item['data_root']}]")
    else:
        print("Detected subject candidates: none")
    print("Use one of:")
    print("- python3 runtime/synapse.py engage")
    print("- python3 runtime/synapse.py focus --subject <SUBJECT>")


def _print_noninteractive_engage_help(candidates: list[dict[str, str]]) -> None:
    print("FAIL: subject is unresolved.")
    if candidates:
        print("Detected subject candidates:")
        for item in candidates:
            print(f"- {item['subject']} [{item['data_root']}]")
    else:
        print("Detected subject candidates: none")
    print("Use one of:")
    print("- python3 runtime/synapse.py engage")
    print("- python3 runtime/synapse.py focus --subject <SUBJECT>")


def _print_noninteractive_engage_active_help(active_subject: str) -> None:
    print("FAIL: non-interactive engage requires explicit intent when an active subject already exists.")
    print(f"active_subject: {active_subject}")
    print("Choose one:")
    print("- continue active lock: python3 runtime/synapse.py engage --continue-active [--shell|--json]")
    print("- new/change subject from current repo: python3 runtime/synapse.py engage --adopt-current-repo [--shell|--json]")
    print("- interactive menu: python3 runtime/synapse.py engage")


def _today_toronto() -> str:
    return _today_toronto_impl()


def _slugify(value: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    if not slug:
        return "task"
    return slug[:max_len].strip("-") or "task"


def _load_quest_template(cwt: Path) -> str:
    return _load_quest_template_impl(cwt)


def _replace_line(lines: list[str], prefix: str, value: str) -> None:
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = f"{prefix} {value}".rstrip()
            return


def _insert_after_contains(lines: list[str], needle: str, content: str) -> None:
    for idx, line in enumerate(lines):
        if needle in line:
            lines.insert(idx + 1, content)
            return


def _fill_quest_template(template: str, values: dict[str, str]) -> str:
    return _fill_quest_template_impl(template, values)


def _next_quest_number(data_root: Path, prefix: str) -> int:
    return _next_quest_number_impl(data_root, prefix)


def _load_plan_items(items: list[str], items_file: str | None) -> list[str]:
    output = [item.strip() for item in items if item.strip()]
    if items_file:
        path = Path(items_file)
        if not path.exists():
            raise FileNotFoundError(f"Plan items file not found: {items_file}")
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            output.append(line)
    return output


def _input_line(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError as exc:
        raise SubjectResolutionError("Interactive selection cancelled (stdin closed).") from exc


def _repo_adoption_defaults(cwt: Path) -> dict[str, str]:
    repo_name = cwt.name.strip()
    if not repo_name:
        raise SubjectResolutionError("Cannot derive subject from current repository root (empty name).")
    if is_placeholder_subject(repo_name):
        raise SubjectResolutionError(
            f"Current repository name '{repo_name}' resolves to a reserved placeholder subject. "
            "Use `--subject <SUBJECT>` with explicit --data-root/--engine-root."
        )
    return {
        "subject": repo_name,
        "data_root": str((cwt.parent / f"{repo_name}_Data").resolve()),
        "engine_root": str(cwt.resolve()),
    }


def _subject_default_roots(subject: str, cwt: Path, home: Path) -> tuple[Path, Path]:
    if (cwt / ".git").exists():
        return (cwt.parent / f"{subject}_Data").resolve(), cwt.resolve()
    return (home / f"{subject}_Data").resolve(), cwt.resolve()


def _apply_root_overrides(selected: dict[str, Any], args: argparse.Namespace, home: Path) -> dict[str, str]:
    cwt = detect_canonical_working_tree()
    subject = str(selected["subject"]).strip()
    default_data_root, default_engine_root = _subject_default_roots(subject, cwt, home)
    data_root = args.data_root or selected.get("data_root") or str(default_data_root)
    engine_root = args.engine_root or selected.get("engine_root") or str(default_engine_root)
    return {
        "subject": subject,
        "data_root": str(Path(str(data_root)).expanduser().resolve()),
        "engine_root": str(Path(str(engine_root)).expanduser().resolve()),
    }


def _choose_subject_from_candidates(candidates: list[dict[str, str]]) -> dict[str, str]:
    if not candidates:
        raise SubjectResolutionError("No *_Data subjects found in $HOME. Choose create new subject instead.")
    print("Detected subjects:")
    for idx, item in enumerate(candidates, start=1):
        print(f"{idx}) {item['subject']} [{item['data_root']}]")
    raw = _input_line("Select subject number: ").strip()
    try:
        pos = int(raw)
    except Exception as exc:
        raise SubjectResolutionError("Invalid subject selection.") from exc
    if pos < 1 or pos > len(candidates):
        raise SubjectResolutionError("Subject selection out of range.")
    return candidates[pos - 1]


def _create_subject_scaffold(home: Path) -> dict[str, str]:
    subject = _input_line("New subject key (e.g. ProductX): ").strip()
    if is_placeholder_subject(subject):
        raise SubjectResolutionError(
            "Reserved placeholder subject keys are not allowed. Choose a real subject key."
        )
    data_root = (home / f"{subject}_Data").resolve()
    engine_root = (home / f"{subject}_Engine").resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    engine_root.mkdir(parents=True, exist_ok=True)
    return {"subject": subject, "data_root": str(data_root), "engine_root": str(engine_root)}


def _interactive_new_or_change_selection(home: Path, args: argparse.Namespace, candidates: list[dict[str, str]]) -> dict[str, Any] | None:
    cwt = detect_canonical_working_tree()
    repo_defaults = _repo_adoption_defaults(cwt)

    print("New / Change subject:")
    print(f"1) adopt current repo [{repo_defaults['subject']}]")
    print("2) choose existing subject")
    print("3) create new subject (legacy scaffold)")
    print("4) cancel")
    choice = _input_line("> ").strip()

    if choice == "1":
        return {
            **_apply_root_overrides(repo_defaults, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_adopt_repo",
        }
    if choice == "2":
        picked = _choose_subject_from_candidates(candidates)
        return {
            **_apply_root_overrides(picked, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_switch",
        }
    if choice == "3":
        picked = _create_subject_scaffold(home)
        return {
            **_apply_root_overrides(picked, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_create",
        }
    if choice == "4":
        return None
    raise SubjectResolutionError("Invalid New / Change selection.")


def _interactive_engage_selection(home: Path, args: argparse.Namespace) -> dict[str, Any] | None:
    candidates = detect_subject_candidates(home)
    current = None
    current_error = None
    if load_active_focus_lock(session_id=getattr(args, "session_id", None)):
        try:
            current = resolve_subject(session_id=getattr(args, "session_id", None))
        except SubjectResolutionError as exc:
            current_error = str(exc)

    if current_error:
        print(f"NOTE: {current_error}")

    if current:
        print("Session start:")
        print(f"[Enter]/1) Continue active subject {current['subject']}")
        print("2) New / Change subject")
        print("3) cancel")
        choice = _input_line("> ").strip()
        if choice in {"", "1"}:
            return {
                **_apply_root_overrides(current, args, home),
                "selection_method": "lockfile",
                "source_detail": current.get("source_detail", "lockfile"),
            }
        if choice == "2":
            return _interactive_new_or_change_selection(home, args, candidates)
        if choice == "3":
            return None
        raise SubjectResolutionError("Invalid session-start selection.")

    repo_defaults = _repo_adoption_defaults(detect_canonical_working_tree())
    if candidates:
        print("Session start:")
        print(f"1) adopt current repo [{repo_defaults['subject']}]")
        print("2) choose existing subject")
        print("3) create new subject (legacy scaffold)")
        print("4) cancel")
        choice = _input_line("> ").strip()
        if choice == "1":
            return {
                **_apply_root_overrides(repo_defaults, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_adopt_repo",
            }
        if choice == "2":
            selected = _choose_subject_from_candidates(candidates)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_select",
            }
        if choice == "3":
            selected = _create_subject_scaffold(home)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_create",
            }
        if choice == "4":
            return None
        raise SubjectResolutionError("Invalid session-start selection.")

    print("Session start:")
    print(f"1) adopt current repo [{repo_defaults['subject']}]")
    print("2) create new subject (legacy scaffold)")
    print("3) cancel")
    choice = _input_line("> ").strip()
    if choice == "1":
        return {
            **_apply_root_overrides(repo_defaults, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_adopt_repo",
        }
    if choice == "2":
        selected = _create_subject_scaffold(home)
        return {
            **_apply_root_overrides(selected, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_create",
        }
    if choice == "3":
        return None
    raise SubjectResolutionError("Invalid session-start selection.")


def _write_subject_lock_from_selection(selection: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return write_focus_lock(
        subject=selection["subject"],
        data_root=selection["data_root"],
        engine_root=selection["engine_root"],
        selected_by=args.selected_by,
        selection_method=selection["selection_method"],
        source_detail=selection["source_detail"],
        write_home_lock=not args.no_home_lock,
        session_id=getattr(args, "session_id", None),
    )


def _initialize_adopted_subject_state(subject: str, data_root: Path, engine_root: Path) -> dict[str, list[str]]:
    return initialize_subject_state(subject, data_root, engine_root)


def _adopt_current_repo_receipt(args: argparse.Namespace) -> dict[str, Any]:
    home = Path.home().resolve()
    explicit_session_id = _resolved_session_id(args)
    repo_defaults = _repo_adoption_defaults(detect_canonical_working_tree())
    selection = _apply_root_overrides(repo_defaults, args, home)
    init_receipt = _initialize_adopted_subject_state(
        selection["subject"],
        Path(selection["data_root"]),
        Path(selection["engine_root"]),
    )
    selection["selection_method"] = "flag"
    selection["source_detail"] = "engage_adopt_repo"
    if explicit_session_id:
        receipt = _write_subject_lock_from_selection(selection, args)
    else:
        repo_lock_args = argparse.Namespace(**vars(args))
        repo_lock_args.session_id = None
        receipt = _write_subject_lock_from_selection(selection, repo_lock_args)
        generated_session_id = _ensure_generated_session_id(args)
        receipt["session_id"] = generated_session_id
        receipt["session_lockfile"] = str(session_focus_lock_path(generated_session_id, Path.home().resolve()).resolve())
    receipt["initialized_created"] = init_receipt["created"]
    receipt["initialized_existing"] = init_receipt["existing"]
    bridges = ensure_subject_repo_bridges(
        subject=receipt["subject"],
        repo_root=Path(selection["engine_root"]),
        data_root=Path(selection["data_root"]),
        synapse_root=resolve_synapse_root(),
    )
    receipt["subject_repo_bridges"] = bridges
    receipt["subject_repo_bridge"] = bridges["AGENTS.md"]
    mark_adopted_existing_repo(subject=receipt["subject"], data_root=Path(receipt["data_root"]))
    return receipt


def _emit_adopted_repo_engage(args: argparse.Namespace) -> int:
    receipt = _adopt_current_repo_receipt(args)
    bootstrap_payload, event_info = _run_onboarding_bootstrap(ctx=receipt)
    payload = {
        **receipt,
        **_readiness_payload(Path(receipt["data_root"])),
        "onboarding_bootstrap": bootstrap_payload,
    }
    runtime_status = event_info.get("runtime_status") if event_info else None
    exit_code = 3 if runtime_status and runtime_status.get("operation_status") == "partial" else 0
    if runtime_status is not None:
        payload["runtime_status"] = runtime_status
    if args.shell:
        _subject_receipt_to_shell(receipt)
        if runtime_status and runtime_status.get("operation_status") == "partial":
            _print_partial_runtime_status(runtime_status, stream=sys.stderr)
        return exit_code
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code
    _print_subject_receipt(receipt)
    print(f"onboarding_required: {payload.get('onboarding_required')}")
    print(f"continuity_ready: {payload.get('continuity_ready')}")
    print(f"onboarding_state: {bootstrap_payload.get('onboarding_state') or bootstrap_payload.get('state') or 'none'}")
    print(f"active_onboarding_id: {bootstrap_payload.get('onboarding_id') or bootstrap_payload.get('active_onboarding_id') or 'none'}")
    bridge = receipt.get("subject_repo_bridge") or {}
    if bridge:
        print(f"subject_repo_bridge: {bridge.get('bridge_status')} [{bridge.get('bridge_path')}]")
    return exit_code


def _current_repo_is_clear_subject() -> bool:
    cwt = detect_canonical_working_tree()
    return (cwt / ".git").exists()


def _run_onboarding_bootstrap(
    *,
    ctx: dict[str, Any],
    depth: str = "deep",
    rescan: bool = False,
    restart: bool = False,
    allow_switch_for_run: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    active_run, session_id = _require_onboarding_context(
        ctx=ctx,
        action_name="onboard-repo",
        allow_create_onboard_run=True,
        allow_replace_onboard_run=allow_switch_for_run,
    )
    result = onboard_repo(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        engine_root=Path(ctx["engine_root"]),
        active_run=active_run,
        depth=depth,
        rescan=rescan,
        restart=restart,
    )
    readiness = _readiness_payload(Path(ctx["data_root"]))
    payload = {
        **result,
        **readiness,
        "active_session_mode": active_run.get("session_mode"),
        "active_run_id": active_run.get("run_id"),
    }
    if result.get("resumed_existing") or result.get("already_completed"):
        return payload, None

    written_artifacts = [
        str(item)
        for item in [
            result.get("session_path"),
            result.get("pointer_path"),
            result.get("scan_artifact_path"),
            result.get("analysis_brief_path"),
        ]
        if str(item or "").strip()
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboard-repo",
        summary=f"Prepared onboarding scan {result.get('scan_id')} for {ctx['subject']}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "scan_id": result.get("scan_id"),
            "changed_files": written_artifacts,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "scan_id": result.get("scan_id"),
            "scan_artifact_path": result.get("scan_artifact_path"),
            "analysis_brief_path": result.get("analysis_brief_path"),
            "session_path": result.get("session_path"),
            "pointer_path": result.get("pointer_path"),
        },
    )
    payload["event"] = event_info["event"]
    payload["reducer"] = event_info["reducer"]
    payload["rehydrate"] = event_info["reducer"]["rehydrate"]
    payload["continuity"] = event_info["reducer"]["continuity"]
    return payload, event_info


def _next_onboarding_action(state: str | None) -> str | None:
    value = str(state or "").strip()
    if value in {"needs_draft_submission", "needs_draft_revision"}:
        return "onboarding-update"
    if value == "awaiting_user_clarification":
        return "onboarding-respond"
    if value == "awaiting_confirmation":
        return "onboarding-confirm"
    if value:
        return "onboard-repo"
    return None


def cmd_attach_existing_repo(args: argparse.Namespace) -> int:
    try:
        receipt = _adopt_current_repo_receipt(args)
        doctor_stream = io.StringIO()
        with contextlib.redirect_stdout(doctor_stream):
            doctor_exit_code = run_doctor(None, receipt)
        bootstrap_payload, event_info = _run_onboarding_bootstrap(
            ctx=receipt,
            depth="deep",
            rescan=False,
            restart=False,
            allow_switch_for_run=True,
        )
    except (SubjectResolutionError, LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    payload = {
        **receipt,
        **_readiness_payload(Path(receipt["data_root"])),
        "doctor_exit_code": doctor_exit_code,
        "doctor_ready": doctor_exit_code == 0,
        "doctor_report": doctor_stream.getvalue(),
        "onboarding_bootstrap": bootstrap_payload,
        "next_required_action": _next_onboarding_action(
            bootstrap_payload.get("onboarding_state") or bootstrap_payload.get("state")
        ),
    }
    runtime_status = event_info.get("runtime_status") if event_info else None
    exit_code = 3 if runtime_status and runtime_status.get("operation_status") == "partial" else 0
    if runtime_status is not None:
        payload["runtime_status"] = runtime_status
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code
    print("=== ATTACH EXISTING REPO ===")
    _print_subject_receipt(receipt)
    print(f"doctor_ready: {payload.get('doctor_ready')}")
    print(f"onboarding_required: {payload.get('onboarding_required')}")
    print(f"continuity_ready: {payload.get('continuity_ready')}")
    print(f"onboarding_state: {bootstrap_payload.get('onboarding_state') or bootstrap_payload.get('state') or 'none'}")
    print(f"next_required_action: {payload.get('next_required_action') or 'none'}")
    if runtime_status and runtime_status.get("operation_status") == "partial":
        _print_partial_runtime_status(runtime_status)
    return exit_code


def cmd_focus(args: argparse.Namespace) -> int:
    home = Path.home().resolve()

    try:
        if args.subject:
            subject = args.subject.strip()
            selection = _apply_root_overrides({"subject": subject}, args, home)
            receipt = write_focus_lock(
                subject=selection["subject"],
                data_root=selection["data_root"],
                engine_root=selection["engine_root"],
                selected_by=args.selected_by,
                selection_method="flag",
                source_detail="flag",
                write_home_lock=not args.no_home_lock,
                session_id=args.session_id,
            )
            _print_subject_receipt(receipt)
            return 0

        if not _stdin_is_interactive():
            _print_noninteractive_focus_help("python3 runtime/synapse.py focus", detect_subject_candidates(home))
            return 2

        current = None
        if load_active_focus_lock(session_id=args.session_id):
            try:
                current = resolve_subject(allow_switch=False, session_id=args.session_id)
            except SubjectResolutionError as exc:
                print(f"NOTE: {exc}")

        candidates = detect_subject_candidates(home)
        if current:
            print("Focus menu:")
            print(f"[Enter]/1) continue with {current['subject']}")
            print("2) switch subject")
            print("3) create new subject")
            print("4) cancel")
            choice = _input_line("> ").strip()
            if choice in {"", "1"}:
                selected = {
                    **_apply_root_overrides(current, args, home),
                    "selection_method": "lockfile",
                    "source_detail": current.get("source_detail", "lockfile"),
                }
            elif choice == "2":
                picked = _choose_subject_from_candidates(candidates)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_switch",
                }
            elif choice == "3":
                picked = _create_subject_scaffold(home)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_create",
                }
            elif choice == "4":
                print("CANCELLED")
                return 130
            else:
                raise SubjectResolutionError("Invalid focus selection.")
        else:
            print("Focus menu:")
            print("1) choose existing subject")
            print("2) create new subject")
            print("3) cancel")
            choice = _input_line("> ").strip()
            if choice == "1":
                picked = _choose_subject_from_candidates(candidates)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_select",
                }
            elif choice == "2":
                picked = _create_subject_scaffold(home)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_create",
                }
            elif choice == "3":
                print("CANCELLED")
                return 130
            else:
                raise SubjectResolutionError("Invalid focus selection.")

        receipt = _write_subject_lock_from_selection(selected, args)
        _print_subject_receipt(receipt)
        return 0
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        return 2


def cmd_engage(args: argparse.Namespace) -> int:
    home = Path.home().resolve()

    try:
        if args.continue_active and args.adopt_current_repo:
            print("FAIL: --continue-active and --adopt-current-repo are mutually exclusive.")
            return 2

        if args.subject:
            selection = _apply_root_overrides({"subject": args.subject.strip()}, args, home)
            selection["selection_method"] = "flag"
            selection["source_detail"] = "flag"
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        if args.continue_active:
            active_lock = load_active_focus_lock(session_id=args.session_id)
            if not active_lock:
                print("FAIL: --continue-active requires an existing active subject lock.")
                return 2
            receipt = resolve_subject(allow_switch=False, session_id=args.session_id)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        if args.adopt_current_repo:
            return _emit_adopted_repo_engage(args)

        if _stdin_is_interactive():
            selection = _interactive_engage_selection(home, args)
            if selection is None:
                print("CANCELLED")
                return 130
            if selection.get("source_detail") == "interactive_adopt_repo":
                _ensure_generated_session_id(args)
                _initialize_adopted_subject_state(
                    selection["subject"],
                    Path(selection["data_root"]),
                    Path(selection["engine_root"]),
                )
            receipt = _write_subject_lock_from_selection(selection, args)
            if selection.get("source_detail") == "interactive_adopt_repo":
                mark_adopted_existing_repo(subject=receipt["subject"], data_root=Path(receipt["data_root"]))
                bootstrap_payload, event_info = _run_onboarding_bootstrap(ctx=receipt)
                payload = {
                    **receipt,
                    **_readiness_payload(Path(receipt["data_root"])),
                    "onboarding_bootstrap": bootstrap_payload,
                }
                runtime_status = event_info.get("runtime_status") if event_info else None
                exit_code = 3 if runtime_status and runtime_status.get("operation_status") == "partial" else 0
                if args.json:
                    if runtime_status is not None:
                        payload["runtime_status"] = runtime_status
                    print(json.dumps(payload, indent=2, sort_keys=True))
                    return exit_code
                _print_subject_receipt(receipt)
                print(f"onboarding_required: {payload.get('onboarding_required')}")
                print(f"continuity_ready: {payload.get('continuity_ready')}")
                print(f"onboarding_state: {bootstrap_payload.get('onboarding_state') or bootstrap_payload.get('state') or 'none'}")
                print(f"active_onboarding_id: {bootstrap_payload.get('onboarding_id') or bootstrap_payload.get('active_onboarding_id') or 'none'}")
                if runtime_status and runtime_status.get("operation_status") == "partial":
                    _print_partial_runtime_status(runtime_status)
                return exit_code
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        if _current_repo_is_clear_subject():
            return _emit_adopted_repo_engage(args)

        active_lock = load_active_focus_lock(session_id=args.session_id)
        if active_lock:
            receipt = resolve_subject(allow_switch=False, session_id=args.session_id)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        candidates = detect_subject_candidates(home)
        if len(candidates) == 1:
            selection = {
                **_apply_root_overrides(candidates[0], args, home),
                "selection_method": "inferred",
                "source_detail": "single_candidate",
            }
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        _print_noninteractive_engage_help(candidates)
        return 2
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        return 2


def cmd_governance_map(args: argparse.Namespace) -> int:
    cwt = detect_canonical_working_tree()
    try:
        governance_root = resolve_governance_root(args.governance_root)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2
    payload = build_governance_inventory(governance_root)

    output_path = None
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (cwt / output_path).resolve()
        write_governance_inventory(output_path, payload)

    if args.json or not output_path:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== GOVERNANCE MAP RECEIPT ===")
    print(f"governance_root: {payload['governance_root']}")
    print(f"doc_count: {payload['summary']['doc_count']}")
    print(f"contradiction_count: {payload['summary']['contradiction_count']}")
    print(f"output: {output_path}")
    return 0


def cmd_attach_or_init(args: argparse.Namespace) -> int:
    try:
        receipt = _resolve_or_attach_subject_from_args(args)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    attachment_changed = bool(receipt.get("auto_initialized") or receipt.get("initialized_created") or receipt.get("live_created"))
    event_info = None
    if attachment_changed:
        try:
            event_info = _event_pipeline(
                ctx=receipt,
                action_name="attach-or-init",
                summary="Attached subject and initialized canonical runtime surfaces.",
                signals={
                    "selection_method": receipt.get("selection_method"),
                    "source_detail": receipt.get("source_detail"),
                    "initialized_created": list(receipt.get("initialized_created") or []),
                    "live_created": list(receipt.get("live_created") or []),
                    "accepted_context": _accepted_context_snapshot(Path(receipt["data_root"])),
                    "related_quest_ids": [],
                    "related_sidequest_ids": [],
                    "changed_files": [],
                    "verification_entries": [],
                },
                truth_flags={
                    "canon_mutated": bool(receipt.get("auto_initialized")),
                    "derived_state_changed": True,
                    "governed": False,
                    "uncertainty_present": False,
                },
                outputs={
                    "data_root": receipt.get("data_root"),
                    "engine_root": receipt.get("engine_root"),
                    "initialized_created": list(receipt.get("initialized_created") or []),
                    "live_created": list(receipt.get("live_created") or []),
                },
            )
            receipt.update(event_info)
            if event_info["reducer"].get("rehydrate") is not None:
                receipt["rehydrate"] = event_info["reducer"]["rehydrate"]
            if event_info["reducer"].get("continuity") is not None:
                receipt["continuity"] = event_info["reducer"]["continuity"]
        except LiveMemoryError as exc:
            print(f"FAIL: {exc}")
            return 2

    def _emit_attach_or_init(payload: dict[str, Any]) -> None:
        if args.shell:
            _emit_subject_output(payload, json_mode=False, shell_mode=True)
            return
        print("=== ATTACH / INIT RECEIPT ===")
        _print_subject_receipt(payload)
        print(f"auto_initialized: {'YES' if payload.get('auto_initialized') else 'NO'}")
        print(f"live_root: {payload.get('live_root')}")
        if payload.get("initialized_created"):
            print("initialized_created:")
            for path in payload["initialized_created"]:
                print(f"- {path}")
        if payload.get("live_created"):
            print("live_created:")
            for path in payload["live_created"]:
                print(f"- {path}")

    if attachment_changed:
        return _finalize_mutation_result(
            payload=receipt,
            event_info=event_info,
            json_mode=args.json,
            text_emitter=_emit_attach_or_init,
            shell_mode=args.shell,
        )

    if args.shell or args.json:
        _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
        return 0
    _emit_attach_or_init(receipt)
    return 0


def cmd_resolve_subject(args: argparse.Namespace) -> int:
    try:
        receipt = resolve_subject(
            subject_flag=args.subject,
            data_root_flag=args.data_root,
            engine_root_flag=args.engine_root,
            allow_switch=args.allow_switch,
            session_id=args.session_id,
        )
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
    return 0


def cmd_persona(args: argparse.Namespace) -> int:
    receipt = resolve_persona()
    if args.shell:
        print(f"PERSONA_ID={receipt['PERSONA_ID']}")
        print(f"PERSONA_SOURCE={receipt['PERSONA_SOURCE']}")
        print(f"PERSONA_PATH={receipt['PERSONA_PATH']}")
        print(f"PERSONA_EXISTS={receipt['PERSONA_EXISTS']}")
        return 0
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    print("=== PERSONA RECEIPT ===")
    print(f"PERSONA_ID: {receipt['PERSONA_ID']}")
    print(f"PERSONA_SOURCE: {receipt['PERSONA_SOURCE']}")
    print(f"PERSONA_PATH: {receipt['PERSONA_PATH']}")
    print(f"PERSONA_EXISTS: {receipt['PERSONA_EXISTS']}")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    if args.set_mode:
        state = set_mode(args.set_mode)
        _print_mode_receipt(str(state["mode"]))
        return 0

    state = load_state()
    _print_mode_receipt(str(state["mode"]))
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    status = drift_status()
    cmds = drift_commands(status)

    if args.json:
        payload = dict(status)
        payload["commands"] = cmds
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== DRIFT STATUS ===")
    print(f"mode: {status.get('mode')}")
    print(f"head_commit: {status.get('head_commit') or '(unknown)'}")
    print(f"last_ack_commit: {status.get('last_ack_commit') or '(unset)'}")
    print(f"governance_changed: {'YES' if status.get('governance_changed') else 'NO'}")
    reason = str(status.get("reason") or "").strip()
    if reason:
        print(f"reason: {reason}")
    files = status.get("changed_files") or []
    if files:
        print("changed_files:")
        for item in files:
            print(f"- {item}")
    print("inspect_commands:")
    print(f"- {cmds[0]}")
    print(f"- {cmds[1]}")
    print("acknowledge_command:")
    print("- python3 runtime/synapse.py acknowledge")
    return 0


def cmd_acknowledge(_args: argparse.Namespace) -> int:
    status_before = drift_status()
    state = acknowledge_head()
    status_after = drift_status()
    print("=== ACK RECEIPT ===")
    print(f"last_ack_commit_before: {status_before.get('last_ack_commit') or '(unset)'}")
    print(f"last_ack_commit_after: {state.get('last_ack_commit') or '(unset)'}")
    print(f"governance_changed_after_ack: {'YES' if status_after.get('governance_changed') else 'NO'}")
    print(f"state_path: {state_path().resolve()}")
    return 0


def cmd_enforce(args: argparse.Namespace) -> int:
    allowed, msg = enforce_execution_gate(
        risk=args.risk,
        tool=args.tool,
        action=args.action,
    )
    if msg:
        stream = sys.stderr if msg.startswith("BLOCKED:") else sys.stdout
        print(msg, file=stream)
    return 0 if allowed else 2


def _write_file(path: Path, text: str, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return "SKIP"
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return "WRITE"


def cmd_scaffold_subject(args: argparse.Namespace) -> int:
    try:
        ctx = resolve_subject(subject_flag=args.subject, allow_switch=False)
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        print("Hint: run `python3 runtime/synapse.py engage` or `python3 runtime/synapse.py focus --subject <SUBJECT>`.")
        return 2

    data_root = Path(str(ctx["data_root"])).expanduser().resolve()
    now_day = dt.datetime.now().astimezone().date().isoformat()

    do_incubation = not args.codex_only
    do_codex = not args.incubation_only
    if not do_incubation and not do_codex:
        do_incubation = True
        do_codex = True

    receipts: list[tuple[str, str]] = []

    if do_incubation:
        receipts.append((_write_file(data_root / "Incubation" / "SessionLogs" / ".gitkeep", "", args.force), "Incubation/SessionLogs/.gitkeep"))
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "DISCOVERIES.md",
                    """# DISCOVERIES (FINAL ONLY)

Compatibility note: if DATA_ROOT/.synapse exists, that sidecar is the canonical live runtime truth.
This file remains as a legacy/human-helper surface only.

Only FINAL decisions live here.

## ACTIVE DECISIONS
- D-001 | Status: ACTIVE | Decision: <fill>
  - Rationale: <fill>
  - Constraints: <fill>
  - Effective: <YYYY-MM-DD>

## SUPERSEDED DECISIONS
- D-000 | Status: SUPERSEDED | SUPERSEDED_BY: D-001
  - Former Decision: <fill>
  - Why Superseded: <fill>

## RULES
- Do not store brainstorming chatter here.
- Store explorations in SessionLogs or Draftshots.
""",
                    args.force,
                ),
                "Incubation/DISCOVERIES.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "OPEN_QUESTIONS.md",
                    """# OPEN QUESTIONS

Compatibility note: if DATA_ROOT/.synapse exists, that sidecar is the canonical live runtime truth.
This file remains as a legacy/human-helper surface only.

Only unresolved design/execution questions belong here.

## BLOCKING (INTERRUPTS USER)
- Q-001 | Status: BLOCKING | Question: <fill>
  - Why Blocking: <fill>
  - Needed Decision By: <phase>

## NONBLOCKING (DEFERRED)
- Q-002 | Status: NONBLOCKING | Question: <fill>
  - Deferred Until: <milestone>
  - Owner: <fill>

## TRIAGE RULE
- BLOCKING items interrupt.
- NONBLOCKING items are recorded and deferred.
""",
                    args.force,
                ),
                "Incubation/OPEN_QUESTIONS.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "DRAFTSHOT__INCUBATION__TEMPLATE.md",
                    f"""# DRAFTSHOT — INCUBATION

- Date: {now_day}
- Status: ACTIVE
- Scope: Incubation
- Subject: {ctx.get("subject")}

## Capture Rules
- Keep only decisions, constraints, definitions, non-goals, risks, dependencies, interfaces.
- Exclude chatter and non-project banter.

## Session Notes
- <fill>

## Candidate Decisions
- <fill>
""",
                    args.force,
                ),
                "Incubation/DRAFTSHOT__INCUBATION__TEMPLATE.md",
            )
        )

    if do_codex:
        receipts.append((_write_file(data_root / "Codex" / "Sections" / ".gitkeep", "", args.force), "Codex/Sections/.gitkeep"))
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "TOC_DRAFT.md",
                    """# TOC_DRAFT

Status: DRAFT

## Sections
1. <Section Name>
2. <Section Name>

## Notes
- Section PART files are allowed for large sections.
- Stitch PART files into final section file under `Codex/Sections/`.
""",
                    args.force,
                ),
                "Codex/TOC_DRAFT.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "ANCHOR_INDEX.yaml",
                    """schema_version: 1
updated_at: null
terms: []
invariants: []
contracts: []
section_receipts: []
""",
                    args.force,
                ),
                "Codex/ANCHOR_INDEX.yaml",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "CODEX_BUILD_STATE.yaml",
                    """schema_version: 1
overall_status: NOT_STARTED
spec_completeness_gate:
  status: NEEDS_DECISIONS
  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]
consistency_gate:
  status: NEEDS_DECISIONS
  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]
sections: []
notes:
  - "Only BLOCKING questions should interrupt."
  - "NONBLOCKING questions are deferred in the legacy compatibility surface Incubation/OPEN_QUESTIONS.md when needed."
""",
                    args.force,
                ),
                "Codex/CODEX_BUILD_STATE.yaml",
            )
        )

    print("=== SUBJECT SCAFFOLD RECEIPT ===")
    _print_subject_receipt(ctx)
    print("artifacts:")
    for action, rel in receipts:
        print(f"- {action}: {data_root / rel}")
    return 0


def cmd_live_bootstrap(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        result = ensure_live_scaffold(ctx["subject"], Path(ctx["data_root"]))
        event_info = None
        if result.get("created"):
            event_info = _event_pipeline(
                ctx=ctx,
                action_name="live-bootstrap",
                summary="Ensured live sidecar scaffold exists.",
                signals={
                    "created_paths": list(result.get("created") or []),
                    "existing_paths": list(result.get("existing") or []),
                    "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
                    "related_quest_ids": [],
                    "related_sidequest_ids": [],
                    "changed_files": list(result.get("created") or []),
                    "verification_entries": [],
                },
                truth_flags={
                    "canon_mutated": False,
                    "derived_state_changed": True,
                    "governed": False,
                    "uncertainty_present": False,
                },
                outputs={
                    "live_root": result.get("live_root"),
                    "created_paths": list(result.get("created") or []),
                },
            )
            result.update(event_info)
            if event_info["reducer"].get("rehydrate") is not None:
                result["rehydrate"] = event_info["reducer"]["rehydrate"]
            if event_info["reducer"].get("continuity") is not None:
                result["continuity"] = event_info["reducer"]["continuity"]
    except (LiveMemoryError, PublicationCandidateError) as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_live_bootstrap(payload: dict[str, Any]) -> None:
        print("=== LIVE BOOTSTRAP RECEIPT ===")
        _print_subject_receipt(ctx)
        print(f"live_root: {payload['live_root']}")
        if payload["created"]:
            print("created:")
            for path in payload["created"]:
                print(f"- {path}")
        if payload["existing"]:
            print("existing:")
            for path in payload["existing"]:
                print(f"- {path}")

    if result.get("created"):
        return _finalize_mutation_result(
            payload=result,
            event_info=event_info,
            json_mode=args.json,
            text_emitter=_emit_live_bootstrap,
        )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    _emit_live_bootstrap(result)
    return 0


def _default_session_title(ctx: dict[str, Any]) -> str:
    session_id = str(ctx.get("session_id") or _resolved_session_id(argparse.Namespace(session_id=None)) or "").strip()
    suffix = f" [{session_id}]" if session_id else ""
    return f"{ctx['subject']} Ambient Session{suffix}"


def _current_session_mode_fields(ctx: dict[str, Any]) -> dict[str, Any]:
    active_run = _load_active_run_with_session_repair(ctx)
    return session_mode_signal_fields(active_run)


def _active_session_policy(ctx: dict[str, Any]) -> tuple[dict[str, Any], Any | None]:
    active_run = _load_active_run_with_session_repair(ctx)
    return active_run, policy_for_run(active_run)


def _fail_blocked_by_session_posture(
    *,
    action_name: str,
    active_run: dict[str, Any],
    json_mode: bool,
) -> int:
    session_mode = str(active_run.get("session_mode") or "").strip() or "unknown"
    message = (
        f"Session posture '{session_mode}' blocks `{action_name}`. "
        "Use `python3 runtime/synapse.py session-mode --set <mode> --reason <text>` to transition first."
    )
    if json_mode:
        print(
            json.dumps(
                {
                    "error": message,
                    "active_run_id": active_run.get("run_id"),
                    "active_session_mode": active_run.get("session_mode"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(f"FAIL: {message}")
    return 2


def _read_json_or_yaml_file(path: Path, *, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise LiveMemoryError(f"Unable to read {label}: {path}") from exc
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except Exception as exc:
        raise LiveMemoryError(f"Invalid {label}: {path}") from exc


def _read_inline_json(raw: str, *, label: str) -> Any:
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise LiveMemoryError(f"Invalid {label}: {exc}") from exc


def _read_onboarding_payload(args: argparse.Namespace, *, kind: str) -> Any:
    if kind == "draft":
        if bool(args.draft_file) == bool(args.draft_json):
            raise LiveMemoryError("onboarding-update requires exactly one of --draft-file or --draft-json.")
        if args.draft_json is not None:
            return _read_inline_json(args.draft_json, label="--draft-json payload")
        return _read_json_or_yaml_file(Path(str(args.draft_file)).expanduser(), label="draft file")
    if kind == "questions":
        if bool(args.questions_file) == bool(args.questions_json):
            raise LiveMemoryError("onboarding-update requires exactly one of --questions-file or --questions-json.")
        if args.questions_json is not None:
            return _read_inline_json(args.questions_json, label="--questions-json payload")
        return _read_json_or_yaml_file(Path(str(args.questions_file)).expanduser(), label="question-set file")
    raise LiveMemoryError(f"Unknown onboarding payload kind: {kind}")


def _read_optional_id_list(args: argparse.Namespace) -> list[str]:
    if getattr(args, "question_ids_json", None) is None and getattr(args, "question_ids_file", None) is None:
        return []
    if getattr(args, "question_ids_json", None) is not None and getattr(args, "question_ids_file", None) is not None:
        raise LiveMemoryError("Use only one of --question-ids-json or --question-ids-file.")
    payload = (
        _read_inline_json(args.question_ids_json, label="--question-ids-json payload")
        if getattr(args, "question_ids_json", None) is not None
        else _read_json_or_yaml_file(Path(str(args.question_ids_file)).expanduser(), label="question ids file")
    )
    if not isinstance(payload, list):
        raise LiveMemoryError("Linked onboarding question ids must be a list.")
    ids: list[str] = []
    seen: set[str] = set()
    for raw in payload:
        text = str(raw or "").strip()
        if text and text not in seen:
            ids.append(text)
            seen.add(text)
    return ids


def _set_active_run_session_mode(
    *,
    ctx: dict[str, Any],
    active_run: dict[str, Any],
    target_mode: SessionMode,
    reason: str,
    source: str,
) -> dict[str, Any]:
    current_mode = SessionMode(str(active_run.get("session_mode") or ""))
    if current_mode == target_mode:
        return {
            "changed": False,
            "run_path": str(Path(ctx["data_root"]) / ".synapse" / "ACTIVE_RUN.yaml"),
            "event": None,
            "reducer": _empty_reducer_receipt(),
            "rehydrate": None,
            "continuity": None,
            "runtime_status": None,
        }
    _assert_ready_state_mode_allowed(ctx, target_mode)
    allowed, next_modes = validate_transition(current_mode, target_mode)
    if not allowed:
        raise LiveMemoryError(
            f"Invalid session-mode transition: {current_mode.value} -> {target_mode.value}. "
            f"Allowed next modes: {', '.join(mode.value for mode in next_modes)}"
        )
    run_path = Path(ctx["data_root"]) / ".synapse" / "ACTIVE_RUN.yaml"
    transition_at = dt.datetime.now().astimezone().isoformat()
    session_id = _effective_session_id(ctx, active_run=active_run)
    active_run = dict(active_run)
    active_run["session_mode"] = target_mode.value
    active_run["session_mode_source"] = source
    active_run["session_mode_set_at"] = transition_at
    active_run["session_mode_reason"] = reason
    active_run["session_mode_policy_version"] = active_run.get("session_mode_policy_version") or SESSION_MODE_POLICY_VERSION
    run_path.write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="session-mode-set",
        summary=f"Changed session posture from {current_mode.value} to {target_mode.value}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "from_session_mode": current_mode.value,
            "to_session_mode": target_mode.value,
            "session_mode_reason": reason,
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "run_id": active_run.get("run_id"),
            "run_path": str(run_path),
        },
    )
    return {
        "changed": True,
        "run_path": str(run_path),
        "active_run": active_run,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
        "runtime_status": event_info.get("runtime_status"),
    }


def _require_onboarding_context(
    *,
    ctx: dict[str, Any],
    action_name: str,
    allow_create_onboard_run: bool = False,
    allow_replace_onboard_run: bool = False,
) -> tuple[dict[str, Any], str]:
    active_run = _load_active_run_with_session_repair(ctx)
    effective_session_id = _effective_session_id(ctx, active_run=active_run)
    if allow_create_onboard_run and (
        not active_run.get("run_id")
        or (
            allow_replace_onboard_run
            and str(active_run.get("session_mode") or "").strip() != SessionMode.ONBOARDING_EXISTING_REPO.value
        )
    ):
        if not effective_session_id:
            raise LiveMemoryError(f"{action_name} requires a current session id to create an onboarding run.")
        run_receipt = run_start(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            title=f"{ctx['subject']} Existing Repo Onboarding",
            goal="Build and confirm a durable project model for the existing repository.",
            items=[],
            command_name="session-start",
            session_mode=SessionMode.ONBOARDING_EXISTING_REPO.value,
            session_mode_source="command_default",
            session_mode_reason="defaulted from onboard-repo",
            session_id=effective_session_id,
            mutate_proposals=False,
        )
        active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
        _write_session_overlay(ctx, run_receipt, active_run=active_run, session_id=effective_session_id)
        return active_run, effective_session_id
    if not active_run.get("run_id"):
        raise LiveMemoryError(f"{action_name} requires an active run in onboarding_existing_repo posture.")
    if not effective_session_id:
        raise LiveMemoryError(f"{action_name} requires an active session with a non-null session_id.")
    if str(active_run.get("session_mode") or "").strip() != SessionMode.ONBOARDING_EXISTING_REPO.value:
        raise LiveMemoryError(
            f"{action_name} requires active posture onboarding_existing_repo; current posture is "
            f"{str(active_run.get('session_mode') or 'none').strip() or 'none'}."
        )
    return active_run, effective_session_id


def _read_capture_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        text = str(args.text)
    else:
        path = Path(str(args.text_file or "")).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise LiveMemoryError(f"Unable to read capture text file: {path}") from exc
    if not text.strip():
        raise LiveMemoryError("Capture text must be non-empty.")
    return text


def _read_capture_payload(args: argparse.Namespace) -> Any:
    if args.captures_json is not None:
        raw = str(args.captures_json)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LiveMemoryError(f"Invalid --captures-json payload: {exc}") from exc

    path = Path(str(args.captures_file or "")).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise LiveMemoryError(f"Unable to read capture payload file: {path}") from exc
    try:
        return yaml.safe_load(text)
    except Exception as exc:
        raise LiveMemoryError(f"Invalid capture payload file: {path}") from exc


def _session_mode_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = _load_active_run_with_session_repair(ctx)
    live = data_root / ".synapse"
    try:
        state = yaml.safe_load((live / "STATE.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        state = {}
    active_mode_text = str(active_run.get("session_mode") or "").strip()
    active_mode = SessionMode(active_mode_text) if active_mode_text else None
    active_summary = policy_summary(active_mode) if active_mode else None
    return {
        "subject": ctx["subject"],
        "active_run_id": active_run.get("run_id"),
        "active_session_mode": active_mode.value if active_mode else None,
        "active_session_mode_source": active_run.get("session_mode_source") if active_mode else None,
        "active_session_mode_set_at": active_run.get("session_mode_set_at") if active_mode else None,
        "active_session_mode_reason": active_run.get("session_mode_reason") if active_mode else None,
        "active_session_mode_policy_version": active_run.get("session_mode_policy_version") if active_mode else None,
        "current_interaction_mode": active_run.get("interaction_mode") if active_mode else None,
        "policy_summary": active_summary,
        "allowed_next_modes": list(active_summary.get("allowed_next_modes") or []) if active_summary else [],
        "last_session_mode": state.get("last_session_mode"),
        "last_session_mode_ended_at": state.get("last_session_mode_ended_at"),
    }


def _session_mode_change_error(payload: dict[str, Any], *, json_mode: bool, message: str) -> int:
    if json_mode:
        error_payload = dict(payload)
        error_payload["error"] = message
        print(json.dumps(error_payload, indent=2, sort_keys=True))
        return 2
    print(f"FAIL: {message}")
    if payload.get("active_session_mode") is not None:
        print(f"active_session_mode: {payload.get('active_session_mode')}")
    if payload.get("allowed_next_modes"):
        print(f"allowed_next_modes: {', '.join(payload.get('allowed_next_modes') or [])}")
    return 2


def _write_session_overlay(
    ctx: dict[str, Any],
    run_payload: dict[str, Any] | None,
    *,
    active_run: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str | None:
    session_id = _effective_session_id(ctx, active_run=active_run, session_id=session_id)
    if not session_id:
        return None
    payload = {
        "subject": ctx["subject"],
        "data_root": ctx["data_root"],
        "engine_root": ctx["engine_root"],
        "run_id": run_payload.get("run_id") if run_payload else None,
        "run_path": run_payload.get("run_path") if run_payload else None,
        "status": "active" if run_payload and run_payload.get("run_id") else "idle",
        "updated_at": dt.datetime.now().astimezone().isoformat(),
    }
    return _write_session_run_overlay(session_id, payload)


def _continuity_session_anchor(
    ctx: dict[str, Any],
    *,
    active_run: dict[str, Any] | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> str | None:
    active_run = active_run or {}
    resolved = _effective_session_id(ctx, active_run=active_run, session_id=session_id)
    if resolved:
        return resolved
    fallback_run_id = str(run_id or active_run.get("run_id") or "").strip()
    return fallback_run_id or None


def _start_or_resume_session_run(
    ctx: dict[str, Any],
    *,
    title: str | None,
    goal: str | None,
    items: list[str],
    command_name: str,
    requested_session_mode: str | None = None,
) -> dict[str, Any]:
    active_run = _load_active_run_with_session_repair(ctx)
    if active_run.get("run_id"):
        current_mode = str(active_run.get("session_mode") or "").strip()
        requested_mode = str(requested_session_mode or "").strip()
        if requested_mode:
            _assert_ready_state_mode_allowed(ctx, requested_mode)
        if requested_mode and current_mode and requested_mode != current_mode:
            raise LiveMemoryError(
                f"Active run is already in session mode '{current_mode}'. "
                "Use `python3 runtime/synapse.py session-mode --set <mode> --reason <text>` to change posture."
            )
        _assert_ready_state_mode_allowed(ctx, current_mode or None)
        return {
            "run_id": active_run["run_id"],
            "session_id": active_run.get("session_id"),
            "run_path": str(Path(ctx["data_root"]) / ".synapse" / "ACTIVE_RUN.yaml"),
            "title": active_run.get("title"),
            "goal": active_run.get("goal"),
            "items": active_run.get("plan", {}).get("items", []),
            "session_mode": active_run.get("session_mode"),
            "session_mode_source": active_run.get("session_mode_source"),
            "session_mode_set_at": active_run.get("session_mode_set_at"),
            "session_mode_reason": active_run.get("session_mode_reason"),
            "session_mode_policy_version": active_run.get("session_mode_policy_version"),
            "resumed": True,
        }
    readiness = _readiness_payload(Path(ctx["data_root"]))
    target_mode = requested_session_mode or (
        SessionMode.ONBOARDING_EXISTING_REPO.value
        if readiness.get("onboarding_required")
        else default_mode_for_command(command_name).value
    )
    _assert_ready_state_mode_allowed(ctx, target_mode)
    return run_start(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        title=title or _default_session_title(ctx),
        goal=goal,
        items=items,
        command_name=command_name,
        session_mode=requested_session_mode,
        session_id=_effective_session_id(ctx),
    )


def cmd_run_start(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        items = _load_plan_items(args.plan_item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    try:
        _assert_ready_state_mode_allowed(
            ctx,
            getattr(args, "session_mode", None) or default_mode_for_command("run-start").value,
        )
        result = run_start(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            title=args.title,
            goal=args.goal,
            items=items,
            command_name="run-start",
            session_mode=getattr(args, "session_mode", None),
            session_id=_effective_session_id(ctx),
        )
        session_id = _effective_session_id(ctx, session_id=result.get("session_id"))
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-start",
            summary=f"Started active run: {result.get('title')}",
            session_id=session_id,
            signals={
                "run_id": result.get("run_id"),
                "run_title": result.get("title"),
                "run_goal": result.get("goal"),
                "run_summary": result.get("goal"),
                "plan_items": _compact_plan_items(result.get("items")),
                "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
                "related_quest_ids": [],
                "related_sidequest_ids": [],
                "changed_files": [],
                "verification_entries": [],
                **session_mode_signal_fields(result),
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "verification_present": False,
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "run_path": result.get("run_path"),
                "ledger_path": result.get("ledger_path"),
            },
        )
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    overlay_path = _write_session_overlay(ctx, result, session_id=session_id)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    def _emit_run_start(payload: dict[str, Any]) -> None:
        print("=== RUN STARTED ===")
        print(f"run_id: {payload['run_id']}")
        print(f"run_path: {payload['run_path']}")
        if overlay_path:
            print(f"session_overlay: {overlay_path}")
        if payload.get("items"):
            print("plan_items:")
            for item in payload["items"]:
                print(f"- {item['id']}: {item['text']} ({item['status']})")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_run_start,
    )


def cmd_session_start(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        items = _load_plan_items(args.plan_item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    try:
        result = _start_or_resume_session_run(
            ctx,
            title=args.title or _default_session_title(ctx),
            goal=args.goal,
            items=items,
            command_name="session-start",
            requested_session_mode=getattr(args, "session_mode", None),
        )
        session_id = _effective_session_id(ctx, session_id=result.get("session_id"))
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="session-start",
            summary=f"Started or resumed session run: {result.get('title') or ctx['subject']}",
            session_id=session_id,
            signals={
                "run_id": result.get("run_id"),
                "run_title": result.get("title"),
                "run_goal": result.get("goal"),
                "plan_items": _compact_plan_items(result.get("items")),
                "resumed": bool(result.get("resumed")),
                "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
                "related_quest_ids": [],
                "related_sidequest_ids": [],
                "changed_files": [],
                "verification_entries": [],
                **session_mode_signal_fields(result),
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "run_path": result.get("run_path"),
                "resumed": bool(result.get("resumed")),
            },
        )
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
        snapshot_candidate_result = _snapshot_candidate_boundary_noop(
            data_root=Path(ctx["data_root"]),
            boundary="session-start",
            reason="no_stale_prior_day_candidate_required",
        )
        latest_active_draftshot = load_active_draftshot(Path(ctx["data_root"]), session_id=None)
        session_start_decision = evaluate_snapshot_checkpoint(
            boundary="session-start",
            requested_candidate_kinds=[],
            target_day_hint=None,
            current_summary=dict(snapshot_candidate_result.get("summary") or {}),
            draftshot=latest_active_draftshot,
            session_anchor_present=bool(session_id),
        )
        if session_start_decision.candidate_action == "refresh" and session_start_decision.required_candidate_kinds:
            snapshot_candidate_result = _refresh_snapshot_candidate_boundary(
                ctx=ctx,
                boundary="session-start",
                candidate_kinds=list(session_start_decision.required_candidate_kinds),
                target_day=session_start_decision.target_day,
                prefer_latest_active_draftshot=True,
                refresh_draftshot_first=False,
                session_id_override=session_id,
                run_id_override=result.get("run_id"),
            )
        else:
            snapshot_candidate_result = _snapshot_candidate_boundary_noop(
                data_root=Path(ctx["data_root"]),
                boundary="session-start",
                reason=str(session_start_decision.blocked_reason or "no_stale_prior_day_candidate_required"),
                decision=session_start_decision.to_dict(),
            )
        result["snapshot_candidates"] = snapshot_candidate_result
        result["publication_candidates"] = _refresh_publication_candidate_boundary(
            ctx=ctx,
            boundary="session-start",
        )
    except (LiveMemoryError, SnapshotCandidateError, PublicationCandidateError) as exc:
        print(f"FAIL: {exc}")
        return 2

    overlay_path = _write_session_overlay(ctx, result, session_id=session_id)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    payload = {"subject": ctx, "run": result}

    def _emit_session_start(rendered_payload: dict[str, Any]) -> None:
        print("=== SESSION STARTED ===")
        _print_subject_receipt(rendered_payload["subject"])
        print(f"run_id: {rendered_payload['run'].get('run_id')}")
        if overlay_path:
            print(f"session_overlay: {overlay_path}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_session_start,
    )


def cmd_run_update(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        items = _load_plan_items(args.add_item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    try:
        active_run = _load_active_run_with_session_repair(ctx)
        session_id = _effective_session_id(ctx, active_run=active_run)
        result = run_update(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            add_items=items,
            status_updates=args.set_item_status,
            commands=args.commands,
            files_touched=args.file,
            notes=args.note,
            verification=args.verification,
            related_sidequests=args.related_sidequest,
            related_quests=args.related_quest,
            status=args.status,
            summary=args.summary,
        )
        automation = _execute_automation_side_effects(
            ctx=ctx,
            active_run=active_run,
            activity_source="direct_cli",
            activity_kind="run-update",
            summary=args.summary,
            changed_files=list(args.file or []),
            notes=list(args.note or []),
        )
        signals = {
            "run_id": result.get("run_id"),
            "plan_items_added": _compact_plan_items(result.get("added_items")),
            "plan_items": _compact_plan_items(result.get("added_items")),
            "status_updates": [f"{item_id}:{status}" for item_id, status in result.get("status_updates") or []],
            "commands": list(args.commands or []),
            "changed_files": list(args.file or []),
            "notes": list(args.note or []),
            "discoveries": list(args.note or []) + ([args.summary] if args.summary else []),
            "run_summary": args.summary,
            "run_status": args.status,
            "verification_entries": list(args.verification or []),
            "related_quest_ids": list(args.related_quest or []),
            "related_sidequest_ids": list(args.related_sidequest or []),
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **session_mode_signal_fields(active_run),
        }
        outputs = {
            "run_id": result.get("run_id"),
            "run_path": result.get("run_path"),
            "ledger_path": result.get("ledger_path"),
            "discoveries_path": result.get("discoveries_path"),
        }
        truth_flags = {
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "verification_present": bool(args.verification),
            "uncertainty_present": False,
        }
        _apply_automation_event_metadata(
            signals=signals,
            outputs=outputs,
            truth_flags=truth_flags,
            automation=automation,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-update",
            summary=args.summary or f"Updated active run {result.get('run_id')}",
            session_id=session_id,
            signals=signals,
            truth_flags=truth_flags,
            outputs=outputs,
        )
        event_info = _apply_automation_partial_status(event_info=event_info, automation=automation)
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
        result["automation"] = automation
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    overlay_path = _write_session_overlay(ctx, result, active_run=active_run, session_id=session_id)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    def _emit_run_update(payload: dict[str, Any]) -> None:
        print("=== RUN UPDATED ===")
        print(f"run_id: {payload.get('run_id')}")
        if payload.get("added_items"):
            print("added_items:")
            for item in payload["added_items"]:
                print(f"- {item['id']}: {item['text']} ({item['status']})")
        if payload.get("status_updates"):
            print("status_updates:")
            for item_id, status in payload["status_updates"]:
                print(f"- {item_id}: {status}")
        if overlay_path:
            print(f"session_overlay: {overlay_path}")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_run_update,
    )


def cmd_session_tick(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        items = _load_plan_items(args.plan_item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    try:
        start_result = _start_or_resume_session_run(
            ctx,
            title=args.title or _default_session_title(ctx),
            goal=args.goal,
            items=items,
            command_name="session-tick",
            requested_session_mode=getattr(args, "session_mode", None),
        )
        session_id = _effective_session_id(ctx, session_id=start_result.get("session_id"))
        files_touched = list(args.file)
        if args.capture_git:
            files_touched.extend(_git_status_changed_files(detect_canonical_working_tree()))
        notes = list(args.note) + list(args.discovery)
        result = run_update(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            add_items=items,
            status_updates=[],
            commands=args.commands,
            files_touched=files_touched,
            notes=notes,
            verification=args.verification,
            related_sidequests=args.related_sidequest,
            related_quests=args.related_quest,
            status=args.status,
            summary=args.summary,
        )
        decision_result = None
        if args.decision_title and args.decision_summary:
            decision_result = log_decision(
                subject=ctx["subject"],
                data_root=Path(ctx["data_root"]),
                title=args.decision_title,
                summary=args.decision_summary,
                why=args.decision_why,
                constraints=[],
                tradeoffs=[],
                related_runs=[str(result.get("run_id") or "")],
                related_quests=args.related_quest,
            )
        automation = _execute_automation_side_effects(
            ctx=ctx,
            active_run=_load_active_run_with_session_repair(ctx),
            activity_source="direct_cli",
            activity_kind="session-tick",
            summary=args.summary,
            changed_files=list(files_touched),
            notes=list(notes),
            decision_boundary=bool(args.decision_title and args.decision_summary),
            explicit_decision_logged=bool(decision_result),
        )
        observer = _execute_continuity_observer(
            ctx=ctx,
            active_run=_load_active_run_with_session_repair(ctx),
            trigger="session-tick",
            summary=args.summary,
            notes=list(notes),
            changed_files=list(files_touched),
            decision_boundary=bool(args.decision_title and args.decision_summary),
            uncertainty_present=bool(automation.get("automation_context", {}).get("uncertainty_present")),
            accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=_current_session_mode_fields(ctx),
        )
        signals = {
            "run_id": result.get("run_id"),
            "plan_items": _compact_plan_items(items),
            "commands": list(args.commands or []),
            "changed_files": list(files_touched),
            "notes": list(notes),
            "discoveries": list(notes),
            "decisions": [args.decision_title] if args.decision_title else [],
            "run_summary": args.summary,
            "run_status": args.status,
            "verification_entries": list(args.verification or []),
            "decision_titles": [args.decision_title] if args.decision_title else [],
            "related_quest_ids": list(args.related_quest or []),
            "related_sidequest_ids": list(args.related_sidequest or []),
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        }
        outputs = {
            "run_id": result.get("run_id"),
            "run_path": result.get("run_path"),
            "discoveries_path": result.get("discoveries_path"),
            "decision_path": decision_result.get("decision_path") if decision_result else None,
            "decisions_ledger_path": decision_result.get("decisions_ledger_path") if decision_result else None,
        }
        truth_flags = {
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "verification_present": bool(args.verification),
            "uncertainty_present": False,
        }
        _apply_automation_event_metadata(
            signals=signals,
            outputs=outputs,
            truth_flags=truth_flags,
            automation=automation,
        )
        _apply_observer_event_metadata(
            signals=signals,
            outputs=outputs,
            truth_flags=truth_flags,
            observer=observer,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="session-tick",
            summary=args.summary or f"Session tick for {result.get('run_id')}",
            session_id=session_id,
            signals=signals,
            truth_flags=truth_flags,
            outputs=outputs,
        )
        event_info = _apply_automation_partial_status(event_info=event_info, automation=automation)
        event_info = _apply_observer_partial_status(event_info=event_info, observer=observer)
        continuity_result = {
            "rehydrate": event_info["reducer"]["rehydrate"],
            "continuity": event_info["reducer"]["continuity"],
        }
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    accepted_context = _accepted_context_snapshot(Path(ctx["data_root"]))
    artifact_routing = _route_artifact_boundary(
        ctx=ctx,
        trigger="session-tick",
        boundary="session-tick",
        invoke_reason="session_tick_boundary",
        active_run=_load_active_run_with_session_repair(ctx),
        accepted_context=accepted_context,
        summary=args.summary,
        notes=list(notes),
        changed_files=list(files_touched),
        observer_action_kinds=list(observer.get("observer_action_kinds") or []),
        requested_snapshot_kinds=[],
        requested_publication_candidate_kinds=[],
    )
    overlay_path = _write_session_overlay(ctx, result, session_id=session_id)
    payload = {
        "subject": ctx,
        "run_update": result,
        "decision": decision_result,
        "rehydrate": continuity_result["rehydrate"],
        "continuity": continuity_result["continuity"],
        "session_overlay_path": overlay_path,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "automation": automation,
        "continuity_observer": observer,
        "artifact_routing": artifact_routing,
    }
    def _emit_session_tick(rendered_payload: dict[str, Any]) -> None:
        run_update_payload = rendered_payload["run_update"]
        print("=== SESSION TICK ===")
        print(f"run_id: {run_update_payload.get('run_id')}")
        print(f"discoveries_path: {run_update_payload.get('discoveries_path')}")
        if rendered_payload.get("decision"):
            print(f"decision_path: {rendered_payload['decision'].get('decision_path')}")
        observer_payload = dict(rendered_payload.get("continuity_observer") or {})
        print(f"observer_status: {observer_payload.get('observer_status')}")
        print(f"observer_backend: {observer_payload.get('observer_backend')}")
        print(f"observer_action_kinds: {','.join(observer_payload.get('observer_action_kinds') or []) or 'none'}")
        if overlay_path:
            print(f"session_overlay: {overlay_path}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_session_tick,
    )


def cmd_run_finalize(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        active_run = _load_active_run_with_session_repair(ctx)
        result = run_finalize(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            status=args.status,
            summary=args.summary,
        )
        session_id = _effective_session_id(ctx, active_run=active_run, session_id=result.get("session_id"))
        observer = _execute_continuity_observer(
            ctx=ctx,
            active_run={**active_run, "run_id": result.get("run_id"), "session_id": session_id},
            trigger="run-finalize",
            summary=args.summary or f"Finalized run {result.get('run_id')}",
            accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields={
                "session_mode": result.get("session_mode"),
                "session_mode_source": result.get("session_mode_source"),
                "session_mode_policy_version": result.get("session_mode_policy_version"),
            },
        )
        signals = {
            "run_id": result.get("run_id"),
            "final_status": args.status,
            "run_status": args.status,
            "run_summary": args.summary,
            "changed_files": [],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            "session_mode": result.get("session_mode"),
            "session_mode_source": result.get("session_mode_source"),
            "session_mode_policy_version": result.get("session_mode_policy_version"),
        }
        outputs = {
            "run_id": result.get("run_id"),
            "archive_path": result.get("archive_path"),
        }
        truth_flags = {
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        }
        _apply_observer_event_metadata(
            signals=signals,
            outputs=outputs,
            truth_flags=truth_flags,
            observer=observer,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-finalize",
            summary=args.summary or f"Finalized run {result.get('run_id')}",
            session_id=session_id,
            signals=signals,
            truth_flags=truth_flags,
            outputs=outputs,
        )
        event_info = _apply_observer_partial_status(event_info=event_info, observer=observer)
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    event_info, truth_compile = _merge_truth_compile_follow_on(
        ctx=ctx,
        session_id=session_id,
        event_info=event_info,
        primary_action_label="Run finalization",
    )
    result.update(event_info)
    result["rehydrate"] = event_info["reducer"]["rehydrate"]
    result["continuity"] = event_info["reducer"]["continuity"]
    result["truth_compile"] = truth_compile
    result["continuity_observer"] = observer
    try:
        accepted_context = _accepted_context_snapshot(Path(ctx["data_root"]))
        artifact_routing = _route_artifact_boundary(
            ctx=ctx,
            trigger="run-finalize",
            boundary="run-finalize",
            invoke_reason="run_finalize_boundary",
            active_run={**active_run, **result, "session_id": session_id},
            accepted_context=accepted_context,
            summary=args.summary or f"Finalized run {result.get('run_id')}",
            observer_action_kinds=list(observer.get("observer_action_kinds") or []),
            requested_snapshot_kinds=[EOD_KIND],
            requested_publication_candidate_kinds=list(PUBLICATION_CANDIDATE_KINDS),
        )
        result["artifact_routing"] = artifact_routing
        result["snapshot_candidates"] = artifact_routing["dispatch"].get("snapshot_candidates") or _snapshot_candidate_boundary_noop(
            data_root=Path(ctx["data_root"]),
            boundary="run-finalize",
            reason="router_no_snapshot_dispatch",
        )
        result["publication_candidates"] = artifact_routing["dispatch"].get("publication_candidates") or _publication_candidate_boundary_noop(
            data_root=Path(ctx["data_root"]),
            boundary="run-finalize",
            reason="router_no_publication_dispatch",
        )
    except (SnapshotCandidateError, PublicationCandidateError) as exc:
        print(f"FAIL: {exc}")
        return 2

    overlay_path = None
    if session_id:
        overlay_path = _clear_session_run_overlay(session_id)
        result["session_overlay_path"] = overlay_path

    def _emit_run_finalize(payload: dict[str, Any]) -> None:
        print("=== RUN FINALIZED ===")
        print(f"run_id: {payload.get('run_id')}")
        print(f"archive_path: {payload.get('archive_path')}")
        observer_payload = dict(payload.get("continuity_observer") or {})
        print(f"observer_status: {observer_payload.get('observer_status')}")
        print(f"observer_backend: {observer_payload.get('observer_backend')}")
        print(f"observer_action_kinds: {','.join(observer_payload.get('observer_action_kinds') or []) or 'none'}")
        if overlay_path:
            print(f"session_overlay_cleared: {overlay_path}")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_run_finalize,
    )


def cmd_capture_chunk(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    active_run = _load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        message = "capture-chunk requires an active run. Start or resume a session first."
        if args.json:
            print(json.dumps({"error": message, "subject": ctx}, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {message}")
        return 2
    if not active_run.get("session_id") or not active_run.get("session_mode"):
        message = "capture-chunk requires an active session with a current session posture. Start or resume a session first."
        if args.json:
            print(json.dumps({"error": message, "subject": ctx}, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {message}")
        return 2

    try:
        raw_text = _read_capture_text(args)
        payload = _read_capture_payload(args)
        source_role = normalize_capture_source_role(args.source_role)
        capture_receipt = write_capture_batch(
            subject=ctx["subject"],
            data_root=data_root,
            engine_root=engine_root,
            run_data=active_run,
            raw_text=raw_text,
            payload=payload,
            source_role=source_role,
            title_override=args.title,
        )
    except (LiveMemoryError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    capture_batch = capture_receipt["batch"]
    session_id = _effective_session_id(ctx, active_run=active_run)
    capture_ids = [str(item.get("capture_id")) for item in capture_batch.get("captures") or [] if str(item.get("capture_id") or "").strip()]
    capture_signal = AmbientSignal(
        source="capture-chunk",
        subject=ctx["subject"],
        title=str(args.title or capture_batch.get("title") or "Semantic capture batch"),
        summary=f"Recorded {len(capture_ids)} semantic captures.",
        notes=tuple(
            str(item.get("summary") or "").strip()
            for item in capture_batch.get("captures") or []
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ),
        status="captured",
    )
    try:
        sidecar = _sync_sidecar(
            subject=ctx["subject"],
            data_root=data_root,
            active_run=active_run,
            signal=capture_signal,
            semantic_capture_batch=capture_batch,
            mutate_proposals=True,
        )
    except (LiveMemoryError, SemanticIntakeError) as exc:
        partial_payload = {
            "subject": ctx,
            "capture_batch_id": capture_batch.get("capture_batch_id"),
            "capture_artifact_path": capture_receipt["artifact_path"],
            "capture_ledger_path": capture_receipt["ledger_path"],
            "capture_ids": capture_ids,
            "open_questions_path": None,
            "proposal_paths": [],
            "written_artifacts": [capture_receipt["artifact_path"], capture_receipt["ledger_path"]],
            "event": None,
            "reducer": _empty_reducer_receipt(),
        }

        def _emit_capture_partial(rendered_payload: dict[str, Any]) -> None:
            print("=== CAPTURE RECEIPT ===")
            print(f"capture_batch_id: {rendered_payload.get('capture_batch_id')}")
            print(f"capture_artifact_path: {rendered_payload.get('capture_artifact_path')}")
            print(f"capture_ledger_path: {rendered_payload.get('capture_ledger_path')}")

        partial_event_info, truth_status = _refresh_truth_status_after_mutation(
            ctx=ctx,
            event_info=_partial_after_primary_mutation(
                error_code="SEMANTIC_PROJECTION_FAILED",
                error_message=str(exc),
                recovery_hint=(
                    "Raw capture truth was written, but semantic projection failed before the event append. "
                    "Repair the projection conflict, then rerun the relevant refresh path or re-capture if needed."
                ),
            ),
        )
        partial_payload["truth_status"] = truth_status

        return _finalize_mutation_result(
            payload=partial_payload,
            event_info=partial_event_info,
            json_mode=args.json,
            text_emitter=_emit_capture_partial,
        )

    proposal_paths = list(sidecar.get("proposal_paths") or [])
    open_questions_path = sidecar.get("open_questions_path")
    written_artifacts = [capture_receipt["artifact_path"], capture_receipt["ledger_path"]]
    if open_questions_path:
        written_artifacts.append(str(open_questions_path))
    written_artifacts.extend(proposal_paths)
    automation = _execute_automation_side_effects(
        ctx=ctx,
        active_run=active_run,
        activity_source="direct_cli",
        activity_kind="capture-chunk",
        summary=str(args.title or capture_batch.get("title") or "Recorded semantic capture batch."),
        notes=[
            str(item.get("summary") or "").strip()
            for item in capture_batch.get("captures") or []
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ],
        uncertainty_present=batch_uncertainty_present(capture_batch),
        explicit_capture_written=True,
    )
    signals = {
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_count": len(capture_ids),
        "capture_kinds": semantic_capture_kinds(capture_batch),
        "capture_source_role": source_role.value,
        "changed_files": written_artifacts,
        "verification_entries": [],
        "related_quest_ids": [],
        "related_sidequest_ids": [],
        **session_mode_signal_fields(active_run),
    }
    outputs = {
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_artifact_path": capture_receipt["artifact_path"],
        "capture_ledger_path": capture_receipt["ledger_path"],
        "open_questions_path": open_questions_path,
        "proposal_paths": proposal_paths,
        "written_artifacts": written_artifacts,
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "uncertainty_present": batch_uncertainty_present(capture_batch),
        "disclosure_open": batch_disclosure_needed(capture_batch),
    }
    _apply_automation_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        automation=automation,
    )

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="capture-chunk",
        summary=str(args.title or capture_batch.get("title") or "Recorded semantic capture batch."),
        session_id=session_id,
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = _apply_automation_partial_status(event_info=event_info, automation=automation)
    event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)

    result = {
        "subject": ctx,
        "capture_batch_id": capture_batch.get("capture_batch_id"),
        "capture_artifact_path": capture_receipt["artifact_path"],
        "capture_ledger_path": capture_receipt["ledger_path"],
        "capture_ids": capture_ids,
        "open_questions_path": open_questions_path,
        "proposal_paths": proposal_paths,
        "written_artifacts": written_artifacts,
        "sidecar": sidecar,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
        "automation": automation,
        "truth_status": truth_status,
    }

    def _emit_capture_chunk(rendered_payload: dict[str, Any]) -> None:
        print("=== CAPTURE RECEIPT ===")
        print(f"capture_batch_id: {rendered_payload.get('capture_batch_id')}")
        print(f"capture_artifact_path: {rendered_payload.get('capture_artifact_path')}")
        print(f"capture_ledger_path: {rendered_payload.get('capture_ledger_path')}")
        if rendered_payload.get("open_questions_path"):
            print(f"open_questions_path: {rendered_payload.get('open_questions_path')}")
        if rendered_payload.get("proposal_paths"):
            print("proposal_paths:")
            for path in rendered_payload["proposal_paths"]:
                print(f"- {path}")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_capture_chunk,
    )


def cmd_onboard_repo(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        payload, event_info = _run_onboarding_bootstrap(
            ctx=ctx,
            depth=args.depth,
            rescan=bool(args.rescan),
            restart=bool(args.restart),
            allow_switch_for_run=bool(args.allow_switch),
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    if payload.get("resumed_existing") or payload.get("already_completed"):
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        print("=== ONBOARDING STATUS ===")
        print(f"onboarding_id: {payload.get('onboarding_id') or 'none'}")
        print(f"state: {payload.get('state') or payload.get('onboarding_state') or 'none'}")
        if payload.get("resumed_existing"):
            print("resumed_existing: true")
        if payload.get("already_completed"):
            print("already_completed: true")
        return 0
    payload["subject"] = ctx

    def _emit_onboard_repo(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING STARTED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"scan_id: {rendered_payload.get('scan_id')}")
        print(f"scan_artifact_path: {rendered_payload.get('scan_artifact_path')}")
        print(f"analysis_brief_path: {rendered_payload.get('analysis_brief_path')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_onboard_repo,
    )


def cmd_onboarding_status(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        payload = onboarding_status_payload(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError) as exc:
        print(f"FAIL: {exc}")
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("=== ONBOARDING STATUS ===")
    print(f"onboarding_id: {payload.get('onboarding_id') or 'none'}")
    print(f"state: {payload.get('state') or 'none'}")
    if payload.get("depth"):
        print(f"depth: {payload.get('depth')}")
    if payload.get("draft_is_stale"):
        print("draft_is_stale: true")
    return 0


def cmd_onboarding_update(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        active_run, session_id = _require_onboarding_context(ctx=ctx, action_name="onboarding-update")
        session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
        if not session:
            raise RepoOnboardingError("No current onboarding session exists.")
        draft_payload = _read_onboarding_payload(args, kind="draft")
        questions_payload = _read_onboarding_payload(args, kind="questions")
        result = onboarding_update(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            session=session,
            draft_payload=draft_payload,
            questions_payload=questions_payload,
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError) as exc:
        print(f"FAIL: {exc}")
        return 2

    written_artifacts = [
        str(item)
        for item in [result.get("draft_path"), result.get("question_set_path"), result.get("delta_path")]
        if str(item or "").strip()
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboarding-update",
        summary=f"Updated onboarding draft {result.get('draft_revision_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "draft_revision_id": result.get("draft_revision_id"),
            "question_set_id": result.get("question_set_id"),
            "changed_files": written_artifacts,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "draft_revision_id": result.get("draft_revision_id"),
            "question_set_id": result.get("question_set_id"),
            "revision_delta_id": result.get("revision_delta_id"),
            "draft_path": result.get("draft_path"),
            "question_set_path": result.get("question_set_path"),
            "delta_path": result.get("delta_path"),
        },
    )
    payload = {
        **result,
        "subject": ctx,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }

    def _emit_onboarding_update(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING UPDATED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"draft_revision_id: {rendered_payload.get('draft_revision_id')}")
        print(f"question_set_id: {rendered_payload.get('question_set_id')}")
        if rendered_payload.get("revision_delta_id"):
            print(f"revision_delta_id: {rendered_payload.get('revision_delta_id')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_onboarding_update,
    )


def cmd_onboarding_respond(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    try:
        active_run, session_id = _require_onboarding_context(ctx=ctx, action_name="onboarding-respond")
        session = current_onboarding_session(subject=ctx["subject"], data_root=data_root, require_current=True)
        if not session:
            raise RepoOnboardingError("No current onboarding session exists.")
        raw_text = _read_capture_text(args)
        payload = _read_capture_payload(args)
        source_role = normalize_capture_source_role(args.source_role)
        linked_question_ids = _read_optional_id_list(args)
        result = onboarding_respond(
            subject=ctx["subject"],
            data_root=data_root,
            engine_root=engine_root,
            session=session,
            active_run=active_run,
            raw_text=raw_text,
            payload=payload,
            title=args.title,
            source_role=source_role.value,
            linked_question_ids=linked_question_ids,
        )
        sidecar = _sync_sidecar(
            subject=ctx["subject"],
            data_root=data_root,
            active_run=active_run,
            signal=AmbientSignal(
                source="onboarding-respond",
                subject=ctx["subject"],
                title=str(args.title or "Onboarding clarification"),
                summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
                status="captured",
            ),
            semantic_capture_batch=result["batch"],
            mutate_proposals=False,
        )
        automation = _execute_automation_side_effects(
            ctx=ctx,
            active_run=active_run,
            activity_source="onboarding_response",
            activity_kind="onboarding-respond",
            summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
            notes=[
                str(item.get("summary") or "").strip()
                for item in result["batch"].get("captures") or []
                if isinstance(item, dict) and str(item.get("summary") or "").strip()
            ],
            uncertainty_present=batch_uncertainty_present(result["batch"]),
            explicit_capture_written=True,
            onboarding_response=True,
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    written_artifacts = [
        result.get("capture_artifact_path"),
        result.get("capture_ledger_path"),
    ]
    if sidecar.get("open_questions_path"):
        written_artifacts.append(sidecar.get("open_questions_path"))
    signals = {
        "run_id": active_run.get("run_id"),
        "onboarding_id": result.get("onboarding_id"),
        "question_set_id": session.get("current_question_set_id"),
        "capture_batch_id": result.get("capture_batch_id"),
        "linked_question_ids": list(result.get("linked_question_ids") or []),
        "changed_files": [str(item) for item in written_artifacts if str(item or "").strip()],
        "verification_entries": [],
        "related_quest_ids": [],
        "related_sidequest_ids": [],
        **session_mode_signal_fields(active_run),
    }
    outputs = {
        "onboarding_id": result.get("onboarding_id"),
        "capture_batch_id": result.get("capture_batch_id"),
        "capture_artifact_path": result.get("capture_artifact_path"),
        "capture_ledger_path": result.get("capture_ledger_path"),
        "linked_question_ids": list(result.get("linked_question_ids") or []),
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "uncertainty_present": True,
    }
    _apply_automation_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        automation=automation,
    )
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboarding-respond",
        summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
        session_id=session_id,
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = _apply_automation_partial_status(event_info=event_info, automation=automation)
    event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)
    payload_out = {
        **{key: value for key, value in result.items() if key != "batch"},
        "subject": ctx,
        "sidecar": sidecar,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
        "automation": automation,
        "truth_status": truth_status,
    }

    def _emit_onboarding_respond(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING RESPONSE CAPTURED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"capture_batch_id: {rendered_payload.get('capture_batch_id')}")
        print(f"capture_artifact_path: {rendered_payload.get('capture_artifact_path')}")

    return _finalize_mutation_result(
        payload=payload_out,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_onboarding_respond,
    )


def cmd_onboarding_confirm(args: argparse.Namespace) -> int:
    if not args.yes_i_confirm:
        print("FAIL: onboarding-confirm requires --yes-i-confirm.")
        return 2
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        active_run, session_id = _require_onboarding_context(ctx=ctx, action_name="onboarding-confirm")
        session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
        if not session:
            raise RepoOnboardingError("No current onboarding session exists.")
        result = onboarding_confirm(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            session=session,
            active_run=active_run,
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError) as exc:
        print(f"FAIL: {exc}")
        return 2

    written_artifacts = [
        result.get("published_project_model_path"),
        result.get("published_project_story_path"),
        result.get("published_vision_path"),
        result.get("published_codex_current_path"),
        result.get("published_codex_future_path"),
        result.get("publication_receipt_path"),
        *list(result.get("proposal_paths") or []),
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboarding-confirm",
        summary=f"Confirmed onboarding session {result.get('onboarding_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "publication_receipt_path": result.get("publication_receipt_path"),
            "changed_files": [str(item) for item in written_artifacts if str(item or "").strip()],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "publication_receipt_path": result.get("publication_receipt_path"),
            "published_project_model_path": result.get("published_project_model_path"),
            "published_project_story_path": result.get("published_project_story_path"),
            "published_vision_path": result.get("published_vision_path"),
            "published_codex_current_path": result.get("published_codex_current_path"),
            "published_codex_future_path": result.get("published_codex_future_path"),
            "compile_status": result.get("compile_status"),
            "compiled_current_state_path": result.get("compiled_current_state_path"),
            "proposal_paths": list(result.get("proposal_paths") or []),
        },
    )
    if str(result.get("compile_status") or "").lower() != "ok":
        event_info = _apply_follow_on_partial_status(
            event_info=event_info,
            error_code="POST_PUBLICATION_TRUTH_COMPILE_FAILED",
            error_message=str(result.get("compile_error_message") or "Canonical onboarding publications were written, but post-publication truth compile did not complete successfully."),
            recovery_hint=(
                "Onboarding publications are already written. Repair the truth-compile path and rerun `python3 runtime/synapse.py compile-current-state`."
            ),
        )
    truth_compile = result.get("truth_compile")
    payload = {
        **result,
        "subject": ctx,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
        "truth_compile": truth_compile,
    }

    def _emit_onboarding_confirm(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING CONFIRMED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"published_project_model_path: {rendered_payload.get('published_project_model_path')}")
        print(f"published_project_story_path: {rendered_payload.get('published_project_story_path')}")
        print(f"published_vision_path: {rendered_payload.get('published_vision_path')}")
        print(f"published_codex_current_path: {rendered_payload.get('published_codex_current_path')}")
        print(f"published_codex_future_path: {rendered_payload.get('published_codex_future_path')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_onboarding_confirm,
    )


def cmd_onboarding_abandon(args: argparse.Namespace) -> int:
    if not str(args.reason or "").strip():
        print("FAIL: onboarding-abandon requires --reason.")
        return 2
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        active_run, session_id = _require_onboarding_context(ctx=ctx, action_name="onboarding-abandon")
        session = current_onboarding_session(subject=ctx["subject"], data_root=Path(ctx["data_root"]), require_current=True)
        if not session:
            raise RepoOnboardingError("No current onboarding session exists.")
        result = onboarding_abandon(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            session=session,
            reason=args.reason,
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError) as exc:
        print(f"FAIL: {exc}")
        return 2

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboarding-abandon",
        summary=f"Abandoned onboarding session {result.get('onboarding_id')}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "onboarding_id": result.get("onboarding_id"),
            "changed_files": [str(Path(ctx["data_root"]) / ".synapse" / "ONBOARDING" / "CURRENT.yaml")],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "abandon_reason": result.get("abandon_reason"),
        },
    )
    payload = {
        **result,
        "subject": ctx,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }

    def _emit_onboarding_abandon(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING ABANDONED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"reason: {rendered_payload.get('abandon_reason')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_onboarding_abandon,
    )


def cmd_session_mode(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    data_root = Path(ctx["data_root"])
    payload = _session_mode_payload(ctx)
    if not args.target_session_mode:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        print("=== SESSION MODE ===")
        print(f"active_run_id: {payload.get('active_run_id') or 'none'}")
        print(f"active_session_mode: {payload.get('active_session_mode') or 'none'}")
        if payload.get("active_session_mode"):
            print(f"allowed_next_modes: {', '.join(payload.get('allowed_next_modes') or [])}")
        if payload.get("last_session_mode"):
            print(f"last_session_mode: {payload.get('last_session_mode')}")
            print(f"last_session_mode_ended_at: {payload.get('last_session_mode_ended_at')}")
        return 0

    active_run = _load_active_run_with_session_repair(ctx)
    if not active_run.get("run_id"):
        return _session_mode_change_error(
            payload,
            json_mode=args.json,
            message="No active run exists. Start or resume a run before changing session posture.",
        )

    current_mode = SessionMode(str(active_run.get("session_mode") or ""))
    target_mode = SessionMode(args.target_session_mode)
    payload["target_session_mode"] = target_mode.value
    if current_mode == target_mode:
        payload["changed"] = False
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("=== SESSION MODE ===")
            print(f"active_run_id: {payload.get('active_run_id')}")
            print(f"active_session_mode: {payload.get('active_session_mode')}")
            print("changed: false")
        return 0

    gate = ready_state_gate_for_mode(data_root=data_root, target_mode=target_mode)
    if gate.get("blocked"):
        return _session_mode_change_error(
            payload,
            json_mode=args.json,
            message=_onboarding_gate_message(target_mode=target_mode.value, gate=gate),
        )

    if not str(args.reason or "").strip():
        return _session_mode_change_error(
            payload,
            json_mode=args.json,
            message="Changing session posture requires --reason.",
        )

    allowed, next_modes = validate_transition(current_mode, target_mode)
    payload["allowed_next_modes"] = [mode.value for mode in next_modes]
    if not allowed:
        return _session_mode_change_error(
            payload,
            json_mode=args.json,
            message=(
                f"Invalid session-mode transition: {current_mode.value} -> {target_mode.value}. "
                "Use one of the allowed next modes instead."
            ),
        )

    run_path = data_root / ".synapse" / "ACTIVE_RUN.yaml"
    transition_at = dt.datetime.now().astimezone().isoformat()
    session_id = _effective_session_id(ctx, active_run=active_run)
    active_run["session_mode"] = target_mode.value
    active_run["session_mode_source"] = "explicit_transition"
    active_run["session_mode_set_at"] = transition_at
    active_run["session_mode_reason"] = str(args.reason).strip()
    active_run["session_mode_policy_version"] = active_run.get("session_mode_policy_version") or SESSION_MODE_POLICY_VERSION
    run_path.write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="session-mode-set",
        summary=f"Changed session posture from {current_mode.value} to {target_mode.value}.",
        session_id=session_id,
        signals={
            "run_id": active_run.get("run_id"),
            "from_session_mode": current_mode.value,
            "to_session_mode": target_mode.value,
            "session_mode_reason": str(args.reason).strip(),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "run_id": active_run.get("run_id"),
            "run_path": str(run_path),
        },
    )

    payload = _session_mode_payload(ctx)
    payload["changed"] = True
    payload["from_session_mode"] = current_mode.value
    payload["to_session_mode"] = target_mode.value
    payload["run_path"] = str(run_path)
    payload["event"] = event_info["event"]
    payload["reducer"] = event_info["reducer"]
    payload["rehydrate"] = event_info["reducer"]["rehydrate"]
    payload["continuity"] = event_info["reducer"]["continuity"]

    def _emit_session_mode(rendered_payload: dict[str, Any]) -> None:
        print("=== SESSION MODE UPDATED ===")
        print(f"active_run_id: {rendered_payload.get('active_run_id')}")
        print(f"from: {rendered_payload.get('from_session_mode')}")
        print(f"to: {rendered_payload.get('to_session_mode')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_session_mode,
    )


def cmd_log_decision(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        active_run = _load_active_run_with_session_repair(ctx)
        session_id = _effective_session_id(ctx, active_run=active_run)
        result = log_decision(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            title=args.title,
            summary=args.summary,
            why=args.why,
            constraints=args.constraint,
            tradeoffs=args.tradeoff,
            related_runs=args.related_run,
            related_quests=args.related_quest,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="log-decision",
            summary=args.summary,
            session_id=session_id,
            signals={
                "decision_title": args.title,
                "decisions": [args.title],
                "notes": [args.why] if args.why else [],
                "decision_constraints": list(args.constraint or []),
                "decision_tradeoffs": list(args.tradeoff or []),
                "related_quest_ids": list(args.related_quest or []),
                "related_sidequest_ids": [],
                "changed_files": [result.get("decision_path")] if result.get("decision_path") else [],
                "verification_entries": [],
                "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
                **session_mode_signal_fields(active_run),
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "decision_path": result.get("decision_path"),
                "decisions_ledger_path": result.get("decisions_ledger_path"),
            },
        )
        event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
        result["truth_status"] = truth_status
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_log_decision(payload: dict[str, Any]) -> None:
        print("=== DECISION LOGGED ===")
        print(f"path: {payload.get('decision_path')}")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_log_decision,
    )


def cmd_log_disclosure(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        active_run = _load_active_run_with_session_repair(ctx)
        session_id = _effective_session_id(ctx, active_run=active_run)
        result = log_disclosure(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            trigger=args.trigger,
            expected=args.expected,
            provable=args.provable,
            status_labels=args.status_label,
            impact=args.impact,
            safe_options=args.safe_option,
            decision_needed=args.decision_needed,
            related_runs=args.related_run,
            related_quests=args.related_quest,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="log-disclosure",
            summary=args.impact,
            session_id=session_id,
            signals={
                "disclosure_trigger": args.trigger,
                "disclosures": [args.trigger],
                "notes": [
                    value
                    for value in [args.expected, args.provable, args.decision_needed, *(args.safe_option or [])]
                    if str(value).strip()
                ],
                "status_labels": list(args.status_label or []),
                "safe_options": list(args.safe_option or []),
                "related_quest_ids": list(args.related_quest or []),
                "related_sidequest_ids": [],
                "changed_files": [result.get("disclosure_path")] if result.get("disclosure_path") else [],
                "verification_entries": [],
                "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
                **session_mode_signal_fields(active_run),
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": True,
                "disclosure_open": True,
            },
            outputs={
                "disclosure_path": result.get("disclosure_path"),
                "disclosures_ledger_path": result.get("disclosures_ledger_path"),
            },
        )
        event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
        result["truth_status"] = truth_status
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_log_disclosure(payload: dict[str, Any]) -> None:
        print("=== DISCLOSURE LOGGED ===")
        print(f"path: {payload.get('disclosure_path')}")

    return _finalize_mutation_result(
        payload=result,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_log_disclosure,
    )


def cmd_render_rehydrate(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        result = _render_and_refresh_continuity(ctx["subject"], Path(ctx["data_root"]), Path(ctx["engine_root"]))
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.json:
        payload = dict(result["rehydrate"])
        payload["continuity"] = result["continuity"]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== REHYDRATE RENDERED ===")
    print(f"path: {result['rehydrate'].get('rehydrate_path')}")
    print(f"continuity_lock: {result['continuity'].get('continuity_lock_path')}")
    return 0


def cmd_refresh_continuity(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        refresh_provenance_projection(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            engine_root=Path(ctx["engine_root"]),
        )
        result = refresh_rehydration_pack(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            engine_root=Path(ctx["engine_root"]),
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== CONTINUITY REFRESHED ===")
    print(f"bootstrap_prompt: {result.get('bootstrap_prompt_path')}")
    print(f"continuity_lock: {result.get('continuity_lock_path')}")
    return 0


def cmd_compile_current_state(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    active_run = _load_active_run_with_session_repair(ctx)
    session_id = _effective_session_id(ctx, active_run=active_run)
    compile_result, event_info, compile_error = _run_truth_compile(ctx=ctx, session_id=session_id)
    if compile_error is not None:
        payload = {
            "subject": ctx,
            **(dict(getattr(compile_error, "payload", {}) or {})),
        }

        def _emit_compile_partial(rendered_payload: dict[str, Any]) -> None:
            print("=== CURRENT STATE COMPILE ===")
            print(f"statement_store_path: {rendered_payload.get('statement_store_path')}")
            print(f"compiler_report_path: {rendered_payload.get('compiler_report_path')}")

        if isinstance(compile_error, TruthCompilerPartialError):
            return _finalize_mutation_result(
                payload=payload,
                event_info=_partial_after_primary_mutation(
                    error_code="TRUTH_PUBLICATION_RENDER_FAILED",
                    error_message=str(compile_error),
                    recovery_hint=(
                        "Statement store and compiler report were written, but publication replacement did not complete. "
                        "Repair the publication renderer and rerun compile-current-state."
                    ),
                ),
                json_mode=args.json,
                text_emitter=_emit_compile_partial,
            )
        print(f"FAIL: {compile_error}")
        return 2

    payload = {
        "subject": ctx,
        **compile_result,
    }

    def _emit_compile(rendered_payload: dict[str, Any]) -> None:
        print("=== CURRENT STATE COMPILED ===")
        print(f"compile_cycle_id: {rendered_payload.get('compile_cycle_id')}")
        print(f"statement_store_path: {rendered_payload.get('statement_store_path')}")
        print(f"compiler_report_path: {rendered_payload.get('compiler_report_path')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_compile,
    )


def _accept_quest_mutation(
    ctx: dict[str, Any],
    quest_ref: str,
    *,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    active_run = active_run or _active_session_policy(ctx)[0]
    session_id = _effective_session_id(ctx, active_run=active_run)
    acceptance = accept_quest(
        subject=ctx["subject"],
        data_root=data_root,
        engine_root=engine_root,
        quest_ref=quest_ref,
    )
    sidecar = record_quest_acceptance(
        subject=ctx["subject"],
        data_root=data_root,
        quest_id=str(acceptance["quest_id"]),
        quest_title=str(acceptance["quest_title"]),
        accepted_path=Path(str(acceptance["accepted_path"])),
        audit_bundle_path=Path(str(acceptance["audit_bundle_path"])),
        control_sync_state_path=Path(str(acceptance["control_sync_state_path"])),
    )
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="accept-quest",
        summary=f"Accepted quest {acceptance.get('quest_id')} for governed execution.",
        session_id=session_id,
        signals={
            "related_quest_ids": [acceptance.get("quest_id")],
            "related_sidequest_ids": [],
            "changed_files": [acceptance.get("accepted_path"), acceptance.get("audit_bundle_path")],
            "verification_entries": [],
            "accepted_context": _accepted_context_snapshot(data_root),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": True,
            "governed_execution_changed": True,
            "uncertainty_present": False,
        },
        outputs={
            "accepted_path": acceptance.get("accepted_path"),
            "audit_bundle_path": acceptance.get("audit_bundle_path"),
            "quest_id": acceptance.get("quest_id"),
            "accepted_quest_id": acceptance.get("quest_id"),
            "written_artifacts": [acceptance.get("accepted_path"), acceptance.get("audit_bundle_path")],
        },
    )
    return {
        "subject": ctx,
        "acceptance": acceptance,
        "sidecar": sidecar,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "runtime_status": event_info["runtime_status"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }


def _complete_quest_mutation(
    ctx: dict[str, Any],
    quest_ref: str,
    *,
    milestone_entries: list[str],
    check_entries: list[str],
    commands_run: list[str],
    changed_files: list[str],
    receipt_refs: list[str],
    skipped_items: list[str],
    unresolved_gaps: list[str],
    known_bugs: list[str],
    blockers: list[str],
    disclosures: list[str],
    notes: list[str],
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = active_run or _active_session_policy(ctx)[0]
    session_id = _effective_session_id(ctx, active_run=active_run)
    completion = complete_quest(
        subject=ctx["subject"],
        data_root=data_root,
        quest_ref=quest_ref,
        milestone_entries=milestone_entries,
        check_entries=check_entries,
        commands_run=commands_run,
        changed_files=changed_files,
        receipt_refs=receipt_refs,
        skipped_items=skipped_items,
        unresolved_gaps=unresolved_gaps,
        known_bugs=known_bugs,
        blockers=blockers,
        disclosures=disclosures,
        notes=notes,
    )
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="complete-quest",
        summary=(
            f"Completed quest {completion.get('quest_id')} with a clean PASS completion audit."
            if completion.get("final_state_decision") == "COMPLETED"
            else f"Quest {completion.get('quest_id')} remains active after a {completion.get('overall_verdict')} completion audit."
        ),
        session_id=session_id,
        signals={
            "related_quest_ids": [completion.get("quest_id")],
            "related_sidequest_ids": [],
            "changed_files": [
                completion.get("active_path"),
                completion.get("audit_bundle_path"),
                completion.get("latest_completion_audit_path"),
                *changed_files,
            ],
            "verification_entries": [*check_entries, *receipt_refs],
            "accepted_context": _accepted_context_snapshot(data_root),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": True,
            "governed_execution_changed": True,
            "uncertainty_present": bool(unresolved_gaps or blockers or known_bugs or skipped_items),
        },
        outputs={
            "quest_id": completion.get("quest_id"),
            "active_path": completion.get("active_path"),
            "audit_bundle_path": completion.get("audit_bundle_path"),
            "latest_completion_audit_path": completion.get("latest_completion_audit_path"),
            "final_state_decision": completion.get("final_state_decision"),
            "overall_verdict": completion.get("overall_verdict"),
            "written_artifacts": [
                completion.get("active_path"),
                completion.get("latest_completion_audit_path"),
                completion.get("audit_bundle_path"),
            ],
        },
    )
    return {
        "subject": ctx,
        "completion": completion,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "runtime_status": event_info["runtime_status"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }


def _plan_quests_mutation(
    ctx: dict[str, Any],
    *,
    items: list[str],
    title: str | None,
    goal: str | None,
    coherent_outcome: str | None,
    closure_statement: str | None,
    split_triggers: list[str],
    separate_outcomes: list[str],
    dependencies: list[str],
    out_of_scope: str | None,
    verification_plan: str | None,
    guild_orders_ref: str | None,
    guild_orders_artifact: str | None,
    dungeon_ref: str | None,
    dungeon_id: str | None,
    dungeon_coverage: str,
    plan_id: str | None,
    priority: str,
    risk: str,
    change_class: str,
    vision_delta: str,
    door_impact: str,
    testing_level: str,
    origin: str | None,
    anchors: list[str],
    constraints: list[str],
    deprecated_alias: bool,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_run = active_run or _active_session_policy(ctx)[0]
    session_id = _effective_session_id(ctx, active_run=active_run)
    payload = _plan_quests_payload(
        ctx,
        items=items,
        title=title,
        goal=goal,
        coherent_outcome=coherent_outcome,
        closure_statement=closure_statement,
        split_triggers=split_triggers,
        separate_outcomes=separate_outcomes,
        dependencies=dependencies,
        out_of_scope=out_of_scope,
        verification_plan=verification_plan,
        guild_orders_ref=guild_orders_ref,
        guild_orders_artifact=guild_orders_artifact,
        dungeon_ref=dungeon_ref,
        dungeon_id=dungeon_id,
        dungeon_coverage=dungeon_coverage,
        plan_id=plan_id,
        priority=priority,
        risk=risk,
        change_class=change_class,
        vision_delta=vision_delta,
        door_impact=door_impact,
        testing_level=testing_level,
        origin=origin,
        anchors=anchors,
        constraints=constraints,
        deprecated_alias=deprecated_alias,
        dry_run=False,
    )
    quest_ids = [str(entry.get("quest_id") or "").strip() for entry in payload.get("quests") or [] if str(entry.get("quest_id") or "").strip()]
    changed_files = [
        payload.get("plan_artifact_path"),
        *[entry.get("path") for entry in payload.get("quests") or []],
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="plan-quests",
        summary=f"Persisted plan {payload.get('plan_id')} and drafted {len(quest_ids)} quest(s) on BOARD.",
        session_id=session_id,
        signals={
            "plan_items": list(items),
            "related_quest_ids": quest_ids,
            "related_sidequest_ids": [],
            "changed_files": changed_files,
            "verification_entries": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": False,
            "governed_execution_changed": False,
            "uncertainty_present": False,
        },
        outputs={
            "plan_id": payload.get("plan_id"),
            "plan_artifact_path": payload.get("plan_artifact_path"),
            "quest_id": quest_ids[0] if len(quest_ids) == 1 else None,
            "written_artifacts": [item for item in changed_files if item],
        },
    )
    payload.update(
        {
            "subject_context": ctx,
            "event": event_info["event"],
            "reducer": event_info["reducer"],
            "runtime_status": event_info["runtime_status"],
            "rehydrate": event_info["reducer"]["rehydrate"],
            "continuity": event_info["reducer"]["continuity"],
        }
    )
    return payload


def cmd_accept_quest(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    active_run, session_policy = _active_session_policy(ctx)
    if session_policy is not None and not session_policy.quest_acceptance_allowed:
        return _fail_blocked_by_session_posture(
            action_name="accept-quest",
            active_run=active_run,
            json_mode=args.json,
        )
    try:
        payload = _accept_quest_mutation(ctx, args.quest, active_run=active_run)
        event_info = {"event": payload["event"], "reducer": payload["reducer"], "runtime_status": payload.get("runtime_status")}
        event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)
        payload["truth_status"] = truth_status
    except (QuestAcceptanceError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_accept_quest(rendered_payload: dict[str, Any]) -> None:
        acceptance_payload = rendered_payload["acceptance"]
        print("=== QUEST ACCEPTED ===")
        print(f"quest_id: {acceptance_payload.get('quest_id')}")
        print(f"accepted_path: {acceptance_payload.get('accepted_path')}")
        print(f"audit_bundle_path: {acceptance_payload.get('audit_bundle_path')}")
        print(f"governed_execution_ready: {acceptance_payload.get('governed_execution_ready')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_accept_quest,
    )


def cmd_complete_quest(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    active_run, session_policy = _active_session_policy(ctx)
    if session_policy is not None and "complete-quest" in session_policy.blocked_mutation_commands:
        return _fail_blocked_by_session_posture(
            action_name="complete-quest",
            active_run=active_run,
            json_mode=args.json,
        )
    try:
        payload = _complete_quest_mutation(
            ctx,
            args.quest,
            milestone_entries=args.milestone_status,
            check_entries=args.check,
            commands_run=args.command_runs,
            changed_files=args.changed_file,
            receipt_refs=args.receipt_ref,
            skipped_items=args.skipped_item,
            unresolved_gaps=args.unresolved_gap,
            known_bugs=args.known_bug,
            blockers=args.blocker,
            disclosures=args.disclosure,
            notes=args.note,
            active_run=active_run,
        )
        event_info = {"event": payload["event"], "reducer": payload["reducer"], "runtime_status": payload.get("runtime_status")}
        event_info, truth_status = _refresh_truth_status_after_mutation(ctx=ctx, event_info=event_info)
        payload["truth_status"] = truth_status
    except (QuestCompletionError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_complete_quest(rendered_payload: dict[str, Any]) -> None:
        completion_payload = rendered_payload["completion"]
        print("=== QUEST COMPLETION AUDIT ===")
        print(f"quest_id: {completion_payload.get('quest_id')}")
        print(f"overall_verdict: {completion_payload.get('overall_verdict')}")
        print(f"final_state_decision: {completion_payload.get('final_state_decision')}")
        print(f"active_path: {completion_payload.get('active_path')}")
        print(f"latest_completion_audit_path: {completion_payload.get('latest_completion_audit_path')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_complete_quest,
    )


def _proposal_by_id(data_root: Path, proposal_id: str) -> dict[str, Any]:
    for proposal in list_proposals(data_root=data_root):
        if str(proposal.get("proposal_id") or "") == proposal_id:
            return proposal
    raise LiveMemoryError(f"Proposal not found: {proposal_id}")


def _snapshot_writer(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "tools" / "synapse_snapshot_writer.py"), *args],
        cwd=str(detect_canonical_working_tree()),
        check=False,
        capture_output=True,
        text=True,
    )


def _codex_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "tools" / "synapse_codex_gate.py"), *args],
        cwd=str(detect_canonical_working_tree()),
        check=False,
        capture_output=True,
        text=True,
    )


def _snapshot_path_from_output(output: str) -> str | None:
    for line in output.splitlines():
        if "snapshot:" in line:
            return line.split("snapshot:", 1)[1].strip()
    return None


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _formalize_snapshot(ctx: dict[str, Any], proposal: dict[str, Any], *, control_sync: bool) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = load_active_run_record(subject=ctx["subject"], data_root=data_root)
    commands = list(active_run.get("commands") or [])
    files = list(active_run.get("files_touched") or [])
    verification = list(active_run.get("verification") or [])
    notes = list(active_run.get("notes") or [])

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        if control_sync:
            decisions_file = tmp / "decisions.txt"
            decisions_file.write_text(
                f"- {proposal.get('title')}: {proposal.get('summary')}\n- Reason: {proposal.get('reason')}\n",
                encoding="utf-8",
            )
            open_result = _snapshot_writer(
                [
                    "--subject",
                    ctx["subject"],
                    "--data-root",
                    str(data_root),
                    "control-open",
                    "--participants",
                    "Brains, Hands",
                    "--reason",
                    proposal.get("reason") or "ambient control-sync formalization",
                    "--topic",
                    proposal.get("title") or "",
                ]
            )
            if open_result.returncode != 0 and "already active" not in (open_result.stdout + open_result.stderr):
                raise LiveMemoryError(open_result.stdout + open_result.stderr)
            close_result = _snapshot_writer(
                [
                    "--subject",
                    ctx["subject"],
                    "--data-root",
                    str(data_root),
                    "control-close",
                    "--decisions-file",
                    str(decisions_file),
                    "--next-action",
                    proposal.get("summary") or "",
                    "--topic",
                    proposal.get("title") or "",
                ]
            )
            if close_result.returncode != 0:
                raise LiveMemoryError(close_result.stdout + close_result.stderr)
            artifact_path = _snapshot_path_from_output(close_result.stdout + close_result.stderr)
            raw_output = close_result.stdout + close_result.stderr
        else:
            work_file = tmp / "work.txt"
            completed_file = tmp / "completed.txt"
            verification_file = tmp / "verification.txt"
            resume_file = tmp / "resume.txt"
            work_file.write_text(
                "\n".join(
                    [
                        f"- Proposal: {proposal.get('proposal_id')}",
                        f"- Summary: {proposal.get('summary')}",
                        *(f"- Command: {item}" for item in commands),
                        *(f"- File: {item}" for item in files),
                        *(f"- Note: {item}" for item in notes),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            completed_file.write_text(f"- {proposal.get('summary')}\n", encoding="utf-8")
            verification_file.write_text("\n".join(f"- {item}" for item in verification) + ("\n" if verification else "- none\n"), encoding="utf-8")
            resume_file.write_text(
                f"- Review proposal {proposal.get('proposal_id')}\n- Next focus: {proposal.get('title')}\n",
                encoding="utf-8",
            )
            eod_result = _snapshot_writer(
                [
                    "--subject",
                    ctx["subject"],
                    "--data-root",
                    str(data_root),
                    "eod",
                    "--topic",
                    proposal.get("title") or "",
                    "--work-file",
                    str(work_file),
                    "--completed-file",
                    str(completed_file),
                    "--verification-file",
                    str(verification_file),
                    "--resume-file",
                    str(resume_file),
                ]
            )
            if eod_result.returncode != 0:
                raise LiveMemoryError(eod_result.stdout + eod_result.stderr)
            artifact_path = _snapshot_path_from_output(eod_result.stdout + eod_result.stderr)
            raw_output = eod_result.stdout + eod_result.stderr

    if not artifact_path:
        raise LiveMemoryError("Snapshot writer did not report artifact path.")
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=artifact_path,
        note="Formalized via synapse formalize.",
    )
    return {"artifact_path": artifact_path, "proposal": proposal_receipt, "raw_output": raw_output}


def _formalize_quest(ctx: dict[str, Any], proposal: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    if str(proposal.get("state") or "") == ProposalState.BLOCKED.value:
        raise LiveMemoryError(f"Proposal {proposal['proposal_id']} is BLOCKED and cannot be formalized.")

    data_root = Path(ctx["data_root"])
    draft = draft_quest_from_proposal(subject=ctx["subject"], data_root=data_root, proposal=proposal, prefix=prefix)
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(draft["artifact_path"]),
        note=f"Formalized into {draft['quest_id']}.",
    )
    return {"artifact_path": str(draft["artifact_path"]), "proposal": proposal_receipt}


def _ensure_codex_build_state(data_root: Path) -> Path:
    codex_dir = data_root / "Codex"
    sections_dir = codex_dir / "Sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    build_state = codex_dir / "CODEX_BUILD_STATE.yaml"
    if not build_state.exists():
        build_state.write_text(
            "schema_version: 1\noverall_status: IN_PROGRESS\nspec_completeness_gate:\n  status: NEEDS_DECISIONS\nconsistency_gate:\n  status: NEEDS_DECISIONS\nsections: []\nnotes: []\n",
            encoding="utf-8",
        )
    return build_state


def _formalize_codex(ctx: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    today = _today_toronto()
    slug = _slugify(str(proposal.get("title") or "codex"))
    section_path = data_root / "Codex" / "Sections" / f"CANDIDATE__{slug}__{today}.md"
    section_path.parent.mkdir(parents=True, exist_ok=True)
    section_path.write_text(
        "\n".join(
            [
                f"# Codex Candidate - {proposal.get('title')}",
                "",
                f"- Proposal ID: {proposal.get('proposal_id')}",
                f"- Formalized On: {today}",
                "",
                "## Summary",
                str(proposal.get("summary") or ""),
                "",
                "## Reason",
                str(proposal.get("reason") or ""),
                "",
                "## Codex Implications",
                *(f"- {item}" for item in proposal.get("codex_implications") or []),
                "",
                "## Evidence",
                *(f"- {item}" for item in proposal.get("evidence") or []),
                "",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    build_state_path = _ensure_codex_build_state(data_root)
    build_state = yaml.safe_load(build_state_path.read_text(encoding="utf-8")) or {}
    sections = build_state.get("sections")
    if not isinstance(sections, list):
        sections = []
    sections.append(
        {
            "section_path": _relative_to_root(data_root, section_path),
            "status": "PROPOSED_FROM_AMBIENT",
            "source_proposal_id": proposal.get("proposal_id"),
            "updated_at": dt.datetime.now().astimezone().isoformat(),
        }
    )
    build_state["sections"] = sections
    build_state["overall_status"] = "IN_PROGRESS"
    build_state_path.write_text(yaml.safe_dump(build_state, sort_keys=False), encoding="utf-8")
    gate_result = _codex_gate(
        [
            "--subject",
            ctx["subject"],
            "--data-root",
            str(data_root),
            "consistency",
            "--section",
            str(section_path),
            "--write-state",
            "--update-anchor",
        ]
    )
    if gate_result.returncode != 0:
        raise LiveMemoryError(gate_result.stdout + gate_result.stderr)
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(section_path),
        note="Codex candidate shard written.",
    )
    return {
        "artifact_path": str(section_path),
        "proposal": proposal_receipt,
        "raw_output": gate_result.stdout + gate_result.stderr,
    }


def _ensure_build_manual_root(data_root: Path, subject: str) -> tuple[Path, Path]:
    build_dir = data_root / "Build_Manual"
    updates_dir = build_dir / "Updates"
    build_dir.mkdir(parents=True, exist_ok=True)
    updates_dir.mkdir(parents=True, exist_ok=True)
    manual_path = build_dir / "BUILD_MANUAL.md"
    if not manual_path.exists():
        manual_path.write_text(
            "\n".join(
                [
                    "# Build Manual",
                    "",
                    f"- Subject: {subject}",
                    "- Purpose: Define HOW to make the Codex true without redefining Codex law.",
                    "- Authority: Subordinate to Codex. Conflicts require Control Sync.",
                    "",
                    "## Core Construction Rules",
                    "- Review Codex and current Guild Orders before structural execution.",
                    "- Keep implementation slices small enough to verify with receipts.",
                    "- Preserve proof for every claimed command, test, and artifact transition.",
                    "",
                    "## Active Guidance Deltas",
                    "- None yet.",
                    "",
                    "## Verification Expectations",
                    "- Capture raw command/test receipts for each structural slice.",
                    "- Do not promote ambient guidance into law without proof and review.",
                    "",
                    "## Formalization History",
                    "- None yet.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return manual_path, updates_dir


def _formalize_build_manual(ctx: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    today = _today_toronto()
    manual_path, updates_dir = _ensure_build_manual_root(data_root, ctx["subject"])
    slug = _slugify(str(proposal.get("title") or "build-manual"))
    update_path = updates_dir / f"UPDATE__{today}__{slug}.md"
    evidence = [str(item) for item in proposal.get("evidence") or []]
    codex_implications = [str(item) for item in proposal.get("codex_implications") or []]

    update_lines = [
        f"# Build Manual Update - {proposal.get('title')}",
        "",
        f"- Proposal ID: {proposal.get('proposal_id')}",
        f"- Formalized On: {today}",
        "",
        "## Why this update exists",
        str(proposal.get("reason") or ""),
        "",
        "## Current HOW delta",
        str(proposal.get("summary") or ""),
        "",
        "## Sequencing guidance",
        "- Reconfirm relevant Codex anchors before structural execution.",
        "- Apply scaffolding or wiring changes before dependent feature work.",
        "- Re-run verification receipts after each meaningful construction slice.",
        "",
        "## Verification expectations",
        "- Preserve exact command and test output for the affected build path.",
        "- Treat Build Manual guidance as subordinate to Codex and active Control Sync outputs.",
    ]
    if codex_implications:
        update_lines.extend(["", "## Codex constraints", *[f"- {item}" for item in codex_implications]])
    if evidence:
        update_lines.extend(["", "## Evidence", *[f"- {item}" for item in evidence]])
    update_lines.append("")
    update_path.write_text("\n".join(update_lines), encoding="utf-8")

    manual_text = manual_path.read_text(encoding="utf-8", errors="replace").rstrip()
    delta_block = (
        f"### {today} - {proposal.get('title')}\n"
        f"- Summary: {proposal.get('summary')}\n"
        f"- Reason: {proposal.get('reason')}\n"
        f"- Update receipt: {update_path.relative_to(data_root).as_posix()}"
    )
    history_entry = f"- {today}: {proposal.get('title')} ({update_path.relative_to(data_root).as_posix()})"
    if "## Active Guidance Deltas\n- None yet." in manual_text:
        manual_text = manual_text.replace("## Active Guidance Deltas\n- None yet.", f"## Active Guidance Deltas\n{delta_block}", 1)
    elif "## Verification Expectations" in manual_text and "## Active Guidance Deltas" in manual_text:
        manual_text = manual_text.replace("## Verification Expectations", f"{delta_block}\n\n## Verification Expectations", 1)
    else:
        manual_text += f"\n\n## Active Guidance Deltas\n{delta_block}"
    if "## Formalization History\n- None yet." in manual_text:
        manual_text = manual_text.replace("## Formalization History\n- None yet.", f"## Formalization History\n{history_entry}", 1)
    else:
        manual_text += f"\n{history_entry}"
    manual_path.write_text(manual_text.rstrip() + "\n", encoding="utf-8")

    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(manual_path),
        note=f"Build Manual updated from {update_path.name}.",
    )
    return {
        "artifact_path": str(manual_path),
        "proposal": proposal_receipt,
        "update_path": str(update_path),
    }


def _ensure_talent_files(data_root: Path) -> tuple[Path, Path]:
    talent_dir = data_root / "Talent Tree"
    talent_dir.mkdir(parents=True, exist_ok=True)
    tree_path = talent_dir / "TALENT_TREE.txt"
    log_path = talent_dir / "TALENT_LOG.txt"
    if not tree_path.exists():
        shutil.copy2(resolve_governance_asset("Talent Tree", "TALENT_TREE.txt"), tree_path)
    if not log_path.exists():
        shutil.copy2(resolve_governance_asset("Talent Tree", "TALENT_LOG.txt"), log_path)
    return tree_path, log_path


def _next_talent_id(tree_text: str) -> str:
    matches = [int(item) for item in re.findall(r"(?im)^TALENT ID:\s*T-(\d{3})\b", tree_text)]
    next_num = (max(matches) if matches else 0) + 1
    return f"T-{next_num:03d}"


def _formalize_talent(ctx: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    tree_path, log_path = _ensure_talent_files(data_root)
    tree_text = tree_path.read_text(encoding="utf-8", errors="replace")
    talent_id = _next_talent_id(tree_text)
    today = _today_toronto()
    evidence = [str(item) for item in proposal.get("evidence") or []] or [f".synapse/RUNS/{proposal.get('source_id')}"]
    source_ref = str(proposal.get("source_id") or "AMBIENT-RUN")
    tree_entry = (
        "\n"
        f"TALENT ID: {talent_id}\n"
        f"Name: {proposal.get('title')}\n"
        f"Unlocked On: {today}\n"
        f"Source Quest: {source_ref} + {evidence[0]}\n"
        "Scope: Engine\n\n"
        "Capability:\n"
        f"{proposal.get('summary')}\n\n"
        "Implications / Constraints:\n"
        f"{proposal.get('reason')}\n\n"
        "Evidence / Receipts:\n"
        + "\n".join(f"- {item}" for item in evidence)
        + "\n\nNotes:\n"
        f"Formalized from ambient proposal {proposal.get('proposal_id')}.\n"
    )
    tree_path.write_text(tree_text.rstrip() + "\n" + tree_entry, encoding="utf-8")

    log_entry = (
        "\n"
        f"Timestamp: {today} 00:00 (America/Toronto)\n"
        f"Quest ID: {source_ref}\n"
        f"Quest Path: {evidence[0]}\n"
        "Quest Completed: YES\n"
        "Talent Point Awarded: YES\n"
        f"Talent Spent On: {talent_id} — {proposal.get('title')}\n"
        "Evidence Paths:\n"
        + "\n".join(f"- {item}" for item in evidence)
        + "\n"
        f"Notes: Formalized from ambient proposal {proposal.get('proposal_id')}.\n"
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_path.write_text(log_text.rstrip() + "\n" + log_entry, encoding="utf-8")

    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(tree_path),
        note=f"Talent formalized as {talent_id}.",
    )
    return {"artifact_path": str(tree_path), "proposal": proposal_receipt, "talent_id": talent_id}


def _formalize_guild_orders(ctx: dict[str, Any], proposal: dict[str, Any], *, topic: str | None) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    formalized = formalize_guild_orders_from_proposal(
        subject=str(ctx["subject"]),
        data_root=data_root,
        proposal=proposal,
        topic=topic,
    )
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(formalized["artifact_path"]),
        note=f"Guild Orders formalized as {formalized['orders_id']}.",
    )
    return {
        "artifact_path": str(formalized["artifact_path"]),
        "proposal": proposal_receipt,
        "orders_id": str(formalized["orders_id"]),
        "operation_receipt": dict(formalized.get("operation_receipt") or {}),
        "lineage_family_id": str(formalized.get("lineage_family_id") or ""),
    }


def _formalize_disclosure(ctx: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    evidence = [str(item) for item in proposal.get("evidence") or []]
    blockers = [str(item) for item in proposal.get("blockers") or []]
    with tempfile.TemporaryDirectory(prefix="synapse-disclosure-") as tmpdir:
        tmp = Path(tmpdir)
        purpose_file = tmp / "purpose.txt"
        content_file = tmp / "content.txt"
        notes_file = tmp / "notes.txt"
        purpose_file.write_text(
            "Record a Disclosure Gate event durably because uncertainty changed the next safe action.\n",
            encoding="utf-8",
        )
        content_lines = [
            f"- Proposal: {proposal.get('proposal_id')}",
            f"- Summary: {proposal.get('summary')}",
            f"- Reason: {proposal.get('reason')}",
        ]
        if evidence:
            content_lines.extend(["- Evidence:"] + [f"  - {item}" for item in evidence])
        content_file.write_text("\n".join(content_lines) + "\n", encoding="utf-8")
        notes_lines = ["- Disclosure formalized from ambient proposal."]
        notes_lines.extend(f"- Blocker: {item}" for item in blockers)
        notes_file.write_text("\n".join(notes_lines) + "\n", encoding="utf-8")
        result = _snapshot_writer(
            [
                "--subject",
                ctx["subject"],
                "--data-root",
                str(data_root),
                "general",
                "--topic",
                proposal.get("title") or "Disclosure Gate Event",
                "--purpose-file",
                str(purpose_file),
                "--content-file",
                str(content_file),
                "--notes-file",
                str(notes_file),
            ]
        )
    if result.returncode != 0:
        raise LiveMemoryError(result.stdout + result.stderr)
    artifact_path = _snapshot_path_from_output(result.stdout + result.stderr)
    if not artifact_path:
        raise LiveMemoryError("Snapshot writer did not report disclosure artifact path.")
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=artifact_path,
        note="Disclosure formalized into a General Snapshot.",
    )
    return {
        "artifact_path": artifact_path,
        "proposal": proposal_receipt,
        "raw_output": result.stdout + result.stderr,
    }


def _formalize_candidate_dry_run(
    ctx: dict[str, Any],
    proposal_id: str | None = None,
    *,
    candidate_handle: str | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    if candidate_handle:
        candidate = resolve_publication_candidate(Path(ctx["data_root"]), candidate_handle)
        return {
            "subject": ctx,
            "candidate_handle": candidate_handle,
            "publication_candidate": candidate,
            "would_formalize_as": f"canonical_{str(candidate.get('candidate_kind') or '').lower()}",
            "topic": topic,
            "dry_run": True,
        }
    if not proposal_id:
        raise LiveMemoryError("formalize requires --proposal-id or --candidate-handle.")
    proposal = _proposal_by_id(Path(ctx["data_root"]), proposal_id)
    kind = ProposalKind(str(proposal.get("kind")))
    return {
        "subject": ctx,
        "proposal": proposal,
        "would_formalize_as": kind.value,
        "topic": topic,
        "dry_run": True,
    }


def _formalize_candidate_mutation(
    ctx: dict[str, Any],
    proposal_id: str | None = None,
    *,
    candidate_handle: str | None = None,
    topic: str | None = None,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    active_run = active_run or _active_session_policy(ctx)[0]
    session_id = _effective_session_id(ctx, active_run=active_run)

    if candidate_handle:
        result = publish_publication_candidate(
            subject=ctx["subject"],
            data_root=data_root,
            active_run=active_run,
            candidate_handle=candidate_handle,
        )
        changed_files = [
            str(path)
            for path in [
                result.get("publication_receipt_path"),
                *list(dict(result.get("archive_paths") or {}).values()),
                *list(dict(result.get("canonical_paths") or {}).values()),
            ]
            if path
        ]
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="formalize",
            summary=f"Published publication candidate {candidate_handle} as canonical {result.get('candidate_kind')}.",
            session_id=session_id,
            signals={
                "publication_candidate_handle": candidate_handle,
                "publication_candidate_kind": result.get("candidate_kind"),
                "changed_files": changed_files,
                "verification_entries": [],
                "accepted_context": _accepted_context_snapshot(data_root),
                **session_mode_signal_fields(active_run),
            },
            truth_flags={
                "canon_mutated": True,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "publication_candidate_handle": candidate_handle,
                "candidate_kind": result.get("candidate_kind"),
                "publication_receipt_path": result.get("publication_receipt_path"),
                "canonical_paths": result.get("canonical_paths"),
            },
        )
        event_info, truth_compile = _merge_truth_compile_follow_on(
            ctx=ctx,
            session_id=session_id,
            event_info=event_info,
            primary_action_label=f"Publication candidate formalization ({candidate_handle})",
        )
        return {
            "subject": ctx,
            "result": result,
            "proposal": None,
            "proposal_kind": None,
            "candidate_handle": candidate_handle,
            "candidate_kind": result.get("candidate_kind"),
            "event": event_info["event"],
            "reducer": event_info["reducer"],
            "rehydrate": event_info["reducer"]["rehydrate"],
            "continuity": event_info["reducer"]["continuity"],
            "truth_compile": truth_compile,
        }

    if not proposal_id:
        raise LiveMemoryError("formalize requires --proposal-id or --candidate-handle.")
    proposal = _proposal_by_id(data_root, proposal_id)
    kind = ProposalKind(str(proposal.get("kind")))

    if kind == ProposalKind.SNAPSHOT:
        result = _formalize_snapshot(ctx, proposal, control_sync=False)
    elif kind == ProposalKind.CONTROL_SYNC:
        result = _formalize_snapshot(ctx, proposal, control_sync=True)
    elif kind == ProposalKind.QUEST:
        result = _formalize_quest(ctx, proposal, prefix="QUEST")
    elif kind == ProposalKind.SIDE_QUEST:
        result = _formalize_quest(ctx, proposal, prefix="SIDE-QUEST")
    elif kind == ProposalKind.CODEX:
        result = _formalize_codex(ctx, proposal)
    elif kind == ProposalKind.BUILD_MANUAL:
        result = _formalize_build_manual(ctx, proposal)
    elif kind == ProposalKind.TALENT:
        result = _formalize_talent(ctx, proposal)
    elif kind == ProposalKind.GUILD_ORDERS:
        result = _formalize_guild_orders(ctx, proposal, topic=topic)
    elif kind == ProposalKind.DISCLOSURE:
        result = _formalize_disclosure(ctx, proposal)
    else:
        raise LiveMemoryError(f"Formalization is not implemented for proposal kind {kind.value}.")

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="formalize",
        summary=f"Formalized proposal {proposal_id} as {kind.value}.",
        session_id=session_id,
        signals={
            "proposal_id": proposal_id,
            "proposal_kind": kind.value,
            "related_quest_ids": [proposal.get("proposal_id")] if kind in {ProposalKind.QUEST, ProposalKind.SIDE_QUEST} else [],
            "related_sidequest_ids": [],
            "changed_files": [result.get("artifact_path")] if result.get("artifact_path") else [],
            "verification_entries": [],
            "accepted_context": _accepted_context_snapshot(data_root),
            **session_mode_signal_fields(active_run),
        },
        truth_flags={
            "canon_mutated": True,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "proposal_id": proposal_id,
            "proposal_kind": kind.value,
            "artifact_path": result.get("artifact_path"),
        },
    )
    return {
        "subject": ctx,
        "result": result,
        "proposal": proposal,
        "proposal_kind": kind.value,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }


def cmd_formalize(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    data_root = Path(ctx["data_root"])
    if args.proposal_id and args.candidate_handle:
        print("FAIL: formalize accepts either --proposal-id or --candidate-handle, not both.")
        return 2
    kind_filter = ProposalKind(args.kind) if args.kind else None
    state_filter = ProposalState(args.state) if args.state else None

    if args.list or (not args.proposal_id and not args.candidate_handle):
        proposals = list_proposals(data_root=data_root, kind=kind_filter, state=state_filter)
        if args.json:
            print(json.dumps({"subject": ctx, "proposals": proposals}, indent=2, sort_keys=True))
            return 0
        print("=== PROPOSALS ===")
        for proposal in proposals:
            print(
                f"- {proposal.get('proposal_id')} [{proposal.get('state')}] "
                f"{proposal.get('kind')} :: {proposal.get('title')}"
            )
        return 0

    try:
        if args.dry_run:
            payload = _formalize_candidate_dry_run(
                ctx,
                args.proposal_id,
                candidate_handle=args.candidate_handle,
                topic=args.topic,
            )
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("=== FORMALIZE DRY RUN ===")
                if payload.get("proposal"):
                    print(f"proposal_id: {payload['proposal'].get('proposal_id')}")
                    print(f"kind: {payload.get('would_formalize_as')}")
                    print(f"title: {payload['proposal'].get('title')}")
                else:
                    candidate = dict(payload.get("publication_candidate") or {})
                    print(f"candidate_handle: {payload.get('candidate_handle')}")
                    print(f"kind: {payload.get('would_formalize_as')}")
                    print(f"revision_id: {candidate.get('revision_id')}")
                    print(f"summary: {candidate.get('summary')}")
            return 0
        active_run, session_policy = _active_session_policy(ctx)
        if session_policy is not None and not session_policy.manual_formalize_allowed:
            return _fail_blocked_by_session_posture(
                action_name="formalize",
                active_run=active_run,
                json_mode=args.json,
            )
        payload = _formalize_candidate_mutation(
            ctx,
            args.proposal_id,
            candidate_handle=args.candidate_handle,
            topic=args.topic,
            active_run=active_run,
        )
        event_info = {"event": payload["event"], "reducer": payload["reducer"]}
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_formalize(rendered_payload: dict[str, Any]) -> None:
        print("=== FORMALIZATION RECEIPT ===")
        if args.proposal_id:
            print(f"proposal_id: {args.proposal_id}")
            print(f"artifact_path: {rendered_payload['result'].get('artifact_path')}")
            return
        print(f"candidate_handle: {args.candidate_handle}")
        print(f"candidate_kind: {rendered_payload['result'].get('candidate_kind')}")
        print(f"publication_receipt_path: {rendered_payload['result'].get('publication_receipt_path')}")
        print(f"canonical_paths: {rendered_payload['result'].get('canonical_paths')}")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_formalize,
    )


def cmd_watch(args: argparse.Namespace) -> int:
    iterations = max(1, int(args.iterations))
    if not args.no_provenance and _try_resolve_subject_without_attach(args) is None:
        return _watch_without_subject(args, iterations=iterations)

    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    payloads: list[dict[str, Any]] = []
    last_files: list[str] = []
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    if args.no_provenance:
        for idx in range(iterations):
            files = _git_status_changed_files(detect_canonical_working_tree()) if args.capture_git else []
            changed_files = [item for item in files if item not in last_files]
            result = None
            if changed_files or idx == 0:
                try:
                    _start_or_resume_session_run(
                        ctx,
                        title=args.title or _default_session_title(ctx),
                        goal=args.goal,
                        items=[],
                        command_name="session-tick",
                    )
                    result = run_update(
                        subject=ctx["subject"],
                        data_root=data_root,
                        add_items=[],
                        status_updates=[],
                        commands=[],
                        files_touched=changed_files,
                        notes=[f"watch tick {idx + 1}"],
                        verification=[],
                        related_sidequests=[],
                        related_quests=[],
                        status="active",
                        summary=f"watch tick {idx + 1}",
                    )
                    active_run = _load_active_run_with_session_repair(ctx)
                    _write_session_overlay(
                        ctx,
                        result,
                        active_run=active_run,
                        session_id=_effective_session_id(ctx, active_run=active_run),
                    )
                    _render_and_refresh_continuity(ctx["subject"], data_root, engine_root)
                except LiveMemoryError as exc:
                    print(f"FAIL: {exc}")
                    return 2
            cycle_payload: dict[str, Any] = {
                "iteration": idx + 1,
                "changed_files": changed_files,
            }
            if result is not None:
                cycle_payload["tick"] = result
            payloads.append(cycle_payload)
            last_files = files
            if idx < iterations - 1:
                time.sleep(max(args.interval, 0.1))

        if args.json:
            print(json.dumps({"subject": ctx, "ticks": payloads}, indent=2, sort_keys=True))
            return 0

        print("=== WATCH RECEIPT ===")
        print(f"iterations: {iterations}")
        print(f"captured_ticks: {len(payloads)}")
        return 0

    for idx in range(iterations):
        files = _git_status_changed_files(detect_canonical_working_tree()) if args.capture_git else []
        changed_files = [item for item in files if item not in last_files]
        cycle_payload: dict[str, Any] = {
            "iteration": idx + 1,
            "changed_files": changed_files,
        }
        try:
            provenance_cycle = run_provenance_watch_cycle(
                subject=ctx["subject"],
                data_root=data_root,
                engine_root=engine_root,
            )
            refresh_provenance_projection(
                subject=ctx["subject"],
                data_root=data_root,
                engine_root=engine_root,
                summary=provenance_cycle["summary"],
            )
            cycle_payload["provenance"] = provenance_cycle["summary"]
            cycle_payload["baseline_path"] = provenance_cycle["baseline_path"]
            cycle_payload["anomaly_ledger_path"] = provenance_cycle.get("anomaly_ledger_path")
            cycle_payload["new_anomaly_ids"] = list(provenance_cycle.get("new_anomaly_ids") or [])
            if provenance_cycle.get("provenance_changed"):
                event_info = _event_pipeline(
                    ctx=ctx,
                    action_name="provenance-watch-cycle",
                    summary=f"Observed provenance watch cycle for {ctx['subject']}.",
                    session_id=_effective_session_id(
                        ctx,
                        active_run=_load_active_run_with_session_repair(ctx),
                    ),
                    signals={
                        "changed_files": [],
                        "verification_entries": [],
                        "related_quest_ids": [],
                        "related_sidequest_ids": [],
                        "accepted_context": _accepted_context_snapshot(data_root),
                        **_current_session_mode_fields(ctx),
                    },
                    truth_flags={
                        "canon_mutated": False,
                        "derived_state_changed": True,
                        "governed": False,
                        "uncertainty_present": False,
                    },
                    outputs={
                        "provenance_status": provenance_cycle["summary"].get("provenance_status"),
                        "baseline_path": provenance_cycle.get("baseline_path"),
                        "anomaly_ledger_path": provenance_cycle.get("anomaly_ledger_path"),
                        "new_anomaly_ids": list(provenance_cycle.get("new_anomaly_ids") or []),
                        "current_wrapper_proof_status": provenance_cycle["summary"].get("current_wrapper_proof_status"),
                        "git_hooks_status": provenance_cycle["summary"].get("git_hooks_status"),
                    },
                )
                cycle_payload["provenance_event"] = event_info
                runtime_status = event_info.get("runtime_status") if isinstance(event_info, dict) else None
                if isinstance(runtime_status, dict) and str(runtime_status.get("operation_status") or "").lower() == "partial":
                    if args.json:
                        print(json.dumps({"subject": ctx, "ticks": payloads + [cycle_payload], "runtime_status": runtime_status}, indent=2, sort_keys=True))
                    else:
                        print("PARTIAL: provenance watch raw state was written, but event/reducer refresh failed.")
                    return 3
        except Exception as exc:
            print(f"FAIL: {exc}")
            return 2
        payloads.append(cycle_payload)
        last_files = files
        if idx < iterations - 1:
            time.sleep(max(args.interval, 0.1))

    if args.json:
        print(json.dumps({"subject": ctx, "ticks": payloads}, indent=2, sort_keys=True))
        return 0

    print("=== WATCH RECEIPT ===")
    print(f"iterations: {iterations}")
    print(f"captured_ticks: {len(payloads)}")
    if not args.no_provenance and payloads:
        last_summary = payloads[-1].get("provenance") or {}
        print(f"provenance_status: {last_summary.get('provenance_status') or 'unknown'}")
    return 0


def cmd_provenance_status(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        summary = _current_provenance_summary(ctx)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    payload = {
        "subject": ctx,
        "provenance_status": summary.get("provenance_status"),
        "blockers": list(summary.get("blockers") or []),
        "warnings": list(summary.get("warnings") or []),
        "integration_posture": summary.get("integration_posture"),
        "local_integration_health": summary.get("local_integration_health"),
        "local_integration_missing_assets": list(summary.get("local_integration_missing_assets") or []),
        "degraded_mode": bool(summary.get("degraded_mode")),
        "degraded_mode_reason": summary.get("degraded_mode_reason"),
        "strict_boundary_status": summary.get("strict_boundary_status"),
        "open_continuity_obligation_count": summary.get("open_continuity_obligation_count") or 0,
        "blocker_continuity_obligation_count": summary.get("blocker_continuity_obligation_count") or 0,
        "import_review_required_count": summary.get("import_review_required_count") or 0,
        "recent_open_continuity_obligation_details": list(summary.get("recent_open_continuity_obligation_details") or []),
        "recent_import_review_details": list(summary.get("recent_import_review_details") or []),
        "continuity_blockers": list(summary.get("continuity_blockers") or []),
        "continuity_warnings": list(summary.get("continuity_warnings") or []),
        "current_wrapper_proof_status": summary.get("current_wrapper_proof_status"),
        "current_wrapper_proof_path": summary.get("current_wrapper_proof_path"),
        "git_hooks_status": summary.get("git_hooks_status"),
        "git_hooks_template_version": summary.get("git_hooks_template_version"),
        "last_watch_at": summary.get("last_watch_at"),
        "recent_anomaly_count": summary.get("recent_anomaly_count"),
        "baseline_path": summary.get("baseline_path"),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("=== PROVENANCE STATUS ===")
        print(f"provenance_status: {payload.get('provenance_status')}")
        print(f"honesty_note: {summary.get('honesty_note')}")
        print(f"current_wrapper_proof_status: {payload.get('current_wrapper_proof_status')}")
        print(f"git_hooks_status: {payload.get('git_hooks_status')}")
        print(f"blockers: {len(payload.get('blockers') or [])}")
        print(f"warnings: {len(payload.get('warnings') or [])}")
        print(f"integration_posture: {summary.get('integration_posture')}")
        print(f"local_integration_health: {summary.get('local_integration_health')}")
        print(f"open_continuity_obligation_count: {summary.get('open_continuity_obligation_count') or 0}")
        print(f"blocker_continuity_obligation_count: {summary.get('blocker_continuity_obligation_count') or 0}")
        print(f"import_review_required_count: {summary.get('import_review_required_count') or 0}")
        if summary.get("degraded_mode"):
            print(f"degraded_mode_reason: {summary.get('degraded_mode_reason')}")
        print(f"last_watch_at: {payload.get('last_watch_at')}")
        print(f"baseline_path: {payload.get('baseline_path')}")
    if args.strict and payload.get("provenance_status") == ProvenanceStatus.BLOCKED.value:
        return 2
    return 0


def cmd_record_raw_turn(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        text = _read_text_input(
            literal=getattr(args, "text", None),
            file_path=getattr(args, "text_file", None),
            read_stdin=bool(getattr(args, "stdin", False)),
            label="record-raw-turn",
        )
        metadata = _load_json_text(getattr(args, "metadata_json", None), label="record-raw-turn metadata")
        payload = record_raw_turn(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            role=args.role,
            text=text,
            source_surface=args.source_surface,
            session_id=_resolved_session_id(args),
            run_id=getattr(args, "run_id", None),
            metadata=metadata,
        )
    except (ConversationIngestError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    raw_ref = raw_artifact_ref(
        raw_id=payload["raw_turn_id"],
        family="CONVERSATION_TURNS",
        path=payload["raw_turn_path"],
        sha256=payload["raw_turn_sha256"],
    )
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="record-raw-turn",
        summary=f"Recorded raw {args.role} turn for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals=raw_capture_signals(
            accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=_current_session_mode_fields(ctx),
            raw_refs=[raw_ref],
            source_surface=args.source_surface,
            raw_role=args.role,
        ),
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "raw_turn_id": payload["raw_turn_id"],
            "raw_turn_path": payload["raw_turn_path"],
            "raw_turn_sha256": payload["raw_turn_sha256"],
            "raw_text_blob_path": payload["text_blob"]["path"],
            "raw_text_blob_sha256": payload["text_blob"]["sha256"],
        },
    )
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_raw_turn(result_payload: dict[str, Any]) -> None:
        print("=== RAW TURN RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"role: {result_payload.get('role')}")
        print(f"raw_turn_id: {result_payload.get('raw_turn_id')}")
        print(f"raw_turn_path: {result_payload.get('raw_turn_path')}")
        print(f"text_blob_path: {result_payload.get('text_blob', {}).get('path')}")
        print(f"integration_posture: {result_payload.get('kernel_posture', {}).get('posture')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_raw_turn,
    )


def cmd_record_raw_execution(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        metadata = _load_json_text(getattr(args, "metadata_json", None), label="record-raw-execution metadata")
        payload_body = _read_payload_input(
            literal=getattr(args, "payload", None),
            json_text=getattr(args, "payload_json", None),
            file_path=getattr(args, "payload_file", None),
            label="record-raw-execution payload",
        )
        payload = record_raw_execution(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            family=args.family,
            source_surface=args.source_surface,
            phase=getattr(args, "phase", None),
            session_id=_resolved_session_id(args),
            run_id=getattr(args, "run_id", None),
            command=getattr(args, "command_text", None),
            tool_name=getattr(args, "tool_name", None),
            status=getattr(args, "status", None),
            changed_files=list(getattr(args, "changed_file", []) or []),
            payload=payload_body,
            metadata=metadata,
        )
    except (ExecutionObserverError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    raw_ref = raw_artifact_ref(
        raw_id=payload["raw_event_id"],
        family=payload["family"],
        path=payload["raw_event_path"],
        sha256=payload["raw_event_sha256"],
    )
    outputs = {
        "raw_event_id": payload["raw_event_id"],
        "raw_event_path": payload["raw_event_path"],
        "raw_event_sha256": payload["raw_event_sha256"],
        "payload_blob_path": payload.get("payload_blob", {}).get("path") if payload.get("payload_blob") else None,
        "payload_blob_sha256": payload.get("payload_blob", {}).get("sha256") if payload.get("payload_blob") else None,
    }
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="record-raw-execution",
        summary=f"Recorded raw {args.family} evidence for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals=raw_capture_signals(
            accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
            session_mode_fields=_current_session_mode_fields(ctx),
            raw_refs=[raw_ref],
            source_surface=args.source_surface,
            raw_family=payload["family"],
        ),
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs=outputs,
    )
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_raw_execution(result_payload: dict[str, Any]) -> None:
        print("=== RAW EXECUTION RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"family: {result_payload.get('family')}")
        print(f"raw_event_id: {result_payload.get('raw_event_id')}")
        print(f"raw_event_path: {result_payload.get('raw_event_path')}")
        if result_payload.get("payload_blob"):
            print(f"payload_blob_path: {result_payload.get('payload_blob', {}).get('path')}")
        print(f"integration_posture: {result_payload.get('kernel_posture', {}).get('posture')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_raw_execution,
    )


def cmd_close_turn(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        active_run = _load_active_run_with_session_repair(ctx)
        accepted_context = _accepted_context_snapshot(Path(ctx["data_root"]))
        session_mode_fields = _current_session_mode_fields(ctx)
        observer = _execute_continuity_observer(
            ctx=ctx,
            active_run=active_run,
            trigger="close-turn",
            summary=f"Validated close-turn continuity boundary for {ctx['subject']}.",
            boundary=args.boundary,
            accepted_context=accepted_context,
            session_mode_fields=session_mode_fields,
        )
        signals = {
            "changed_files": [],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": accepted_context,
            **session_mode_fields,
        }
        outputs = {"boundary": args.boundary}
        truth_flags = {
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        }
        _apply_observer_event_metadata(
            signals=signals,
            outputs=outputs,
            truth_flags=truth_flags,
            observer=observer,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="close-turn",
            summary=f"Validated close-turn continuity boundary for {ctx['subject']}.",
            session_id=_resolved_session_id(args),
            refresh_continuity=False,
            signals=signals,
            truth_flags=truth_flags,
            outputs=outputs,
        )
        event_info = _apply_observer_partial_status(event_info=event_info, observer=observer)
        artifact_routing = _route_artifact_boundary(
            ctx=ctx,
            trigger="close-turn",
            boundary=args.boundary,
            invoke_reason="close_turn_boundary",
            active_run=active_run,
            accepted_context=accepted_context,
            summary=f"Validated close-turn continuity boundary for {ctx['subject']}.",
            observer_action_kinds=list(observer.get("observer_action_kinds") or []),
            requested_snapshot_kinds=None,
            requested_publication_candidate_kinds=list(PUBLICATION_CANDIDATE_KINDS),
        )
        snapshot_candidate_result = artifact_routing["dispatch"].get("snapshot_candidates") or _snapshot_candidate_boundary_noop(
            data_root=Path(ctx["data_root"]),
            boundary=args.boundary,
            reason="router_no_snapshot_dispatch",
        )
        publication_candidate_result = artifact_routing["dispatch"].get("publication_candidates") or _publication_candidate_boundary_noop(
            data_root=Path(ctx["data_root"]),
            boundary=args.boundary,
            reason="router_no_publication_dispatch",
        )
        payload = _close_turn_validation_payload(ctx, boundary=args.boundary)
    except (SnapshotCandidateError, PublicationCandidateError) as exc:
        print(f"FAIL: {exc}")
        return 2
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        "continuity_observer": observer,
        "artifact_routing": artifact_routing,
        "snapshot_candidates": snapshot_candidate_result,
        "publication_candidates": publication_candidate_result,
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_close_turn(result_payload: dict[str, Any]) -> None:
        print("=== CLOSE TURN RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"boundary: {result_payload.get('boundary')}")
        print(f"validation_status: {result_payload.get('validation_status')}")
        print(f"integration_posture: {result_payload.get('integration_posture')}")
        print(f"local_integration_health: {result_payload.get('local_integration_health')}")
        observer_payload = dict(result_payload.get("continuity_observer") or {})
        print(f"observer_status: {observer_payload.get('observer_status')}")
        print(f"observer_backend: {observer_payload.get('observer_backend')}")
        print(f"observer_action_kinds: {','.join(observer_payload.get('observer_action_kinds') or []) or 'none'}")
        print(f"open_continuity_obligation_count: {result_payload.get('open_continuity_obligation_count')}")
        print(f"blocker_continuity_obligation_count: {result_payload.get('blocker_continuity_obligation_count')}")
        if result_payload.get("degraded_mode"):
            print(f"degraded_mode_reason: {result_payload.get('degraded_mode_reason')}")
        if result_payload.get("continuation_required"):
            print("continuation_required: yes")

    exit_code = _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_close_turn,
    )
    if exit_code != 0:
        return exit_code
    if args.strict and rendered.get("validation_status") == ProvenanceStatus.BLOCKED.value:
        return 2
    return 0


def cmd_import_continuity(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        parsed = parse_imported_continuity_source(
            source_path=Path(str(args.source_file)),
            source_kind=args.kind,
        )
        parsed["recorded_at"] = kernel_now_iso()
        payload = record_raw_execution(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            family="import",
            source_surface=args.source_surface,
            phase="imported_continuity",
            session_id=_resolved_session_id(args),
            run_id=getattr(args, "run_id", None),
            command=f"import-continuity {parsed.get('source_kind')} {parsed.get('source_path')}",
            tool_name="import-continuity",
            status=str(parsed.get("parser_status") or "parsed"),
            changed_files=[],
            payload=parsed,
            metadata={
                "source_kind": parsed.get("source_kind"),
                "parser_status": parsed.get("parser_status"),
                "confidence_band": parsed.get("confidence_band"),
                "source_path": parsed.get("source_path"),
                "warnings": list(parsed.get("warnings") or []),
            },
        )
    except (ImportedContinuityError, ExecutionObserverError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    raw_ref = raw_artifact_ref(
        raw_id=payload["raw_event_id"],
        family=payload["family"],
        path=payload["raw_event_path"],
        sha256=payload["raw_event_sha256"],
    )
    observer = _execute_continuity_observer(
        ctx=ctx,
        active_run=_load_active_run_with_session_repair(ctx),
        trigger="import-continuity",
        summary=f"Imported {parsed.get('source_kind')} continuity evidence for {ctx['subject']}.",
        notes=list(parsed.get("warnings") or []),
        source_refs=[raw_ref],
        uncertainty_present=str(parsed.get("confidence_band") or "").strip().lower() == "low",
        accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
        session_mode_fields=_current_session_mode_fields(ctx),
    )
    signals = raw_capture_signals(
        accepted_context=_accepted_context_snapshot(Path(ctx["data_root"])),
        session_mode_fields=_current_session_mode_fields(ctx),
        raw_refs=[raw_ref],
        source_surface=args.source_surface,
        raw_family=payload["family"],
    )
    outputs = {
        "raw_event_id": payload["raw_event_id"],
        "raw_event_path": payload["raw_event_path"],
        "raw_event_sha256": payload["raw_event_sha256"],
        "payload_blob_path": payload.get("payload_blob", {}).get("path") if payload.get("payload_blob") else None,
        "payload_blob_sha256": payload.get("payload_blob", {}).get("sha256") if payload.get("payload_blob") else None,
        "import_source_path": parsed.get("source_path"),
        "import_source_kind": parsed.get("source_kind"),
        "import_parser_status": parsed.get("parser_status"),
        "import_confidence_band": parsed.get("confidence_band"),
    }
    truth_flags = {
        "canon_mutated": False,
        "derived_state_changed": True,
        "governed": False,
        "uncertainty_present": str(parsed.get("confidence_band") or "").strip().lower() == "low",
    }
    _apply_observer_event_metadata(
        signals=signals,
        outputs=outputs,
        truth_flags=truth_flags,
        observer=observer,
    )
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="import-continuity",
        summary=f"Imported {parsed.get('source_kind')} continuity evidence for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals=signals,
        truth_flags=truth_flags,
        outputs=outputs,
    )
    event_info = _apply_observer_partial_status(event_info=event_info, observer=observer)
    try:
        followup = _orchestrate_import_continuity_followup(
            ctx=ctx,
            parsed=parsed,
            raw_payload=payload,
            session_id_override=_resolved_session_id(args),
            run_id_override=getattr(args, "run_id", None),
        )
    except (SnapshotCandidateError, PublicationCandidateError) as exc:
        print(f"FAIL: {exc}")
        return 2
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        "continuity_observer": observer,
        "import_envelope": parsed,
        "artifact_routing": followup.get("artifact_routing"),
        "snapshot_candidates": followup["snapshot_candidates"],
        "publication_candidates": followup["publication_candidates"],
        "opened_import_review_obligations": followup["opened_import_review_obligations"],
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_import(result_payload: dict[str, Any]) -> None:
        envelope = result_payload.get("import_envelope") or {}
        print("=== IMPORT CONTINUITY RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"source_kind: {envelope.get('source_kind')}")
        print(f"source_path: {envelope.get('source_path')}")
        print(f"parser_status: {envelope.get('parser_status')}")
        print(f"confidence_band: {envelope.get('confidence_band')}")
        observer_payload = dict(result_payload.get("continuity_observer") or {})
        print(f"observer_status: {observer_payload.get('observer_status')}")
        print(f"observer_backend: {observer_payload.get('observer_backend')}")
        print(f"observer_action_kinds: {','.join(observer_payload.get('observer_action_kinds') or []) or 'none'}")
        print(f"raw_event_id: {result_payload.get('raw_event_id')}")
        print(f"raw_event_path: {result_payload.get('raw_event_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_import,
    )


def _install_local_integration_receipt(
    ctx: dict[str, Any],
    *,
    observer_backend: str | None = None,
) -> dict[str, Any]:
    return install_local_codex_integration(
        subject=ctx["subject"],
        repo_root=Path(ctx["engine_root"]),
        data_root=Path(ctx["data_root"]),
        synapse_root=resolve_synapse_root(),
        observer_backend=observer_backend,
    )


def _interactive_observer_backend_choice(payload: dict[str, Any]) -> str | None:
    options = list(payload.get("available_observer_backends") or [])
    if not options:
        return None
    print("Multiple continuity observer backends are available from this environment/profile:")
    for index, option in enumerate(options, start=1):
        backend = str(option.get("backend") or "")
        label = str(option.get("label") or backend)
        matched = ",".join(option.get("matched_env_vars") or []) or "detected"
        print(f"{index}. {label} [{backend}] via {matched}")
    print(f"{len(options) + 1}. Degraded fallback [noop]")
    choice = input("Select observer backend number: ").strip()
    try:
        selected_index = int(choice)
    except ValueError:
        return None
    if 1 <= selected_index <= len(options):
        return str(options[selected_index - 1].get("backend") or "").strip() or None
    if selected_index == len(options) + 1:
        return "noop"
    return None


def cmd_install_local_integration(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        payload = _install_local_integration_receipt(ctx, observer_backend=args.observer_backend)
        if (
            payload.get("observer_backend_selection_required")
            and not args.json
            and _stdin_is_interactive()
            and not args.observer_backend
        ):
            selected_backend = _interactive_observer_backend_choice(payload)
            if not selected_backend:
                print("FAIL: observer backend selection is required. Re-run with --observer-backend <backend> or choose a valid option.")
                return 2
            payload = _install_local_integration_receipt(ctx, observer_backend=selected_backend)
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    changed_files = [
        str(payload.get("manifest_path") or ""),
        str(payload.get("config_path") or ""),
        str(payload.get("hooks_config_path") or ""),
        str(payload.get("mcp_config_path") or ""),
        str(payload.get("mcp_wrapper_path") or ""),
        str(payload.get("readme_path") or ""),
        *[str(path) for path in (payload.get("hook_paths") or {}).values()],
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="install-local-integration",
        summary=f"Installed or refreshed optional local integration for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals={
            "changed_files": [path for path in changed_files if path],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "integration_posture": payload.get("integration_posture"),
            "integration_health": payload.get("integration_health"),
            "integration_dir": payload.get("integration_dir"),
            "selected_observer_backend": payload.get("selected_observer_backend"),
            "selected_observer_backend_ready": payload.get("selected_observer_backend_ready"),
            "observer_backend_selection_required": payload.get("observer_backend_selection_required"),
            "manifest_path": payload.get("manifest_path"),
            "config_path": payload.get("config_path"),
            "hooks_config_path": payload.get("hooks_config_path"),
            "mcp_config_path": payload.get("mcp_config_path"),
            "mcp_wrapper_path": payload.get("mcp_wrapper_path"),
            "readme_path": payload.get("readme_path"),
            "hook_paths": payload.get("hook_paths"),
            "missing_assets": list(payload.get("missing_assets") or []),
        },
    )
    rendered = {
        "subject_context": ctx,
        **payload,
        "kernel_posture": _kernel_posture_payload(ctx),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_local_integration(result_payload: dict[str, Any]) -> None:
        print("=== LOCAL INTEGRATION RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"integration_posture: {result_payload.get('integration_posture')}")
        print(f"integration_health: {result_payload.get('integration_health')}")
        print(f"integration_dir: {result_payload.get('integration_dir')}")
        print(f"selected_observer_backend: {result_payload.get('selected_observer_backend') or 'unset'}")
        print(f"observer_backend_selection_required: {bool(result_payload.get('observer_backend_selection_required'))}")
        available = list(result_payload.get("available_observer_backends") or [])
        if available:
            labels = [f"{item.get('label')} [{item.get('backend')}]" for item in available]
            print(f"available_observer_backends: {', '.join(labels)}")
        print(f"manifest_path: {result_payload.get('manifest_path')}")
        print(f"config_path: {result_payload.get('config_path')}")
        print(f"hooks_config_path: {result_payload.get('hooks_config_path')}")
        print(f"mcp_config_path: {result_payload.get('mcp_config_path')}")
        print(f"mcp_wrapper_path: {result_payload.get('mcp_wrapper_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_local_integration,
    )


def cmd_refresh_draftshot(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    active_run = _load_active_run_with_session_repair(ctx)
    session_id = _continuity_session_anchor(ctx, active_run=active_run, session_id=_resolved_session_id(args))
    if not session_id:
        print("FAIL: refresh-draftshot requires a session id or active run context.")
        return 2
    try:
        payload = refresh_draftshot(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            session_id=session_id,
            run_id=active_run.get("run_id"),
        )
        refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    except (DraftshotError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    changed_files = [
        str(payload.get("body_path") or ""),
        str(payload.get("revision_path") or ""),
        str(payload.get("draftshot", {}).get("state_path") or ""),
    ]
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="refresh-draftshot",
        summary=f"Refreshed Draftshot continuity for {ctx['subject']}.",
        session_id=session_id,
        signals={
            "changed_files": [path for path in changed_files if path],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "draftshot_status": payload.get("status"),
            "draftshot_revision_id": payload.get("revision_id"),
            "draftshot_body_path": payload.get("body_path"),
            "draftshot_revision_path": payload.get("revision_path"),
        },
    )
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_draftshot(result_payload: dict[str, Any]) -> None:
        print("=== DRAFTSHOT RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"session_id: {session_id}")
        print(f"status: {result_payload.get('status')}")
        print(f"revision_id: {result_payload.get('revision_id')}")
        print(f"body_path: {result_payload.get('body_path')}")
        print(f"state_path: {result_payload.get('draftshot', {}).get('state_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_draftshot,
    )


def cmd_refresh_snapshot_candidates(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    active_run = _load_active_run_with_session_repair(ctx)
    session_id = _continuity_session_anchor(ctx, active_run=active_run, session_id=_resolved_session_id(args))
    try:
        payload = _refresh_snapshot_candidate_boundary(
            ctx=ctx,
            boundary="refresh-snapshot-candidates",
            candidate_kinds=list(SNAPSHOT_CANDIDATE_KINDS),
            session_id_override=session_id,
            run_id_override=str(active_run.get("run_id") or "").strip() or None,
        )
    except (SnapshotCandidateError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    snapshot_payload = dict(payload.get("snapshot_candidates") or {})
    summary = dict(payload.get("summary") or {})
    changed_files: list[str] = []
    for item in list(snapshot_payload.get("candidates") or []):
        manifest_path = str(item.get("manifest_path") or "").strip()
        body_path = str(item.get("body_path") or "").strip()
        if manifest_path:
            changed_files.append(manifest_path)
        if body_path:
            changed_files.append(body_path)
    index_path = str(summary.get("index_path") or "").strip()
    if index_path:
        changed_files.append(index_path)

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="refresh-snapshot-candidates",
        summary=f"Refreshed typed snapshot candidates for {ctx['subject']}.",
        session_id=session_id,
        signals={
            "changed_files": changed_files,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "snapshot_candidate_status": snapshot_payload.get("status"),
            "snapshot_candidate_paths": [str(item.get("body_path") or "") for item in list(snapshot_payload.get("candidates") or [])],
            "snapshot_candidate_manifest_paths": [
                str(item.get("manifest_path") or "") for item in list(snapshot_payload.get("candidates") or [])
            ],
        },
    )
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_snapshot_candidates(result_payload: dict[str, Any]) -> None:
        summary = dict(result_payload.get("summary") or {})
        snapshot_payload = dict(result_payload.get("snapshot_candidates") or {})
        print("=== SNAPSHOT CANDIDATE RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"session_id: {snapshot_payload.get('session_id') or 'none'}")
        print(f"status: {snapshot_payload.get('status')}")
        print(f"current_eod_candidate_path: {summary.get('current_eod_candidate_path')}")
        print(f"current_control_sync_candidate_path: {summary.get('current_control_sync_candidate_path')}")
        print(f"index_path: {summary.get('index_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_snapshot_candidates,
    )


def cmd_refresh_publication_candidates(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
        payload = refresh_publication_candidates(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
        )
        refresh_synthesis_projection(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    except (PublicationCandidateError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    changed_files: list[str] = []
    for item in list(payload.get("candidates") or []):
        manifest_path = str(item.get("manifest_path") or "").strip()
        body_path = str(item.get("body_path") or "").strip()
        if manifest_path:
            changed_files.append(manifest_path)
        if body_path:
            changed_files.append(body_path)
    index_path = str(payload.get("index_path") or payload.get("summary", {}).get("index_path") or "").strip()
    if index_path:
        changed_files.append(index_path)

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="refresh-publication-candidates",
        summary=f"Refreshed publication candidates for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals={
            "changed_files": changed_files,
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "publication_candidate_status": payload.get("status"),
            "publication_candidate_paths": [str(item.get("body_path") or "") for item in list(payload.get("candidates") or [])],
            "publication_candidate_manifest_paths": [
                str(item.get("manifest_path") or "") for item in list(payload.get("candidates") or [])
            ],
        },
    )
    rendered = {
        "subject_context": ctx,
        "kernel_posture": _kernel_posture_payload(ctx),
        **payload,
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_publication_candidates(result_payload: dict[str, Any]) -> None:
        summary = dict(result_payload.get("summary") or {})
        print("=== PUBLICATION CANDIDATE RECEIPT ===")
        print(f"subject: {result_payload['subject_context']['subject']}")
        print(f"status: {result_payload.get('status')}")
        print(f"current_story_candidate_path: {summary.get('current_story_candidate_path')}")
        print(f"current_vision_candidate_path: {summary.get('current_vision_candidate_path')}")
        print(f"current_codex_candidate_paths: {summary.get('current_codex_candidate_paths')}")
        print(f"index_path: {summary.get('index_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_publication_candidates,
    )


def cmd_install_hooks(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        payload = _install_hooks_receipt(ctx, force=bool(args.force))
    except (GitHooksError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2
    if payload.get("git_hooks_status") == GitHooksStatus.NOT_APPLICABLE.value:
        result = {"subject": ctx, **payload}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("=== HOOK INSTALL RECEIPT ===")
            print("git_hooks_status: not_applicable")
        return 0

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="install-hooks",
        summary=f"Installed or verified managed git hooks for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals={
            "changed_files": [payload["hooks_receipt_path"]],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "git_hooks_status": payload.get("hooks_status"),
            "hooks_receipt_path": payload.get("hooks_receipt_path"),
            "template_version": payload.get("template_version"),
            "pre_commit_status": payload.get("pre_commit_status"),
            "pre_push_status": payload.get("pre_push_status"),
            "backups": list(payload.get("backups") or []),
        },
    )
    rendered = {
        "subject": ctx,
        "git_hooks_status": payload.get("hooks_status"),
        "hooks_receipt_path": payload.get("hooks_receipt_path"),
        "template_version": payload.get("template_version"),
        "pre_commit_status": payload.get("pre_commit_status"),
        "pre_push_status": payload.get("pre_push_status"),
        "backups": list(payload.get("backups") or []),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_install_hooks(result_payload: dict[str, Any]) -> None:
        print("=== HOOK INSTALL RECEIPT ===")
        print(f"git_hooks_status: {result_payload.get('git_hooks_status')}")
        print(f"hooks_receipt_path: {result_payload.get('hooks_receipt_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_install_hooks,
    )


def cmd_verify_hooks(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2
    try:
        payload = _verify_hooks_receipt(ctx)
    except (GitHooksError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2
    if payload.get("git_hooks_status") == GitHooksStatus.NOT_APPLICABLE.value:
        result = {"subject": ctx, **payload}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("=== HOOK VERIFY RECEIPT ===")
            print("git_hooks_status: not_applicable")
        return 0

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="verify-hooks",
        summary=f"Verified managed git hooks for {ctx['subject']}.",
        session_id=_resolved_session_id(args),
        signals={
            "changed_files": [payload["hooks_receipt_path"]],
            "verification_entries": [],
            "related_quest_ids": [],
            "related_sidequest_ids": [],
            "accepted_context": _accepted_context_snapshot(Path(ctx["data_root"])),
            **_current_session_mode_fields(ctx),
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": False,
        },
        outputs={
            "git_hooks_status": payload.get("hooks_status"),
            "hooks_receipt_path": payload.get("hooks_receipt_path"),
            "template_version": payload.get("template_version"),
            "pre_commit_status": payload.get("pre_commit_status"),
            "pre_push_status": payload.get("pre_push_status"),
        },
    )
    rendered = {
        "subject": ctx,
        "git_hooks_status": payload.get("hooks_status"),
        "hooks_receipt_path": payload.get("hooks_receipt_path"),
        "template_version": payload.get("template_version"),
        "pre_commit_status": payload.get("pre_commit_status"),
        "pre_push_status": payload.get("pre_push_status"),
        "event": event_info.get("event"),
        "reducer": event_info.get("reducer"),
    }

    def _emit_verify_hooks(result_payload: dict[str, Any]) -> None:
        print("=== HOOK VERIFY RECEIPT ===")
        print(f"git_hooks_status: {result_payload.get('git_hooks_status')}")
        print(f"hooks_receipt_path: {result_payload.get('hooks_receipt_path')}")

    return _finalize_mutation_result(
        payload=rendered,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_verify_hooks,
    )


def _default_verification_plan() -> str:
    return (
        "Run the scope-appropriate commands/checks for this quest, record the exact commands and receipts in the "
        "completion audit, and do not close the quest without a clean PASS."
    )


def _milestones_text_for_quest(items: list[str]) -> str:
    if not items:
        return "- MILESTONE-001 :: Close the bounded coherent outcome and record a clean completion audit PASS."
    return "\n".join(f"- MILESTONE-{index:03d} :: {item}" for index, item in enumerate(items, start=1))


def _state_history_text_for_quest(created_at: str) -> str:
    return f"- {created_at} :: BOARD"


def _normalize_outcome_specs(items: list[str], explicit_outcomes: list[str], default_title: str) -> list[tuple[str, list[str]]]:
    outcomes = [value.strip() for value in explicit_outcomes if value.strip()]
    if not outcomes:
        return [(default_title, items or [default_title])]

    grouped: dict[str, list[str]] = {outcome: [] for outcome in outcomes}
    for item in items:
        if "::" in item:
            head, tail = item.split("::", 1)
            outcome_key = head.strip()
            for outcome in outcomes:
                if _slugify(outcome_key) == _slugify(outcome) or outcome_key.lower() == outcome.lower():
                    if tail.strip():
                        grouped[outcome].append(tail.strip())
                    break
        else:
            continue
    results: list[tuple[str, list[str]]] = []
    for outcome in outcomes:
        results.append((outcome, grouped[outcome] or [outcome]))
    return results


def _plan_revision_preview(data_root: Path, title: str, plan_id: str | None) -> tuple[str, str]:
    effective_plan_id = str(plan_id or f"PLAN-{dt.datetime.now(tz=ZoneInfo('America/Toronto')).strftime('%Y%m%dT%H%M%S%f%z')}").strip()
    plans_dir = data_root / ".synapse" / "PLANS"
    revision_number = len(list(plans_dir.glob(f"PLAN__{effective_plan_id}__REVISION-*.yaml"))) + 1
    slug = _slugify(title)[:64] or "plan"
    filename = f"PLAN__{effective_plan_id}__REVISION-{revision_number:03d}__{slug}.yaml"
    return effective_plan_id, str((plans_dir / filename).resolve())


def _plan_quests_payload(
    ctx: dict[str, Any],
    *,
    items: list[str],
    title: str | None,
    goal: str | None,
    coherent_outcome: str | None,
    closure_statement: str | None,
    split_triggers: list[str],
    separate_outcomes: list[str],
    dependencies: list[str],
    out_of_scope: str | None,
    verification_plan: str | None,
    guild_orders_ref: str | None,
    guild_orders_artifact: str | None,
    dungeon_ref: str | None,
    dungeon_id: str | None,
    dungeon_coverage: str,
    plan_id: str | None,
    priority: str,
    risk: str,
    change_class: str,
    vision_delta: str,
    door_impact: str,
    testing_level: str,
    origin: str | None,
    anchors: list[str],
    constraints: list[str],
    deprecated_alias: bool,
    dry_run: bool,
) -> dict[str, Any]:
    state = load_state()
    if state.get("mode") == "INCUBATION":
        raise LiveMemoryError(
            "mode=INCUBATION. Quest drafting is not allowed during Incubation. "
            "Switch to PLAN or EXECUTE with `python3 runtime/synapse.py mode --set PLAN` if appropriate."
        )

    data_root = Path(ctx["data_root"])
    board_dir = data_root / "Quest Board"
    board_dir.mkdir(parents=True, exist_ok=True)
    active_run = _load_active_run_with_session_repair(ctx)
    plan_links: list[str] = []
    lineage_family_id: str | None = None

    if guild_orders_artifact or dungeon_id:
        if not guild_orders_artifact or not dungeon_id:
            raise LiveMemoryError("Canonical dungeon-derived planning requires both --guild-orders-artifact and --dungeon-id.")
        if guild_orders_ref or dungeon_ref:
            raise LiveMemoryError(
                "Use either canonical dungeon-derived inputs (--guild-orders-artifact/--dungeon-id) "
                "or manual lineage inputs (--guild-orders-ref/--dungeon-ref), not both."
            )
        try:
            derived = derive_canonical_dungeon_plan_inputs(
                data_root=data_root,
                guild_orders_artifact=guild_orders_artifact,
                dungeon_id=dungeon_id,
                items=items,
                separate_outcomes=separate_outcomes,
                requested_dungeon_coverage=dungeon_coverage,
            )
        except ValueError as exc:
            raise LiveMemoryError(str(exc)) from exc
        items = list(derived["items"])
        title = title or str(derived["title"])
        goal = goal or str(derived["goal"])
        coherent_outcome = coherent_outcome or str(derived["coherent_outcome"])
        closure_statement = closure_statement or str(derived["closure_statement"])
        out_of_scope = out_of_scope or str(derived["out_of_scope"])
        verification_plan = verification_plan or str(derived["verification_plan"])
        guild_orders_ref = str(derived["guild_orders_ref"])
        dungeon_ref = str(derived["dungeon_ref"])
        dungeon_coverage = str(derived["dungeon_coverage"])
        constraints = list(derived.get("constraints") or []) + constraints
        plan_links = [str(item) for item in derived.get("evidence_links") or []]
        lineage_family_id = str(derived.get("lineage_family_id") or "").strip() or None

    prefix = "QUEST"
    next_id = _next_quest_number(data_root, prefix)
    today = _today_toronto()

    codex_anchors = ", ".join(anchors) if anchors else "BLOCKED - CODEX_ANCHORS_MISSING"
    codex_constraints = "; ".join(constraints) if constraints else "TBD - derive from anchors"
    plan_title = (title or items[0]).strip()
    plan_goal = (goal or items[0]).strip()
    outcome_specs = _normalize_outcome_specs(items, separate_outcomes, plan_title)
    plan_id_preview, plan_path_preview = _plan_revision_preview(data_root, plan_title, plan_id)
    origin_value = origin or f"Plan decomposition (auto) - {today}"
    quest_specs: list[dict[str, str]] = []

    for offset, (outcome_title, outcome_items) in enumerate(outcome_specs):
        qnum = next_id + offset
        qid = f"{prefix}_{qnum:03d}"
        slug = _slugify(outcome_title)
        filename = f"{qid}__{slug}__{today}.txt"
        path = board_dir / filename
        if path.exists():
            raise LiveMemoryError(f"quest file already exists: {path}")
        quest_specs.append(
            {
                "quest_id": qid,
                "title": outcome_title,
                "path": str(path.resolve()),
                "milestones": outcome_items,
            }
        )

    if dry_run:
        return {
            "subject": ctx["subject"],
            "data_root": str(data_root),
            "plan_id": plan_id_preview,
            "plan_artifact_path": plan_path_preview,
            "quests": [
                {
                    **entry,
                    "state": "BOARD",
                    "risk": risk,
                    "change_class": change_class,
                    "vision_delta": vision_delta,
                }
                for entry in quest_specs
            ],
            "deprecated_alias": deprecated_alias,
            "dry_run": True,
        }

    plan_payload = persist_execution_plan(
        subject=ctx["subject"],
        data_root=data_root,
        title=plan_title,
        summary=plan_goal,
        origin=origin_value,
        objective=plan_goal,
        coherent_outcome=(
            coherent_outcome
            or plan_goal
            or ("Multiple independently closable outcomes under one persisted plan." if len(quest_specs) > 1 else plan_title)
        ),
        closure_statement=(
            closure_statement
            or "Close only when the quest outcome is honestly satisfied and the completion audit returns PASS."
        ),
        out_of_scope=out_of_scope or "Anything outside the persisted bounded outcome(s) described by this plan revision.",
        dependencies=dependencies or ["None"],
        risk=risk,
        verification_plan=verification_plan or _default_verification_plan(),
        milestones=items or [plan_title],
        split_triggers=split_triggers or ["Split if the plan reveals multiple independently closable outcomes."],
        guild_orders_ref=guild_orders_ref,
        dungeon_ref=dungeon_ref,
        dungeon_coverage=dungeon_coverage,
        links=plan_links,
        quest_refs=[entry["path"] for entry in quest_specs],
        related_run_ids=[str(active_run.get("run_id") or "").strip()] if isinstance(active_run, dict) and str(active_run.get("run_id") or "").strip() else [],
        source="plan-quests",
        plan_id=plan_id,
        lineage_family_id=lineage_family_id,
    )

    created_at = dt.datetime.now(tz=ZoneInfo("America/Toronto")).isoformat()
    results: list[dict[str, str]] = []
    for entry in quest_specs:
        outcome_title = entry["title"]
        milestone_items = entry["milestones"]
        values = {
            "quest_id": entry["quest_id"],
            "title": outcome_title,
            "subject": ctx["subject"],
            "origin": origin_value,
            "priority": priority,
            "links": f"- {plan_payload['path']}",
            "quest_state": "BOARD",
            "created_at": created_at,
            "codex_anchors": codex_anchors,
            "codex_constraints": codex_constraints,
            "change_class": change_class,
            "vision_delta": vision_delta,
            "system_context": "Plan-created bounded outcome within the current subject runtime; acceptance and completion stay on the governed quest path.",
            "anti_dup": f"Run rg -n \"{_slugify(outcome_title).replace('-', '|')}\" repo {ctx['subject']}_Data if present.",
            "placement_intent": "Intended layer: review before acceptance; Intended target path(s): derive from scoped work.",
            "guild_orders_ref": guild_orders_ref or "N/A",
            "dungeon_ref": dungeon_ref or "N/A",
            "dungeon_coverage": dungeon_coverage,
            "coherent_outcome": coherent_outcome or outcome_title,
            "closure_statement": closure_statement or f"Close only when {outcome_title.lower()} is honestly satisfied and the completion audit returns PASS.",
            "split_triggers": "\n".join(split_triggers or ["- Split if the work reveals more than one independently closable outcome."]),
            "risk": risk,
            "door_impact": door_impact,
            "testing_level": testing_level,
            "description": f"Plan outcome: {outcome_title}",
            "objective": goal or outcome_title,
            "milestones": _milestones_text_for_quest(milestone_items),
            "out_of_scope": out_of_scope or "Anything outside this bounded outcome and its listed milestones.",
            "dependencies": "\n".join(dependencies or ["None"]),
            "verification_plan": verification_plan or _default_verification_plan(),
            "plan_artifact_refs": f"- {plan_payload['path']}",
            "audit_state": "not_started",
            "audit_bundle_path": "",
            "state_history": _state_history_text_for_quest(created_at),
        }
        write_quest_document(quest_path=Path(entry["path"]), values=values)
        results.append(
            {
                "quest_id": entry["quest_id"],
                "title": outcome_title,
                "path": entry["path"],
                "state": "BOARD",
                "risk": risk,
                "change_class": change_class,
                "vision_delta": vision_delta,
                "plan_artifact_path": plan_payload["path"],
                "plan_id": plan_payload["plan_id"],
                "plan_revision_id": plan_payload["revision_id"],
            }
        )
    return {
        "subject": ctx["subject"],
        "data_root": str(data_root),
        "plan_id": plan_payload["plan_id"],
        "plan_artifact_path": plan_payload["path"],
        "plan_revision_id": plan_payload["revision_id"],
        "quests": results,
        "deprecated_alias": deprecated_alias,
        "dry_run": False,
    }


def cmd_plan_quests(args: argparse.Namespace) -> int:
    try:
        ctx = _resolve_or_attach_subject_from_args(args)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    try:
        items = _load_plan_items(args.item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    if not items and not (getattr(args, "guild_orders_artifact", None) and getattr(args, "dungeon_id", None)):
        print("FAIL: no plan items provided. Use --item or --items-file.")
        return 2

    try:
        common_kwargs = dict(
            items=items,
            title=getattr(args, "title", None),
            goal=getattr(args, "goal", None),
            coherent_outcome=getattr(args, "coherent_outcome", None),
            closure_statement=getattr(args, "closure_statement", None),
            split_triggers=[item.strip() for item in getattr(args, "split_trigger", []) if item.strip()],
            separate_outcomes=[item.strip() for item in getattr(args, "separate_outcome", []) if item.strip()],
            dependencies=[item.strip() for item in getattr(args, "dependency", []) if item.strip()],
            out_of_scope=getattr(args, "out_of_scope", None),
            verification_plan=getattr(args, "verification_plan", None),
            guild_orders_ref=getattr(args, "guild_orders_ref", None),
            guild_orders_artifact=getattr(args, "guild_orders_artifact", None),
            dungeon_ref=getattr(args, "dungeon_ref", None),
            dungeon_id=getattr(args, "dungeon_id", None),
            dungeon_coverage=getattr(args, "dungeon_coverage", "N/A"),
            plan_id=getattr(args, "plan_id", None),
            priority=args.priority,
            risk=args.risk,
            change_class=args.change_class,
            vision_delta=args.vision_delta,
            door_impact=args.door_impact,
            testing_level=args.testing_level,
            origin=args.origin,
            anchors=[a.strip() for a in args.anchor if a.strip()],
            constraints=[c.strip() for c in args.constraint if c.strip()],
            deprecated_alias=args.command == "plan-sidequests",
        )
        if args.dry_run:
            payload = _plan_quests_payload(ctx, dry_run=True, **common_kwargs)
            event_info = None
        else:
            active_run = _active_session_policy(ctx)[0]
            payload = _plan_quests_mutation(ctx, active_run=active_run, **common_kwargs)
            event_info = {
                "event": payload.get("event"),
                "reducer": payload.get("reducer"),
                "runtime_status": payload.get("runtime_status"),
            }
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_plan_receipt(rendered_payload: dict[str, Any]) -> None:
        print("=== QUEST PLAN RECEIPT ===")
        print(f"subject: {rendered_payload['subject']}")
        print(f"plan_id: {rendered_payload['plan_id']}")
        print(f"plan_artifact_path: {rendered_payload['plan_artifact_path']}")
        if not rendered_payload.get("dry_run"):
            print(f"data_root: {rendered_payload['data_root']}")
        print(f"created: {len(rendered_payload['quests'])}")
        if rendered_payload.get("deprecated_alias"):
            print("note: `plan-sidequests` is deprecated; use `plan-quests`.")
        for entry in rendered_payload["quests"]:
            print(f"- {entry['quest_id']}: {entry['path']}")
        if not rendered_payload.get("dry_run"):
            print("note: quests were drafted on BOARD only; acceptance and completion still require governed Control Sync + validation.")

    return _finalize_mutation_result(
        payload=payload,
        event_info=event_info,
        json_mode=args.json,
        text_emitter=_emit_plan_receipt,
        shell_mode=False,
    )


def cmd_plan_sidequests(args: argparse.Namespace) -> int:
    return cmd_plan_quests(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        if args.no_subject:
            return run_doctor(args.governance_root, None)
        try:
            receipt = resolve_subject(subject_flag=args.subject, allow_switch=False)
        except SubjectResolutionError as exc:
            print(f"FAIL: {exc}")
            print("Hint: run `python3 runtime/synapse.py engage` first, or use `doctor --no-subject` for governance-only work.")
            return 2
        return run_doctor(args.governance_root, receipt)
    if args.command == "governance-map":
        return cmd_governance_map(args)
    if args.command == "engage":
        return cmd_engage(args)
    if args.command == "attach-existing-repo":
        return cmd_attach_existing_repo(args)
    if args.command == "attach-or-init":
        return cmd_attach_or_init(args)
    if args.command == "focus":
        return cmd_focus(args)
    if args.command == "resolve-subject":
        return cmd_resolve_subject(args)
    if args.command == "persona":
        return cmd_persona(args)
    if args.command == "mode":
        return cmd_mode(args)
    if args.command == "drift":
        return cmd_drift(args)
    if args.command == "acknowledge":
        return cmd_acknowledge(args)
    if args.command == "enforce":
        return cmd_enforce(args)
    if args.command == "scaffold-subject":
        return cmd_scaffold_subject(args)
    if args.command == "live-bootstrap":
        return cmd_live_bootstrap(args)
    if args.command == "run-start":
        return cmd_run_start(args)
    if args.command == "session-start":
        return cmd_session_start(args)
    if args.command == "session-mode":
        return cmd_session_mode(args)
    if args.command == "run-update":
        return cmd_run_update(args)
    if args.command == "session-tick":
        return cmd_session_tick(args)
    if args.command == "capture-chunk":
        return cmd_capture_chunk(args)
    if args.command == "onboard-repo":
        return cmd_onboard_repo(args)
    if args.command == "onboarding-status":
        return cmd_onboarding_status(args)
    if args.command == "onboarding-update":
        return cmd_onboarding_update(args)
    if args.command == "onboarding-respond":
        return cmd_onboarding_respond(args)
    if args.command == "onboarding-confirm":
        return cmd_onboarding_confirm(args)
    if args.command == "onboarding-abandon":
        return cmd_onboarding_abandon(args)
    if args.command == "run-finalize":
        return cmd_run_finalize(args)
    if args.command == "log-decision":
        return cmd_log_decision(args)
    if args.command == "log-disclosure":
        return cmd_log_disclosure(args)
    if args.command == "render-rehydrate":
        return cmd_render_rehydrate(args)
    if args.command == "refresh-continuity":
        return cmd_refresh_continuity(args)
    if args.command == "compile-current-state":
        return cmd_compile_current_state(args)
    if args.command == "accept-quest":
        return cmd_accept_quest(args)
    if args.command == "complete-quest":
        return cmd_complete_quest(args)
    if args.command == "formalize":
        return cmd_formalize(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "provenance-status":
        return cmd_provenance_status(args)
    if args.command == "install-hooks":
        return cmd_install_hooks(args)
    if args.command == "verify-hooks":
        return cmd_verify_hooks(args)
    if args.command == "record-raw-turn":
        return cmd_record_raw_turn(args)
    if args.command == "record-raw-execution":
        return cmd_record_raw_execution(args)
    if args.command == "close-turn":
        return cmd_close_turn(args)
    if args.command == "import-continuity":
        return cmd_import_continuity(args)
    if args.command == "install-local-integration":
        return cmd_install_local_integration(args)
    if args.command == "refresh-draftshot":
        return cmd_refresh_draftshot(args)
    if args.command == "refresh-snapshot-candidates":
        return cmd_refresh_snapshot_candidates(args)
    if args.command == "refresh-publication-candidates":
        return cmd_refresh_publication_candidates(args)
    if args.command == "plan-quests":
        return cmd_plan_quests(args)
    if args.command == "plan-sidequests":
        return cmd_plan_sidequests(args)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

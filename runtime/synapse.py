#!/usr/bin/env python3
"""Synapse runtime CLI."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.doctor import run_doctor
from synapse_runtime.event_log import EventLogError, REDUCER_VERSION, append_event, build_event
from synapse_runtime.governance_pack import resolve_governance_asset, resolve_governance_root
from synapse_runtime.governance_inventory import build_governance_inventory, write_governance_inventory
from synapse_runtime.governance_model import AmbientSignal, ProposalKind, ProposalState
from synapse_runtime.live_journal import log_decision, log_disclosure, record_quest_acceptance
from synapse_runtime.live_memory_common import LiveMemoryError
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
    onboard_repo,
    onboarding_abandon,
    onboarding_confirm,
    onboarding_respond,
    onboarding_status_payload,
    onboarding_update,
)
from synapse_runtime.quest_candidates import list_proposals, mark_proposal_state
from synapse_runtime.reducer import ReducerError, reduce_after_event, reducer_mode
from synapse_runtime.rehydration_pack import refresh_rehydration_pack
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.run_lifecycle import load_active_run_record, run_finalize, run_start, run_update
from synapse_runtime.repo_state import (
    acknowledge_head,
    drift_commands,
    drift_status,
    enforce_execution_gate,
    load_state,
    set_mode,
    state_path,
)
from synapse_runtime.session_modes import (
    SESSION_MODE_POLICY_VERSION,
    SessionMode,
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
from synapse_runtime.sidecar_projection import _sync_sidecar, refresh_provenance_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state, repo_subject_defaults
from synapse_runtime.quest_acceptance import QuestAcceptanceError, accept_quest
from synapse_runtime.quest_board import (
    draft_quest_from_proposal,
    fill_quest_template as _fill_quest_template_impl,
    load_quest_template as _load_quest_template_impl,
    next_quest_number as _next_quest_number_impl,
    today_toronto as _today_toronto_impl,
)
from synapse_runtime.subject_resolver import (
    SubjectResolutionError,
    detect_subject_candidates,
    is_placeholder_subject,
    load_active_focus_lock,
    resolve_subject,
    session_focus_lock_path,
    write_focus_lock,
)


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
        "plan-sidequests",
        help="Draft SIDE-QUEST files from a short plan (BOARD state only)",
    )
    plan_parser.add_argument("--item", action="append", default=[], help="Plan item (repeatable)")
    plan_parser.add_argument("--items-file", help="Text file with one plan item per line")
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
        default="DEFERRED TO 01_PREQUEST.md",
        help="Testing Level value or 'DEFERRED TO 01_PREQUEST.md'",
    )
    plan_parser.add_argument("--origin", help="Override Origin field")
    plan_parser.add_argument("--anchor", action="append", default=[], help="Codex anchor (repeatable)")
    plan_parser.add_argument("--constraint", action="append", default=[], help="Codex constraint (repeatable)")
    plan_parser.add_argument("--dry-run", action="store_true", help="Show planned quests without writing files")
    plan_parser.add_argument("--json", action="store_true", help="Print JSON output")

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

    formalize_parser = subparsers.add_parser("formalize", help="Formalize ambient proposals into canonical artifacts")
    formalize_parser.add_argument("--proposal-id", help="Proposal id to formalize")
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


def _current_provenance_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    return compute_current_provenance_summary(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        engine_root=Path(ctx["engine_root"]),
        write_projection=False,
    )


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
            repo_defaults = _repo_adoption_defaults(detect_canonical_working_tree())
            selection = _apply_root_overrides(repo_defaults, args, home)
            init_receipt = _initialize_adopted_subject_state(
                selection["subject"],
                Path(selection["data_root"]),
                Path(selection["engine_root"]),
            )
            selection["selection_method"] = "flag"
            selection["source_detail"] = "engage_adopt_repo"
            receipt = _write_subject_lock_from_selection(selection, args)
            receipt["initialized_created"] = init_receipt["created"]
            receipt["initialized_existing"] = init_receipt["existing"]
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        if _stdin_is_interactive():
            selection = _interactive_engage_selection(home, args)
            if selection is None:
                print("CANCELLED")
                return 130
            if selection.get("source_detail") == "interactive_adopt_repo":
                _initialize_adopted_subject_state(
                    selection["subject"],
                    Path(selection["data_root"]),
                    Path(selection["engine_root"]),
                )
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        active_lock = load_active_focus_lock(session_id=args.session_id)
        if active_lock:
            active_subject = str(active_lock.get("subject") or "(unknown)")
            _print_noninteractive_engage_active_help(active_subject)
            return 2

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
    except LiveMemoryError as exc:
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
        if requested_mode and current_mode and requested_mode != current_mode:
            raise LiveMemoryError(
                f"Active run is already in session mode '{current_mode}'. "
                "Use `python3 runtime/synapse.py session-mode --set <mode> --reason <text>` to change posture."
            )
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
    except LiveMemoryError as exc:
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
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-update",
            summary=args.summary or f"Updated active run {result.get('run_id')}",
            session_id=session_id,
            signals={
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
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "verification_present": bool(args.verification),
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "run_path": result.get("run_path"),
                "ledger_path": result.get("ledger_path"),
                "discoveries_path": result.get("discoveries_path"),
            },
        )
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
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
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="session-tick",
            summary=args.summary or f"Session tick for {result.get('run_id')}",
            session_id=session_id,
            signals={
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
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "verification_present": bool(args.verification),
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "run_path": result.get("run_path"),
                "discoveries_path": result.get("discoveries_path"),
                "decision_path": decision_result.get("decision_path") if decision_result else None,
            },
        )
        continuity_result = {
            "rehydrate": event_info["reducer"]["rehydrate"],
            "continuity": event_info["reducer"]["continuity"],
        }
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

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
    }
    def _emit_session_tick(rendered_payload: dict[str, Any]) -> None:
        run_update_payload = rendered_payload["run_update"]
        print("=== SESSION TICK ===")
        print(f"run_id: {run_update_payload.get('run_id')}")
        print(f"discoveries_path: {run_update_payload.get('discoveries_path')}")
        if rendered_payload.get("decision"):
            print(f"decision_path: {rendered_payload['decision'].get('decision_path')}")
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
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-finalize",
            summary=args.summary or f"Finalized run {result.get('run_id')}",
            session_id=session_id,
            signals={
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
            },
            truth_flags={
                "canon_mutated": False,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "run_id": result.get("run_id"),
                "archive_path": result.get("archive_path"),
            },
        )
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
    except LiveMemoryError as exc:
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

        return _finalize_mutation_result(
            payload=partial_payload,
            event_info=_partial_after_primary_mutation(
                error_code="SEMANTIC_PROJECTION_FAILED",
                error_message=str(exc),
                recovery_hint=(
                    "Raw capture truth was written, but semantic projection failed before the event append. "
                    "Repair the projection conflict, then rerun the relevant refresh path or re-capture if needed."
                ),
            ),
            json_mode=args.json,
            text_emitter=_emit_capture_partial,
        )

    proposal_paths = list(sidecar.get("proposal_paths") or [])
    open_questions_path = sidecar.get("open_questions_path")
    written_artifacts = [capture_receipt["artifact_path"], capture_receipt["ledger_path"]]
    if open_questions_path:
        written_artifacts.append(str(open_questions_path))
    written_artifacts.extend(proposal_paths)

    event_info = _event_pipeline(
        ctx=ctx,
        action_name="capture-chunk",
        summary=str(args.title or capture_batch.get("title") or "Recorded semantic capture batch."),
        session_id=session_id,
        signals={
            "capture_batch_id": capture_batch.get("capture_batch_id"),
            "capture_count": len(capture_ids),
            "capture_kinds": semantic_capture_kinds(capture_batch),
            "capture_source_role": source_role.value,
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
            "uncertainty_present": batch_uncertainty_present(capture_batch),
            "disclosure_open": batch_disclosure_needed(capture_batch),
        },
        outputs={
            "capture_batch_id": capture_batch.get("capture_batch_id"),
            "capture_artifact_path": capture_receipt["artifact_path"],
            "capture_ledger_path": capture_receipt["ledger_path"],
            "open_questions_path": open_questions_path,
            "proposal_paths": proposal_paths,
            "written_artifacts": written_artifacts,
        },
    )

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
        active_run, session_id = _require_onboarding_context(
            ctx=ctx,
            action_name="onboard-repo",
            allow_create_onboard_run=True,
            allow_replace_onboard_run=bool(args.allow_switch),
        )
        result = onboard_repo(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            engine_root=Path(ctx["engine_root"]),
            active_run=active_run,
            depth=args.depth,
            rescan=bool(args.rescan),
            restart=bool(args.restart),
        )
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    if result.get("resumed_existing") or result.get("already_completed"):
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        print("=== ONBOARDING STATUS ===")
        print(f"onboarding_id: {result.get('onboarding_id') or 'none'}")
        print(f"state: {result.get('state') or result.get('onboarding_state') or 'none'}")
        if result.get("resumed_existing"):
            print("resumed_existing: true")
        if result.get("already_completed"):
            print("already_completed: true")
        return 0

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
    payload = {
        **result,
        "subject": ctx,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }

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
    except (LiveMemoryError, RepoOnboardingError, ProjectModelError, RepoArchaeologyError, SemanticIntakeError) as exc:
        print(f"FAIL: {exc}")
        return 2

    written_artifacts = [
        result.get("capture_artifact_path"),
        result.get("capture_ledger_path"),
    ]
    if sidecar.get("open_questions_path"):
        written_artifacts.append(sidecar.get("open_questions_path"))
    event_info = _event_pipeline(
        ctx=ctx,
        action_name="onboarding-respond",
        summary=f"Captured onboarding clarification batch {result.get('capture_batch_id')}.",
        session_id=session_id,
        signals={
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
        },
        truth_flags={
            "canon_mutated": False,
            "derived_state_changed": True,
            "governed": False,
            "uncertainty_present": True,
        },
        outputs={
            "onboarding_id": result.get("onboarding_id"),
            "capture_batch_id": result.get("capture_batch_id"),
            "capture_artifact_path": result.get("capture_artifact_path"),
            "capture_ledger_path": result.get("capture_ledger_path"),
            "linked_question_ids": list(result.get("linked_question_ids") or []),
        },
    )
    payload_out = {
        **{key: value for key, value in result.items() if key != "batch"},
        "subject": ctx,
        "sidecar": sidecar,
        "event": event_info["event"],
        "reducer": event_info["reducer"],
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
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
            "proposal_paths": list(result.get("proposal_paths") or []),
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

    def _emit_onboarding_confirm(rendered_payload: dict[str, Any]) -> None:
        print("=== ONBOARDING CONFIRMED ===")
        print(f"onboarding_id: {rendered_payload.get('onboarding_id')}")
        print(f"published_project_model_path: {rendered_payload.get('published_project_model_path')}")
        print(f"published_project_story_path: {rendered_payload.get('published_project_story_path')}")
        print(f"published_vision_path: {rendered_payload.get('published_vision_path')}")

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
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
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
        result.update(event_info)
        result["rehydrate"] = event_info["reducer"]["rehydrate"]
        result["continuity"] = event_info["reducer"]["continuity"]
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
        "rehydrate": event_info["reducer"]["rehydrate"],
        "continuity": event_info["reducer"]["continuity"],
    }


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
        event_info = {"event": payload["event"], "reducer": payload["reducer"]}
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


def _derive_dungeons(ctx: dict[str, Any], proposal: dict[str, Any]) -> list[dict[str, str]]:
    roots = [Path(ctx["engine_root"]), Path(ctx["data_root"])]
    headings: list[str] = []
    for evidence in proposal.get("evidence") or []:
        candidate = None
        for root in roots:
            probe = Path(str(evidence))
            if probe.is_absolute() and probe.exists():
                candidate = probe
                break
            local = root / str(evidence)
            if local.exists():
                candidate = local
                break
        if candidate is None or candidate.suffix.lower() not in {".md", ".txt"}:
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
            elif line.startswith("- "):
                heading = line[2:].strip()
            else:
                continue
            if len(heading) < 8 or len(heading) > 96:
                continue
            if heading.lower() in {"summary", "notes", "scope", "non-goals", "purpose"}:
                continue
            if heading not in headings:
                headings.append(heading)
            if len(headings) >= 4:
                break
    if not headings:
        headings.append(str(proposal.get("title") or "Ambient Scope Slice"))
    return [
        {
            "id": f"DUNGEON_{idx:02d}",
            "title": heading,
            "objective": str(proposal.get("summary") or heading),
            "scope": heading,
            "non_goals": "Anything outside the current ambient proposal scope.",
            "constraints": str(proposal.get("reason") or "Respect current Codex and runtime constraints."),
        }
        for idx, heading in enumerate(headings, start=1)
    ]


def _formalize_guild_orders(ctx: dict[str, Any], proposal: dict[str, Any], *, topic: str | None) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    today = _today_toronto()
    slug = _slugify(topic or str(proposal.get("title") or "guild-orders"))
    orders_id = f"GO-{today.replace('-', '')}-{slug}"
    orders_path = data_root / "Guild Orders" / "PAUSED" / f"{orders_id}.txt"
    orders_path.parent.mkdir(parents=True, exist_ok=True)
    dungeons = _derive_dungeons(ctx, proposal)

    lines = [
        "SYNAPSE GUILD ORDERS",
        "",
        f"- Subject: {ctx['subject']}",
        f"- Guild Orders ID: {orders_id}",
        "- Status: PAUSED",
        "- Owner(s): Brains, Hands",
        f"- Date Opened: {today}",
        f"- Date Updated: {today}",
        "",
        "Scope:",
        f"- {proposal.get('summary')}",
        "Non-Goals:",
        "- Any work outside the ambiently captured scope.",
        "",
        "Global Constraints:",
        f"- {proposal.get('reason')}",
        "",
        "Raid Done Definition:",
        f"- {proposal.get('summary')}",
        "Raid Verification Method:",
        "- Raw command output + changed-file receipts + governed artifacts.",
        "",
        "Dungeons:",
    ]
    for dungeon in dungeons:
        lines.extend(
            [
                "",
                f"Dungeon ID: {dungeon['id']}",
                f"- Title: {dungeon['title']}",
                f"- Objective: {dungeon['objective']}",
                f"- Scope: {dungeon['scope']}",
                f"- Non-Goals: {dungeon['non_goals']}",
                "- Dependencies: None",
                f"- Constraints: {dungeon['constraints']}",
                "- Interfaces/Boundaries: derive from proposal evidence",
                "- Verification:",
                "  - acceptance criteria derived from proposal evidence",
                "  - evidence required: receipts + artifact diffs",
                "- Stop Conditions (block immediately):",
                "  - contradiction vs codex/invariants",
                "  - missing required dependency/token/consent",
                "- Quest decomposition notes:",
                "  - expected quest families derived from ambient evidence",
            ]
        )
    lines.extend(
        [
            "",
            "Execution Policy:",
            "- R0/R1: execute automatically in EXECUTE mode.",
            "- R2+: explicit consent once per batch.",
            "- No silent scope expansion.",
            "",
            "Change Log:",
            f"- {today} Synapse ambient formalization from proposal {proposal.get('proposal_id')}",
            "",
        ]
    )
    orders_path.write_text("\n".join(lines), encoding="utf-8")
    proposal_receipt = mark_proposal_state(
        data_root=data_root,
        proposal_id=str(proposal["proposal_id"]),
        state=ProposalState.FORMALIZED,
        artifact_path=str(orders_path),
        note=f"Guild Orders formalized as {orders_id}.",
    )
    return {"artifact_path": str(orders_path), "proposal": proposal_receipt, "orders_id": orders_id}


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
    proposal_id: str,
    *,
    topic: str | None = None,
) -> dict[str, Any]:
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
    proposal_id: str,
    *,
    topic: str | None = None,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    proposal = _proposal_by_id(data_root, proposal_id)
    kind = ProposalKind(str(proposal.get("kind")))
    active_run = active_run or _active_session_policy(ctx)[0]
    session_id = _effective_session_id(ctx, active_run=active_run)

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
    kind_filter = ProposalKind(args.kind) if args.kind else None
    state_filter = ProposalState(args.state) if args.state else None

    if args.list or not args.proposal_id:
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
            payload = _formalize_candidate_dry_run(ctx, args.proposal_id, topic=args.topic)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("=== FORMALIZE DRY RUN ===")
                print(f"proposal_id: {payload['proposal'].get('proposal_id')}")
                print(f"kind: {payload.get('would_formalize_as')}")
                print(f"title: {payload['proposal'].get('title')}")
            return 0
        active_run, session_policy = _active_session_policy(ctx)
        if session_policy is not None and not session_policy.manual_formalize_allowed:
            return _fail_blocked_by_session_posture(
                action_name="formalize",
                active_run=active_run,
                json_mode=args.json,
            )
        payload = _formalize_candidate_mutation(ctx, args.proposal_id, topic=args.topic, active_run=active_run)
        event_info = {"event": payload["event"], "reducer": payload["reducer"]}
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    def _emit_formalize(rendered_payload: dict[str, Any]) -> None:
        print("=== FORMALIZATION RECEIPT ===")
        print(f"proposal_id: {args.proposal_id}")
        print(f"artifact_path: {rendered_payload['result'].get('artifact_path')}")

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
        print(f"last_watch_at: {payload.get('last_watch_at')}")
        print(f"baseline_path: {payload.get('baseline_path')}")
    if args.strict and payload.get("provenance_status") == ProvenanceStatus.BLOCKED.value:
        return 2
    return 0


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


def cmd_plan_sidequests(args: argparse.Namespace) -> int:
    try:
        ctx = _resolve_or_attach_subject_from_args(args)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    state = load_state()
    if state.get("mode") == "INCUBATION":
        print("BLOCKED: mode=INCUBATION. Quest drafting is not allowed during Incubation.")
        print("Switch to PLAN or EXECUTE with `python3 runtime/synapse.py mode --set PLAN` if appropriate.")
        return 2

    try:
        items = _load_plan_items(args.item, args.items_file)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    if not items:
        print("FAIL: no plan items provided. Use --item or --items-file.")
        return 2

    cwt = detect_canonical_working_tree()
    try:
        template = _load_quest_template(cwt)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    data_root = Path(ctx["data_root"])
    board_dir = data_root / "Quest Board"
    board_dir.mkdir(parents=True, exist_ok=True)

    prefix = args.quest_prefix
    next_id = _next_quest_number(data_root, prefix)
    today = _today_toronto()

    anchors = [a.strip() for a in args.anchor if a.strip()]
    constraints = [c.strip() for c in args.constraint if c.strip()]
    codex_anchors = ", ".join(anchors) if anchors else "BLOCKED - CODEX_ANCHORS_MISSING"
    codex_constraints = "; ".join(constraints) if constraints else "TBD - derive from anchors"

    origin = args.origin or f"Plan decomposition (auto) - {today}"
    results: list[dict[str, str]] = []

    for offset, item in enumerate(items):
        qnum = next_id + offset
        qid = f"{prefix}_{qnum:03d}"
        slug = _slugify(item)
        filename = f"{qid}__{slug}__{today}.txt"
        path = board_dir / filename
        if path.exists():
            print(f"FAIL: quest file already exists: {path}")
            return 2

        values = {
            "quest_id": qid,
            "title": item,
            "subject": ctx["subject"],
            "origin": origin,
            "priority": args.priority,
            "links": "None",
            "codex_anchors": codex_anchors,
            "codex_constraints": codex_constraints,
            "change_class": args.change_class,
            "vision_delta": args.vision_delta,
            "system_context": "TBD - requires review before acceptance.",
            "anti_dup": f"Run rg -n \"{slug}\" in repo and Subject_Data.",
            "placement_intent": "Intended layer: unknown; Intended target path(s): unknown.",
            "atomicity": "Atomic: yes - single independently verifiable outcome.",
            "risk": args.risk,
            "door_impact": args.door_impact,
            "testing_level": args.testing_level,
            "talent_awarded": "NO",
            "description": f"Plan item: {item}",
            "objective": f"Success when: {item}",
            "out_of_scope": "Anything beyond the single plan item described above.",
            "dependencies": "None",
            "verification_plan": "DEFERRED TO 01_PREQUEST.md",
        }

        quest_text = _fill_quest_template(template, values)
        if not args.dry_run:
            path.write_text(quest_text, encoding="utf-8")

        results.append(
            {
                "quest_id": qid,
                "title": item,
                "path": str(path),
                "state": "BOARD",
                "risk": args.risk,
                "change_class": args.change_class,
                "vision_delta": args.vision_delta,
            }
        )

    if args.json:
        print(json.dumps({"subject": ctx["subject"], "data_root": str(data_root), "quests": results}, indent=2))
        return 0

    print("=== SIDE-QUEST PLAN RECEIPT ===")
    print(f"subject: {ctx['subject']}")
    print(f"data_root: {data_root}")
    print(f"quest_prefix: {prefix}")
    print(f"created: {len(results)}")
    for entry in results:
        print(f"- {entry['quest_id']}: {entry['path']}")
    print("note: quests were drafted on BOARD only; acceptance/execution requires Control Sync + validation.")
    return 0


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
    if args.command == "accept-quest":
        return cmd_accept_quest(args)
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
    if args.command == "plan-sidequests":
        return cmd_plan_sidequests(args)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

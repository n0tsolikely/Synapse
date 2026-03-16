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
from synapse_runtime.event_log import EventLogError, append_event, build_event
from synapse_runtime.governance_pack import resolve_governance_asset, resolve_governance_root
from synapse_runtime.governance_inventory import build_governance_inventory, write_governance_inventory
from synapse_runtime.governance_model import ProposalKind, ProposalState
from synapse_runtime.live_journal import log_decision, log_disclosure, record_quest_acceptance
from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.persona import resolve_persona
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

    doctor_parser = subparsers.add_parser("doctor", help="Run deterministic governance checks")
    doctor_parser.add_argument(
        "--governance-root",
        required=True,
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
    session_tick_parser.add_argument("--json", action="store_true", help="Print JSON output")

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
    watch_parser.add_argument("--json", action="store_true", help="Print JSON output")

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
        continuity = refresh_rehydration_pack(subject=subject, data_root=data_root, engine_root=engine_root)
        return {"rehydrate": rehydrate, "continuity": continuity}
    except Exception as exc:
        raise LiveMemoryError(str(exc)) from exc


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
) -> dict[str, Any]:
    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    session_id = str(ctx.get("session_id") or "").strip() or None
    run_id = str(outputs.get("run_id") or signals.get("run_id") or "").strip() or None
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
    try:
        append_receipt = append_event(data_root=data_root, event=event)
    except EventLogError as exc:
        raise LiveMemoryError(f"Primary action succeeded, but event append failed: {exc}") from exc

    mode = reducer_mode()
    if mode == "legacy":
        legacy_refresh = _render_and_refresh_continuity(ctx["subject"], data_root, engine_root)
        return {
            "event": {"receipt": append_receipt, "payload": event},
            "reducer": {
                "mode": "legacy",
                "rehydrate": legacy_refresh["rehydrate"],
                "continuity": legacy_refresh["continuity"],
            },
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
        raise LiveMemoryError(
            f"Primary action succeeded and event {append_receipt['event_id']} was recorded, but reducer refresh failed: {exc}"
        ) from exc

    return {
        "event": {"receipt": append_receipt, "payload": event},
        "reducer": reduction,
    }


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

    if args.shell or args.json:
        _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
        return 0

    print("=== ATTACH / INIT RECEIPT ===")
    _print_subject_receipt(receipt)
    print(f"auto_initialized: {'YES' if receipt.get('auto_initialized') else 'NO'}")
    print(f"live_root: {receipt.get('live_root')}")
    if receipt.get("initialized_created"):
        print("initialized_created:")
        for path in receipt["initialized_created"]:
            print(f"- {path}")
    if receipt.get("live_created"):
        print("live_created:")
        for path in receipt["live_created"]:
            print(f"- {path}")
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
  - "NONBLOCKING questions are deferred in Incubation/OPEN_QUESTIONS.md."
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

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== LIVE BOOTSTRAP RECEIPT ===")
    _print_subject_receipt(ctx)
    print(f"live_root: {result['live_root']}")
    if result["created"]:
        print("created:")
        for path in result["created"]:
            print(f"- {path}")
    if result["existing"]:
        print("existing:")
        for path in result["existing"]:
            print(f"- {path}")
    return 0


def _default_session_title(ctx: dict[str, Any]) -> str:
    session_id = str(ctx.get("session_id") or _resolved_session_id(argparse.Namespace(session_id=None)) or "").strip()
    suffix = f" [{session_id}]" if session_id else ""
    return f"{ctx['subject']} Ambient Session{suffix}"


def _write_session_overlay(ctx: dict[str, Any], run_payload: dict[str, Any] | None) -> str | None:
    session_id = str(ctx.get("session_id") or "").strip()
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


def _start_or_resume_session_run(ctx: dict[str, Any], *, title: str | None, goal: str | None, items: list[str]) -> dict[str, Any]:
    active_run = load_active_run_record(subject=ctx["subject"], data_root=Path(ctx["data_root"]))
    if active_run.get("run_id"):
        return {
            "run_id": active_run["run_id"],
            "run_path": str(Path(ctx["data_root"]) / ".synapse" / "ACTIVE_RUN.yaml"),
            "title": active_run.get("title"),
            "goal": active_run.get("goal"),
            "items": active_run.get("plan", {}).get("items", []),
            "resumed": True,
        }
    return run_start(
        subject=ctx["subject"],
        data_root=Path(ctx["data_root"]),
        title=title or _default_session_title(ctx),
        goal=goal,
        items=items,
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
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-start",
            summary=f"Started active run: {result.get('title')}",
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

    overlay_path = _write_session_overlay(ctx, result)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== RUN STARTED ===")
    print(f"run_id: {result['run_id']}")
    print(f"run_path: {result['run_path']}")
    if overlay_path:
        print(f"session_overlay: {overlay_path}")
    if result.get("items"):
        print("plan_items:")
        for item in result["items"]:
            print(f"- {item['id']}: {item['text']} ({item['status']})")
    return 0


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
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="session-start",
            summary=f"Started or resumed session run: {result.get('title') or ctx['subject']}",
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

    overlay_path = _write_session_overlay(ctx, result)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    if args.json:
        print(json.dumps({"subject": ctx, "run": result}, indent=2, sort_keys=True))
        return 0

    print("=== SESSION STARTED ===")
    _print_subject_receipt(ctx)
    print(f"run_id: {result.get('run_id')}")
    if overlay_path:
        print(f"session_overlay: {overlay_path}")
    return 0


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

    overlay_path = _write_session_overlay(ctx, result)
    if overlay_path:
        result["session_overlay_path"] = overlay_path

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== RUN UPDATED ===")
    print(f"run_id: {result.get('run_id')}")
    if result.get("added_items"):
        print("added_items:")
        for item in result["added_items"]:
            print(f"- {item['id']}: {item['text']} ({item['status']})")
    if result.get("status_updates"):
        print("status_updates:")
        for item_id, status in result["status_updates"]:
            print(f"- {item_id}: {status}")
    if overlay_path:
        print(f"session_overlay: {overlay_path}")
    return 0


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
        _start_or_resume_session_run(
            ctx,
            title=args.title or _default_session_title(ctx),
            goal=args.goal,
            items=items,
        )
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

    overlay_path = _write_session_overlay(ctx, result)
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
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== SESSION TICK ===")
    print(f"run_id: {result.get('run_id')}")
    print(f"discoveries_path: {result.get('discoveries_path')}")
    if decision_result:
        print(f"decision_path: {decision_result.get('decision_path')}")
    if overlay_path:
        print(f"session_overlay: {overlay_path}")
    return 0


def cmd_run_finalize(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
        result = run_finalize(
            subject=ctx["subject"],
            data_root=Path(ctx["data_root"]),
            status=args.status,
            summary=args.summary,
        )
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="run-finalize",
            summary=args.summary or f"Finalized run {result.get('run_id')}",
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
    session_id = str(ctx.get("session_id") or "").strip()
    if session_id:
        overlay_path = _clear_session_run_overlay(session_id)
        result["session_overlay_path"] = overlay_path

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== RUN FINALIZED ===")
    print(f"run_id: {result.get('run_id')}")
    print(f"archive_path: {result.get('archive_path')}")
    if overlay_path:
        print(f"session_overlay_cleared: {overlay_path}")
    return 0


def cmd_log_decision(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
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

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== DECISION LOGGED ===")
    print(f"path: {result.get('decision_path')}")
    return 0


def cmd_log_disclosure(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    try:
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

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=== DISCLOSURE LOGGED ===")
    print(f"path: {result.get('disclosure_path')}")
    return 0


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


def cmd_accept_quest(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    data_root = Path(ctx["data_root"])
    engine_root = Path(ctx["engine_root"])
    try:
        acceptance = accept_quest(
            subject=ctx["subject"],
            data_root=data_root,
            engine_root=engine_root,
            quest_ref=args.quest,
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
        payload = {
            "subject": ctx,
            "acceptance": acceptance,
            "sidecar": sidecar,
        }
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="accept-quest",
            summary=f"Accepted quest {acceptance.get('quest_id')} for governed execution.",
            signals={
                "related_quest_ids": [acceptance.get("quest_id")],
                "related_sidequest_ids": [],
                "changed_files": [acceptance.get("accepted_path"), acceptance.get("audit_bundle_path")],
                "verification_entries": [],
                "accepted_context": _accepted_context_snapshot(data_root),
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
        payload["event"] = event_info["event"]
        payload["reducer"] = event_info["reducer"]
        payload["rehydrate"] = event_info["reducer"]["rehydrate"]
        payload["continuity"] = event_info["reducer"]["continuity"]
    except (QuestAcceptanceError, LiveMemoryError) as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== QUEST ACCEPTED ===")
    print(f"quest_id: {acceptance.get('quest_id')}")
    print(f"accepted_path: {acceptance.get('accepted_path')}")
    print(f"audit_bundle_path: {acceptance.get('audit_bundle_path')}")
    print(f"governed_execution_ready: {acceptance.get('governed_execution_ready')}")
    return 0


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
        proposal = _proposal_by_id(data_root, args.proposal_id)
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
            result = _formalize_guild_orders(ctx, proposal, topic=args.topic)
        elif kind == ProposalKind.DISCLOSURE:
            result = _formalize_disclosure(ctx, proposal)
        else:
            raise LiveMemoryError(f"Formalization is not implemented for proposal kind {kind.value}.")
        event_info = _event_pipeline(
            ctx=ctx,
            action_name="formalize",
            summary=f"Formalized proposal {args.proposal_id} as {kind.value}.",
            signals={
                "proposal_id": args.proposal_id,
                "proposal_kind": kind.value,
                "related_quest_ids": [proposal.get("proposal_id")] if kind in {ProposalKind.QUEST, ProposalKind.SIDE_QUEST} else [],
                "related_sidequest_ids": [],
                "changed_files": [result.get("artifact_path")] if result.get("artifact_path") else [],
                "verification_entries": [],
                "accepted_context": _accepted_context_snapshot(data_root),
            },
            truth_flags={
                "canon_mutated": True,
                "derived_state_changed": True,
                "governed": False,
                "uncertainty_present": False,
            },
            outputs={
                "proposal_id": args.proposal_id,
                "proposal_kind": kind.value,
                "artifact_path": result.get("artifact_path"),
            },
        )
        payload = {
            "subject": ctx,
            "result": result,
            "rehydrate": event_info["reducer"]["rehydrate"],
            "continuity": event_info["reducer"]["continuity"],
            "event": event_info["event"],
            "reducer": event_info["reducer"],
        }
    except LiveMemoryError as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== FORMALIZATION RECEIPT ===")
    print(f"proposal_id: {args.proposal_id}")
    print(f"artifact_path: {result.get('artifact_path')}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    ctx = _resolve_or_attach_subject_from_args(args)
    if not ctx:
        return 2

    iterations = max(1, int(args.iterations))
    payloads: list[dict[str, Any]] = []
    last_files: list[str] = []
    for idx in range(iterations):
        files = _git_status_changed_files(detect_canonical_working_tree()) if args.capture_git else []
        changed_files = [item for item in files if item not in last_files]
        tick_args = argparse.Namespace(
            plan_item=[],
            items_file=None,
            commands=[],
            file=changed_files,
            note=[f"watch iteration {idx + 1}"],
            discovery=[],
            verification=[],
            related_sidequest=[],
            related_quest=[],
            status="active",
            summary=f"watch tick {idx + 1}",
            decision_title=None,
            decision_summary=None,
            decision_why=None,
            capture_git=False,
            title=args.title,
            goal=args.goal,
            subject=ctx["subject"],
            data_root=ctx["data_root"],
            engine_root=ctx["engine_root"],
            selected_by=args.selected_by,
            no_home_lock=args.no_home_lock,
            session_id=args.session_id,
            json=False,
        )
        if changed_files or idx == 0:
            try:
                _start_or_resume_session_run(ctx, title=args.title or _default_session_title(ctx), goal=args.goal, items=[])
                result = run_update(
                    subject=ctx["subject"],
                    data_root=Path(ctx["data_root"]),
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
                payloads.append(result)
                _write_session_overlay(ctx, result)
                _render_and_refresh_continuity(ctx["subject"], Path(ctx["data_root"]), Path(ctx["engine_root"]))
            except LiveMemoryError as exc:
                print(f"FAIL: {exc}")
                return 2
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
    if args.command == "run-update":
        return cmd_run_update(args)
    if args.command == "session-tick":
        return cmd_session_tick(args)
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
    if args.command == "plan-sidequests":
        return cmd_plan_sidequests(args)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

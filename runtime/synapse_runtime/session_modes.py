"""Session posture model and policy for Synapse runtime flows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from synapse_runtime.governance_model import ProposalKind


class SessionMode(str, Enum):
    ONBOARDING_EXISTING_REPO = "onboarding_existing_repo"
    BRAINSTORM_SPEC = "brainstorm_spec"
    CONTROL_SYNC = "control_sync"
    SCOPE_PLANNING = "scope_planning"
    EXECUTION = "execution"
    CLOSEOUT = "closeout"


@dataclass(frozen=True)
class SessionModePolicy:
    mode: SessionMode
    description: str
    allowed_proposal_kinds: tuple[ProposalKind, ...]
    auto_formalize_ready_quests: bool
    manual_formalize_allowed: bool
    quest_acceptance_allowed: bool
    blocked_mutation_commands: tuple[str, ...]
    allowed_next_modes: tuple[SessionMode, ...]


SESSION_MODE_POLICY_VERSION = 1

_COMMON_PRE_EXECUTION_PROPOSAL_KINDS = (
    ProposalKind.QUEST,
    ProposalKind.SIDE_QUEST,
    ProposalKind.SNAPSHOT,
    ProposalKind.CONTROL_SYNC,
    ProposalKind.GUILD_ORDERS,
    ProposalKind.CODEX,
    ProposalKind.BUILD_MANUAL,
    ProposalKind.DISCLOSURE,
)

_EXECUTION_PROPOSAL_KINDS = _COMMON_PRE_EXECUTION_PROPOSAL_KINDS + (
    ProposalKind.TALENT,
)

_CLOSEOUT_PROPOSAL_KINDS = (
    ProposalKind.SNAPSHOT,
    ProposalKind.CONTROL_SYNC,
    ProposalKind.CODEX,
    ProposalKind.BUILD_MANUAL,
    ProposalKind.TALENT,
    ProposalKind.DISCLOSURE,
)


_POLICY_REGISTRY: dict[SessionMode, SessionModePolicy] = {
    SessionMode.ONBOARDING_EXISTING_REPO: SessionModePolicy(
        mode=SessionMode.ONBOARDING_EXISTING_REPO,
        description="Attach to and map an existing repo without binding canon or governed execution yet.",
        allowed_proposal_kinds=_COMMON_PRE_EXECUTION_PROPOSAL_KINDS,
        auto_formalize_ready_quests=False,
        manual_formalize_allowed=False,
        quest_acceptance_allowed=False,
        blocked_mutation_commands=("formalize", "accept-quest", "complete-quest"),
        allowed_next_modes=(
            SessionMode.BRAINSTORM_SPEC,
            SessionMode.CONTROL_SYNC,
            SessionMode.SCOPE_PLANNING,
            SessionMode.CLOSEOUT,
        ),
    ),
    SessionMode.BRAINSTORM_SPEC: SessionModePolicy(
        mode=SessionMode.BRAINSTORM_SPEC,
        description="Explore ideas, spec shape, and ambiguity without mutating canon or accepting governed scope.",
        allowed_proposal_kinds=_COMMON_PRE_EXECUTION_PROPOSAL_KINDS,
        auto_formalize_ready_quests=False,
        manual_formalize_allowed=False,
        quest_acceptance_allowed=False,
        blocked_mutation_commands=("formalize", "accept-quest", "complete-quest"),
        allowed_next_modes=(
            SessionMode.CONTROL_SYNC,
            SessionMode.SCOPE_PLANNING,
            SessionMode.CLOSEOUT,
        ),
    ),
    SessionMode.CONTROL_SYNC: SessionModePolicy(
        mode=SessionMode.CONTROL_SYNC,
        description="Hold formal alignment and binding decision review without accepting governed execution yet.",
        allowed_proposal_kinds=_COMMON_PRE_EXECUTION_PROPOSAL_KINDS,
        auto_formalize_ready_quests=False,
        manual_formalize_allowed=True,
        quest_acceptance_allowed=False,
        blocked_mutation_commands=("accept-quest", "complete-quest"),
        allowed_next_modes=(
            SessionMode.BRAINSTORM_SPEC,
            SessionMode.SCOPE_PLANNING,
            SessionMode.EXECUTION,
            SessionMode.CLOSEOUT,
        ),
    ),
    SessionMode.SCOPE_PLANNING: SessionModePolicy(
        mode=SessionMode.SCOPE_PLANNING,
        description="Shape scoped work, allow quest formalization, and prepare governed execution deliberately.",
        allowed_proposal_kinds=_COMMON_PRE_EXECUTION_PROPOSAL_KINDS,
        auto_formalize_ready_quests=True,
        manual_formalize_allowed=True,
        quest_acceptance_allowed=True,
        blocked_mutation_commands=(),
        allowed_next_modes=(
            SessionMode.BRAINSTORM_SPEC,
            SessionMode.CONTROL_SYNC,
            SessionMode.EXECUTION,
            SessionMode.CLOSEOUT,
        ),
    ),
    SessionMode.EXECUTION: SessionModePolicy(
        mode=SessionMode.EXECUTION,
        description="Execute active work while preserving continuity and allowing governed formalization surfaces.",
        allowed_proposal_kinds=_EXECUTION_PROPOSAL_KINDS,
        auto_formalize_ready_quests=True,
        manual_formalize_allowed=True,
        quest_acceptance_allowed=True,
        blocked_mutation_commands=(),
        allowed_next_modes=(
            SessionMode.CONTROL_SYNC,
            SessionMode.SCOPE_PLANNING,
            SessionMode.CLOSEOUT,
        ),
    ),
    SessionMode.CLOSEOUT: SessionModePolicy(
        mode=SessionMode.CLOSEOUT,
        description="Wrap up and crystallize current truth without opening new governed scope.",
        allowed_proposal_kinds=_CLOSEOUT_PROPOSAL_KINDS,
        auto_formalize_ready_quests=False,
        manual_formalize_allowed=False,
        quest_acceptance_allowed=False,
        blocked_mutation_commands=("formalize", "accept-quest"),
        allowed_next_modes=(
            SessionMode.BRAINSTORM_SPEC,
            SessionMode.CONTROL_SYNC,
            SessionMode.SCOPE_PLANNING,
        ),
    ),
}


_LEGACY_INTERACTION_TO_SESSION: dict[str, SessionMode] = {
    "execution": SessionMode.EXECUTION,
    "capability_expansion": SessionMode.EXECUTION,
    "decision": SessionMode.CONTROL_SYNC,
    "closeout": SessionMode.CLOSEOUT,
    "exploration": SessionMode.BRAINSTORM_SPEC,
    "maintenance": SessionMode.BRAINSTORM_SPEC,
}


def policy_for(mode: SessionMode) -> SessionModePolicy:
    return _POLICY_REGISTRY[SessionMode(mode)]


def active_session_mode(run_data: dict[str, Any] | None) -> SessionMode | None:
    if not isinstance(run_data, dict):
        return None
    if not run_data.get("active"):
        return None
    mode = str(run_data.get("session_mode") or "").strip()
    return SessionMode(mode) if mode else None


def policy_for_run(run_data: dict[str, Any] | None) -> SessionModePolicy | None:
    mode = active_session_mode(run_data)
    return policy_for(mode) if mode else None


def policy_summary(mode: SessionMode) -> dict[str, Any]:
    policy = policy_for(mode)
    return {
        "description": policy.description,
        "blocked_mutation_commands": list(policy.blocked_mutation_commands),
        "allowed_next_modes": [item.value for item in policy.allowed_next_modes],
        "auto_formalize_ready_quests": policy.auto_formalize_ready_quests,
        "manual_formalize_allowed": policy.manual_formalize_allowed,
        "quest_acceptance_allowed": policy.quest_acceptance_allowed,
        "allowed_proposal_kinds": [item.value for item in policy.allowed_proposal_kinds],
    }


def default_mode_for_command(command_name: str) -> SessionMode:
    command = str(command_name or "").strip()
    if command in {"session-start", "session-tick"}:
        return SessionMode.BRAINSTORM_SPEC
    if command == "run-start":
        return SessionMode.EXECUTION
    raise ValueError(f"No default session mode defined for command '{command_name}'.")


def backfill_mode_from_active_run(run_data: dict[str, Any], now_iso: str) -> tuple[dict[str, Any], bool]:
    normalized = dict(run_data)
    existing = str(normalized.get("session_mode") or "").strip()
    if existing:
        return normalized, False
    if not normalized.get("run_id") and not normalized.get("active"):
        return normalized, False

    interaction_mode = str(normalized.get("interaction_mode") or "").strip().lower()
    mode = _LEGACY_INTERACTION_TO_SESSION.get(interaction_mode, SessionMode.BRAINSTORM_SPEC)
    normalized["session_mode"] = mode.value
    normalized["session_mode_source"] = "legacy_backfill"
    normalized["session_mode_set_at"] = now_iso
    normalized["session_mode_reason"] = "backfilled from pre-phase1 interaction_mode"
    normalized["session_mode_policy_version"] = SESSION_MODE_POLICY_VERSION
    return normalized, True


def validate_transition(current: SessionMode, target: SessionMode) -> tuple[bool, tuple[SessionMode, ...]]:
    policy = policy_for(current)
    allowed = policy.allowed_next_modes
    return SessionMode(target) in allowed, allowed


def session_mode_signal_fields(run_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run_data, dict):
        return {}
    mode = str(run_data.get("session_mode") or "").strip()
    if not mode:
        return {}
    return {
        "session_mode": mode,
        "session_mode_source": run_data.get("session_mode_source"),
        "session_mode_policy_version": run_data.get("session_mode_policy_version"),
    }

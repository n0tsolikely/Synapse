"""Governance domain model and promotion heuristics for Synapse."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


class AuthorityClass(str, Enum):
    LOCK_AUTHORITY = "lock_authority"
    DEFINITIONAL_LAW = "definitional_law"
    PROCESS_PROCEDURE = "process_procedure"
    TEMPLATE_SPEC = "template_spec"
    TERMINOLOGY_REFERENCE = "terminology_reference"
    ROUTING_INDEXING = "routing_indexing"
    SCHEMA_CONTRACT = "schema_contract"
    SUPPORTING_DOC = "supporting_doc"


class GovernanceCategory(str, Enum):
    ROUTING = "routing"
    CONTINUITY = "continuity"
    CANONICAL = "canonical"
    PROCESS = "process"
    SNAPSHOT = "snapshot"
    QUEST_SYSTEM = "quest_system"
    TALENT_TREE = "talent_tree"
    TERMINOLOGY_TERM = "terminology_term"
    TERMINOLOGY_LOCK = "terminology_lock"
    SCHEMA = "schema"
    SUPPORT = "support"


class ImplementationStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    MISSING = "missing"
    DOC_ONLY = "doc_only"
    CONTRADICTORY = "contradictory"


class ArtifactType(str, Enum):
    SUBJECT_STATE = "subject_state"
    BUFF_EXECUTION_PROTOCOL = "buff_execution_protocol"
    BUFF_DIRECTORY_MAP = "buff_directory_map"
    BUFF_SESSION_START = "buff_session_start"
    BOOTSTRAP_PROMPT = "bootstrap_prompt"
    CONTINUITY_LOCK = "continuity_lock"
    EXECUTION_PACK = "execution_pack"
    CODEX = "codex"
    CODEX_FREEZE = "codex_freeze"
    BUILD_MANUAL = "build_manual"
    GUILD_ORDERS = "guild_orders"
    QUEST = "quest"
    SIDE_QUEST = "side_quest"
    EXECUTION_AUDIT = "execution_audit"
    SNAPSHOT_CONTROL_SYNC = "snapshot_control_sync"
    SNAPSHOT_EOD = "snapshot_eod"
    SNAPSHOT_GENERAL = "snapshot_general"
    DRAFTSHOT = "draftshot"
    TALENT_TREE = "talent_tree"
    TALENT_LOG = "talent_log"
    RESPEC_RULES = "respec_rules"
    SIDECAR_STATE = "sidecar_state"
    SIDECAR_MANIFOLD = "sidecar_manifold"
    ACTIVE_RUN = "active_run"
    RUN_LEDGER = "run_ledger"
    DECISION_LEDGER = "decision_ledger"
    DISCOVERY_LEDGER = "discovery_ledger"
    DISCLOSURE_LEDGER = "disclosure_ledger"
    THREADS = "threads"
    REHYDRATE = "rehydrate"
    VISION = "vision"
    PROPOSAL = "proposal"


class WorldState(str, Enum):
    FOG_OF_WAR = "fog_of_war"
    FOG_LIFTED = "fog_lifted"


class QuestState(str, Enum):
    BOARD = "board"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class DraftshotState(str, Enum):
    NONE = "none"
    ACTIVE = "active"
    CONSUMED = "consumed"
    ABANDONED = "abandoned"


class ProposalKind(str, Enum):
    QUEST = "quest"
    SIDE_QUEST = "side_quest"
    SNAPSHOT = "snapshot"
    CONTROL_SYNC = "control_sync"
    GUILD_ORDERS = "guild_orders"
    CODEX = "codex"
    BUILD_MANUAL = "build_manual"
    TALENT = "talent"
    DISCLOSURE = "disclosure"


class ProposalState(str, Enum):
    AMBIENT = "ambient"
    DRAFT = "draft"
    PROPOSED = "proposed"
    READY = "ready"
    FORMALIZED = "formalized"
    BLOCKED = "blocked"
    ESCALATED = "escalated"


class InteractionMode(str, Enum):
    EXPLORATION = "exploration"
    DECISION = "decision"
    EXECUTION = "execution"
    CLOSEOUT = "closeout"
    CAPABILITY_EXPANSION = "capability_expansion"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class ConceptSpec:
    slug: str
    display_name: str
    aliases: tuple[str, ...]
    capabilities: tuple[str, ...]
    artifact_types: tuple[ArtifactType, ...] = ()


@dataclass(frozen=True)
class CapabilityStatus:
    key: str
    status: ImplementationStatus
    source_paths: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class AmbientSignal:
    source: str
    subject: str
    title: str | None = None
    summary: str | None = None
    notes: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    related_sidequests: tuple[str, ...] = ()
    related_quests: tuple[str, ...] = ()
    status: str | None = None


@dataclass(frozen=True)
class PromotionRecord:
    kind: ProposalKind
    state: ProposalState
    title: str
    summary: str
    reason: str
    blockers: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    codex_implications: tuple[str, ...] = ()


def _today_iso() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).date().isoformat()


def now_iso() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).isoformat()


def current_session_id(env: dict[str, str] | None = None) -> str | None:
    env_map = env or os.environ
    raw = str(env_map.get("SYNAPSE_SESSION_ID") or "").strip()
    return raw or None


def codex_freeze_marker(data_root: Path) -> Path:
    return data_root / "Codex" / "CODEX_FREEZE.md"


def codex_freeze_proof(data_root: Path) -> tuple[bool, list[str]]:
    marker = codex_freeze_marker(data_root)
    if not marker.exists():
        return False, [f"missing marker: {marker}"]

    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, [f"unable to read marker {marker}: {exc}"]

    problems: list[str] = []
    if not re.search(r"(?im)\b(?:Brains|Brains Approval)\b", text):
        problems.append("Codex Freeze marker is missing explicit Brains approval text")
    if not re.search(r"(?im)\b\d{4}-\d{2}-\d{2}\b", text):
        problems.append("Codex Freeze marker is missing a date/timestamp")
    return not problems, problems


def derive_world_state(data_root: Path) -> WorldState:
    ok, _ = codex_freeze_proof(data_root)
    return WorldState.FOG_LIFTED if ok else WorldState.FOG_OF_WAR


def quest_state_from_path(path: Path, data_root: Path) -> QuestState | None:
    board_root = (data_root / "Quest Board").resolve()
    try:
        relative = path.resolve().relative_to(board_root)
    except Exception:
        return None

    parts = relative.parts
    if not parts:
        return None
    if parts[0] == "Accepted":
        return QuestState.ACCEPTED
    if parts[0] == "Completed":
        return QuestState.COMPLETED
    if parts[0] == "Abandoned":
        return QuestState.ABANDONED
    return QuestState.BOARD


def infer_interaction_mode(signal: AmbientSignal) -> InteractionMode:
    text = " ".join(
        [
            signal.source or "",
            signal.title or "",
            signal.summary or "",
            *signal.notes,
            *signal.commands,
            *signal.files_touched,
        ]
    ).lower()

    capability_markers = (
        "runtime",
        "governance",
        "capability",
        "adapter",
        "door",
        "codex",
        "talent",
        "engine",
    )
    decision_markers = (
        "decision",
        "constraint",
        "tradeoff",
        "binding",
        "architecture",
        "scope",
    )
    closeout_markers = ("final", "finalize", "closeout", "snapshot", "resume", "rehydrate", "end of day")

    if signal.source in {"run-finalize", "render-rehydrate"} or any(marker in text for marker in closeout_markers):
        return InteractionMode.CLOSEOUT
    if any(part.startswith("runtime/") or part.startswith("governance/") for part in signal.files_touched) or any(
        marker in text for marker in capability_markers
    ):
        return InteractionMode.CAPABILITY_EXPANSION
    if signal.source == "log-decision":
        return InteractionMode.DECISION
    if any(marker in text for marker in decision_markers) and not (signal.commands or signal.files_touched):
        return InteractionMode.DECISION
    if signal.commands or signal.files_touched or signal.related_quests or signal.related_sidequests:
        return InteractionMode.EXECUTION
    if signal.notes or signal.summary:
        return InteractionMode.EXPLORATION
    return InteractionMode.MAINTENANCE


def _normalize_title(raw: str | None, fallback: str) -> str:
    value = (raw or "").strip()
    return value if value else fallback


def evaluate_promotion(signal: AmbientSignal, data_root: Path) -> list[PromotionRecord]:
    world_state = derive_world_state(data_root)
    interaction = infer_interaction_mode(signal)
    evidence: list[str] = [path for path in signal.files_touched if path]
    evidence.extend(cmd for cmd in signal.commands if cmd)
    text = " ".join(
        [
            signal.source or "",
            signal.title or "",
            signal.summary or "",
            *signal.notes,
            *signal.commands,
            *signal.files_touched,
        ]
    ).lower()
    disclosure_markers = (
        "disclosure",
        "blocked",
        "unknown",
        "unverified",
        "ambiguous",
        "cannot prove",
        "missing artifact",
        "missing",
        "truth gate",
    )

    records: list[PromotionRecord] = []

    if interaction == InteractionMode.DECISION:
        records.append(
            PromotionRecord(
                kind=ProposalKind.CONTROL_SYNC,
                state=ProposalState.READY,
                title=_normalize_title(signal.title, "Control Sync Candidate"),
                summary=_normalize_title(signal.summary, "Binding decision captured; Control Sync formalization warranted."),
                reason="Decision-like interaction captured constraints or tradeoffs.",
                evidence=tuple(evidence),
                codex_implications=("Review Codex/Guild Orders if decision changes meaning or scope.",),
            )
        )
        if any(marker in text for marker in ("scope", "guild order", "raid", "dungeon", "roadmap", "phase", "release")):
            records.append(
                PromotionRecord(
                    kind=ProposalKind.GUILD_ORDERS,
                    state=ProposalState.PROPOSED,
                    title=_normalize_title(signal.title, "Guild Orders Candidate"),
                    summary=_normalize_title(signal.summary, "Scope-shaping decision suggests Guild Orders formalization."),
                    reason="Decision-like interaction changed bounded build scope or campaign intent.",
                    evidence=tuple(evidence),
                    codex_implications=("Guild Orders must remain aligned to Codex constraints and active Control Sync outputs.",),
                )
            )

    if interaction in {InteractionMode.EXECUTION, InteractionMode.CAPABILITY_EXPANSION} or (
        interaction == InteractionMode.EXPLORATION and signal.source in {"run-start", "run-update", "run-finalize"}
    ):
        sidequest_markers = ("bug", "hotfix", "regression", "incident", "unexpected", "out-of-band")
        proposal_kind = ProposalKind.SIDE_QUEST if signal.related_sidequests or any(marker in text for marker in sidequest_markers) else ProposalKind.QUEST
        state = ProposalState.AMBIENT
        blockers: tuple[str, ...] = ()
        reason = "Recorded runtime signals indicate a concentrated work unit that should be tracked as a quest candidate."
        if interaction == InteractionMode.CAPABILITY_EXPANSION:
            reason = "Capability-shaping work detected; quest clustering and codex promotion should be considered."
        records.append(
            PromotionRecord(
                kind=proposal_kind,
                state=state,
                title=_normalize_title(signal.title, "Quest Candidate"),
                summary=_normalize_title(signal.summary, "Execution signals captured from active run."),
                reason=reason,
                blockers=blockers,
                evidence=tuple(evidence),
            )
        )
        if interaction == InteractionMode.CAPABILITY_EXPANSION:
            records.append(
                PromotionRecord(
                    kind=ProposalKind.CODEX,
                    state=ProposalState.PROPOSED,
                    title=_normalize_title(signal.title, "Codex Candidate"),
                    summary="Capability-shaping work likely changes first-class system knowledge.",
                    reason="Runtime/governance/module boundaries changed during execution.",
                    evidence=tuple(evidence),
                )
            )
            if any(marker in text for marker in ("build manual", "build strategy", "sequencing", "scaffold", "wiring", "verification expectations")):
                records.append(
                    PromotionRecord(
                        kind=ProposalKind.BUILD_MANUAL,
                        state=ProposalState.PROPOSED,
                        title=_normalize_title(signal.title, "Build Manual Candidate"),
                        summary="Capability-shaping work likely changed the recommended HOW-layer construction path.",
                        reason="Execution changed scaffolding, sequencing, or verification expectations enough to warrant Build Manual guidance.",
                        evidence=tuple(evidence),
                        codex_implications=("Build Manual must not redefine Codex laws; conflicts require Control Sync.",),
                    )
                )
            if any(marker in text for marker in ("scope", "campaign", "dungeon", "raid", "phase")):
                records.append(
                    PromotionRecord(
                        kind=ProposalKind.GUILD_ORDERS,
                        state=ProposalState.PROPOSED,
                        title=_normalize_title(signal.title, "Guild Orders Candidate"),
                        summary="Capability work changed execution scope enough to consider refreshed Guild Orders.",
                        reason="Runtime changes imply a new or updated bounded execution campaign.",
                        evidence=tuple(evidence),
                    )
                )

    if interaction == InteractionMode.CLOSEOUT:
        records.append(
            PromotionRecord(
                kind=ProposalKind.SNAPSHOT,
                state=ProposalState.READY,
                title=_normalize_title(signal.title, "Snapshot Candidate"),
                summary=_normalize_title(signal.summary, "Session closeout indicates a snapshot should be formalized."),
                reason="Closeout interaction detected; snapshot promotion is warranted.",
                evidence=tuple(evidence),
            )
        )

    if signal.verification and signal.files_touched and interaction in {
        InteractionMode.EXECUTION,
        InteractionMode.CAPABILITY_EXPANSION,
        InteractionMode.CLOSEOUT,
    }:
        records.append(
            PromotionRecord(
                kind=ProposalKind.TALENT,
                state=ProposalState.PROPOSED,
                title=_normalize_title(signal.title, "Talent Candidate"),
                summary="Verified work changed capabilities enough to review for Talent updates.",
                reason="Verified implementation changed files and may have unlocked a durable capability.",
                evidence=tuple(signal.verification + tuple(evidence)),
                codex_implications=("If capability is durable, update Talent Tree and related Codex anchors.",),
            )
        )

    if signal.source == "log-disclosure" or str(signal.status or "").strip().lower() in {"blocked", "unknown", "unverified", "fail", "failed"}:
        records.append(
            PromotionRecord(
                kind=ProposalKind.DISCLOSURE,
                state=ProposalState.READY if signal.source == "log-disclosure" else ProposalState.PROPOSED,
                title=_normalize_title(signal.title, "Disclosure Gate Event"),
                summary=_normalize_title(signal.summary, "Uncertainty changed the next safe action and requires durable disclosure."),
                reason="Disclosure Gate trigger detected from blocked/unprovable/ambiguous runtime state.",
                evidence=tuple(evidence),
            )
        )
    elif any(marker in text for marker in disclosure_markers) and signal.notes:
        records.append(
            PromotionRecord(
                kind=ProposalKind.DISCLOSURE,
                state=ProposalState.PROPOSED,
                title=_normalize_title(signal.title, "Disclosure Gate Candidate"),
                summary=_normalize_title(signal.summary, "Potential disclosure-worthy uncertainty detected."),
                reason="Runtime notes include ambiguity or proof-blocking markers that may require Disclosure Gate handling.",
                evidence=tuple(evidence),
            )
        )

    if interaction == InteractionMode.EXPLORATION and signal.notes:
        records.append(
            PromotionRecord(
                kind=ProposalKind.SNAPSHOT,
                state=ProposalState.AMBIENT,
                title=_normalize_title(signal.title, "Ambient Discovery"),
                summary="Exploration signals captured; keep ambient until a binding decision or closeout occurs.",
                reason="Exploratory interaction does not justify formalization yet.",
                evidence=tuple(evidence),
            )
        )

    return records


KNOWN_CONCEPTS: tuple[ConceptSpec, ...] = (
    ConceptSpec(
        slug="subject",
        display_name="Subject",
        aliases=("subject", "subject model", "subject_data", "subject_state"),
        capabilities=("subject_resolution", "subject_bootstrap", "schema_validation"),
        artifact_types=(ArtifactType.SUBJECT_STATE,),
    ),
    ConceptSpec(
        slug="bootstrap_prompt",
        display_name="Bootstrap Prompt",
        aliases=("bootstrap prompt",),
        capabilities=("subject_bootstrap", "rehydration_renderer", "continuity_refresh"),
        artifact_types=(ArtifactType.BOOTSTRAP_PROMPT,),
    ),
    ConceptSpec(
        slug="buffs",
        display_name="Buffs",
        aliases=("buffs", "execution protocol", "session start check", "data directory map"),
        capabilities=("subject_bootstrap", "auto_attach_or_init"),
        artifact_types=(
            ArtifactType.BUFF_EXECUTION_PROTOCOL,
            ArtifactType.BUFF_DIRECTORY_MAP,
            ArtifactType.BUFF_SESSION_START,
        ),
    ),
    ConceptSpec(
        slug="continuity_lock",
        display_name="Continuity Lock",
        aliases=("continuity lock",),
        capabilities=("subject_bootstrap", "rehydration_renderer", "continuity_refresh"),
        artifact_types=(ArtifactType.CONTINUITY_LOCK,),
    ),
    ConceptSpec(
        slug="execution_pack",
        display_name="Execution Pack",
        aliases=("execution pack",),
        capabilities=("proposal_promotion",),
        artifact_types=(ArtifactType.EXECUTION_PACK,),
    ),
    ConceptSpec(
        slug="control_sync",
        display_name="Control Sync",
        aliases=("control sync",),
        capabilities=("control_sync_runtime", "snapshot_runtime"),
        artifact_types=(ArtifactType.SNAPSHOT_CONTROL_SYNC,),
    ),
    ConceptSpec(
        slug="draftshot",
        display_name="Draftshot",
        aliases=("draftshot", "draft shots"),
        capabilities=("draftshot_bridge", "snapshot_runtime", "ambient_sidecar_manifold"),
        artifact_types=(ArtifactType.DRAFTSHOT,),
    ),
    ConceptSpec(
        slug="snapshot",
        display_name="Snapshot",
        aliases=("snapshot", "end-of-day snapshot", "control sync snapshot", "general snapshot"),
        capabilities=("snapshot_runtime", "draftshot_bridge", "formalization_engine"),
        artifact_types=(
            ArtifactType.SNAPSHOT_CONTROL_SYNC,
            ArtifactType.SNAPSHOT_EOD,
            ArtifactType.SNAPSHOT_GENERAL,
        ),
    ),
    ConceptSpec(
        slug="quest",
        display_name="Quest",
        aliases=("quest", "side-quest", "quest board"),
        capabilities=("quest_state_machine", "execution_audits", "formalization_engine"),
        artifact_types=(ArtifactType.QUEST, ArtifactType.SIDE_QUEST, ArtifactType.EXECUTION_AUDIT),
    ),
    ConceptSpec(
        slug="codex",
        display_name="Codex",
        aliases=("codex", "toc", "legend", "codex freeze", "fog of war", "fog lifted"),
        capabilities=("world_state_gate", "codex_gate", "proposal_promotion"),
        artifact_types=(ArtifactType.CODEX, ArtifactType.CODEX_FREEZE),
    ),
    ConceptSpec(
        slug="build_manual",
        display_name="Build Manual",
        aliases=("build manual", "build_manual"),
        capabilities=("build_manual_runtime", "proposal_promotion"),
        artifact_types=(ArtifactType.BUILD_MANUAL,),
    ),
    ConceptSpec(
        slug="truth_gate",
        display_name="Truth Gate",
        aliases=("truth gate",),
        capabilities=("truth_gate_receipts", "execution_audits"),
    ),
    ConceptSpec(
        slug="disclosure_gate",
        display_name="Disclosure Gate",
        aliases=("disclosure gate",),
        capabilities=("disclosure_gate_enforcement", "disclosure_artifact_runtime"),
    ),
    ConceptSpec(
        slug="verification_ladder",
        display_name="Verification Ladder",
        aliases=("verification ladder", "testing level", "tl1", "tl2", "tl3", "tl4"),
        capabilities=("verification_gate",),
    ),
    ConceptSpec(
        slug="risk_consent",
        display_name="Risk Rubric / Consent Gate",
        aliases=("risk rubric", "consent gate", "r2", "confirmation artifact"),
        capabilities=("risk_consent_gate",),
    ),
    ConceptSpec(
        slug="talent_tree",
        display_name="Talent Tree",
        aliases=("talent tree", "talent log", "respec"),
        capabilities=("talent_pipeline", "proposal_promotion"),
        artifact_types=(ArtifactType.TALENT_TREE, ArtifactType.TALENT_LOG, ArtifactType.RESPEC_RULES),
    ),
    ConceptSpec(
        slug="ambient_sidecar",
        display_name="Ambient Sidecar",
        aliases=("state.yaml", "manifold.yaml", "active_run", "discoveries", "decisions", "rehydrate", "vision"),
        capabilities=("ambient_sidecar_manifold", "session_runtime"),
        artifact_types=(
            ArtifactType.SIDECAR_STATE,
            ArtifactType.SIDECAR_MANIFOLD,
            ArtifactType.ACTIVE_RUN,
            ArtifactType.RUN_LEDGER,
            ArtifactType.DECISION_LEDGER,
            ArtifactType.DISCOVERY_LEDGER,
            ArtifactType.DISCLOSURE_LEDGER,
            ArtifactType.REHYDRATE,
            ArtifactType.VISION,
            ArtifactType.PROPOSAL,
        ),
    ),
)


CAPABILITY_REGISTRY: dict[str, CapabilityStatus] = {
    "subject_resolution": CapabilityStatus(
        key="subject_resolution",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/subject_resolver.py",
        ),
        summary="Explicit subject resolution, lock precedence, and placeholder blocking are implemented.",
    ),
    "auto_attach_or_init": CapabilityStatus(
        key="auto_attach_or_init",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/subject_bootstrap.py",
        ),
        summary="Subject-aware runtime commands can auto-attach or initialize current repo subject state.",
    ),
    "subject_bootstrap": CapabilityStatus(
        key="subject_bootstrap",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/subject_bootstrap.py",
        ),
        summary="Canonical Subject_Data skeleton, Buffs, Bootstrap Prompt, Continuity Lock, and sidecar scaffold are created deterministically.",
    ),
    "schema_validation": CapabilityStatus(
        key="schema_validation",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/schema_validation.py",
            "runtime/synapse_runtime/doctor.py",
        ),
        summary="SYNAPSE_STATE and SUBJECT_STATE schema validation is enforced by doctor/runtime.",
    ),
    "world_state_gate": CapabilityStatus(
        key="world_state_gate",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/governance_model.py",
            "runtime/synapse_runtime/repo_state.py",
            "runtime/tools/synapse_governance_guard.py",
        ),
        summary="Fog of War vs Fog Lifted is derived from Codex Freeze proof and used to gate execution.",
    ),
    "control_sync_runtime": CapabilityStatus(
        key="control_sync_runtime",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=("runtime/tools/synapse_snapshot_writer.py",),
        summary="Control Sync open/close state and snapshot closeout are implemented with deterministic writer tooling.",
    ),
    "snapshot_runtime": CapabilityStatus(
        key="snapshot_runtime",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=("runtime/tools/synapse_snapshot_writer.py",),
        summary="Canonical Snapshot writing, naming, duplicate counters, and templates are enforced by tool.",
    ),
    "draftshot_bridge": CapabilityStatus(
        key="draftshot_bridge",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=("runtime/tools/synapse_snapshot_writer.py",),
        summary="Active Draftshots are detected, referenced by snapshots, and marked CONSUMED during formalization.",
    ),
    "quest_state_machine": CapabilityStatus(
        key="quest_state_machine",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/tools/synapse_governance_guard.py",
            "runtime/tools/synapse_quest_run.sh",
        ),
        summary="Quest drafting, validation gating, wrapper receipts, and completion rules are enforced on filesystem state.",
    ),
    "execution_audits": CapabilityStatus(
        key="execution_audits",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/tools/synapse_governance_guard.py",
            "runtime/tools/synapse_quest_run.sh",
        ),
        summary="Audit bundle initialization, wrapper-proof validation, and receipt requirements are enforced.",
    ),
    "truth_gate_receipts": CapabilityStatus(
        key="truth_gate_receipts",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/tools/synapse_governance_guard.py",
            "runtime/tools/synapse_quest_run.sh",
            "runtime/synapse_runtime/governance_inventory.py",
        ),
        summary="Executed-command receipts and raw-output validation are enforced by guardrails and inventory coverage.",
    ),
    "disclosure_gate_enforcement": CapabilityStatus(
        key="disclosure_gate_enforcement",
        status=ImplementationStatus.PARTIALLY_IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/doctor.py",
            "runtime/tools/synapse_governance_guard.py",
        ),
        summary="Runtime blocks and messages cover major disclosure events, but a dedicated durable disclosure artifact writer is still lightweight.",
    ),
    "verification_gate": CapabilityStatus(
        key="verification_gate",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/tools/synapse_governance_guard.py",
            "runtime/tools/synapse_quest_run.sh",
        ),
        summary="Verification PASS/FAIL/BLOCKED outcomes and wrapper receipts are enforced before quest completion.",
    ),
    "risk_consent_gate": CapabilityStatus(
        key="risk_consent_gate",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/repo_state.py",
            "runtime/tools/synapse_consent.sh",
            "runtime/tools/require_r2_confirmation.sh",
        ),
        summary="R2 gating and on-disk confirmation flow are implemented.",
    ),
    "codex_gate": CapabilityStatus(
        key="codex_gate",
        status=ImplementationStatus.PARTIALLY_IMPLEMENTED,
        source_paths=("runtime/tools/synapse_codex_gate.py",),
        summary="Codex spec/consistency gates exist, but full anchor extraction and cross-section law checks remain lighter than the prose canon.",
    ),
    "build_manual_runtime": CapabilityStatus(
        key="build_manual_runtime",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/governance_model.py",
        ),
        summary="Build Manual proposals and deterministic formalization paths exist in the ambient/runtime workflow.",
    ),
    "talent_pipeline": CapabilityStatus(
        key="talent_pipeline",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/tools/synapse_governance_guard.py",
            "runtime/synapse.py",
        ),
        summary="Talent award validation, template initialization, and proposal surfacing are implemented.",
    ),
    "ambient_sidecar_manifold": CapabilityStatus(
        key="ambient_sidecar_manifold",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/live_memory.py",
            "runtime/synapse_runtime/governance_model.py",
        ),
        summary="Canonical .synapse STATE/MANIFOLD, daily ledgers, proposals, and rehydrate rendering are implemented.",
    ),
    "disclosure_artifact_runtime": CapabilityStatus(
        key="disclosure_artifact_runtime",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/live_memory.py",
        ),
        summary="Disclosure Gate events can be recorded durably in canonical sidecar artifacts and formalized into snapshots.",
    ),
    "session_runtime": CapabilityStatus(
        key="session_runtime",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/live_memory.py",
        ),
        summary="Session start/tick/watch flows update the ambient sidecar without explicit engage rituals.",
    ),
    "proposal_promotion": CapabilityStatus(
        key="proposal_promotion",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/governance_model.py",
            "runtime/synapse_runtime/live_memory.py",
            "runtime/synapse.py",
        ),
        summary="Ambient signals are translated into proposal/promotion records with block/escalate/formalize states.",
    ),
    "rehydration_renderer": CapabilityStatus(
        key="rehydration_renderer",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/live_memory.py",
            "runtime/synapse.py",
        ),
        summary="REHYDRATE rendering synthesizes state, ledgers, proposals, and current run truth.",
    ),
    "continuity_refresh": CapabilityStatus(
        key="continuity_refresh",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/synapse_runtime/rehydration_pack.py",
        ),
        summary="Latest Rehydration Pack bootstrap/continuity artifacts are refreshed from canonical sidecar truth and superseded active files are archived.",
    ),
    "governance_inventory": CapabilityStatus(
        key="governance_inventory",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse_runtime/governance_inventory.py",
            "runtime/synapse_runtime/governance_model.py",
            "runtime/synapse.py",
        ),
        summary="Governance corpus ingestion, authority mapping, and implementation coverage are available as runtime data.",
    ),
    "formalization_engine": CapabilityStatus(
        key="formalization_engine",
        status=ImplementationStatus.IMPLEMENTED,
        source_paths=(
            "runtime/synapse.py",
            "runtime/tools/synapse_snapshot_writer.py",
        ),
        summary="Snapshot and quest proposal formalization flows are available from runtime commands.",
    ),
}


KNOWN_CONTRADICTIONS: dict[str, str] = {
    "governance/The Guild/Guild Members/Guild_Members.txt": (
        "Member labels are internally swapped: 'MEMBER 001 — HANDS' describes Brains authority, "
        "while 'MEMBER 002 — BRAINS' describes Hands duties."
    ),
    "governance/The Guild/Terminology/Terms/Rehydration.md": (
        "Rehydration term forbids guessing 'latest' by timestamp, while Bootstrap Prompt, Continuity Lock, "
        "and Rehydration Pack docs define date-token latest-selection rules. The authority boundary between "
        "explicit pointers and deterministic date selection is ambiguous."
    ),
    "governance/SYNAPSE_STATE.yaml": (
        "Governance routing manifest uses single_required pick rules for latest rehydration artifacts, while "
        "continuity docs discuss date-based latest selection if multiple artifacts exist. The runtime treats "
        "Latest Rehydration Pack as a single-active surface and flags ambiguity."
    ),
}


def concept_matches(alias: str, text: str) -> bool:
    pattern = r"\b" + re.escape(alias).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def matched_concepts(text: str) -> list[ConceptSpec]:
    matches: list[ConceptSpec] = []
    haystack = text.lower()
    for spec in KNOWN_CONCEPTS:
        if any(concept_matches(alias, haystack) for alias in spec.aliases):
            matches.append(spec)
    return matches


def capability_status(keys: Iterable[str]) -> list[CapabilityStatus]:
    statuses: list[CapabilityStatus] = []
    for key in keys:
        item = CAPABILITY_REGISTRY.get(key)
        if item is not None:
            statuses.append(item)
    return statuses


def implementation_status_from_capabilities(keys: Iterable[str], *, path: str | None = None) -> ImplementationStatus:
    key_list = list(dict.fromkeys(keys))
    if path and path in KNOWN_CONTRADICTIONS:
        return ImplementationStatus.CONTRADICTORY
    if not key_list:
        return ImplementationStatus.DOC_ONLY

    statuses = capability_status(key_list)
    if not statuses:
        return ImplementationStatus.MISSING

    values = {item.status for item in statuses}
    if values == {ImplementationStatus.IMPLEMENTED}:
        return ImplementationStatus.IMPLEMENTED
    if ImplementationStatus.IMPLEMENTED in values or ImplementationStatus.PARTIALLY_IMPLEMENTED in values:
        return ImplementationStatus.PARTIALLY_IMPLEMENTED
    if values == {ImplementationStatus.CONTRADICTORY}:
        return ImplementationStatus.CONTRADICTORY
    return ImplementationStatus.MISSING


def authority_precedence() -> list[str]:
    return [
        "Terminology Locks",
        "Governance Processes / Canonical Law",
        "Continuity Lock",
        "Buffs",
        "Chat / conversation intent",
    ]


def required_sidecar_paths(data_root: Path) -> dict[ArtifactType, Path]:
    live_root = data_root / ".synapse"
    today = _today_iso()
    return {
        ArtifactType.SIDECAR_STATE: live_root / "STATE.yaml",
        ArtifactType.SIDECAR_MANIFOLD: live_root / "MANIFOLD.yaml",
        ArtifactType.ACTIVE_RUN: live_root / "ACTIVE_RUN.yaml",
        ArtifactType.RUN_LEDGER: live_root / "RUNS",
        ArtifactType.DECISION_LEDGER: live_root / "DECISIONS" / f"{today}.yaml",
        ArtifactType.DISCOVERY_LEDGER: live_root / "DISCOVERIES" / f"{today}.yaml",
        ArtifactType.DISCLOSURE_LEDGER: live_root / "DISCLOSURES" / f"{today}.yaml",
        ArtifactType.THREADS: live_root / "THREADS" / "open_questions.md",
        ArtifactType.REHYDRATE: live_root / "REHYDRATE.md",
        ArtifactType.VISION: live_root / "VISION.md",
        ArtifactType.PROPOSAL: live_root / "PROPOSALS",
    }

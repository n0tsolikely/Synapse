"""Bounded Guild Orders canonization runtime."""

from __future__ import annotations

import datetime as dt
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from synapse_runtime.governance_model import WorldState, derive_world_state
from synapse_runtime.live_memory_common import LiveMemoryError, _normalize_relpaths, _slugify, _unique_strings


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


class GuildOrdersOperation(str, Enum):
    CREATE_PAUSED = "create_paused"
    REVISE_PAUSED = "revise_paused"
    START_ACTIVE = "start_active"
    PAUSE_ACTIVE = "pause_active"
    COMPLETE_ORDERS = "complete_orders"
    BLOCK = "block"


class GuildOrdersRevisionClass(str, Enum):
    CREATE = "create"
    EDITORIAL = "editorial"
    MATERIAL_SCOPE_CHANGE = "material_scope_change"
    STATE_TRANSITION = "state_transition"
    BLOCKED = "blocked"


class GuildOrdersState(str, Enum):
    PAUSED = "PAUSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class GuildOrdersDungeonSpec:
    dungeon_id: str
    title: str
    objective: str
    coherent_outcome: str
    closure_statement: str
    out_of_scope: str
    constraints: tuple[str, ...]
    verification_plan: str
    evidence: tuple[str, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class GuildOrdersPacket:
    proposal_id: str
    subject: str
    title: str
    summary: str
    objective: str
    coherent_outcome: str
    closure_statement: str
    out_of_scope: str
    constraints: tuple[str, ...]
    verification_plan: str
    evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    codex_implications: tuple[str, ...]
    lineage_family_id: str
    dungeon_specs: tuple[GuildOrdersDungeonSpec, ...]


@dataclass(frozen=True)
class GuildOrdersMutationResult:
    ok: bool
    operation: GuildOrdersOperation
    revision_class: GuildOrdersRevisionClass
    world_state: str
    state_before: str | None
    state_after: str | None
    source_artifact_path: str | None
    destination_artifact_path: str | None
    lineage_family_id: str
    orders_id: str | None
    supporting_receipt_refs: tuple[str, ...]
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation.value,
            "revision_class": self.revision_class.value,
            "world_state": self.world_state,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "source_artifact_path": self.source_artifact_path,
            "destination_artifact_path": self.destination_artifact_path,
            "lineage_family_id": self.lineage_family_id,
            "orders_id": self.orders_id,
            "supporting_receipt_refs": list(self.supporting_receipt_refs),
            "blocked_reason": self.blocked_reason,
        }


def today_toronto() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).date().isoformat()


def normalize_guild_orders_packet(
    *,
    subject: str,
    data_root: Path,
    proposal: dict[str, Any],
    topic: str | None = None,
    explicit_dungeon_specs: Iterable[dict[str, Any]] | None = None,
) -> GuildOrdersPacket:
    proposal_id = _require_scalar(proposal, "proposal_id")
    title = _clean_text(topic) or _require_scalar(proposal, "title")
    summary = _require_scalar(proposal, "summary")
    objective = _clean_text(proposal.get("objective")) or summary
    coherent_outcome = _require_scalar(proposal, "coherent_outcome")
    closure_statement = _require_scalar(proposal, "closure_statement")
    verification_plan = _require_scalar(proposal, "verification_plan")
    reason = _require_scalar(proposal, "reason")
    evidence = tuple(_normalize_evidence(data_root, proposal.get("evidence") or ()))
    if not evidence:
        raise LiveMemoryError("Guild Orders formalization requires at least one evidence ref.")
    blockers = tuple(_unique_strings(str(item) for item in proposal.get("blockers") or () if str(item).strip()))
    codex_implications = tuple(
        _unique_strings(str(item) for item in proposal.get("codex_implications") or () if str(item).strip())
    )
    out_of_scope = _clean_text(proposal.get("out_of_scope")) or "Any work beyond the bounded Guild Orders proposal."
    constraints = tuple(_unique_strings([reason, *codex_implications]))
    lineage_family_id = f"GOFAMILY__{_slugify(title).upper()}"
    dungeon_specs = _normalize_dungeon_specs(
        data_root=data_root,
        proposal=proposal,
        title=title,
        objective=objective,
        coherent_outcome=coherent_outcome,
        closure_statement=closure_statement,
        verification_plan=verification_plan,
        out_of_scope=out_of_scope,
        constraints=constraints,
        evidence=evidence,
        blockers=blockers,
        explicit_dungeon_specs=explicit_dungeon_specs,
    )
    return GuildOrdersPacket(
        proposal_id=proposal_id,
        subject=subject,
        title=title,
        summary=summary,
        objective=objective,
        coherent_outcome=coherent_outcome,
        closure_statement=closure_statement,
        out_of_scope=out_of_scope,
        constraints=constraints,
        verification_plan=verification_plan,
        evidence=evidence,
        blockers=blockers,
        codex_implications=codex_implications,
        lineage_family_id=lineage_family_id,
        dungeon_specs=dungeon_specs,
    )


def classify_guild_orders_revision(
    *,
    existing_packet: GuildOrdersPacket,
    incoming_packet: GuildOrdersPacket,
    operation: GuildOrdersOperation | str = GuildOrdersOperation.REVISE_PAUSED,
) -> GuildOrdersRevisionClass:
    op = _coerce_operation(operation)
    if op == GuildOrdersOperation.CREATE_PAUSED:
        return GuildOrdersRevisionClass.CREATE
    if op in {
        GuildOrdersOperation.START_ACTIVE,
        GuildOrdersOperation.PAUSE_ACTIVE,
        GuildOrdersOperation.COMPLETE_ORDERS,
    }:
        return GuildOrdersRevisionClass.STATE_TRANSITION

    material_fields = (
        existing_packet.title != incoming_packet.title
        or existing_packet.summary != incoming_packet.summary
        or existing_packet.objective != incoming_packet.objective
        or existing_packet.coherent_outcome != incoming_packet.coherent_outcome
        or existing_packet.closure_statement != incoming_packet.closure_statement
        or existing_packet.out_of_scope != incoming_packet.out_of_scope
        or existing_packet.constraints != incoming_packet.constraints
        or _dungeon_material_signature(existing_packet.dungeon_specs) != _dungeon_material_signature(incoming_packet.dungeon_specs)
    )
    return GuildOrdersRevisionClass.MATERIAL_SCOPE_CHANGE if material_fields else GuildOrdersRevisionClass.EDITORIAL


def execute_guild_orders_operation(
    *,
    data_root: Path,
    packet: GuildOrdersPacket,
    requested_operation: GuildOrdersOperation | str = GuildOrdersOperation.CREATE_PAUSED,
    supporting_receipt_refs: Iterable[str] = (),
    source_artifact_path: str | Path | None = None,
    existing_packet: GuildOrdersPacket | None = None,
) -> GuildOrdersMutationResult:
    operation = _coerce_operation(requested_operation)
    world_state = derive_world_state(data_root).value
    receipt_refs = tuple(_normalize_evidence(data_root, supporting_receipt_refs))
    source_path = _resolve_source_path(data_root, source_artifact_path)
    state_before = _state_from_path(source_path, data_root)

    if operation == GuildOrdersOperation.CREATE_PAUSED:
        orders_id = _next_orders_id(data_root, packet.title)
        destination = _orders_state_dir(data_root, GuildOrdersState.PAUSED) / f"{orders_id}.txt"
        _write_orders_artifact(
            path=destination,
            packet=packet,
            orders_id=orders_id,
            state=GuildOrdersState.PAUSED,
            operation=operation,
            revision_class=GuildOrdersRevisionClass.CREATE,
            source_artifact_path=None,
            supporting_receipt_refs=receipt_refs,
        )
        return GuildOrdersMutationResult(
            ok=True,
            operation=operation,
            revision_class=GuildOrdersRevisionClass.CREATE,
            world_state=world_state,
            state_before=None,
            state_after=GuildOrdersState.PAUSED.value,
            source_artifact_path=None,
            destination_artifact_path=str(destination),
            lineage_family_id=packet.lineage_family_id,
            orders_id=orders_id,
            supporting_receipt_refs=receipt_refs,
        )

    if source_path is None:
        return _blocked(
            operation=operation,
            revision_class=GuildOrdersRevisionClass.BLOCKED,
            world_state=world_state,
            lineage_family_id=packet.lineage_family_id,
            supporting_receipt_refs=receipt_refs,
            blocked_reason="missing_source_artifact_path",
        )

    if operation == GuildOrdersOperation.REVISE_PAUSED:
        if state_before != GuildOrdersState.PAUSED.value:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.BLOCKED,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=f"source_artifact_not_paused:{state_before or 'unknown'}",
            )
        if existing_packet is None:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.BLOCKED,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason="existing_packet_required_for_revision",
            )
        revision_class = classify_guild_orders_revision(
            existing_packet=existing_packet,
            incoming_packet=packet,
            operation=operation,
        )
        if revision_class == GuildOrdersRevisionClass.MATERIAL_SCOPE_CHANGE:
            missing_reason = _require_control_sync_receipts(data_root, receipt_refs)
            if missing_reason is not None:
                return _blocked(
                    operation=operation,
                    revision_class=revision_class,
                    world_state=world_state,
                    lineage_family_id=packet.lineage_family_id,
                    source_artifact_path=str(source_path),
                    supporting_receipt_refs=receipt_refs,
                    blocked_reason=missing_reason,
                )
        orders_id = _extract_orders_id(source_path)
        _write_orders_artifact(
            path=source_path,
            packet=packet,
            orders_id=orders_id,
            state=GuildOrdersState.PAUSED,
            operation=operation,
            revision_class=revision_class,
            source_artifact_path=str(source_path),
            supporting_receipt_refs=receipt_refs,
        )
        return GuildOrdersMutationResult(
            ok=True,
            operation=operation,
            revision_class=revision_class,
            world_state=world_state,
            state_before=GuildOrdersState.PAUSED.value,
            state_after=GuildOrdersState.PAUSED.value,
            source_artifact_path=str(source_path),
            destination_artifact_path=str(source_path),
            lineage_family_id=packet.lineage_family_id,
            orders_id=orders_id,
            supporting_receipt_refs=receipt_refs,
        )

    if operation == GuildOrdersOperation.START_ACTIVE:
        if world_state == WorldState.FOG_OF_WAR.value:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason="fog_of_war_blocks_active_transition",
            )
        if state_before != GuildOrdersState.PAUSED.value:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=f"source_artifact_not_paused:{state_before or 'unknown'}",
            )
        missing_reason = _require_transition_receipts(data_root, receipt_refs)
        if missing_reason is not None:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=missing_reason,
            )
        destination = _orders_state_dir(data_root, GuildOrdersState.ACTIVE) / source_path.name
        _move_orders_artifact(source_path, destination)
        return GuildOrdersMutationResult(
            ok=True,
            operation=operation,
            revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
            world_state=world_state,
            state_before=GuildOrdersState.PAUSED.value,
            state_after=GuildOrdersState.ACTIVE.value,
            source_artifact_path=str(source_path),
            destination_artifact_path=str(destination),
            lineage_family_id=packet.lineage_family_id,
            orders_id=_extract_orders_id(destination),
            supporting_receipt_refs=receipt_refs,
        )

    if operation == GuildOrdersOperation.PAUSE_ACTIVE:
        if state_before != GuildOrdersState.ACTIVE.value:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=f"source_artifact_not_active:{state_before or 'unknown'}",
            )
        missing_reason = _require_transition_receipts(data_root, receipt_refs)
        if missing_reason is not None:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=missing_reason,
            )
        destination = _orders_state_dir(data_root, GuildOrdersState.PAUSED) / source_path.name
        _move_orders_artifact(source_path, destination)
        return GuildOrdersMutationResult(
            ok=True,
            operation=operation,
            revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
            world_state=world_state,
            state_before=GuildOrdersState.ACTIVE.value,
            state_after=GuildOrdersState.PAUSED.value,
            source_artifact_path=str(source_path),
            destination_artifact_path=str(destination),
            lineage_family_id=packet.lineage_family_id,
            orders_id=_extract_orders_id(destination),
            supporting_receipt_refs=receipt_refs,
        )

    if operation == GuildOrdersOperation.COMPLETE_ORDERS:
        if state_before not in {GuildOrdersState.PAUSED.value, GuildOrdersState.ACTIVE.value}:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=f"source_artifact_not_completable:{state_before or 'unknown'}",
            )
        missing_reason = _require_transition_receipts(data_root, receipt_refs)
        if missing_reason is not None:
            return _blocked(
                operation=operation,
                revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
                world_state=world_state,
                lineage_family_id=packet.lineage_family_id,
                source_artifact_path=str(source_path),
                supporting_receipt_refs=receipt_refs,
                blocked_reason=missing_reason,
            )
        destination = _orders_state_dir(data_root, GuildOrdersState.COMPLETED) / source_path.name
        _move_orders_artifact(source_path, destination)
        return GuildOrdersMutationResult(
            ok=True,
            operation=operation,
            revision_class=GuildOrdersRevisionClass.STATE_TRANSITION,
            world_state=world_state,
            state_before=state_before,
            state_after=GuildOrdersState.COMPLETED.value,
            source_artifact_path=str(source_path),
            destination_artifact_path=str(destination),
            lineage_family_id=packet.lineage_family_id,
            orders_id=_extract_orders_id(destination),
            supporting_receipt_refs=receipt_refs,
        )

    return _blocked(
        operation=GuildOrdersOperation.BLOCK,
        revision_class=GuildOrdersRevisionClass.BLOCKED,
        world_state=world_state,
        lineage_family_id=packet.lineage_family_id,
        supporting_receipt_refs=receipt_refs,
        blocked_reason=f"unsupported_operation:{operation.value}",
    )


def formalize_guild_orders_from_proposal(
    *,
    subject: str,
    data_root: Path,
    proposal: dict[str, Any],
    topic: str | None = None,
) -> dict[str, Any]:
    packet = normalize_guild_orders_packet(
        subject=subject,
        data_root=data_root,
        proposal=proposal,
        topic=topic,
    )
    result = execute_guild_orders_operation(
        data_root=data_root,
        packet=packet,
        requested_operation=GuildOrdersOperation.CREATE_PAUSED,
    )
    if not result.ok:
        raise LiveMemoryError(result.blocked_reason or "Guild Orders formalization blocked.")
    return {
        "artifact_path": result.destination_artifact_path,
        "orders_id": result.orders_id,
        "operation_receipt": result.to_dict(),
        "lineage_family_id": packet.lineage_family_id,
    }


def _normalize_dungeon_specs(
    *,
    data_root: Path,
    proposal: dict[str, Any],
    title: str,
    objective: str,
    coherent_outcome: str,
    closure_statement: str,
    verification_plan: str,
    out_of_scope: str,
    constraints: tuple[str, ...],
    evidence: tuple[str, ...],
    blockers: tuple[str, ...],
    explicit_dungeon_specs: Iterable[dict[str, Any]] | None,
) -> tuple[GuildOrdersDungeonSpec, ...]:
    if explicit_dungeon_specs:
        normalized: list[GuildOrdersDungeonSpec] = []
        for idx, raw in enumerate(explicit_dungeon_specs, start=1):
            if not isinstance(raw, dict):
                raise LiveMemoryError(f"Invalid dungeon spec at position {idx}.")
            dungeon_id = _clean_text(raw.get("dungeon_id")) or f"DUNGEON_{idx:02d}"
            dungeon_title = _clean_text(raw.get("title")) or _clean_text(raw.get("objective")) or title
            dungeon_objective = _clean_text(raw.get("objective")) or objective
            dungeon_outcome = _clean_text(raw.get("coherent_outcome")) or coherent_outcome
            dungeon_closure = _clean_text(raw.get("closure_statement")) or closure_statement
            dungeon_verification = _clean_text(raw.get("verification_plan")) or verification_plan
            dungeon_out_of_scope = _clean_text(raw.get("out_of_scope")) or out_of_scope
            if not all((dungeon_title, dungeon_objective, dungeon_outcome, dungeon_closure, dungeon_verification)):
                raise LiveMemoryError(f"Dungeon spec {dungeon_id} is missing required fields.")
            dungeon_constraints = tuple(
                _unique_strings(str(item) for item in raw.get("constraints") or constraints if str(item).strip())
            ) or constraints
            dungeon_evidence = tuple(
                _normalize_evidence(data_root, raw.get("evidence") or evidence)
            ) or evidence
            dungeon_blockers = tuple(
                _unique_strings(str(item) for item in raw.get("blockers") or blockers if str(item).strip())
            )
            normalized.append(
                GuildOrdersDungeonSpec(
                    dungeon_id=dungeon_id,
                    title=dungeon_title,
                    objective=dungeon_objective,
                    coherent_outcome=dungeon_outcome,
                    closure_statement=dungeon_closure,
                    out_of_scope=dungeon_out_of_scope,
                    constraints=dungeon_constraints,
                    verification_plan=dungeon_verification,
                    evidence=dungeon_evidence,
                    blockers=dungeon_blockers,
                )
            )
        return tuple(normalized)

    return (
        GuildOrdersDungeonSpec(
            dungeon_id="DUNGEON_01",
            title=title,
            objective=objective,
            coherent_outcome=coherent_outcome,
            closure_statement=closure_statement,
            out_of_scope=out_of_scope,
            constraints=constraints,
            verification_plan=verification_plan,
            evidence=evidence,
            blockers=blockers,
        ),
    )


def _require_scalar(proposal: dict[str, Any], key: str) -> str:
    value = _clean_text(proposal.get(key))
    if not value:
        raise LiveMemoryError(f"Guild Orders proposal missing required field: {key}")
    return value


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _coerce_operation(value: GuildOrdersOperation | str) -> GuildOrdersOperation:
    if isinstance(value, GuildOrdersOperation):
        return value
    return GuildOrdersOperation(str(value))


def _normalize_evidence(data_root: Path, values: Iterable[Any]) -> list[str]:
    return _unique_strings(_normalize_relpaths(data_root, [str(item) for item in values if str(item).strip()]))


def _dungeon_material_signature(specs: tuple[GuildOrdersDungeonSpec, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (
            spec.dungeon_id,
            spec.title,
            spec.objective,
            spec.coherent_outcome,
            spec.closure_statement,
            spec.out_of_scope,
            "\n".join(spec.constraints),
        )
        for spec in specs
    )


def _orders_state_dir(data_root: Path, state: GuildOrdersState) -> Path:
    path = data_root / "Guild Orders" / state.value
    path.mkdir(parents=True, exist_ok=True)
    return path


def _next_orders_id(data_root: Path, title: str) -> str:
    today = today_toronto().replace("-", "")
    base = f"GO-{today}-{_slugify(title)}"
    existing_names = {
        path.name
        for state in GuildOrdersState
        for path in _orders_state_dir(data_root, state).glob("*.txt")
        if path.is_file()
    }
    if f"{base}.txt" not in existing_names:
        return base
    index = 2
    while True:
        candidate = f"{base}-{index:02d}"
        if f"{candidate}.txt" not in existing_names:
            return candidate
        index += 1


def _render_labeled_block(label: str, value: str) -> list[str]:
    raw = str(value or "").rstrip()
    if not raw:
        return [f"{label}:", ""]
    if "\n" not in raw:
        return [f"{label}: {raw}", ""]
    lines = [f"{label}:"]
    lines.extend(raw.splitlines())
    lines.append("")
    return lines


def _bullet_block(values: Iterable[str], *, empty: str = "- none") -> str:
    normalized = _unique_strings(str(item) for item in values if str(item).strip())
    if not normalized:
        return empty
    return "\n".join(f"- {item}" for item in normalized)


def _write_orders_artifact(
    *,
    path: Path,
    packet: GuildOrdersPacket,
    orders_id: str,
    state: GuildOrdersState,
    operation: GuildOrdersOperation,
    revision_class: GuildOrdersRevisionClass,
    source_artifact_path: str | None,
    supporting_receipt_refs: tuple[str, ...],
) -> None:
    lines: list[str] = [
        "GUILD ORDERS — SYNAPSE",
        "Version: v2.0",
        "Status: Generated Guild Orders Artifact",
        "",
        "=" * 80,
        "IDENTITY",
        "=" * 80,
    ]
    lines.extend(_render_labeled_block("Guild Orders ID", orders_id))
    lines.extend(_render_labeled_block("Subject", packet.subject))
    lines.extend(_render_labeled_block("Orders State", state.value))
    lines.extend(_render_labeled_block("Operation Class", operation.value))
    lines.extend(_render_labeled_block("Revision Class", revision_class.value))
    lines.extend(_render_labeled_block("Lineage Family ID", packet.lineage_family_id))
    lines.extend(_render_labeled_block("Source Proposal ID", packet.proposal_id))
    lines.extend(_render_labeled_block("Created At", f"{today_toronto()} 00:00 (America/Toronto)"))
    lines.extend(_render_labeled_block("Updated At", f"{today_toronto()} 00:00 (America/Toronto)"))
    lines.extend(_render_labeled_block("Source Artifact Path", source_artifact_path or "N/A"))
    lines.extend(_render_labeled_block("Destination Artifact Path", str(path)))

    lines.extend(
        [
            "=" * 80,
            "ORDERS",
            "=" * 80,
        ]
    )
    lines.extend(_render_labeled_block("Title", packet.title))
    lines.extend(_render_labeled_block("Scope Statement", packet.summary))
    lines.extend(_render_labeled_block("Raid Coherent Outcome", packet.coherent_outcome))
    lines.extend(_render_labeled_block("Raid Done Definition", packet.closure_statement))
    lines.extend(_render_labeled_block("Out of Scope", packet.out_of_scope))
    lines.extend(_render_labeled_block("Constraints", _bullet_block(packet.constraints)))
    lines.extend(_render_labeled_block("Verification Plan", packet.verification_plan))
    lines.extend(_render_labeled_block("Evidence", _bullet_block(packet.evidence)))
    lines.extend(_render_labeled_block("Blockers / Review", _bullet_block(packet.blockers)))

    lines.extend(
        [
            "=" * 80,
            "DUNGEONS",
            "=" * 80,
        ]
    )
    lines.extend(_render_labeled_block("Dungeon Count", str(len(packet.dungeon_specs))))
    for spec in packet.dungeon_specs:
        lines.extend(_render_labeled_block("Dungeon ID", spec.dungeon_id))
        lines.extend(_render_labeled_block("Dungeon Title", spec.title))
        lines.extend(_render_labeled_block("Dungeon Objective", spec.objective))
        lines.extend(_render_labeled_block("Dungeon Coherent Outcome", spec.coherent_outcome))
        lines.extend(_render_labeled_block("Dungeon Done Definition", spec.closure_statement))
        lines.extend(_render_labeled_block("Dungeon Out of Scope", spec.out_of_scope))
        lines.extend(_render_labeled_block("Dungeon Constraints", _bullet_block(spec.constraints)))
        lines.extend(_render_labeled_block("Dungeon Verification Plan", spec.verification_plan))
        lines.extend(_render_labeled_block("Dungeon Evidence", _bullet_block(spec.evidence)))
        lines.extend(_render_labeled_block("Dungeon Blockers / Review", _bullet_block(spec.blockers)))

    lines.extend(
        [
            "=" * 80,
            "LINEAGE / GATES",
            "=" * 80,
        ]
    )
    lines.extend(_render_labeled_block("Supporting Receipt Refs", _bullet_block(supporting_receipt_refs)))
    lines.extend(_render_labeled_block("World State At Write", derive_world_state(path.parents[2]).value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _resolve_source_path(data_root: Path, source_artifact_path: str | Path | None) -> Path | None:
    if source_artifact_path is None:
        return None
    raw = Path(source_artifact_path).expanduser()
    resolved = raw if raw.is_absolute() else (data_root / raw)
    return resolved.resolve()


def _state_from_path(path: Path | None, data_root: Path) -> str | None:
    if path is None:
        return None
    try:
        relative = path.resolve().relative_to((data_root / "Guild Orders").resolve())
    except Exception:
        return None
    parts = relative.parts
    if not parts:
        return None
    head = parts[0].upper()
    if head in {GuildOrdersState.PAUSED.value, GuildOrdersState.ACTIVE.value, GuildOrdersState.COMPLETED.value}:
        return head
    return None


def _require_control_sync_receipts(data_root: Path, refs: tuple[str, ...]) -> str | None:
    if not refs:
        return "missing_control_sync_receipt_refs"
    for ref in refs:
        name = Path(ref).name.upper()
        if "CONTROL" not in name:
            continue
        if "SYNC" not in name and "SNAPSHOT" not in name:
            continue
        resolved = _resolve_source_path(data_root, ref)
        if resolved is not None and resolved.exists():
            return None
    return "missing_control_sync_snapshot_receipt"


def _require_transition_receipts(data_root: Path, refs: tuple[str, ...]) -> str | None:
    if not refs:
        return "missing_state_transition_receipt_refs"
    for ref in refs:
        resolved = _resolve_source_path(data_root, ref)
        if resolved is not None and resolved.exists():
            return None
    return "missing_existing_state_transition_receipt"


def _move_orders_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise LiveMemoryError(f"Destination Guild Orders artifact already exists: {destination}")
    shutil.move(str(source), str(destination))


def _blocked(
    *,
    operation: GuildOrdersOperation,
    revision_class: GuildOrdersRevisionClass,
    world_state: str,
    lineage_family_id: str,
    supporting_receipt_refs: tuple[str, ...],
    blocked_reason: str,
    source_artifact_path: str | None = None,
) -> GuildOrdersMutationResult:
    return GuildOrdersMutationResult(
        ok=False,
        operation=operation,
        revision_class=revision_class,
        world_state=world_state,
        state_before=None,
        state_after=None,
        source_artifact_path=source_artifact_path,
        destination_artifact_path=None,
        lineage_family_id=lineage_family_id,
        orders_id=None,
        supporting_receipt_refs=supporting_receipt_refs,
        blocked_reason=blocked_reason,
    )


def _extract_orders_id(path: Path) -> str:
    return path.stem

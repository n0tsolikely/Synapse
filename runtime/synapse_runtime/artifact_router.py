"""Governance-aware artifact-family routing for continuity boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.automation_orchestrator import automation_policy_for_context
from synapse_runtime.draftshots import draftshot_summary, load_active_draftshot
from synapse_runtime.governance_model import AmbientSignal, PromotionRecord, ProposalKind, ProposalState, WorldState, derive_world_state, evaluate_promotion
from synapse_runtime.publication_candidates import PUBLICATION_CANDIDATE_KINDS, publication_candidate_summary
from synapse_runtime.session_modes import SessionMode, policy_for
from synapse_runtime.sidecar_store import live_root
from synapse_runtime.snapshot_candidates import CONTROL_SYNC_KIND, EOD_KIND, SNAPSHOT_CANDIDATE_KINDS, snapshot_candidate_summary


SNAPSHOT_TARGET_FAMILY = "snapshot_candidate"
PUBLICATION_TARGET_FAMILY = "publication_candidate"
QUEST_TARGET_FAMILY = "quest_candidate"
GOVERNANCE_PROPOSAL_TARGET_FAMILY = "governance_proposal"
BLOCKED_TARGET_FAMILY = "blocked"
NOOP_TARGET_FAMILY = "noop"

SNAPSHOT_DISPATCH_KEY = "refresh_snapshot_candidate_boundary"
PUBLICATION_DISPATCH_KEY = "refresh_publication_candidate_boundary"
QUEST_DISPATCH_KEY = "upsert_quest_candidate_from_promotion"
GOVERNANCE_PROPOSAL_DISPATCH_KEY = "upsert_operational_proposal_from_promotion"
BLOCKED_DISPATCH_KEY = "blocked"
NOOP_DISPATCH_KEY = "noop"

QUEST_PROMOTION_KINDS = {ProposalKind.QUEST, ProposalKind.SIDE_QUEST}
SUPPORTED_OPERATIONAL_PROPOSAL_KINDS = {
    ProposalKind.GUILD_ORDERS,
    ProposalKind.CODEX,
    ProposalKind.BUILD_MANUAL,
    ProposalKind.DISCLOSURE,
    ProposalKind.CONTROL_SYNC,
    ProposalKind.TALENT,
}
UNSUPPORTED_OWNER_FAMILIES = {"execution_pack"}

TARGET_OWNERS = {
    SNAPSHOT_TARGET_FAMILY: "runtime/synapse_runtime/snapshot_candidates.py",
    PUBLICATION_TARGET_FAMILY: "runtime/synapse_runtime/publication_candidates.py",
    QUEST_TARGET_FAMILY: "runtime/synapse_runtime/quest_candidates.py",
    GOVERNANCE_PROPOSAL_TARGET_FAMILY: "runtime/synapse_runtime/quest_candidates.py",
    BLOCKED_TARGET_FAMILY: "unresolved",
    NOOP_TARGET_FAMILY: "none",
}

INTENT_PRIORITY = {
    "record_disclosure": 10,
    "open_obligation": 20,
    "refresh_snapshot_candidate": 30,
    "refresh_publication_candidate": 40,
    "upsert_quest_candidate": 50,
    "upsert_governance_proposal": 60,
    "blocked_missing_owner": 70,
    "blocked_gate": 80,
    "no_op": 90,
}


@dataclass(frozen=True)
class ArtifactRoutingGateSummary:
    world_state: str
    onboarding_required: bool
    onboarding_requirement_reason: str | None
    session_mode: str | None
    manual_formalize_allowed: bool
    quest_acceptance_allowed: bool
    canonical_mutation_allowed: bool
    candidate_mutation_allowed: bool
    proposal_mutation_allowed: bool
    guild_orders_active_allowed: bool
    codex_publication_allowed: bool
    blocked_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactRoutingIntent:
    intent_kind: str
    target_family: str
    target_owner: str
    target_posture: str
    dispatch_key: str
    required_prerequisites: tuple[str, ...] = ()
    blocking_reason: str | None = None
    supporting_evidence_refs: tuple[dict[str, Any], ...] = ()
    receipt_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supporting_evidence_refs"] = [dict(item) for item in self.supporting_evidence_refs]
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ArtifactRoutingContext:
    subject: str
    trigger: str
    boundary: str | None
    invoke_reason: str
    data_root: str
    engine_root: str | None
    summary: str | None
    notes: tuple[str, ...]
    changed_files: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]
    observer_action_kinds: tuple[str, ...]
    active_run: dict[str, Any]
    accepted_context: dict[str, Any]
    session_mode: str | None
    world_state: str
    automation_policy: dict[str, Any]
    session_policy: dict[str, Any] | None
    snapshot_candidate_kinds: tuple[str, ...]
    publication_candidate_kinds: tuple[str, ...]
    requested_missing_owner_families: tuple[str, ...]
    target_day: str | None
    prefer_latest_active_draftshot: bool
    obligation_fallback: bool
    import_profile: dict[str, Any]
    current_active_refs: tuple[dict[str, Any], ...]
    draftshot_summary: dict[str, Any]
    snapshot_candidate_summary: dict[str, Any]
    publication_candidate_summary: dict[str, Any]
    promotion_payloads: tuple[dict[str, Any], ...]
    envelope_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = [dict(item) for item in self.source_refs]
        payload["current_active_refs"] = [dict(item) for item in self.current_active_refs]
        payload["promotion_payloads"] = [dict(item) for item in self.promotion_payloads]
        return payload


@dataclass(frozen=True)
class ArtifactRoutingResult:
    trigger: str
    boundary: str | None
    invoke_reason: str
    envelope_fingerprint: str
    gates: ArtifactRoutingGateSummary
    intents: tuple[ArtifactRoutingIntent, ...]
    status: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "boundary": self.boundary,
            "invoke_reason": self.invoke_reason,
            "envelope_fingerprint": self.envelope_fingerprint,
            "gates": self.gates.to_dict(),
            "intents": [intent.to_dict() for intent in self.intents],
            "status": self.status,
            "notes": list(self.notes),
        }


def _read_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _normalize_texts(items: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item or "").split()).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_refs(items: Iterable[dict[str, Any]] | None) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items or ():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        ref_id = str(item.get("id") or "").strip()
        path = str(item.get("path") or item.get("body_path") or "").strip()
        key = (kind, ref_id, path)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return tuple(normalized)


def _current_active_refs(
    *,
    accepted_context: dict[str, Any],
    snapshot_summary: dict[str, Any],
    publication_summary: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    refs: list[dict[str, Any]] = []
    current_accepted = str(accepted_context.get("current_accepted_quest_id") or "").strip()
    if current_accepted:
        refs.append({"kind": "accepted_quest", "id": current_accepted})
    for kind, path in (
        ("snapshot_eod_candidate", snapshot_summary.get("current_eod_candidate_path")),
        ("snapshot_control_sync_candidate", snapshot_summary.get("current_control_sync_candidate_path")),
        ("publication_story_candidate", publication_summary.get("current_story_candidate_path")),
        ("publication_vision_candidate", publication_summary.get("current_vision_candidate_path")),
    ):
        text = str(path or "").strip()
        if text:
            refs.append({"kind": kind, "path": text})
    for path in publication_summary.get("current_codex_candidate_paths") or []:
        text = str(path or "").strip()
        if text:
            refs.append({"kind": "publication_codex_candidate", "path": text})
    for order_id in accepted_context.get("active_order_ids") or []:
        text = str(order_id or "").strip()
        if text:
            refs.append({"kind": "active_order_candidate", "id": text})
    return tuple(refs)


def _snapshot_candidate_required_kinds(*, data_root: Path, active_run: dict[str, Any]) -> tuple[str, ...]:
    session_id = str(active_run.get("session_id") or "").strip()
    run_id = str(active_run.get("run_id") or "").strip()
    has_session_anchor = bool(session_id or run_id or load_active_draftshot(data_root, session_id=None) is not None)
    if not has_session_anchor:
        return ()

    manifold = _read_yaml_dict(live_root(data_root) / "MANIFOLD.yaml")

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
    return tuple(required)


def _build_signal(
    *,
    trigger: str,
    subject: str,
    summary: str | None,
    notes: tuple[str, ...],
    changed_files: tuple[str, ...],
) -> AmbientSignal | None:
    if not any((summary, notes, changed_files)):
        return None
    return AmbientSignal(
        source=trigger,
        subject=subject,
        title=summary,
        summary=summary,
        notes=notes,
        files_touched=changed_files,
    )


def promotion_record_to_payload(record: PromotionRecord) -> dict[str, Any]:
    return {
        "kind": record.kind.value,
        "state": record.state.value,
        "title": record.title,
        "summary": record.summary,
        "reason": record.reason,
        "blockers": list(record.blockers),
        "evidence": list(record.evidence),
        "codex_implications": list(record.codex_implications),
    }


def promotion_record_from_payload(payload: dict[str, Any]) -> PromotionRecord:
    return PromotionRecord(
        kind=ProposalKind(str(payload.get("kind") or "")),
        state=ProposalState(str(payload.get("state") or "ambient")),
        title=str(payload.get("title") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
        blockers=tuple(str(item) for item in payload.get("blockers") or [] if str(item).strip()),
        evidence=tuple(str(item) for item in payload.get("evidence") or [] if str(item).strip()),
        codex_implications=tuple(str(item) for item in payload.get("codex_implications") or [] if str(item).strip()),
    )


def build_artifact_routing_context(
    *,
    subject: str,
    data_root: Path,
    trigger: str,
    invoke_reason: str,
    active_run: dict[str, Any] | None,
    accepted_context: dict[str, Any] | None,
    summary: str | None = None,
    notes: Iterable[str] | None = None,
    changed_files: Iterable[str] | None = None,
    source_refs: Iterable[dict[str, Any]] | None = None,
    observer_action_kinds: Iterable[str] | None = None,
    requested_snapshot_kinds: Iterable[str] | None = None,
    requested_publication_candidate_kinds: Iterable[str] | None = None,
    requested_missing_owner_families: Iterable[str] | None = None,
    boundary: str | None = None,
    target_day: str | None = None,
    prefer_latest_active_draftshot: bool = False,
    obligation_fallback: bool = True,
    import_profile: dict[str, Any] | None = None,
    engine_root: Path | None = None,
) -> ArtifactRoutingContext:
    data_root = data_root.resolve()
    active_run_payload = dict(active_run or {})
    accepted_payload = dict(accepted_context or {})
    notes_tuple = _normalize_texts(notes or [])
    changed_files_tuple = _normalize_texts(changed_files or [])
    source_ref_tuple = _normalize_refs(source_refs)
    observer_actions = _normalize_texts(observer_action_kinds or [])
    automation_policy = automation_policy_for_context(data_root=data_root)
    world_state = derive_world_state(data_root).value
    session_mode = str(active_run_payload.get("session_mode") or "").strip() or None
    session_policy = None
    if session_mode:
        try:
            session_policy = policy_for(SessionMode(session_mode))
        except Exception:
            session_policy = None

    signal = _build_signal(
        trigger=trigger,
        subject=subject,
        summary=summary,
        notes=notes_tuple,
        changed_files=changed_files_tuple,
    )
    promotions = list(evaluate_promotion(signal, data_root)) if signal is not None else []
    typed_snapshot_candidates_enabled = (live_root(data_root) / "SNAPSHOT_CANDIDATES").exists()
    if typed_snapshot_candidates_enabled:
        promotions = [promotion for promotion in promotions if promotion.kind != ProposalKind.SNAPSHOT]
    if session_policy is not None:
        allowed = set(session_policy.allowed_proposal_kinds)
        promotions = [promotion for promotion in promotions if promotion.kind in allowed]

    snapshot_summary = snapshot_candidate_summary(data_root)
    publication_summary = publication_candidate_summary(data_root)
    if requested_snapshot_kinds is None:
        snapshot_kinds = _snapshot_candidate_required_kinds(data_root=data_root, active_run=active_run_payload)
    else:
        snapshot_kinds = tuple(str(kind).strip().upper() for kind in requested_snapshot_kinds if str(kind).strip())
    publication_kinds = tuple(
        str(kind).strip().upper() for kind in (requested_publication_candidate_kinds or ()) if str(kind).strip()
    )
    missing_owner_families = tuple(
        str(item).strip().lower() for item in (requested_missing_owner_families or ()) if str(item).strip()
    )
    draftshot_state = draftshot_summary(data_root)
    current_refs = _current_active_refs(
        accepted_context=accepted_payload,
        snapshot_summary=snapshot_summary,
        publication_summary=publication_summary,
    )
    promotion_payloads = tuple(promotion_record_to_payload(item) for item in promotions)

    fingerprint_source = {
        "trigger": trigger,
        "boundary": boundary,
        "invoke_reason": invoke_reason,
        "summary": summary or "",
        "notes": list(notes_tuple),
        "changed_files": list(changed_files_tuple),
        "source_refs": [dict(item) for item in source_ref_tuple],
        "observer_action_kinds": list(observer_actions),
        "session_mode": session_mode,
        "world_state": world_state,
        "onboarding_required": automation_policy.onboarding_required,
        "snapshot_candidate_kinds": list(snapshot_kinds),
        "publication_candidate_kinds": list(publication_kinds),
        "requested_missing_owner_families": list(missing_owner_families),
        "target_day": target_day,
        "promotions": list(promotion_payloads),
        "current_active_refs": [dict(item) for item in current_refs],
        "current_snapshot_candidate_path": snapshot_summary.get("current_snapshot_candidate_path"),
        "current_story_candidate_path": publication_summary.get("current_story_candidate_path"),
        "current_codex_candidate_paths": list(publication_summary.get("current_codex_candidate_paths") or []),
    }
    envelope_fingerprint = hashlib.sha1(
        json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return ArtifactRoutingContext(
        subject=subject,
        trigger=trigger,
        boundary=boundary,
        invoke_reason=invoke_reason,
        data_root=str(data_root),
        engine_root=str(engine_root.resolve()) if engine_root is not None else None,
        summary=summary,
        notes=notes_tuple,
        changed_files=changed_files_tuple,
        source_refs=source_ref_tuple,
        observer_action_kinds=observer_actions,
        active_run=active_run_payload,
        accepted_context=accepted_payload,
        session_mode=session_mode,
        world_state=world_state,
        automation_policy={
            "adopted_existing_repo": automation_policy.adopted_existing_repo,
            "onboarding_required": automation_policy.onboarding_required,
            "onboarding_requirement_reason": automation_policy.onboarding_requirement_reason,
            "onboarding_confirmed": automation_policy.onboarding_confirmed,
            "project_identity_ready": automation_policy.project_identity_ready,
            "continuity_ready": automation_policy.continuity_ready,
            "automation_status": automation_policy.automation_status,
            "automation_pending_gate": automation_policy.automation_pending_gate,
            "current_onboarding_id": automation_policy.current_onboarding_id,
            "latest_confirmed_onboarding_id": automation_policy.latest_confirmed_onboarding_id,
            "missing_publication_fields": list(automation_policy.missing_publication_fields),
        },
        session_policy={
            "mode": session_policy.mode.value,
            "manual_formalize_allowed": session_policy.manual_formalize_allowed,
            "quest_acceptance_allowed": session_policy.quest_acceptance_allowed,
            "blocked_mutation_commands": list(session_policy.blocked_mutation_commands),
            "allowed_proposal_kinds": [item.value for item in session_policy.allowed_proposal_kinds],
        }
        if session_policy is not None
        else None,
        snapshot_candidate_kinds=snapshot_kinds,
        publication_candidate_kinds=publication_kinds,
        requested_missing_owner_families=missing_owner_families,
        target_day=target_day,
        prefer_latest_active_draftshot=prefer_latest_active_draftshot,
        obligation_fallback=obligation_fallback,
        import_profile=dict(import_profile or {}),
        current_active_refs=current_refs,
        draftshot_summary=draftshot_state,
        snapshot_candidate_summary=snapshot_summary,
        publication_candidate_summary=publication_summary,
        promotion_payloads=promotion_payloads,
        envelope_fingerprint=envelope_fingerprint,
    )


def _evaluate_gates(context: ArtifactRoutingContext) -> ArtifactRoutingGateSummary:
    automation_policy = dict(context.automation_policy or {})
    session_policy = dict(context.session_policy or {})
    session_mode = context.session_mode
    onboarding_required = bool(automation_policy.get("onboarding_required"))
    world_state = context.world_state
    manual_formalize_allowed = bool(session_policy.get("manual_formalize_allowed"))
    quest_acceptance_allowed = bool(session_policy.get("quest_acceptance_allowed")) and world_state == WorldState.FOG_LIFTED.value and not onboarding_required
    canonical_mutation_allowed = manual_formalize_allowed and world_state == WorldState.FOG_LIFTED.value and not onboarding_required
    proposal_mutation_allowed = bool(session_policy) and session_mode != SessionMode.ONBOARDING_EXISTING_REPO.value and not onboarding_required
    candidate_mutation_allowed = True
    guild_orders_active_allowed = world_state == WorldState.FOG_LIFTED.value and not onboarding_required
    codex_publication_allowed = canonical_mutation_allowed

    blocked_reasons: list[str] = []
    if onboarding_required:
        blocked_reasons.append(
            f"onboarding_required:{automation_policy.get('onboarding_requirement_reason') or 'project_identity_not_confirmed'}"
        )
    if world_state != WorldState.FOG_LIFTED.value:
        blocked_reasons.append("world_state:fog_of_war")
    if session_mode == SessionMode.ONBOARDING_EXISTING_REPO.value:
        blocked_reasons.append("session_mode:onboarding_existing_repo")

    return ArtifactRoutingGateSummary(
        world_state=world_state,
        onboarding_required=onboarding_required,
        onboarding_requirement_reason=str(automation_policy.get("onboarding_requirement_reason") or "").strip() or None,
        session_mode=session_mode,
        manual_formalize_allowed=manual_formalize_allowed,
        quest_acceptance_allowed=quest_acceptance_allowed,
        canonical_mutation_allowed=canonical_mutation_allowed,
        candidate_mutation_allowed=candidate_mutation_allowed,
        proposal_mutation_allowed=proposal_mutation_allowed,
        guild_orders_active_allowed=guild_orders_active_allowed,
        codex_publication_allowed=codex_publication_allowed,
        blocked_reasons=tuple(blocked_reasons),
    )


def _intent(
    *,
    intent_kind: str,
    target_family: str,
    target_posture: str,
    dispatch_key: str,
    supporting_evidence_refs: tuple[dict[str, Any], ...],
    metadata: dict[str, Any] | None = None,
    required_prerequisites: Iterable[str] | None = None,
    blocking_reason: str | None = None,
    receipt_fields: Iterable[str] | None = None,
) -> ArtifactRoutingIntent:
    return ArtifactRoutingIntent(
        intent_kind=intent_kind,
        target_family=target_family,
        target_owner=TARGET_OWNERS[target_family],
        target_posture=target_posture,
        dispatch_key=dispatch_key,
        required_prerequisites=tuple(required_prerequisites or ()),
        blocking_reason=blocking_reason,
        supporting_evidence_refs=supporting_evidence_refs,
        receipt_fields=tuple(receipt_fields or ()),
        metadata=dict(metadata or {}),
    )


def evaluate_artifact_routing(context: ArtifactRoutingContext) -> ArtifactRoutingResult:
    gates = _evaluate_gates(context)
    intents: list[ArtifactRoutingIntent] = []
    evidence_refs = tuple(context.source_refs)

    if context.snapshot_candidate_kinds:
        if gates.candidate_mutation_allowed:
            intents.append(
                _intent(
                    intent_kind="refresh_snapshot_candidate",
                    target_family=SNAPSHOT_TARGET_FAMILY,
                    target_posture="candidate",
                    dispatch_key=SNAPSHOT_DISPATCH_KEY,
                    supporting_evidence_refs=evidence_refs,
                    metadata={
                        "candidate_kinds": list(context.snapshot_candidate_kinds),
                        "target_day": context.target_day,
                        "prefer_latest_active_draftshot": context.prefer_latest_active_draftshot,
                        "obligation_fallback": context.obligation_fallback,
                    },
                    required_prerequisites=("candidate_mutation_allowed",),
                    receipt_fields=("boundary", "summary", "snapshot_candidates", "projection"),
                )
            )
        else:
            intents.append(
                _intent(
                    intent_kind="blocked_gate",
                    target_family=BLOCKED_TARGET_FAMILY,
                    target_posture="blocked",
                    dispatch_key=BLOCKED_DISPATCH_KEY,
                    supporting_evidence_refs=evidence_refs,
                    metadata={"requested_family": SNAPSHOT_TARGET_FAMILY, "candidate_kinds": list(context.snapshot_candidate_kinds)},
                    blocking_reason="candidate_mutation_not_allowed",
                    required_prerequisites=("candidate_mutation_allowed",),
                    receipt_fields=("blocking_reason",),
                )
            )

    if context.publication_candidate_kinds:
        if gates.candidate_mutation_allowed:
            intents.append(
                _intent(
                    intent_kind="refresh_publication_candidate",
                    target_family=PUBLICATION_TARGET_FAMILY,
                    target_posture="candidate",
                    dispatch_key=PUBLICATION_DISPATCH_KEY,
                    supporting_evidence_refs=evidence_refs,
                    metadata={"candidate_kinds": list(context.publication_candidate_kinds)},
                    required_prerequisites=("candidate_mutation_allowed",),
                    receipt_fields=("boundary", "summary", "publication_candidates", "projection"),
                )
            )
        else:
            intents.append(
                _intent(
                    intent_kind="blocked_gate",
                    target_family=BLOCKED_TARGET_FAMILY,
                    target_posture="blocked",
                    dispatch_key=BLOCKED_DISPATCH_KEY,
                    supporting_evidence_refs=evidence_refs,
                    metadata={"requested_family": PUBLICATION_TARGET_FAMILY, "candidate_kinds": list(context.publication_candidate_kinds)},
                    blocking_reason="candidate_mutation_not_allowed",
                    required_prerequisites=("candidate_mutation_allowed",),
                    receipt_fields=("blocking_reason",),
                )
            )

    for promotion_payload in context.promotion_payloads:
        promotion_kind = ProposalKind(str(promotion_payload.get("kind") or ""))
        if promotion_kind in QUEST_PROMOTION_KINDS:
            if gates.proposal_mutation_allowed:
                intents.append(
                    _intent(
                        intent_kind="upsert_quest_candidate",
                        target_family=QUEST_TARGET_FAMILY,
                        target_posture="candidate",
                        dispatch_key=QUEST_DISPATCH_KEY,
                        supporting_evidence_refs=evidence_refs,
                        metadata={"promotion": dict(promotion_payload)},
                        required_prerequisites=("proposal_mutation_allowed",),
                        receipt_fields=("proposal_id", "path", "status"),
                    )
                )
            else:
                intents.append(
                    _intent(
                        intent_kind="blocked_gate",
                        target_family=BLOCKED_TARGET_FAMILY,
                        target_posture="blocked",
                        dispatch_key=BLOCKED_DISPATCH_KEY,
                        supporting_evidence_refs=evidence_refs,
                        metadata={"requested_family": QUEST_TARGET_FAMILY, "promotion": dict(promotion_payload)},
                        blocking_reason="proposal_mutation_not_allowed",
                        required_prerequisites=("proposal_mutation_allowed",),
                        receipt_fields=("blocking_reason",),
                    )
                )
            continue

        if promotion_kind in SUPPORTED_OPERATIONAL_PROPOSAL_KINDS:
            if gates.proposal_mutation_allowed:
                intents.append(
                    _intent(
                        intent_kind="upsert_governance_proposal",
                        target_family=GOVERNANCE_PROPOSAL_TARGET_FAMILY,
                        target_posture="proposal",
                        dispatch_key=GOVERNANCE_PROPOSAL_DISPATCH_KEY,
                        supporting_evidence_refs=evidence_refs,
                        metadata={"promotion": dict(promotion_payload), "proposal_kind": promotion_kind.value},
                        required_prerequisites=("proposal_mutation_allowed",),
                        receipt_fields=("proposal_id", "path", "status"),
                    )
                )
            else:
                intents.append(
                    _intent(
                        intent_kind="blocked_gate",
                        target_family=BLOCKED_TARGET_FAMILY,
                        target_posture="blocked",
                        dispatch_key=BLOCKED_DISPATCH_KEY,
                        supporting_evidence_refs=evidence_refs,
                        metadata={"requested_family": GOVERNANCE_PROPOSAL_TARGET_FAMILY, "promotion": dict(promotion_payload)},
                        blocking_reason="proposal_mutation_not_allowed",
                        required_prerequisites=("proposal_mutation_allowed",),
                        receipt_fields=("blocking_reason",),
                    )
                )

    for family in context.requested_missing_owner_families:
        if family not in UNSUPPORTED_OWNER_FAMILIES:
            continue
        intents.append(
            _intent(
                intent_kind="blocked_missing_owner",
                target_family=BLOCKED_TARGET_FAMILY,
                target_posture="blocked",
                dispatch_key=BLOCKED_DISPATCH_KEY,
                supporting_evidence_refs=evidence_refs,
                metadata={"requested_family": family},
                blocking_reason=f"missing_owner:{family}",
                required_prerequisites=("downstream_owner_exists",),
                receipt_fields=("blocking_reason",),
            )
        )

    if not intents:
        intents = [
            _intent(
                intent_kind="no_op",
                target_family=NOOP_TARGET_FAMILY,
                target_posture="noop",
                dispatch_key=NOOP_DISPATCH_KEY,
                supporting_evidence_refs=evidence_refs,
                metadata={"reason": "no_routable_artifact_family"},
                receipt_fields=("reason",),
            )
        ]

    intents.sort(key=lambda item: (INTENT_PRIORITY.get(item.intent_kind, 999), item.target_family, item.dispatch_key))

    status = "planned"
    if all(intent.dispatch_key == NOOP_DISPATCH_KEY for intent in intents):
        status = "noop"
    elif all(intent.dispatch_key == BLOCKED_DISPATCH_KEY for intent in intents):
        status = "blocked"

    return ArtifactRoutingResult(
        trigger=context.trigger,
        boundary=context.boundary,
        invoke_reason=context.invoke_reason,
        envelope_fingerprint=context.envelope_fingerprint,
        gates=gates,
        intents=tuple(intents),
        status=status,
        notes=(
            f"intent_count={len(intents)}",
            f"snapshot_candidate_kinds={','.join(context.snapshot_candidate_kinds) or 'none'}",
            f"publication_candidate_kinds={','.join(context.publication_candidate_kinds) or 'none'}",
        ),
    )

"""Governed promotion of normalized semantic events into durable working records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.continuity_obligations import obligation_summary, open_obligation, resolve_matching_obligations
from synapse_runtime.kernel_types import (
    GovernedRecordFamily,
    GovernedWorkingRecordEnvelope,
    SemanticEventEnvelope,
    stable_kernel_id,
)
from synapse_runtime.lineage_store import build_lineage_edge, lineage_summary, load_lineage_edges, persist_lineage_edges
from synapse_runtime.quest_plans import list_plan_artifacts, load_execution_plan, persist_execution_plan


WORKING_RECORD_SCHEMA_VERSION = 1
_HIGH_SIGNAL_TOPICS = {
    "build.plan",
    "project.scope",
    "architecture.shape",
    "decision.locked",
    "risk.blocker",
    "execution.error",
    "project.vision",
}

_ARCHITECTURE_PIVOT_CUES = (
    "rejecting",
    "rejected",
    "reject ",
    "instead",
    "now ",
    "pivot",
    "switch",
    "moving to",
    "move to",
    "no longer",
)

_DISCLOSURE_REVIEW_CUES = (
    "unsafe",
    "cannot safely",
    "can't safely",
    "not safe to claim",
    "unsafe to claim",
    "cannot claim",
    "can't claim",
)


class PromotionEngineError(RuntimeError):
    """Raised when semantic promotion cannot proceed safely."""


def governed_root(data_root: Path) -> Path:
    return data_root / ".synapse"


def working_record_dirs(data_root: Path) -> dict[str, Path]:
    root = governed_root(data_root)
    return {
        GovernedRecordFamily.INTENT_FRAGMENT.value: root / GovernedRecordFamily.INTENT_FRAGMENT.value,
        GovernedRecordFamily.SCOPE_CAMPAIGN.value: root / GovernedRecordFamily.SCOPE_CAMPAIGN.value,
        GovernedRecordFamily.QUEST_LINK.value: root / GovernedRecordFamily.QUEST_LINK.value,
        GovernedRecordFamily.DECISION_GRAPH.value: root / GovernedRecordFamily.DECISION_GRAPH.value,
        GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value: root / GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value,
        GovernedRecordFamily.FAILURE_CHAIN.value: root / GovernedRecordFamily.FAILURE_CHAIN.value,
        GovernedRecordFamily.NARRATIVE_CLAIM.value: root / GovernedRecordFamily.NARRATIVE_CLAIM.value,
        GovernedRecordFamily.PROJECT_IDENTITY_CLAIM.value: root / GovernedRecordFamily.PROJECT_IDENTITY_CLAIM.value,
        GovernedRecordFamily.IMPORTED_EVIDENCE.value: root / GovernedRecordFamily.IMPORTED_EVIDENCE.value,
    }


def ensure_working_record_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    for path in working_record_dirs(data_root).values():
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.resolve()))
    return created


def record_filename(*, family: str, record_id: str, title: str) -> str:
    safe_title = "-".join(str(title or record_id).strip().lower().split())[:64] or "record"
    return f"{family}__{record_id}__{safe_title}.yaml"


def _normalize_semantic_event(event: SemanticEventEnvelope | dict[str, Any]) -> dict[str, Any]:
    return event.to_dict() if isinstance(event, SemanticEventEnvelope) else dict(event)


def _event_title(event: dict[str, Any]) -> str:
    return str(event.get("summary") or event.get("topic_key") or event.get("semantic_event_id") or "record").strip()


def _family_id(subject: str, family: str, event: dict[str, Any]) -> str:
    source_bits = sorted(str(item) for item in event.get("source_segment_ids") or [] if str(item).strip())
    semantic_bits = sorted(str(item) for item in event.get("source_semantic_event_ids") or [] if str(item).strip())
    if not source_bits and not semantic_bits:
        semantic_bits = [str(event.get("semantic_event_id") or "")]
    return stable_kernel_id(
        "FAMILY",
        subject,
        family,
        "|".join(source_bits),
        "|".join(semantic_bits),
        event.get("topic_key"),
        _event_title(event),
    )


def _record_id(subject: str, family: str, event: dict[str, Any]) -> str:
    return stable_kernel_id(
        "REC",
        subject,
        family,
        str(event.get("semantic_event_id") or ""),
        _event_title(event),
    )


def _record_path(data_root: Path, family: str, record_id: str, title: str) -> Path:
    directory = working_record_dirs(data_root).get(family)
    if directory is None:
        raise PromotionEngineError(f"Unknown governed working-record family: {family}")
    return directory / record_filename(family=family, record_id=record_id, title=title)


def persist_working_record(data_root: Path, record: GovernedWorkingRecordEnvelope | dict[str, Any]) -> dict[str, Any]:
    payload = record.to_dict() if isinstance(record, GovernedWorkingRecordEnvelope) else dict(record)
    family = str(payload.get("family") or "").strip()
    record_id = str(payload.get("record_id") or "").strip()
    if not family or not record_id:
        raise PromotionEngineError("Governed working record is missing family or record_id.")
    path = _record_path(data_root, family, record_id, str(payload.get("title") or payload.get("summary") or record_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(payload)
            payload = merged
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {**payload, "path": str(path.resolve())}


def load_working_records(data_root: Path, family: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    dirs = working_record_dirs(data_root)
    selected = {family: dirs[family]} if family else dirs
    for family_name, directory in selected.items():
        if not directory.exists():
            continue
        for path in sorted(directory.glob(f"{family_name}__*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload["path"] = str(path.resolve())
                records.append(payload)
    return records


def _is_identity_like(summary: str) -> bool:
    lowered = str(summary or "").lower()
    return any(token in lowered for token in ("become", "platform", "system", "product", "business", "app"))


def _event_relation_name(family: str) -> str:
    return {
        GovernedRecordFamily.SCOPE_CAMPAIGN.value: "scopes",
        GovernedRecordFamily.DECISION_GRAPH.value: "locks_decision",
        GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value: "describes_architecture",
        GovernedRecordFamily.FAILURE_CHAIN.value: "records_failure",
        GovernedRecordFamily.NARRATIVE_CLAIM.value: "captures_narrative",
        GovernedRecordFamily.PROJECT_IDENTITY_CLAIM.value: "captures_identity",
        GovernedRecordFamily.IMPORTED_EVIDENCE.value: "captures_imported_evidence",
        GovernedRecordFamily.INTENT_FRAGMENT.value: "captures_intent",
    }.get(family, "supports")


def _make_record(
    *,
    subject: str,
    recorded_at: str,
    family: str,
    event: dict[str, Any],
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return GovernedWorkingRecordEnvelope(
        record_id=_record_id(subject, family, event),
        schema_version=WORKING_RECORD_SCHEMA_VERSION,
        recorded_at=recorded_at,
        subject=subject,
        family=family,
        family_id=_family_id(subject, family, event),
        title=_event_title(event),
        summary=str(event.get("summary") or "").strip(),
        detail=str(detail or event.get("summary") or "").strip(),
        confidence_band=str(event.get("confidence_band") or "low").strip(),
        materiality_band=str(event.get("materiality_band") or "low").strip(),
        source_segment_ids=[str(item) for item in event.get("source_segment_ids") or [] if str(item).strip()],
        source_semantic_event_ids=[str(event.get("semantic_event_id") or "").strip()],
        source_refs=[dict(item) for item in event.get("source_refs") or [] if isinstance(item, dict)],
        related_paths=[str(item) for item in event.get("related_paths") or [] if str(item).strip()],
        status="active",
        metadata=dict(metadata or {}),
    ).to_dict()


def _group_key(event: dict[str, Any]) -> tuple[str, ...]:
    source_ids = tuple(sorted(str(item) for item in event.get("source_segment_ids") or [] if str(item).strip()))
    if source_ids:
        return source_ids
    semantic_id = str(event.get("semantic_event_id") or "").strip()
    return (semantic_id,) if semantic_id else (stable_kernel_id("GROUP", event.get("topic_key"), event.get("summary")),)


def _group_events(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(_group_key(event), []).append(event)
    return list(groups.values())


def _group_recorded_at(events: list[dict[str, Any]]) -> str:
    for event in events:
        text = str(event.get("recorded_at") or "").strip()
        if text:
            return text
    return ""


def _is_imported_event(event: dict[str, Any]) -> bool:
    return bool(event.get("imported_source")) or bool(event.get("imported_limited"))


def _non_imported_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if not _is_imported_event(event)]


def _group_topics(events: list[dict[str, Any]]) -> list[str]:
    return sorted({str(event.get("topic_key") or "").strip() for event in events if str(event.get("topic_key") or "").strip()})


def _high_signal_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if str(event.get("topic_key") or "").strip() in _HIGH_SIGNAL_TOPICS
        and str(event.get("materiality_band") or "").strip().lower() == "high"
        and not bool(event.get("transient_noise"))
    ]


def _latest_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda item: (
            str(item.get("recorded_at") or ""),
            str(item.get("path") or ""),
        ),
    )[-1]


def _architecture_shift_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("topic_key") or "") != "architecture.shape":
            continue
        summary = str(event.get("summary") or "").lower()
        if any(cue in summary for cue in _ARCHITECTURE_PIVOT_CUES):
            return event
    return None


def _needs_disclosure_review(event: dict[str, Any]) -> bool:
    topic_key = str(event.get("topic_key") or "")
    if topic_key not in {"risk.blocker", "execution.error"}:
        return False
    summary = str(event.get("summary") or "").lower()
    return any(cue in summary for cue in _DISCLOSURE_REVIEW_CUES)


def _find_latest_plan_for_family(data_root: Path, family_id: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for path in list_plan_artifacts(data_root):
        payload = load_execution_plan(path)
        if str(payload.get("lineage_family_id") or "").strip() != family_id:
            continue
        if latest is None or int(payload.get("revision_number") or 0) > int(latest.get("revision_number") or 0):
            latest = payload
    return latest


def _persist_plan_revision(
    *,
    subject: str,
    data_root: Path,
    recorded_at: str,
    events: list[dict[str, Any]],
    scope_record_ids: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    plan_events = [event for event in events if str(event.get("topic_key") or "") == "build.plan" and not _is_imported_event(event)]
    if not plan_events:
        return None, None
    primary = plan_events[0]
    support_events = [event for event in events if str(event.get("topic_key") or "") in {"project.scope", "architecture.shape", "decision.locked"} and not _is_imported_event(event)]
    summary = str(primary.get("summary") or "").strip()
    support = str((support_events[0].get("summary") if support_events else summary) or summary).strip()
    family_id = stable_kernel_id(
        "PLANFAM",
        subject,
        summary,
        support,
    )
    prior = _find_latest_plan_for_family(data_root, family_id)
    incoming_segment_ids = sorted({str(seg) for event in events for seg in event.get("source_segment_ids") or [] if str(seg).strip()})
    incoming_event_ids = sorted({str(event.get("semantic_event_id") or "").strip() for event in events if str(event.get("semantic_event_id") or "").strip()})
    incoming_refs = [ref for event in events for ref in event.get("source_refs") or [] if isinstance(ref, dict)]
    incoming_topics = _group_topics(events)
    incoming_scope_refs = sorted({str(item) for item in scope_record_ids if str(item).strip()})
    if prior is not None:
        unchanged = (
            sorted(prior.get("source_segment_ids") or []) == incoming_segment_ids
            and sorted(prior.get("source_semantic_event_ids") or []) == incoming_event_ids
            and sorted(prior.get("semantic_topics") or []) == incoming_topics
            and sorted(prior.get("scope_campaign_refs") or []) == incoming_scope_refs
            and str(prior.get("summary") or "").strip() == summary
        )
        if unchanged:
            return prior, None

    milestones = [summary]
    if support and support != summary:
        milestones.append(support)
    plan = persist_execution_plan(
        subject=subject,
        data_root=data_root,
        title=summary,
        summary=summary,
        origin="engaged-semantic",
        objective=support,
        coherent_outcome=support,
        closure_statement="Refine and close this plan through the governed quest/runtime flow.",
        out_of_scope="Unspecified until a later governed scope split or quest acceptance clarifies it.",
        dependencies=[],
        risk="R1",
        verification_plan="Refine verification during quest planning or explicit review before execution.",
        milestones=milestones,
        split_triggers=["Split if later work reveals multiple independently closable outcomes."],
        links=[str(ref.get("path") or "").strip() for ref in incoming_refs if str(ref.get("path") or "").strip()],
        related_run_ids=[],
        source_segment_ids=incoming_segment_ids,
        source_semantic_event_ids=incoming_event_ids,
        source_refs=incoming_refs,
        lineage_family_id=family_id,
        semantic_topics=incoming_topics,
        scope_campaign_refs=incoming_scope_refs,
        plan_metadata={
            "promotion_origin": "phase2_semantic_promotion",
            "recorded_at": recorded_at,
        },
        plan_id=str(prior.get("plan_id") or "").strip() if prior is not None else None,
    )
    return plan, prior


def _persist_records_for_topics(
    *,
    subject: str,
    data_root: Path,
    recorded_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    mapping = (
        ("project.scope", GovernedRecordFamily.SCOPE_CAMPAIGN.value),
        ("decision.locked", GovernedRecordFamily.DECISION_GRAPH.value),
        ("architecture.shape", GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value),
        ("risk.blocker", GovernedRecordFamily.FAILURE_CHAIN.value),
        ("execution.error", GovernedRecordFamily.FAILURE_CHAIN.value),
        ("project.vision", GovernedRecordFamily.NARRATIVE_CLAIM.value),
    )
    for topic_key, family in mapping:
        for event in events:
            if str(event.get("topic_key") or "") != topic_key or _is_imported_event(event):
                continue
            promoted.append(
                persist_working_record(
                    data_root,
                    _make_record(
                        subject=subject,
                        recorded_at=recorded_at,
                        family=family,
                        event=event,
                        metadata={"promotion_origin": "phase2_semantic_promotion", "topic_key": topic_key},
                    ),
                )
            )
    identity_candidates = [
        event for event in events
        if str(event.get("topic_key") or "") in {"project.scope", "project.vision"}
        and not _is_imported_event(event)
        and _is_identity_like(str(event.get("summary") or ""))
    ]
    if identity_candidates:
        event = identity_candidates[0]
        promoted.append(
            persist_working_record(
                data_root,
                _make_record(
                    subject=subject,
                    recorded_at=recorded_at,
                    family=GovernedRecordFamily.PROJECT_IDENTITY_CLAIM.value,
                    event=event,
                    metadata={"promotion_origin": "phase2_semantic_promotion", "identity_like": True},
                ),
            )
        )
    return promoted


def _persist_imported_record(*, subject: str, data_root: Path, recorded_at: str, event: dict[str, Any]) -> dict[str, Any]:
    parser_status = str(event.get("import_parser_status") or "limited").strip().lower() or "limited"
    imported_confidence_band = str(event.get("import_confidence_band") or event.get("confidence_band") or "low").strip().lower() or "low"
    requires_review = bool(event.get("import_requires_review")) or parser_status in {"limited", "unsupported"} or imported_confidence_band == "low"
    return persist_working_record(
        data_root,
        _make_record(
            subject=subject,
            recorded_at=recorded_at,
            family=GovernedRecordFamily.IMPORTED_EVIDENCE.value,
            event=event,
            metadata={
                "promotion_origin": "phase4_imported_continuity",
                "imported_source": True,
                "imported_limited": bool(event.get("imported_limited")),
                "parser_status": parser_status,
                "imported_confidence_band": imported_confidence_band,
                "requires_import_review": requires_review,
                "import_source_kind": str(event.get("import_source_kind") or "").strip() or None,
                "import_id": str(event.get("import_id") or "").strip() or None,
                "draftshot_eligible": parser_status != "unsupported",
                "snapshot_candidate_eligible": parser_status == "parsed" and imported_confidence_band in {"medium", "high"},
                "publication_candidate_eligible": parser_status == "parsed" and imported_confidence_band in {"medium", "high"},
                "contradiction_refs": list(event.get("import_contradiction_refs") or []),
            },
        ),
    )


def promote_semantic_events(
    *,
    subject: str,
    data_root: Path,
    semantic_events: Iterable[SemanticEventEnvelope | dict[str, Any]],
) -> dict[str, Any]:
    ensure_working_record_scaffold(data_root)
    events = [_normalize_semantic_event(item) for item in semantic_events if not bool(_normalize_semantic_event(item).get("transient_noise"))]
    if not events:
        return {
            "plan_revisions": [],
            "promoted_records": [],
            "lineage_edges": [],
            "opened_obligations": [],
            "resolved_obligations": [],
        }

    plan_revisions: list[dict[str, Any]] = []
    promoted_records: list[dict[str, Any]] = []
    lineage_edges: list[dict[str, Any]] = []
    opened_obligations: list[dict[str, Any]] = []
    resolved_obligations: list[dict[str, Any]] = []

    for group in _group_events(events):
        recorded_at = _group_recorded_at(group)
        non_imported = _non_imported_events(group)
        created_for_group: list[dict[str, Any]] = []
        prior_architecture_records = load_working_records(data_root, GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value)

        imported_events = [event for event in group if _is_imported_event(event)]
        if imported_events:
            imported_record = _persist_imported_record(subject=subject, data_root=data_root, recorded_at=recorded_at, event=imported_events[0])
            created_for_group.append(imported_record)
            promoted_records.append(imported_record)
            if bool(imported_record.get("metadata", {}).get("requires_import_review")):
                opened_obligations.append(
                    open_obligation(
                        subject=subject,
                        data_root=data_root,
                        recorded_at=recorded_at,
                        obligation_kind="import.review.required",
                        severity="warn",
                        summary="Imported continuity was preserved with limited confidence and requires human review before stronger governed promotion.",
                        required_record_families=[GovernedRecordFamily.IMPORTED_EVIDENCE.value],
                        source_segment_ids=imported_events[0].get("source_segment_ids") or [],
                        source_semantic_event_ids=[imported_events[0].get("semantic_event_id")],
                        source_refs=imported_events[0].get("source_refs") or [],
                        metadata={
                            "topic_key": imported_events[0].get("topic_key"),
                            "parser_status": imported_record.get("metadata", {}).get("parser_status"),
                            "confidence_band": imported_record.get("metadata", {}).get("imported_confidence_band"),
                            "contradiction_refs": list(imported_record.get("metadata", {}).get("contradiction_refs") or []),
                        },
                    )
                )
            lineage_edges.append(
                build_lineage_edge(
                    subject=subject,
                    recorded_at=recorded_at,
                    source_kind="semantic_event",
                    source_id=str(imported_events[0].get("semantic_event_id") or ""),
                    target_kind="imported_evidence",
                    target_id=str(imported_record.get("record_id") or ""),
                    relation="captures_imported_evidence",
                ).to_dict()
            )

        scope_record_ids: list[str] = []
        for record in _persist_records_for_topics(subject=subject, data_root=data_root, recorded_at=recorded_at, events=non_imported):
            created_for_group.append(record)
            promoted_records.append(record)
            if str(record.get("family") or "") == GovernedRecordFamily.SCOPE_CAMPAIGN.value:
                scope_record_ids.append(str(record.get("record_id") or ""))
            resolved_obligations.extend(
                resolve_matching_obligations(
                    data_root=data_root,
                    recorded_at=recorded_at,
                    source_segment_ids=record.get("source_segment_ids") or [],
                    source_semantic_event_ids=record.get("source_semantic_event_ids") or [],
                    resolution_record_ids=[str(record.get("record_id") or "")],
                )
            )

        plan, prior_plan = _persist_plan_revision(
            subject=subject,
            data_root=data_root,
            recorded_at=recorded_at,
            events=non_imported,
            scope_record_ids=scope_record_ids,
        )
        if plan is not None:
            plan_revisions.append(plan)
            resolved_obligations.extend(
                resolve_matching_obligations(
                    data_root=data_root,
                    recorded_at=recorded_at,
                    source_segment_ids=plan.get("source_segment_ids") or [],
                    source_semantic_event_ids=plan.get("source_semantic_event_ids") or [],
                    resolution_record_ids=[str(plan.get("revision_id") or "")],
                    obligation_kinds=["plan.capture.required", "promotion.review.required"],
                )
            )
            if prior_plan is not None and str(prior_plan.get("revision_id") or "").strip() != str(plan.get("revision_id") or "").strip():
                lineage_edges.append(
                    build_lineage_edge(
                        subject=subject,
                        recorded_at=recorded_at,
                        source_kind="plan_revision",
                        source_id=str(prior_plan.get("revision_id") or ""),
                        target_kind="plan_revision",
                        target_id=str(plan.get("revision_id") or ""),
                        relation="supersedes",
                    ).to_dict()
                )
            for scope_id in scope_record_ids:
                lineage_edges.append(
                    build_lineage_edge(
                        subject=subject,
                        recorded_at=recorded_at,
                        source_kind="scope_campaign",
                        source_id=scope_id,
                        target_kind="plan_revision",
                        target_id=str(plan.get("revision_id") or plan.get("plan_id") or ""),
                        relation="scopes",
                    ).to_dict()
                )
            for event in non_imported:
                for segment_id in event.get("source_segment_ids") or []:
                    lineage_edges.append(
                        build_lineage_edge(
                            subject=subject,
                            recorded_at=recorded_at,
                            source_kind="conversation_segment",
                            source_id=str(segment_id),
                            target_kind="plan_revision",
                            target_id=str(plan.get("revision_id") or plan.get("plan_id") or ""),
                            relation="supports",
                        ).to_dict()
                    )
                lineage_edges.append(
                    build_lineage_edge(
                        subject=subject,
                        recorded_at=recorded_at,
                        source_kind="semantic_event",
                        source_id=str(event.get("semantic_event_id") or ""),
                        target_kind="plan_revision",
                        target_id=str(plan.get("revision_id") or plan.get("plan_id") or ""),
                        relation="promoted_to_plan",
                    ).to_dict()
                )
        elif any(str(event.get("topic_key") or "") == "build.plan" for event in non_imported):
            build_event = next(event for event in non_imported if str(event.get("topic_key") or "") == "build.plan")
            opened_obligations.append(
                open_obligation(
                    subject=subject,
                    data_root=data_root,
                    recorded_at=recorded_at,
                    obligation_kind="plan.capture.required",
                    severity="blocker",
                    summary="High-signal build-plan conversation did not result in a lawful persisted plan revision.",
                    required_record_families=[GovernedRecordFamily.SCOPE_CAMPAIGN.value],
                    source_segment_ids=build_event.get("source_segment_ids") or [],
                    source_semantic_event_ids=[build_event.get("semantic_event_id")],
                    source_refs=build_event.get("source_refs") or [],
                    metadata={"topic_key": build_event.get("topic_key")},
                )
            )

        for record in created_for_group:
            family = str(record.get("family") or "")
            relation = _event_relation_name(family)
            for event in non_imported:
                lineage_edges.append(
                    build_lineage_edge(
                        subject=subject,
                        recorded_at=recorded_at,
                        source_kind="semantic_event",
                        source_id=str(event.get("semantic_event_id") or ""),
                        target_kind=family.lower(),
                        target_id=str(record.get("record_id") or ""),
                        relation=relation,
                    ).to_dict()
                )

        architecture_record = next(
            (record for record in created_for_group if str(record.get("family") or "") == GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value),
            None,
        )
        architecture_shift = _architecture_shift_event(non_imported)
        latest_prior_architecture = _latest_record(
            [
                item
                for item in prior_architecture_records
                if str(item.get("record_id") or "").strip() != str((architecture_record or {}).get("record_id") or "").strip()
            ]
        )
        if architecture_record is not None and architecture_shift is not None and latest_prior_architecture is not None:
            lineage_edges.append(
                build_lineage_edge(
                    subject=subject,
                    recorded_at=recorded_at,
                    source_kind="governed_working_record",
                    source_id=str(latest_prior_architecture.get("record_id") or ""),
                    target_kind="governed_working_record",
                    target_id=str(architecture_record.get("record_id") or ""),
                    relation="supersedes",
                    metadata={"reason": "architecture_pivot"},
                ).to_dict()
            )
            opened_obligations.append(
                open_obligation(
                    subject=subject,
                    data_root=data_root,
                    recorded_at=recorded_at,
                    obligation_kind="architecture.review.required",
                    severity="warn",
                    summary="Architecture meaning shifted and requires review before stronger canon or execution claims.",
                    required_record_families=[GovernedRecordFamily.ARCHITECTURE_EVOLUTION.value],
                    source_segment_ids=architecture_shift.get("source_segment_ids") or [],
                    source_semantic_event_ids=[str(architecture_shift.get("semantic_event_id") or "")],
                    source_refs=architecture_shift.get("source_refs") or [],
                    metadata={
                        "prior_record_id": latest_prior_architecture.get("record_id"),
                        "new_record_id": architecture_record.get("record_id"),
                        "topic_key": architecture_shift.get("topic_key"),
                    },
                )
            )

        for event in non_imported:
            if not _needs_disclosure_review(event):
                continue
            opened_obligations.append(
                open_obligation(
                    subject=subject,
                    data_root=data_root,
                    recorded_at=recorded_at,
                    obligation_kind="disclosure.review.required",
                    severity="warn",
                    summary="Unsafe blocker language requires disclosure-aware review before stronger claims continue.",
                    required_record_families=[GovernedRecordFamily.FAILURE_CHAIN.value],
                    source_segment_ids=event.get("source_segment_ids") or [],
                    source_semantic_event_ids=[str(event.get("semantic_event_id") or "")],
                    source_refs=event.get("source_refs") or [],
                    metadata={"topic_key": event.get("topic_key")},
                )
            )

        if _high_signal_events(non_imported) and not created_for_group and plan is None:
            seed = _high_signal_events(non_imported)[0]
            opened_obligations.append(
                open_obligation(
                    subject=subject,
                    data_root=data_root,
                    recorded_at=recorded_at,
                    obligation_kind="promotion.review.required",
                    severity="warn",
                    summary="High-signal engaged work produced no lawful durable governed record and needs review.",
                    required_record_families=[],
                    source_segment_ids=seed.get("source_segment_ids") or [],
                    source_semantic_event_ids=[seed.get("semantic_event_id")],
                    source_refs=seed.get("source_refs") or [],
                    metadata={"topic_key": seed.get("topic_key")},
                )
            )

    persisted_edges = persist_lineage_edges(data_root, lineage_edges)
    return {
        "plan_revisions": plan_revisions,
        "promoted_records": promoted_records,
        "lineage_edges": persisted_edges,
        "opened_obligations": opened_obligations,
        "resolved_obligations": resolved_obligations,
    }


def promotion_summary(data_root: Path) -> dict[str, Any]:
    records = load_working_records(data_root)
    by_family: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for record in records:
        family = str(record.get("family") or "unknown")
        by_family[family] = by_family.get(family, 0) + 1
        recent.append(
            {
                "record_id": record.get("record_id"),
                "family": family,
                "summary": record.get("summary"),
                "path": record.get("path"),
            }
        )
    plans = [load_execution_plan(path) for path in list_plan_artifacts(data_root)]
    latest_plan = plans[-1] if plans else None
    obligations = obligation_summary(data_root)
    lineage = lineage_summary(data_root)
    return {
        "working_record_count": len(records),
        "working_record_family_counts": by_family,
        "recent_working_record_details": recent[-10:],
        "active_scope_campaign_ids": [
            str(item.get("record_id"))
            for item in records
            if str(item.get("family") or "") == GovernedRecordFamily.SCOPE_CAMPAIGN.value
        ][-10:],
        "last_governed_record_id": recent[-1]["record_id"] if recent else None,
        "recent_plan_revision_details": [
            {
                "plan_id": item.get("plan_id"),
                "revision_id": item.get("revision_id"),
                "summary": item.get("summary"),
                "path": item.get("path"),
            }
            for item in plans[-10:]
        ],
        "last_plan_revision_id": latest_plan.get("revision_id") if latest_plan else None,
        "last_plan_revision_path": latest_plan.get("path") if latest_plan else None,
        **lineage,
        **obligations,
    }

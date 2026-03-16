"""Quest and side-quest candidate shaping for the live sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from synapse_runtime.accepted_execution_view import find_quest_file
from synapse_runtime.governance_model import AmbientSignal, PromotionRecord, ProposalKind, ProposalState
from synapse_runtime.live_memory_common import (
    LiveMemoryError,
    _is_terminal_status,
    _slugify,
    _tokenize_text,
    _tokens_overlap,
    _unique_strings,
)
from synapse_runtime.quest_board import DEFAULT_REPO_ORIENTATION_BLOCKER, draft_quest_from_proposal
from synapse_runtime.sidecar_store import _now_iso, _read_yaml, _write_yaml, live_root


QUEST_PROPOSAL_KINDS = {ProposalKind.QUEST, ProposalKind.SIDE_QUEST}
QUEST_STATE_RANK = {
    ProposalState.AMBIENT.value: 0,
    ProposalState.DRAFT.value: 1,
    ProposalState.PROPOSED.value: 2,
    ProposalState.READY.value: 3,
    ProposalState.FORMALIZED.value: 4,
}


def _proposal_dir(live: Path, kind: ProposalKind) -> Path:
    mapping = {
        ProposalKind.QUEST: live / "PROPOSALS" / "quests",
        ProposalKind.SIDE_QUEST: live / "PROPOSALS" / "side_quests",
        ProposalKind.SNAPSHOT: live / "PROPOSALS" / "snapshots",
        ProposalKind.CONTROL_SYNC: live / "PROPOSALS" / "control_sync",
        ProposalKind.GUILD_ORDERS: live / "PROPOSALS" / "guild_orders",
        ProposalKind.CODEX: live / "PROPOSALS" / "codex",
        ProposalKind.BUILD_MANUAL: live / "PROPOSALS" / "build_manual",
        ProposalKind.TALENT: live / "PROPOSALS" / "talent",
        ProposalKind.DISCLOSURE: live / "PROPOSALS" / "disclosures",
    }
    return mapping[kind]


def _proposal_id(kind: ProposalKind, source_id: str, title: str) -> str:
    return f"{kind.value.upper()}__{source_id}__{_slugify(title)}".upper().replace("-", "_")


def _proposal_path(live: Path, kind: ProposalKind, proposal_id: str) -> Path:
    return _proposal_dir(live, kind) / f"{proposal_id}.yaml"


def _open_plan_items(active_run: dict[str, Any]) -> list[str]:
    plan = active_run.get("plan", {})
    if not isinstance(plan, dict):
        return []
    items = plan.get("items")
    if not isinstance(items, list):
        return []
    open_items: list[str] = []
    closed_items: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if _is_terminal_status(str(item.get("status") or "")):
            closed_items.append(text)
        else:
            open_items.append(text)
    return open_items or closed_items[:1]


def _top_level_scope_tokens(paths: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    for raw in paths:
        text = str(raw).strip()
        if not text:
            continue
        path = Path(text)
        token = path.name if path.is_absolute() else (path.parts[0] if path.parts else text)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _candidate_title(signal: AmbientSignal, active_run: dict[str, Any]) -> str:
    plan_items = _open_plan_items(active_run)
    if plan_items:
        return plan_items[0]
    title = str(signal.title or "").strip()
    if title and "ambient session" not in title.lower():
        return title
    summary = str(signal.summary or "").strip()
    if summary:
        return summary
    for note in signal.notes:
        text = str(note).strip()
        if text:
            return text
    paths = _top_level_scope_tokens(signal.files_touched)
    if paths:
        return f"Work in {paths[0]}"
    commands = [str(item).strip() for item in signal.commands if str(item).strip()]
    if commands:
        return f"Work around {commands[0].split()[0]}"
    return "Untitled work cluster"


def _candidate_summary(signal: AmbientSignal, active_run: dict[str, Any], title: str) -> str:
    summary = str(signal.summary or "").strip()
    if summary:
        return summary
    for note in signal.notes:
        text = str(note).strip()
        if text:
            return text
    plan_items = _open_plan_items(active_run)
    if plan_items:
        return f"Recorded work cluster around: {plan_items[0]}"
    return title


def _candidate_evidence_sources(signal: AmbientSignal, active_run: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    if _open_plan_items(active_run):
        sources.append("plan")
    if signal.summary or signal.notes:
        sources.append("note")
    if signal.commands:
        sources.append("command")
    if signal.files_touched:
        sources.append("file")
    if signal.verification:
        sources.append("verification")
    if signal.related_quests:
        sources.append("related_quest")
    if signal.related_sidequests:
        sources.append("related_sidequest")
    if signal.source == "log-decision":
        sources.append("decision")
    if signal.source == "log-disclosure":
        sources.append("disclosure")
    return _unique_strings(sources)


def _candidate_evidence(signal: AmbientSignal, summary: str) -> list[str]:
    evidence = [str(item) for item in signal.files_touched if str(item).strip()]
    evidence.extend(str(item) for item in signal.commands if str(item).strip())
    evidence.extend(str(item) for item in signal.verification if str(item).strip())
    if summary:
        evidence.append(f"summary: {summary}")
    if signal.source == "log-decision" and signal.title:
        evidence.append(f"decision: {signal.title}")
    if signal.source == "log-disclosure" and signal.title:
        evidence.append(f"disclosure: {signal.title}")
    return _unique_strings(evidence)[:20]


def _accepted_scope_key(current_accepted: dict[str, Any] | None) -> str:
    if not current_accepted:
        return "ambient"
    return str(current_accepted.get("quest_id") or current_accepted.get("title") or "active").strip() or "active"


def _scope_classification(signal: AmbientSignal, current_accepted: dict[str, Any] | None) -> str:
    if not current_accepted:
        return "unknown"
    current_id = str(current_accepted.get("quest_id") or "").strip()
    current_title = str(current_accepted.get("title") or "").strip()
    related_quests = [str(item).strip() for item in signal.related_quests if str(item).strip()]
    if current_id and current_id in related_quests:
        return "in_scope"
    if related_quests and current_id and current_id not in related_quests:
        return "out_of_scope"
    if signal.related_sidequests:
        return "out_of_scope"
    text = " ".join(
        [
            str(signal.title or ""),
            str(signal.summary or ""),
            *[str(item) for item in signal.notes],
            *[str(item) for item in signal.commands],
            *[str(item) for item in signal.files_touched],
        ]
    )
    if current_id and current_id.lower() in text.lower():
        return "in_scope"
    if current_title and _tokens_overlap(text, current_title):
        return "in_scope"
    if any(marker in text.lower() for marker in ("bug", "hotfix", "regression", "incident", "unexpected", "out-of-band")):
        return "out_of_scope"
    return "out_of_scope" if text.strip() else "unknown"


def _candidate_cluster_id(signal: AmbientSignal, active_run: dict[str, Any], current_accepted: dict[str, Any] | None) -> str:
    related_sidequests = [str(item).strip().upper() for item in signal.related_sidequests if str(item).strip()]
    if related_sidequests:
        return f"WORK_CLUSTER__{related_sidequests[0]}"
    related_quests = [str(item).strip().upper() for item in signal.related_quests if str(item).strip()]
    if related_quests:
        return f"WORK_CLUSTER__{related_quests[0]}"
    title = _candidate_title(signal, active_run)
    scope = _accepted_scope_key(current_accepted)
    title_token = _slugify(title)[:24] or "work"
    scope_token = _slugify(scope)[:24] or "ambient"
    if title != "Untitled work cluster":
        return f"WORK_CLUSTER__{title_token}__{scope_token}".upper()
    tokens = _top_level_scope_tokens(signal.files_touched)
    path_token = _slugify(tokens[0])[:24] if tokens else "general"
    return f"WORK_CLUSTER__{title_token}__{path_token}__{scope_token}".upper()


def _candidate_fingerprint(
    signal: AmbientSignal,
    active_run: dict[str, Any],
    *,
    title: str,
    summary: str,
    scope_classification: str,
) -> str:
    parts = [
        str(signal.source or ""),
        title,
        summary,
        scope_classification,
        "|".join(sorted(_candidate_evidence_sources(signal, active_run))),
        "|".join(sorted(_unique_strings(signal.notes))),
        "|".join(sorted(_unique_strings(signal.files_touched))),
        "|".join(sorted(_unique_strings(signal.commands))),
        "|".join(sorted(_unique_strings(signal.verification))),
        "|".join(sorted(_unique_strings(signal.related_quests))),
        "|".join(sorted(_unique_strings(signal.related_sidequests))),
    ]
    return " || ".join(parts)


def _candidate_can_auto_formalize(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "").strip()
    summary = str(record.get("summary") or "").strip()
    if not title or title in {"Untitled work cluster", "Quest Candidate", "Side Quest Candidate"}:
        return False
    if not summary:
        return False
    evidence_sources = record.get("evidence_sources")
    if not isinstance(evidence_sources, list) or len(evidence_sources) < 3:
        return False
    signal_count = int(record.get("signal_count") or 0)
    if signal_count < 2:
        return False
    related_files = record.get("related_files")
    if not isinstance(related_files, list) or not related_files:
        return False
    return True


def _candidate_state(existing_state: str | None, *, signal_count: int, evidence_source_count: int, can_auto_formalize: bool) -> str:
    if existing_state == ProposalState.FORMALIZED.value:
        return ProposalState.FORMALIZED.value
    if can_auto_formalize and signal_count >= 2 and evidence_source_count >= 3:
        next_state = ProposalState.READY.value
    elif signal_count >= 2 or evidence_source_count >= 3:
        next_state = ProposalState.PROPOSED.value
    elif signal_count >= 2 or evidence_source_count >= 2:
        next_state = ProposalState.DRAFT.value
    else:
        next_state = ProposalState.AMBIENT.value
    if existing_state and QUEST_STATE_RANK.get(existing_state, -1) > QUEST_STATE_RANK.get(next_state, -1):
        return existing_state
    return next_state


def _find_existing_quest_candidate(live: Path, cluster_id: str) -> dict[str, Any] | None:
    for kind in QUEST_PROPOSAL_KINDS:
        directory = _proposal_dir(live, kind)
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = _read_yaml(path)
            if not isinstance(data, dict):
                continue
            if str(data.get("cluster_id") or "") != cluster_id:
                continue
            data["path"] = str(path)
            return data
    return None


def _should_skip_quest_candidate(
    *,
    data_root: Path,
    signal: AmbientSignal,
    current_accepted: dict[str, Any] | None,
    scope_classification: str,
) -> bool:
    current_id = str(current_accepted.get("quest_id") or "").strip() if current_accepted else ""
    related_quests = [str(item).strip() for item in signal.related_quests if str(item).strip()]
    if current_id and scope_classification == "in_scope":
        return True
    for quest_id in related_quests:
        if find_quest_file(data_root, quest_id) is not None:
            return True
    for quest_id in signal.related_sidequests:
        if find_quest_file(data_root, str(quest_id).strip()) is not None:
            return True
    return False


def _candidate_kind(signal: AmbientSignal, current_accepted: dict[str, Any] | None, scope_classification: str) -> ProposalKind:
    text = " ".join(
        [
            str(signal.title or ""),
            str(signal.summary or ""),
            *[str(item) for item in signal.notes],
            *[str(item) for item in signal.commands],
            *[str(item) for item in signal.files_touched],
        ]
    ).lower()
    if signal.related_sidequests or scope_classification == "out_of_scope":
        return ProposalKind.SIDE_QUEST
    if any(marker in text for marker in ("bug", "hotfix", "regression", "incident", "unexpected", "out-of-band")):
        return ProposalKind.SIDE_QUEST
    return ProposalKind.QUEST


def _upsert_quest_candidate(
    *,
    live: Path,
    subject: str,
    data_root: Path,
    source_id: str,
    interaction_mode: str,
    active_run: dict[str, Any],
    signal: AmbientSignal,
    promotion: PromotionRecord,
    current_accepted: dict[str, Any] | None,
) -> dict[str, Any] | None:
    scope_classification = _scope_classification(signal, current_accepted)
    if _should_skip_quest_candidate(
        data_root=data_root,
        signal=signal,
        current_accepted=current_accepted,
        scope_classification=scope_classification,
    ):
        return None

    kind = _candidate_kind(signal, current_accepted, scope_classification)
    cluster_id = _candidate_cluster_id(signal, active_run, current_accepted)
    title = _candidate_title(signal, active_run)
    summary = _candidate_summary(signal, active_run, title)
    evidence_sources = _candidate_evidence_sources(signal, active_run)
    evidence = _candidate_evidence(signal, summary)
    related_files = _unique_strings(signal.files_touched)
    related_run_ids = [] if source_id == "NO_RUN" else [source_id]
    related_quest_ids = _unique_strings(signal.related_quests)
    related_sidequest_ids = _unique_strings(signal.related_sidequests)
    fingerprint = _candidate_fingerprint(
        signal,
        active_run,
        title=title,
        summary=summary,
        scope_classification=scope_classification,
    )

    existing = _find_existing_quest_candidate(live, cluster_id)
    existing_state = str(existing.get("state") or "") if existing else None
    last_fingerprint = str(existing.get("last_signal_fingerprint") or "") if existing else ""
    is_noop = existing is not None and last_fingerprint == fingerprint

    signal_count = int(existing.get("signal_count") or 0) if existing else 0
    if not is_noop:
        signal_count += 1

    merged_evidence_sources = _unique_strings([*(existing.get("evidence_sources") or [])] + evidence_sources) if existing else evidence_sources
    merged_evidence = _unique_strings([*(existing.get("evidence") or [])] + evidence) if existing else evidence
    merged_files = _unique_strings([*(existing.get("related_files") or [])] + related_files) if existing else related_files
    merged_run_ids = _unique_strings([*(existing.get("related_run_ids") or [])] + related_run_ids) if existing else related_run_ids
    merged_related_quests = _unique_strings([*(existing.get("related_quest_ids") or [])] + related_quest_ids) if existing else related_quest_ids
    merged_related_sidequests = _unique_strings([*(existing.get("related_sidequest_ids") or [])] + related_sidequest_ids) if existing else related_sidequest_ids

    payload: dict[str, Any] = {
        "schema_version": 1,
        "proposal_id": str(existing.get("proposal_id") or cluster_id) if existing else cluster_id,
        "cluster_id": cluster_id,
        "subject": subject,
        "kind": kind.value,
        "interaction_mode": interaction_mode,
        "source_id": source_id,
        "created_at": str(existing.get("created_at") or _now_iso()) if existing else _now_iso(),
        "updated_at": _now_iso(),
        "last_seen_at": str(existing.get("last_seen_at") or _now_iso()) if is_noop and existing else _now_iso(),
        "title": title,
        "summary": summary,
        "description": summary,
        "objective": summary,
        "reason": promotion.reason,
        "scope_classification": scope_classification,
        "blockers": list(promotion.blockers),
        "evidence": merged_evidence,
        "evidence_sources": merged_evidence_sources,
        "related_run_ids": merged_run_ids,
        "related_files": merged_files,
        "related_quest_ids": merged_related_quests,
        "related_sidequest_ids": merged_related_sidequests,
        "signal_count": signal_count,
        "confidence_reason": "",
        "codex_implications": list(promotion.codex_implications),
        "change_class": "STRUCTURAL",
        "vision_delta": "ALIGNED",
        "priority": "P1",
        "risk": "R0",
        "door_impact": "NONE",
        "testing_level": "DEFERRED TO 01_PREQUEST.md",
        "verification_plan": "DEFERRED TO 01_PREQUEST.md",
        "codex_anchors": "BLOCKED - CODEX_ANCHORS_MISSING",
        "anti_dup": DEFAULT_REPO_ORIENTATION_BLOCKER,
        "placement_intent": DEFAULT_REPO_ORIENTATION_BLOCKER,
        "out_of_scope": "Any work beyond this clustered candidate scope.",
        "dependencies": "None",
        "talent_awarded": "NO",
        "last_signal_fingerprint": fingerprint,
    }
    if existing and existing.get("formalized_artifact_path"):
        payload["formalized_artifact_path"] = existing.get("formalized_artifact_path")

    can_auto_formalize = _candidate_can_auto_formalize(payload)
    payload["state"] = _candidate_state(
        existing_state,
        signal_count=signal_count,
        evidence_source_count=len(merged_evidence_sources),
        can_auto_formalize=can_auto_formalize,
    )
    payload["confidence_reason"] = (
        f"signal_count={signal_count}; evidence_sources={len(merged_evidence_sources)}; "
        f"scope={scope_classification}; auto_formalize={'yes' if can_auto_formalize else 'no'}"
    )

    proposal_path = _proposal_path(live, kind, payload["proposal_id"])
    old_path = Path(str(existing["path"])) if existing and existing.get("path") else None
    payload["path"] = str(proposal_path)
    write_payload = dict(payload)
    write_payload.pop("path", None)
    _write_yaml(proposal_path, write_payload)
    if old_path and old_path.resolve() != proposal_path.resolve() and old_path.exists():
        old_path.unlink()
    return payload


def _collect_quest_candidate_details(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for record in records:
        kind = str(record.get("kind") or "")
        if kind not in {ProposalKind.QUEST.value, ProposalKind.SIDE_QUEST.value}:
            continue
        details.append(
            {
                "proposal_id": str(record.get("proposal_id") or ""),
                "cluster_id": str(record.get("cluster_id") or ""),
                "kind": kind,
                "state": str(record.get("state") or ""),
                "title": str(record.get("title") or ""),
                "summary": str(record.get("summary") or ""),
                "scope_classification": str(record.get("scope_classification") or "unknown"),
                "confidence_reason": str(record.get("confidence_reason") or ""),
                "evidence_sources": list(record.get("evidence_sources") or []),
                "related_run_ids": list(record.get("related_run_ids") or []),
                "related_files": list(record.get("related_files") or []),
                "related_quest_ids": list(record.get("related_quest_ids") or []),
                "related_sidequest_ids": list(record.get("related_sidequest_ids") or []),
                "formalized_artifact_path": record.get("formalized_artifact_path"),
                "last_seen_at": record.get("last_seen_at"),
                "signal_count": int(record.get("signal_count") or 0),
            }
        )
    details.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    return details


def _sync_candidate_backlog(manifold: dict[str, Any], records: list[dict[str, Any]]) -> None:
    quest_details = _collect_quest_candidate_details(records)
    manifold["quest_candidate_details"] = quest_details
    manifold["active_quest_candidates"] = [item["proposal_id"] for item in quest_details if item.get("proposal_id")]
    manifold["pending_formalizations"] = [
        str(record.get("proposal_id") or "")
        for record in records
        if str(record.get("state") or "")
        in {
            ProposalState.PROPOSED.value,
            ProposalState.READY.value,
            ProposalState.BLOCKED.value,
            ProposalState.ESCALATED.value,
        }
        and str(record.get("proposal_id") or "")
    ]


def _load_proposal_records(live: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    proposals_root = live / "PROPOSALS"
    if not proposals_root.exists():
        return records
    for path in sorted(proposals_root.rglob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        data["path"] = str(path)
        records.append(data)
    return records


def _write_proposals(
    *,
    live: Path,
    subject: str,
    source_id: str,
    interaction_mode: str,
    promotions: list[dict[str, Any]],
) -> list[str]:
    written: list[str] = []
    for proposal in promotions:
        kind = ProposalKind(str(proposal["kind"]))
        proposal_path = _proposal_dir(live, kind) / f"{proposal['proposal_id']}.yaml"
        payload = {
            "schema_version": 1,
            "proposal_id": proposal["proposal_id"],
            "subject": subject,
            "kind": kind.value,
            "state": proposal["state"],
            "interaction_mode": interaction_mode,
            "source_id": source_id,
            "created_at": proposal.get("created_at") or _now_iso(),
            "updated_at": _now_iso(),
            "title": proposal["title"],
            "summary": proposal["summary"],
            "reason": proposal["reason"],
            "blockers": proposal.get("blockers", []),
            "evidence": proposal.get("evidence", []),
            "codex_implications": proposal.get("codex_implications", []),
        }
        _write_yaml(proposal_path, payload)
        written.append(str(proposal_path))
    return written


def list_proposals(
    *,
    data_root: Path,
    kind: ProposalKind | None = None,
    state: ProposalState | None = None,
) -> list[dict[str, Any]]:
    live = live_root(data_root)
    records = _load_proposal_records(live)
    results: list[dict[str, Any]] = []
    for record in records:
        if kind is not None and str(record.get("kind") or "") != kind.value:
            continue
        if state is not None and str(record.get("state") or "") != state.value:
            continue
        results.append(record)
    return results


def mark_proposal_state(
    *,
    data_root: Path,
    proposal_id: str,
    state: ProposalState,
    artifact_path: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    live = live_root(data_root)
    proposals = _load_proposal_records(live)
    for proposal in proposals:
        if str(proposal.get("proposal_id") or "") != proposal_id:
            continue
        path = Path(str(proposal["path"]))
        proposal["state"] = state.value
        proposal["updated_at"] = _now_iso()
        if artifact_path:
            proposal["formalized_artifact_path"] = artifact_path
        if note:
            notes = proposal.get("notes")
            if not isinstance(notes, list):
                notes = []
            notes.append(note)
            proposal["notes"] = notes[-10:]
        proposal.pop("path", None)
        _write_yaml(path, proposal)
        return dict(proposal, path=str(path))
    raise LiveMemoryError(f"Proposal not found: {proposal_id}")


def _auto_formalize_ready_quest_candidates(*, subject: str, data_root: Path) -> list[dict[str, Any]]:
    live = live_root(data_root)
    results: list[dict[str, Any]] = []
    for proposal in _load_proposal_records(live):
        kind_text = str(proposal.get("kind") or "")
        if kind_text not in {ProposalKind.QUEST.value, ProposalKind.SIDE_QUEST.value}:
            continue
        if str(proposal.get("state") or "") != ProposalState.READY.value:
            continue
        if str(proposal.get("formalized_artifact_path") or "").strip():
            continue
        prefix = "SIDE-QUEST" if kind_text == ProposalKind.SIDE_QUEST.value else "QUEST"
        draft = draft_quest_from_proposal(subject=subject, data_root=data_root, proposal=proposal, prefix=prefix)
        proposal_receipt = mark_proposal_state(
            data_root=data_root,
            proposal_id=str(proposal["proposal_id"]),
            state=ProposalState.FORMALIZED,
            artifact_path=str(draft["artifact_path"]),
            note=f"Auto-formalized into {draft['quest_id']}.",
        )
        results.append(
            {
                "proposal_id": str(proposal.get("proposal_id") or ""),
                "quest_id": draft["quest_id"],
                "artifact_path": draft["artifact_path"],
                "proposal": proposal_receipt,
            }
        )
    return results

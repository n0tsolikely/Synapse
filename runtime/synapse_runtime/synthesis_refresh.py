"""Derived synthesis refresh for engaged-kernel read models."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.codex_packets import (
    SECTION_TITLES,
    build_codex_packet,
    codex_packet_summary,
    sync_codex_packets,
)
from synapse_runtime.continuity_obligations import load_obligations
from synapse_runtime.live_memory_common import _slugify
from synapse_runtime.promotion_engine import load_working_records
from synapse_runtime.quest_plans import list_plan_artifacts, load_execution_plan
from synapse_runtime.repo_onboarding import canonical_project_model_path


def _parse_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text).astimezone().isoformat()
    except Exception:
        return None


def _file_time(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).astimezone().isoformat()


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).astimezone().isoformat()


def _record_time(payload: dict[str, Any]) -> str:
    return _parse_time(payload.get("recorded_at")) or _file_time(Path(str(payload.get("path"))))


def _dict_source_ref(*, kind: str, payload: dict[str, Any], source_id: str, path: str) -> dict[str, Any]:
    item = {
        "kind": kind,
        "id": source_id,
        "path": path,
    }
    if payload.get("family"):
        item["family"] = payload.get("family")
    if payload.get("revision_id"):
        item["revision_id"] = payload.get("revision_id")
    if payload.get("obligation_kind"):
        item["obligation_kind"] = payload.get("obligation_kind")
    return item


def _baseline_publication_ref(data_root: Path) -> dict[str, Any] | None:
    model_path = canonical_project_model_path(data_root)
    if not model_path.exists():
        return None
    payload = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    confirmed_at = _parse_time(payload.get("confirmed_at")) or _file_time(model_path)
    return {
        "path": str(model_path.resolve()),
        "confirmed_at": confirmed_at,
        "project_identity": str(payload.get("project_identity") or "").strip() or None,
        "purpose": str(payload.get("purpose") or "").strip() or None,
    }


def _latest_plan_revision(data_root: Path) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for path in list_plan_artifacts(data_root):
        payload = load_execution_plan(path)
        payload_time = _parse_time(payload.get("updated_at")) or _parse_time(payload.get("created_at")) or _file_time(path)
        payload["_effective_time"] = payload_time
        if latest is None:
            latest = payload
            continue
        if str(payload_time or "") > str(latest.get("_effective_time") or ""):
            latest = payload
    return latest


def _family_records(data_root: Path, family: str) -> list[dict[str, Any]]:
    records = [item for item in load_working_records(data_root, family) if isinstance(item, dict)]
    return sorted(records, key=_record_time)


def _recent_records(records: Iterable[dict[str, Any]], *, limit: int = 5, baseline_time: str | None = None) -> list[dict[str, Any]]:
    filtered = list(records)
    if baseline_time:
        filtered = [item for item in filtered if str(_record_time(item) or "") > str(baseline_time)]
    return filtered[-limit:]


def _milestone_status_lines(plan: dict[str, Any]) -> list[str]:
    milestones = list(plan.get("milestones") or [])
    pending = [
        item for item in milestones
        if str(item.get("status") or "").strip().upper() not in {"DONE", "COMPLETE", "COMPLETED"}
    ]
    lines = []
    if milestones:
        lines.append(f"Milestones: {len(pending)} pending of {len(milestones)} total.")
        for item in pending[:4]:
            lines.append(f"{item.get('id')}: {item.get('text')}")
    return lines


def _delta_payload(
    *,
    key: str,
    refreshed_at: str,
    summary: str,
    detail_lines: Iterable[str],
    source_refs: Iterable[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_refs = [dict(item) for item in source_refs if isinstance(item, dict)]
    return {
        "delta_key": key,
        "title": SECTION_TITLES.get(key, key.replace("_", " ").title()),
        "summary": " ".join(str(summary or "").split()).strip(),
        "detail_lines": [" ".join(str(item or "").split()).strip() for item in detail_lines if " ".join(str(item or "").split()).strip()],
        "refreshed_at": refreshed_at,
        "source_refs": normalized_refs,
        "source_ref_count": len(normalized_refs),
        "metadata": dict(metadata or {}),
    }


def _active_plan_delta(data_root: Path, refreshed_at: str) -> dict[str, Any] | None:
    latest = _latest_plan_revision(data_root)
    if latest is None:
        return None
    summary = str(latest.get("summary") or latest.get("title") or latest.get("plan_id") or "").strip()
    if not summary:
        return None
    source_ref = _dict_source_ref(
        kind="plan_revision",
        payload=latest,
        source_id=str(latest.get("revision_id") or latest.get("plan_id") or summary),
        path=str(latest.get("path") or ""),
    )
    detail_lines = []
    objective = str(latest.get("objective") or "").strip()
    coherent_outcome = str(latest.get("coherent_outcome") or "").strip()
    if objective:
        detail_lines.append(f"Objective: {objective}")
    if coherent_outcome:
        detail_lines.append(f"Outcome: {coherent_outcome}")
    detail_lines.extend(_milestone_status_lines(latest))
    return _delta_payload(
        key="ACTIVE_PLAN",
        refreshed_at=refreshed_at,
        summary=summary,
        detail_lines=detail_lines,
        source_refs=[source_ref],
        metadata={
            "plan_id": latest.get("plan_id"),
            "revision_id": latest.get("revision_id"),
            "scope_campaign_refs": list(latest.get("scope_campaign_refs") or []),
        },
    )


def _active_scope_delta(data_root: Path, refreshed_at: str) -> dict[str, Any] | None:
    records = _family_records(data_root, "SCOPE_CAMPAIGNS")
    if not records:
        return None
    recent = records[-5:]
    summaries = [str(item.get("summary") or item.get("title") or "").strip() for item in recent]
    summary = summaries[-1] if len(summaries) == 1 else f"{len(recent)} active scope campaigns"
    source_refs = [
        _dict_source_ref(
            kind="governed_working_record",
            payload=item,
            source_id=str(item.get("record_id") or item.get("family_id") or summary),
            path=str(item.get("path") or ""),
        )
        for item in recent
    ]
    detail_lines = [item for item in summaries if item]
    return _delta_payload(
        key="ACTIVE_SCOPE",
        refreshed_at=refreshed_at,
        summary=summary,
        detail_lines=detail_lines,
        source_refs=source_refs,
        metadata={"scope_campaign_ids": [item.get("family_id") for item in recent if item.get("family_id")]},
    )


def _obligation_delta(data_root: Path, refreshed_at: str) -> dict[str, Any] | None:
    open_items = [
        item for item in load_obligations(data_root)
        if str(item.get("state") or "open").strip().lower() == "open"
    ]
    if not open_items:
        return None
    blockers = [item for item in open_items if str(item.get("severity") or "").strip().lower() == "blocker"]
    summary = f"{len(open_items)} open continuity obligations"
    if blockers:
        summary += f" ({len(blockers)} blockers)"
    source_refs = [
        _dict_source_ref(
            kind="continuity_obligation",
            payload=item,
            source_id=str(item.get("obligation_id") or item.get("summary") or ""),
            path=str(item.get("path") or ""),
        )
        for item in open_items[-5:]
    ]
    detail_lines = [str(item.get("summary") or "").strip() for item in open_items[-5:] if str(item.get("summary") or "").strip()]
    return _delta_payload(
        key="OPEN_OBLIGATIONS",
        refreshed_at=refreshed_at,
        summary=summary,
        detail_lines=detail_lines,
        source_refs=source_refs,
        metadata={"open_count": len(open_items), "blocker_count": len(blockers)},
    )


def _family_delta(
    *,
    data_root: Path,
    refreshed_at: str,
    family: str,
    key: str,
    baseline_time: str | None = None,
    baseline_ref: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    records = _recent_records(_family_records(data_root, family), baseline_time=baseline_time)
    if not records:
        return None
    latest = records[-1]
    summary = str(latest.get("summary") or latest.get("title") or "").strip()
    if not summary:
        return None
    source_refs = [
        _dict_source_ref(
            kind="governed_working_record",
            payload=item,
            source_id=str(item.get("record_id") or item.get("family_id") or summary),
            path=str(item.get("path") or ""),
        )
        for item in records
    ]
    if baseline_ref:
        source_refs.append(
            {
                "kind": "canonical_publication",
                "id": _slugify(baseline_ref.get("path") or key),
                "path": baseline_ref.get("path"),
                "baseline_confirmed_at": baseline_ref.get("confirmed_at"),
            }
        )
    detail_lines = [str(item.get("summary") or item.get("title") or "").strip() for item in records]
    metadata = {
        "family": family,
        "record_ids": [item.get("record_id") for item in records if item.get("record_id")],
    }
    if baseline_ref:
        metadata["baseline_confirmed_at"] = baseline_ref.get("confirmed_at")
        metadata["baseline_path"] = baseline_ref.get("path")
    return _delta_payload(
        key=key,
        refreshed_at=refreshed_at,
        summary=summary,
        detail_lines=detail_lines,
        source_refs=source_refs,
        metadata=metadata,
    )


def refresh_synthesis(*, subject: str, data_root: Path) -> dict[str, Any]:
    refreshed_at = _now_iso()
    baseline_ref = _baseline_publication_ref(data_root)
    baseline_time = baseline_ref.get("confirmed_at") if baseline_ref else None

    active_plan = _active_plan_delta(data_root, refreshed_at)
    active_scope = _active_scope_delta(data_root, refreshed_at)
    obligations = _obligation_delta(data_root, refreshed_at)
    architecture = _family_delta(
        data_root=data_root,
        refreshed_at=refreshed_at,
        family="ARCHITECTURE_EVOLUTION",
        key="ARCHITECTURE_DELTA",
        baseline_time=baseline_time,
        baseline_ref=baseline_ref,
    )
    identity = _family_delta(
        data_root=data_root,
        refreshed_at=refreshed_at,
        family="PROJECT_IDENTITY_CLAIMS",
        key="IDENTITY_DELTA",
        baseline_time=baseline_time,
        baseline_ref=baseline_ref,
    )
    narrative = _family_delta(
        data_root=data_root,
        refreshed_at=refreshed_at,
        family="NARRATIVE_CLAIMS",
        key="NARRATIVE_DELTA",
        baseline_time=baseline_time,
        baseline_ref=baseline_ref,
    )

    deltas = {
        "active_plan_delta": active_plan,
        "active_scope_delta": active_scope,
        "obligation_delta": obligations,
        "architecture_delta": architecture,
        "identity_delta": identity,
        "narrative_delta": narrative,
    }

    packets = []
    for delta in deltas.values():
        if not isinstance(delta, dict) or not delta.get("summary"):
            continue
        packets.append(
            build_codex_packet(
                subject=subject,
                section_key=str(delta.get("delta_key") or ""),
                refreshed_at=refreshed_at,
                summary=str(delta.get("summary") or ""),
                detail_lines=list(delta.get("detail_lines") or []),
                source_refs=list(delta.get("source_refs") or []),
                metadata=dict(delta.get("metadata") or {}),
            )
        )
    sync_receipt = sync_codex_packets(data_root, packets)
    packet_summary = codex_packet_summary(data_root)

    return {
        "refreshed_at": refreshed_at,
        **deltas,
        "codex_packets": packet_summary,
        "written_packet_paths": sync_receipt.get("written_paths") or [],
        "removed_packet_paths": sync_receipt.get("removed_paths") or [],
        "baseline_publication_ref": baseline_ref,
    }

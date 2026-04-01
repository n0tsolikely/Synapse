"""Governed continuity-obligation storage and summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.kernel_types import ContinuityObligationEnvelope, stable_kernel_id


OBLIGATION_SCHEMA_VERSION = 1


class ContinuityObligationError(RuntimeError):
    """Raised when continuity obligations cannot be stored or resolved safely."""


def obligations_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "CONTINUITY_OBLIGATIONS"


def ensure_obligations_scaffold(data_root: Path) -> list[str]:
    root = obligations_root(data_root)
    if root.exists():
        return []
    root.mkdir(parents=True, exist_ok=True)
    return [str(root.resolve())]


def obligation_filename(*, obligation_id: str, severity: str) -> str:
    return f"OBLIGATION__{obligation_id}__{str(severity or 'warn').upper()}.yaml"


def persist_obligation(data_root: Path, obligation: ContinuityObligationEnvelope | dict[str, Any]) -> dict[str, Any]:
    ensure_obligations_scaffold(data_root)
    payload = obligation.to_dict() if isinstance(obligation, ContinuityObligationEnvelope) else dict(obligation)
    obligation_id = str(payload.get("obligation_id") or "").strip()
    if not obligation_id:
        raise ContinuityObligationError("Continuity obligation is missing obligation_id.")
    severity = str(payload.get("severity") or "warn").strip().lower() or "warn"
    path = obligations_root(data_root) / obligation_filename(obligation_id=obligation_id, severity=severity)
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(payload)
            payload = merged
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {**payload, "path": str(path.resolve())}


def open_obligation(
    *,
    subject: str,
    data_root: Path,
    recorded_at: str,
    obligation_kind: str,
    severity: str,
    summary: str,
    required_record_families: Iterable[str],
    source_segment_ids: Iterable[str],
    source_semantic_event_ids: Iterable[str],
    source_refs: Iterable[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = ContinuityObligationEnvelope(
        obligation_id=stable_kernel_id(
            "OBLIG",
            subject,
            obligation_kind,
            "|".join(sorted(str(item) for item in source_segment_ids if str(item).strip())),
            "|".join(sorted(str(item) for item in source_semantic_event_ids if str(item).strip())),
        ),
        schema_version=OBLIGATION_SCHEMA_VERSION,
        recorded_at=recorded_at,
        subject=subject,
        obligation_kind=obligation_kind,
        severity=str(severity or "warn").strip().lower() or "warn",
        state="open",
        summary=summary,
        required_record_families=[str(item) for item in required_record_families if str(item).strip()],
        source_segment_ids=[str(item) for item in source_segment_ids if str(item).strip()],
        source_semantic_event_ids=[str(item) for item in source_semantic_event_ids if str(item).strip()],
        source_refs=[dict(item) for item in source_refs if isinstance(item, dict)],
        resolved_at=None,
        resolution_record_ids=[],
        metadata=dict(metadata or {}),
    )
    return persist_obligation(data_root, payload)


def load_obligations(data_root: Path) -> list[dict[str, Any]]:
    root = obligations_root(data_root)
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("OBLIGATION__*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["path"] = str(path.resolve())
            records.append(payload)
    return records


def resolve_matching_obligations(
    *,
    data_root: Path,
    recorded_at: str,
    source_segment_ids: Iterable[str] = (),
    source_semantic_event_ids: Iterable[str] = (),
    resolution_record_ids: Iterable[str] = (),
    obligation_kinds: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    target_segments = {str(item).strip() for item in source_segment_ids if str(item).strip()}
    target_events = {str(item).strip() for item in source_semantic_event_ids if str(item).strip()}
    target_kinds = {str(item).strip() for item in obligation_kinds or [] if str(item).strip()}
    resolved: list[dict[str, Any]] = []
    for obligation in load_obligations(data_root):
        if str(obligation.get("state") or "open").strip().lower() != "open":
            continue
        if target_kinds and str(obligation.get("obligation_kind") or "") not in target_kinds:
            continue
        existing_segments = {str(item).strip() for item in obligation.get("source_segment_ids") or [] if str(item).strip()}
        existing_events = {str(item).strip() for item in obligation.get("source_semantic_event_ids") or [] if str(item).strip()}
        if target_segments and existing_segments.isdisjoint(target_segments) and target_events and existing_events.isdisjoint(target_events):
            continue
        if target_segments and not existing_segments.isdisjoint(target_segments):
            pass
        elif target_events and not existing_events.isdisjoint(target_events):
            pass
        else:
            continue
        obligation["state"] = "resolved"
        obligation["resolved_at"] = recorded_at
        obligation["resolution_record_ids"] = sorted({*map(str, obligation.get("resolution_record_ids") or []), *[str(item) for item in resolution_record_ids if str(item).strip()]})
        resolved.append(persist_obligation(data_root, obligation))
    return resolved


def obligation_summary(data_root: Path) -> dict[str, Any]:
    obligations = load_obligations(data_root)
    open_items = [item for item in obligations if str(item.get("state") or "open").strip().lower() == "open"]
    blocker_items = [item for item in open_items if str(item.get("severity") or "warn").strip().lower() == "blocker"]
    return {
        "open_count": len(open_items),
        "blocker_count": len(blocker_items),
        "recent_open_obligation_ids": [str(item.get("obligation_id")) for item in open_items[-10:]],
        "recent_open_obligation_details": [
            {
                "obligation_id": item.get("obligation_id"),
                "obligation_kind": item.get("obligation_kind"),
                "severity": item.get("severity"),
                "summary": item.get("summary"),
            }
            for item in open_items[-10:]
        ],
    }

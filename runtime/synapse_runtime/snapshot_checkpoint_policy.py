"""Snapshot-family checkpoint policy for passive and explicit snapshot boundaries."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from synapse_runtime.snapshot_candidates import CONTROL_SYNC_KIND, EOD_KIND

DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
GENERAL_KIND = "GENERAL"
MULTI_KIND = "MULTI"
SNAPSHOT_KIND_NONE = "NONE"
SUPPORTED_CANDIDATE_KINDS = (EOD_KIND, CONTROL_SYNC_KIND)
SUPPORTED_SNAPSHOT_KINDS = (EOD_KIND, CONTROL_SYNC_KIND, GENERAL_KIND)
WRITER_COMMAND_BY_KIND = {
    CONTROL_SYNC_KIND: "control-close",
    EOD_KIND: "eod",
    GENERAL_KIND: "general",
}


@dataclass(frozen=True)
class SnapshotCheckpointDecision:
    trigger_boundary: str
    decision_mode: str
    snapshot_kind: str
    target_day: str | None
    candidate_action: str
    canonical_action: str
    draftshot_action: str
    writer_command: str | None
    blocked_reason: str | None
    required_candidate_kinds: tuple[str, ...]
    receipt_requirements: tuple[str, ...]
    stale_prior_day_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_candidate_kinds"] = list(self.required_candidate_kinds)
        payload["receipt_requirements"] = list(self.receipt_requirements)
        return payload


def _today() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).date().isoformat()


def _draftshot_day(draftshot: dict[str, Any] | None) -> str | None:
    if not isinstance(draftshot, dict):
        return None
    refreshed_at = str(draftshot.get("refreshed_at") or draftshot.get("created_at") or "").strip()
    if refreshed_at and "T" in refreshed_at:
        return refreshed_at.split("T", 1)[0]
    return None


def _normalize_boundary(boundary: str | None) -> str:
    return str(boundary or "unknown").strip() or "unknown"


def _normalize_candidate_kinds(kinds: Iterable[str] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in kinds or ():
        text = str(raw or "").strip().upper().replace("-", "_")
        if not text or text in seen:
            continue
        if text not in SUPPORTED_CANDIDATE_KINDS:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_snapshot_kind(kind: str | None) -> str | None:
    text = str(kind or "").strip().upper().replace("-", "_")
    return text if text in SUPPORTED_SNAPSHOT_KINDS else None


def _snapshot_kind_for(required_candidate_kinds: tuple[str, ...], requested_snapshot_kind: str | None = None) -> str:
    explicit = _normalize_snapshot_kind(requested_snapshot_kind)
    if explicit:
        return explicit
    if not required_candidate_kinds:
        return SNAPSHOT_KIND_NONE
    if len(required_candidate_kinds) == 1:
        return required_candidate_kinds[0]
    return MULTI_KIND


def evaluate_snapshot_checkpoint(
    *,
    boundary: str,
    requested_candidate_kinds: Iterable[str] | None,
    target_day_hint: str | None,
    current_summary: dict[str, Any] | None,
    draftshot: dict[str, Any] | None,
    session_anchor_present: bool,
    decision_mode: str = "passive",
    requested_snapshot_kind: str | None = None,
) -> SnapshotCheckpointDecision:
    normalized_boundary = _normalize_boundary(boundary)
    requested_kinds = _normalize_candidate_kinds(requested_candidate_kinds)
    summary = dict(current_summary or {})
    stale_prior_day_required = bool(summary.get("stale_prior_day_candidate_required"))
    draftshot_day = _draftshot_day(draftshot)
    target_day = str(target_day_hint or "").strip() or draftshot_day

    if decision_mode == "explicit_canonical":
        snapshot_kind = _snapshot_kind_for((), requested_snapshot_kind=requested_snapshot_kind)
        blocked_reason = None if snapshot_kind != SNAPSHOT_KIND_NONE else "unsupported_snapshot_kind"
        if not target_day:
            target_day = _today()
        draftshot_action = "consume" if draftshot is not None else "not_required"
        return SnapshotCheckpointDecision(
            trigger_boundary=normalized_boundary,
            decision_mode=decision_mode,
            snapshot_kind=snapshot_kind,
            target_day=target_day,
            candidate_action="skip",
            canonical_action="write" if blocked_reason is None else "forbidden",
            draftshot_action=draftshot_action if blocked_reason is None else "blocked",
            writer_command=WRITER_COMMAND_BY_KIND.get(snapshot_kind),
            blocked_reason=blocked_reason,
            required_candidate_kinds=(),
            receipt_requirements=("decision", "writer_command", "canonical_path"),
            stale_prior_day_required=stale_prior_day_required,
        )

    if normalized_boundary == "session-start" and not requested_kinds:
        if stale_prior_day_required and draftshot_day:
            requested_kinds = (EOD_KIND,)
            target_day = draftshot_day
        else:
            return SnapshotCheckpointDecision(
                trigger_boundary=normalized_boundary,
                decision_mode=decision_mode,
                snapshot_kind=SNAPSHOT_KIND_NONE,
                target_day=target_day,
                candidate_action="skip",
                canonical_action="defer",
                draftshot_action="not_required",
                writer_command=None,
                blocked_reason=None,
                required_candidate_kinds=(),
                receipt_requirements=("decision", "summary"),
                stale_prior_day_required=stale_prior_day_required,
            )

    if requested_kinds and not session_anchor_present:
        return SnapshotCheckpointDecision(
            trigger_boundary=normalized_boundary,
            decision_mode=decision_mode,
            snapshot_kind=_snapshot_kind_for(requested_kinds),
            target_day=target_day,
            candidate_action="skip",
            canonical_action="defer",
            draftshot_action="blocked",
            writer_command=None,
            blocked_reason="missing_session_anchor",
            required_candidate_kinds=requested_kinds,
            receipt_requirements=("decision", "blocking_reason", "summary"),
            stale_prior_day_required=stale_prior_day_required,
        )

    if requested_kinds and draftshot is None:
        return SnapshotCheckpointDecision(
            trigger_boundary=normalized_boundary,
            decision_mode=decision_mode,
            snapshot_kind=_snapshot_kind_for(requested_kinds),
            target_day=target_day,
            candidate_action="skip",
            canonical_action="defer",
            draftshot_action="blocked",
            writer_command=None,
            blocked_reason="no_active_draftshot",
            required_candidate_kinds=requested_kinds,
            receipt_requirements=("decision", "blocking_reason", "summary"),
            stale_prior_day_required=stale_prior_day_required,
        )

    if not requested_kinds:
        return SnapshotCheckpointDecision(
            trigger_boundary=normalized_boundary,
            decision_mode=decision_mode,
            snapshot_kind=SNAPSHOT_KIND_NONE,
            target_day=target_day,
            candidate_action="skip",
            canonical_action="defer",
            draftshot_action="not_required",
            writer_command=None,
            blocked_reason=None,
            required_candidate_kinds=(),
            receipt_requirements=("decision", "summary"),
            stale_prior_day_required=stale_prior_day_required,
        )

    if not target_day:
        target_day = _today()

    return SnapshotCheckpointDecision(
        trigger_boundary=normalized_boundary,
        decision_mode=decision_mode,
        snapshot_kind=_snapshot_kind_for(requested_kinds),
        target_day=target_day,
        candidate_action="refresh",
        canonical_action="defer",
        draftshot_action="preserve",
        writer_command=None,
        blocked_reason=None,
        required_candidate_kinds=requested_kinds,
        receipt_requirements=("decision", "summary", "snapshot_candidates", "projection"),
        stale_prior_day_required=stale_prior_day_required,
    )


def materialize_snapshot_checkpoint_decision(
    decision: SnapshotCheckpointDecision,
    *,
    snapshot_candidate_payload: dict[str, Any] | None = None,
    target_day: str | None = None,
    draftshot_error: str | None = None,
) -> dict[str, Any]:
    payload = decision.to_dict()
    if target_day:
        payload["target_day"] = target_day
    if draftshot_error and payload.get("draftshot_action") != "not_required":
        payload["draftshot_action"] = "blocked"
        payload["draftshot_error"] = draftshot_error

    candidate_payload = dict(snapshot_candidate_payload or {})
    candidates = list(candidate_payload.get("candidates") or [])
    statuses = {str(item.get("status") or "").strip().lower() for item in candidates}
    reasons = {str(item.get("reason") or "").strip().lower() for item in candidates}

    if payload["candidate_action"] == "refresh":
        if statuses.intersection({"written", "updated"}):
            payload["candidate_action"] = "refresh"
        elif statuses == {"noop"} and reasons.intersection({"unchanged_source_signature"}):
            payload["candidate_action"] = "reuse"
        elif statuses == {"noop"}:
            payload["candidate_action"] = "skip"

    if candidate_payload.get("reason") in {"missing_session_id", "no_active_draftshot"} and not payload.get("blocked_reason"):
        payload["blocked_reason"] = str(candidate_payload.get("reason") or None)
        if payload.get("draftshot_action") != "not_required":
            payload["draftshot_action"] = "blocked"

    return payload

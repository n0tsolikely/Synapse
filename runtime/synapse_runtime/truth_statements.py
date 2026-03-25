"""Canonical truth statement schema helpers for compiled current-state truth."""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any


class TruthStatementError(RuntimeError):
    """Raised when truth statements or provenance refs are invalid."""


class TruthLayer(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    INTENDED = "intended"
    SPECULATIVE = "speculative"
    SUPERSEDED = "superseded"


class StatementKind(str, Enum):
    PROJECT_PURPOSE = "project_purpose"
    IDENTITY_CLAIM = "identity_claim"
    CAPABILITY = "capability"
    WORKFLOW = "workflow"
    ARCHITECTURE = "architecture"
    CONSTRAINT = "constraint"
    NON_GOAL = "non_goal"
    CURRENT_FOCUS = "current_focus"
    PROBLEM = "problem"
    DECISION_SUMMARY = "decision_summary"
    HISTORY_TURN = "history_turn"
    DEPLOYMENT_CLAIM = "deployment_claim"
    QUALITY_CLAIM = "quality_claim"


CONFIDENCE_VALUES = {"low", "medium", "high"}
PROVENANCE_SOURCE_TYPES = {
    "semantic_capture",
    "decision",
    "disclosure",
    "receipt",
    "audit_bundle",
    "onboarding_publication",
    "active_run",
    "quest_state",
    "repo_state",
}


def normalize_summary_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        raise TruthStatementError("Statement summary must be non-empty.")
    return text


def normalize_detail_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_topic_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        raise TruthStatementError("topic_key must normalize to a non-empty value.")
    return text


def normalize_confidence(value: Any, *, default: str = "medium") -> str:
    text = str(value or default).strip().lower()
    if text not in CONFIDENCE_VALUES:
        raise TruthStatementError(f"Invalid confidence: {value}")
    return text


def statement_id_for(statement_kind: StatementKind | str, topic_key: str, summary: str) -> str:
    kind = StatementKind(str(statement_kind)).value
    topic = normalize_topic_key(topic_key)
    normalized_summary = normalize_summary_text(summary).lower()
    digest = hashlib.sha256(f"{kind}|{topic}|{normalized_summary}".encode("utf-8")).hexdigest()[:8]
    return f"STMT-{kind}-{topic}-{digest}"


def validate_provenance_ref(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TruthStatementError("Provenance ref must be an object.")
    required = (
        "source_type",
        "source_id",
        "source_path",
        "source_time",
        "evidence_kind",
        "confidence_hint",
        "operator_confirmed",
    )
    result: dict[str, Any] = {}
    for key in required:
        if key not in payload:
            raise TruthStatementError(f"Provenance ref missing required field: {key}")
    source_type = str(payload.get("source_type") or "").strip()
    if source_type not in PROVENANCE_SOURCE_TYPES:
        raise TruthStatementError(f"Invalid provenance source_type: {source_type}")
    result["source_type"] = source_type
    result["source_id"] = normalize_summary_text(payload.get("source_id"))
    result["source_path"] = normalize_summary_text(payload.get("source_path"))
    result["source_time"] = normalize_summary_text(payload.get("source_time"))
    result["evidence_kind"] = normalize_summary_text(payload.get("evidence_kind"))
    result["confidence_hint"] = normalize_confidence(payload.get("confidence_hint"))
    result["operator_confirmed"] = bool(payload.get("operator_confirmed"))
    return result


def normalize_statement_record(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TruthStatementError("Statement record must be an object.")
    kind = StatementKind(str(payload.get("statement_kind") or "").strip())
    truth_layer = TruthLayer(str(payload.get("truth_layer") or "").strip())
    summary = normalize_summary_text(payload.get("summary"))
    topic_key = normalize_topic_key(payload.get("topic_key"))
    statement_id = str(payload.get("statement_id") or "").strip() or statement_id_for(kind, topic_key, summary)
    if statement_id != statement_id_for(kind, topic_key, summary):
        raise TruthStatementError("statement_id does not match deterministic statement id rules.")

    result = {
        "statement_id": statement_id,
        "statement_kind": kind.value,
        "summary": summary,
        "detail": normalize_detail_text(payload.get("detail")),
        "truth_layer": truth_layer.value,
        "confidence": normalize_confidence(payload.get("confidence")),
        "operator_confirmed": bool(payload.get("operator_confirmed")),
        "needs_expansion": bool(payload.get("needs_expansion")),
        "topic_key": topic_key,
        "provenance_refs": [validate_provenance_ref(item) for item in payload.get("provenance_refs") or []],
        "derived_from_statement_ids": [str(item).strip() for item in payload.get("derived_from_statement_ids") or [] if str(item).strip()],
        "supersedes": [str(item).strip() for item in payload.get("supersedes") or [] if str(item).strip()],
        "superseded_by": [str(item).strip() for item in payload.get("superseded_by") or [] if str(item).strip()],
        "contradicted_by": [str(item).strip() for item in payload.get("contradicted_by") or [] if str(item).strip()],
        "first_seen_at": normalize_summary_text(payload.get("first_seen_at")),
        "last_reconciled_at": normalize_summary_text(payload.get("last_reconciled_at")),
        "last_evidence_at": normalize_summary_text(payload.get("last_evidence_at")),
        "active": bool(payload.get("active", truth_layer != TruthLayer.SUPERSEDED)),
    }
    if truth_layer == TruthLayer.SUPERSEDED and result["active"]:
        raise TruthStatementError("Superseded statements must not remain active.")
    return result


def build_statement_record(
    *,
    statement_kind: StatementKind | str,
    summary: str,
    detail: str,
    truth_layer: TruthLayer | str,
    confidence: str,
    operator_confirmed: bool,
    needs_expansion: bool,
    topic_key: str,
    provenance_refs: list[dict[str, Any]],
    derived_from_statement_ids: list[str],
    supersedes: list[str],
    superseded_by: list[str],
    contradicted_by: list[str],
    first_seen_at: str,
    last_reconciled_at: str,
    last_evidence_at: str,
    active: bool,
) -> dict[str, Any]:
    return normalize_statement_record(
        {
            "statement_kind": StatementKind(str(statement_kind)).value,
            "summary": summary,
            "detail": detail,
            "truth_layer": TruthLayer(str(truth_layer)).value,
            "confidence": confidence,
            "operator_confirmed": operator_confirmed,
            "needs_expansion": needs_expansion,
            "topic_key": topic_key,
            "provenance_refs": provenance_refs,
            "derived_from_statement_ids": derived_from_statement_ids,
            "supersedes": supersedes,
            "superseded_by": superseded_by,
            "contradicted_by": contradicted_by,
            "first_seen_at": first_seen_at,
            "last_reconciled_at": last_reconciled_at,
            "last_evidence_at": last_evidence_at,
            "active": active,
        }
    )

"""Compiled current-state truth orchestration and freshness helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.current_state_publication import PUBLICATION_FILENAMES, render_publication_set, write_publication_set_atomic
from synapse_runtime.sidecar_store import _load_manifold, _load_state, _now_iso, _write_yaml, live_root
from synapse_runtime.truth_sources import EvidenceRecord, TruthSourceError, collect_evidence
from synapse_runtime.truth_statements import (
    StatementKind,
    TruthLayer,
    build_statement_record,
    normalize_confidence,
    normalize_topic_key,
    normalize_summary_text,
    statement_id_for,
)


class TruthCompilerError(RuntimeError):
    """Raised when the truth compiler cannot complete."""


_CAPABILITY_PRECEDENCE = {
    "audit_bundle": 1,
    "receipt": 2,
    "quest_state": 3,
    "decision": 4,
    "onboarding_publication": 5,
    "semantic_capture": 6,
    "repo_state": 8,
    "active_run": 9,
    "disclosure": 7,
}
_IDENTITY_PRECEDENCE = {
    "onboarding_publication": 1,
    "decision": 2,
    "semantic_capture": 3,
    "active_run": 4,
    "repo_state": 5,
    "receipt": 4,
    "audit_bundle": 4,
    "quest_state": 4,
    "disclosure": 3,
}
_CURRENT_WORK_PRECEDENCE = {
    "active_run": 1,
    "quest_state": 2,
    "receipt": 3,
    "onboarding_publication": 4,
    "semantic_capture": 5,
    "decision": 5,
    "disclosure": 5,
    "audit_bundle": 3,
    "repo_state": 6,
}


def truth_root(data_root: Path) -> Path:
    return live_root(data_root) / "TRUTH"


def statements_path(data_root: Path) -> Path:
    return truth_root(data_root) / "STATEMENTS.yaml"


def compiler_report_path(data_root: Path) -> Path:
    return truth_root(data_root) / "COMPILER_REPORT.yaml"


def truth_publications_dir(data_root: Path) -> Path:
    return truth_root(data_root) / "PUBLICATIONS"


def canonical_truth_publication_paths(data_root: Path) -> dict[str, str]:
    base = truth_publications_dir(data_root)
    return {filename: str((base / filename).resolve()) for filename in PUBLICATION_FILENAMES.values()}


def _claim_family(statement_kind: str) -> str:
    if statement_kind == StatementKind.CURRENT_FOCUS.value:
        return "current_work"
    if statement_kind in {
        StatementKind.PROJECT_PURPOSE.value,
        StatementKind.IDENTITY_CLAIM.value,
        StatementKind.ARCHITECTURE.value,
        StatementKind.WORKFLOW.value,
        StatementKind.CONSTRAINT.value,
        StatementKind.NON_GOAL.value,
        StatementKind.DECISION_SUMMARY.value,
        StatementKind.HISTORY_TURN.value,
    }:
        return "identity"
    return "capability"


def _precedence_rank(statement_kind: str, source_type: str) -> int:
    family = _claim_family(statement_kind)
    if family == "current_work":
        return _CURRENT_WORK_PRECEDENCE.get(source_type, 99)
    if family == "identity":
        return _IDENTITY_PRECEDENCE.get(source_type, 99)
    return _CAPABILITY_PRECEDENCE.get(source_type, 99)


def _confidence_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(str(value or ""), 0)


def _pick_primary_evidence(statement_kind: str, records: list[EvidenceRecord]) -> EvidenceRecord:
    return sorted(
        records,
        key=lambda record: (
            _precedence_rank(statement_kind, record.source_type),
            -_confidence_rank(record.confidence_hint),
            record.effective_time,
            record.evidence_id,
        ),
    )[0]


def _coerce_truth_layer(records: list[EvidenceRecord], primary: EvidenceRecord) -> TruthLayer:
    if primary.truth_layer_hint:
        return TruthLayer(primary.truth_layer_hint)
    if primary.implemented_hint:
        return TruthLayer.IMPLEMENTED
    if any(record.truth_layer_hint == TruthLayer.IMPLEMENTED.value for record in records):
        return TruthLayer.IMPLEMENTED
    if any(record.truth_layer_hint == TruthLayer.PARTIAL.value for record in records):
        return TruthLayer.PARTIAL
    if any(record.truth_layer_hint == TruthLayer.INTENDED.value for record in records):
        return TruthLayer.INTENDED
    return TruthLayer.SPECULATIVE


def _statement_confidence(records: list[EvidenceRecord], primary: EvidenceRecord) -> str:
    if primary.source_type in {"audit_bundle", "receipt", "quest_state", "onboarding_publication"}:
        return "high"
    if primary.operator_confirmed or len({record.source_type for record in records}) >= 2:
        return "medium"
    return normalize_confidence(primary.confidence_hint)


def _provenance_refs(records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: (item.effective_time, item.evidence_id)):
        refs.append(
            {
                "source_type": record.source_type,
                "source_id": record.evidence_id,
                "source_path": record.path_ref,
                "source_time": record.effective_time,
                "evidence_kind": record.statement_kind_hint,
                "confidence_hint": record.confidence_hint,
                "operator_confirmed": record.operator_confirmed,
            }
        )
    return refs


def _load_previous_statements(data_root: Path) -> dict[str, dict[str, Any]]:
    path = statements_path(data_root)
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TruthCompilerError(f"Unable to read previous statement store: {exc}") from exc
    if not isinstance(payload, dict):
        raise TruthCompilerError("Previous statement store is malformed.")
    previous = {}
    for item in payload.get("statements") or []:
        if isinstance(item, dict) and str(item.get("statement_id") or "").strip():
            previous[str(item["statement_id"])] = item
    return previous


def _cluster_evidence(records: list[EvidenceRecord]) -> dict[tuple[str, str, str], list[EvidenceRecord]]:
    clusters: dict[tuple[str, str, str], list[EvidenceRecord]] = {}
    for record in records:
        if record.metadata.get("freshness_only"):
            continue
        key = (
            record.statement_kind_hint,
            normalize_topic_key(record.topic_key_hint),
            normalize_summary_text(record.summary).lower(),
        )
        clusters.setdefault(key, []).append(record)
    return clusters


def _build_statements(*, data_root: Path, records: list[EvidenceRecord], compiled_at: str) -> list[dict[str, Any]]:
    previous = _load_previous_statements(data_root)
    statements: list[dict[str, Any]] = []
    for (statement_kind, topic_key, normalized_summary), cluster in sorted(_cluster_evidence(records).items()):
        primary = _pick_primary_evidence(statement_kind, cluster)
        statement_id = statement_id_for(statement_kind, topic_key, primary.summary)
        prior = previous.get(statement_id) or {}
        truth_layer = _coerce_truth_layer(cluster, primary)
        statement = build_statement_record(
            statement_kind=statement_kind,
            summary=primary.summary,
            detail=primary.detail,
            truth_layer=truth_layer,
            confidence=_statement_confidence(cluster, primary),
            operator_confirmed=any(item.operator_confirmed for item in cluster),
            needs_expansion=any(item.needs_expansion_hint for item in cluster),
            topic_key=topic_key,
            provenance_refs=_provenance_refs(cluster),
            derived_from_statement_ids=[],
            supersedes=[],
            superseded_by=[],
            contradicted_by=[],
            first_seen_at=str(prior.get("first_seen_at") or compiled_at),
            last_reconciled_at=compiled_at,
            last_evidence_at=max(item.effective_time for item in cluster),
            active=truth_layer != TruthLayer.SUPERSEDED,
        )
        statements.append(statement)
    # Preserve earlier superseded history so recompiles do not erase it.
    known = {item["statement_id"] for item in statements}
    for prior in previous.values():
        if prior.get("statement_id") not in known and str(prior.get("truth_layer") or "") == TruthLayer.SUPERSEDED.value:
            statements.append(dict(prior))
    return statements


def _apply_supersession_and_contradictions(statements: list[dict[str, Any]]) -> dict[str, Any]:
    by_topic: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for statement in statements:
        by_topic.setdefault((str(statement.get("statement_kind")), str(statement.get("topic_key"))), []).append(statement)
    unresolved: list[dict[str, Any]] = []
    material_count = 0
    for group in by_topic.values():
        active = [item for item in group if item.get("active")]
        superseded = [item for item in group if str(item.get("truth_layer")) == TruthLayer.SUPERSEDED.value]
        if superseded and active:
            replacement_id = active[0]["statement_id"]
            for item in superseded:
                item["active"] = False
                item["superseded_by"] = [replacement_id]
                if item["statement_id"] not in active[0]["supersedes"]:
                    active[0]["supersedes"].append(item["statement_id"])
        distinct_summaries = {str(item.get("summary")) for item in active}
        if len(active) > 1 and len(distinct_summaries) > 1:
            ids = [str(item.get("statement_id")) for item in active]
            for item in active:
                item["contradicted_by"] = [other for other in ids if other != item["statement_id"]]
            contradiction = {
                "topic_key": active[0].get("topic_key"),
                "statement_kind": active[0].get("statement_kind"),
                "statement_ids": ids,
                "summaries": [str(item.get("summary")) for item in active],
            }
            unresolved.append(contradiction)
            material = any(
                str(item.get("truth_layer")) in {TruthLayer.IMPLEMENTED.value, TruthLayer.PARTIAL.value}
                or (
                    str(item.get("statement_kind")) in {StatementKind.PROJECT_PURPOSE.value, StatementKind.IDENTITY_CLAIM.value}
                    and bool(item.get("operator_confirmed"))
                )
                for item in active
            )
            if material:
                material_count += 1
    return {
        "statements": statements,
        "unresolved_contradictions": unresolved,
        "material_contradiction_count": material_count,
    }


def _current_work_summary(*, active_run: dict[str, Any] | None, quest_state: dict[str, Any], receipt_records: list[EvidenceRecord], disclosure_records: list[EvidenceRecord], statements: list[dict[str, Any]], stale_active_run_detected: bool) -> dict[str, Any]:
    accepted = list(quest_state.get("accepted") or [])
    completed = list(quest_state.get("completed") or [])
    recent_completion_titles = [str(item.get("title") or item.get("quest_id") or "").strip() for item in completed[:3] if str(item.get("title") or item.get("quest_id") or "").strip()]
    receipt_titles = [record.summary for record in receipt_records if record.metadata.get("completion_like")][:3]
    if not recent_completion_titles:
        recent_completion_titles = receipt_titles
    blocked = None
    for record in disclosure_records:
        labels = {str(item).strip().upper() for item in record.metadata.get("status_labels") or []}
        if labels & {"BLOCKED", "UNVERIFIED", "UNKNOWN"}:
            blocked = record.summary
            break
    current_focus = None
    if active_run and active_run.get("run_id"):
        current_focus = str(active_run.get("result_summary") or active_run.get("goal") or active_run.get("title") or "").strip() or None
    if not current_focus:
        focus_statements = [item for item in statements if item.get("active") and item.get("statement_kind") == StatementKind.CURRENT_FOCUS.value]
        if focus_statements:
            current_focus = str(focus_statements[0].get("summary") or "").strip() or None
    accepted_work = None
    if accepted:
        first = accepted[0]
        accepted_work = str(first.get("title") or first.get("quest_id") or "").strip() or None
    return {
        "current_focus": current_focus,
        "active_run_id": active_run.get("run_id") if active_run else None,
        "accepted_governed_work": accepted_work,
        "recently_completed": recent_completion_titles,
        "blocked_state": blocked,
        "stale_active_run_detected": stale_active_run_detected,
    }


def _stale_active_run(*, active_run: dict[str, Any] | None, completion_records: list[EvidenceRecord]) -> bool:
    if not active_run or not active_run.get("run_id"):
        return False
    run_time = str(active_run.get("updated_at") or active_run.get("started_at") or "").strip()
    if not run_time:
        return False
    run_dt = dt.datetime.fromisoformat(run_time)
    for record in completion_records:
        try:
            evidence_dt = dt.datetime.fromisoformat(record.effective_time)
        except Exception:
            continue
        if evidence_dt > run_dt:
            return True
    return False


def _compile_cycle_id(*, compiled_at: str, records: list[EvidenceRecord]) -> str:
    material = "|".join(sorted(record.evidence_id for record in records))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]
    stamp = dt.datetime.fromisoformat(compiled_at).strftime("%Y%m%dT%H%M%S")
    return f"TRUTH-COMPILE-{stamp}-{digest}"


def _statement_store_payload(*, compile_cycle_id: str, compiled_at: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "compile_cycle_id": compile_cycle_id,
        "compiled_at": compiled_at,
        "statements": statements,
    }


def _report_payload(
    *,
    compile_cycle_id: str,
    compiled_at: str,
    statements: list[dict[str, Any]],
    unresolved_contradictions: list[dict[str, Any]],
    material_contradiction_count: int,
    warnings: list[dict[str, Any]],
    stale_active_run_detected: bool,
    current_work_summary: dict[str, Any],
    publication_paths: dict[str, str] | None,
    truth_compile_stale: bool,
    truth_stale_reasons: list[str],
) -> dict[str, Any]:
    active = [item for item in statements if item.get("active")]
    superseded = [item for item in statements if str(item.get("truth_layer")) == TruthLayer.SUPERSEDED.value]
    return {
        "schema_version": 1,
        "compile_cycle_id": compile_cycle_id,
        "compiled_at": compiled_at,
        "statement_count": len(statements),
        "active_statement_count": len(active),
        "contradiction_count": len(unresolved_contradictions),
        "material_contradiction_count": material_contradiction_count,
        "superseded_count": len(superseded),
        "truth_compile_stale": truth_compile_stale,
        "truth_stale_reasons": list(truth_stale_reasons),
        "stale_active_run_detected": bool(stale_active_run_detected),
        "unresolved_contradictions": unresolved_contradictions,
        "source_warnings": warnings,
        "external_source_warning_count": len(warnings),
        "current_work_summary": current_work_summary,
        "truth_publication_paths": publication_paths or canonical_truth_publication_paths(Path(".")),
    }


def _write_projection_fields(*, subject: str, data_root: Path, report: dict[str, Any]) -> dict[str, str]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)

    state["last_truth_compile_at"] = report.get("compiled_at")
    state["last_truth_compile_cycle_id"] = report.get("compile_cycle_id")
    state["truth_statement_count"] = report.get("statement_count")
    state["truth_active_statement_count"] = report.get("active_statement_count")
    state["truth_contradiction_count"] = report.get("contradiction_count")
    state["truth_superseded_count"] = report.get("superseded_count")
    state["truth_compile_stale"] = bool(report.get("truth_compile_stale"))
    state["truth_stale_reasons"] = list(report.get("truth_stale_reasons") or [])
    state["truth_stale_active_run_detected"] = bool(report.get("stale_active_run_detected"))

    manifold["last_truth_compile_at"] = report.get("compiled_at")
    manifold["last_truth_compile_cycle_id"] = report.get("compile_cycle_id")
    manifold["truth_statement_count"] = report.get("statement_count")
    manifold["truth_active_statement_count"] = report.get("active_statement_count")
    manifold["truth_contradiction_count"] = report.get("contradiction_count")
    manifold["truth_superseded_count"] = report.get("superseded_count")
    manifold["truth_compile_stale"] = bool(report.get("truth_compile_stale"))
    manifold["truth_stale_reasons"] = list(report.get("truth_stale_reasons") or [])
    manifold["stale_active_run_detected"] = bool(report.get("stale_active_run_detected"))
    manifold["current_work_summary"] = dict(report.get("current_work_summary") or {})
    manifold["truth_publication_paths"] = dict(report.get("truth_publication_paths") or {})
    _write_yaml(state_path, state)
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)
    return {"state_path": str(state_path), "manifold_path": str(manifold_path)}


def load_statement_store(data_root: Path) -> dict[str, Any] | None:
    path = statements_path(data_root)
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def load_compiler_report(data_root: Path) -> dict[str, Any] | None:
    path = compiler_report_path(data_root)
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def refresh_truth_status(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    inputs = collect_evidence(subject=subject, data_root=data_root, engine_root=engine_root)
    report = load_compiler_report(data_root)
    compiled_at = str((report or {}).get("compiled_at") or "").strip()
    truth_publication_paths = dict((report or {}).get("truth_publication_paths") or canonical_truth_publication_paths(data_root))
    if not compiled_at:
        stale = True
        stale_reasons = ["no_truth_compile_exists"]
        stale_active_run_detected = False
        current_work_summary = _current_work_summary(
            active_run=inputs.get("active_run"),
            quest_state=inputs.get("quest_state") or {},
            receipt_records=[record for record in inputs["evidence_records"] if record.source_type == "receipt"],
            disclosure_records=[record for record in inputs["evidence_records"] if record.source_type == "disclosure"],
            statements=[],
            stale_active_run_detected=False,
        )
        payload = {
            "schema_version": 1,
            "compile_cycle_id": None,
            "compiled_at": None,
            "statement_count": 0,
            "active_statement_count": 0,
            "contradiction_count": 0,
            "superseded_count": 0,
            "truth_compile_stale": stale,
            "truth_stale_reasons": stale_reasons,
            "stale_active_run_detected": stale_active_run_detected,
            "current_work_summary": current_work_summary,
            "truth_publication_paths": truth_publication_paths,
        }
        _write_projection_fields(subject=subject, data_root=data_root, report=payload)
        return payload

    compiled_dt = dt.datetime.fromisoformat(compiled_at)
    stale_reasons: list[str] = []
    if any(dt.datetime.fromisoformat(item["effective_time"]) > compiled_dt for item in inputs["freshness_signals"] if str(item.get("effective_time") or "").strip()):
        stale_reasons.append("new_evidence_after_last_truth_compile")
    completion_records = [
        record
        for record in inputs["evidence_records"]
        if record.metadata.get("completion_like") or record.source_type in {"audit_bundle"}
    ]
    stale_active_run_detected = _stale_active_run(active_run=inputs.get("active_run"), completion_records=completion_records)
    if stale_active_run_detected:
        stale_reasons.append("stale_active_run_detected")
    stale = bool(stale_reasons)
    current_work_summary = _current_work_summary(
        active_run=inputs.get("active_run"),
        quest_state=inputs.get("quest_state") or {},
        receipt_records=[record for record in inputs["evidence_records"] if record.source_type == "receipt"],
        disclosure_records=[record for record in inputs["evidence_records"] if record.source_type == "disclosure"],
        statements=list((load_statement_store(data_root) or {}).get("statements") or []),
        stale_active_run_detected=stale_active_run_detected,
    )
    updated_report = dict(report)
    updated_report["truth_compile_stale"] = stale
    updated_report["truth_stale_reasons"] = stale_reasons
    updated_report["stale_active_run_detected"] = stale_active_run_detected
    updated_report["current_work_summary"] = current_work_summary
    _write_projection_fields(subject=subject, data_root=data_root, report=updated_report)
    return updated_report


def compile_current_state(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    compiled_at = _now_iso()
    inputs = collect_evidence(subject=subject, data_root=data_root, engine_root=engine_root)
    records = list(inputs["evidence_records"])
    statements = _build_statements(data_root=data_root, records=records, compiled_at=compiled_at)
    contradiction_state = _apply_supersession_and_contradictions(statements)
    statements = contradiction_state["statements"]
    completion_records = [
        record
        for record in records
        if record.metadata.get("completion_like") or record.source_type in {"audit_bundle"}
    ]
    stale_active_run_detected = _stale_active_run(active_run=inputs.get("active_run"), completion_records=completion_records)
    current_work_summary = _current_work_summary(
        active_run=inputs.get("active_run"),
        quest_state=inputs.get("quest_state") or {},
        receipt_records=[record for record in records if record.source_type == "receipt"],
        disclosure_records=[record for record in records if record.source_type == "disclosure"],
        statements=statements,
        stale_active_run_detected=stale_active_run_detected,
    )
    compile_cycle_id = _compile_cycle_id(compiled_at=compiled_at, records=records)
    store_payload = _statement_store_payload(compile_cycle_id=compile_cycle_id, compiled_at=compiled_at, statements=statements)

    report_payload = _report_payload(
        compile_cycle_id=compile_cycle_id,
        compiled_at=compiled_at,
        statements=statements,
        unresolved_contradictions=contradiction_state["unresolved_contradictions"],
        material_contradiction_count=contradiction_state["material_contradiction_count"],
        warnings=[warning.__dict__ for warning in inputs["warnings"]],
        stale_active_run_detected=stale_active_run_detected,
        current_work_summary=current_work_summary,
        publication_paths=canonical_truth_publication_paths(data_root),
        truth_compile_stale=False,
        truth_stale_reasons=[],
    )

    root = truth_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    store_path = statements_path(data_root)
    report_path = compiler_report_path(data_root)
    _write_yaml(store_path, store_payload)
    _write_yaml(report_path, report_payload)

    try:
        rendered = render_publication_set(statement_store=store_payload, compiler_report=report_payload)
        publication_paths = write_publication_set_atomic(publications_dir=truth_publications_dir(data_root), rendered=rendered)
    except Exception as exc:
        partial_report = dict(report_payload)
        partial_report["truth_publication_paths"] = canonical_truth_publication_paths(data_root)
        _write_yaml(report_path, partial_report)
        raise TruthCompilerError(f"Publication rendering failed after statement/report write: {exc}") from exc

    final_report = dict(report_payload)
    final_report["truth_publication_paths"] = publication_paths
    _write_yaml(report_path, final_report)
    projection_paths = _write_projection_fields(subject=subject, data_root=data_root, report=final_report)
    return {
        "compile_cycle_id": compile_cycle_id,
        "statement_store_path": str(store_path.resolve()),
        "compiler_report_path": str(report_path.resolve()),
        "publication_paths": publication_paths,
        "statement_count": final_report["statement_count"],
        "active_statement_count": final_report["active_statement_count"],
        "superseded_count": final_report["superseded_count"],
        "contradiction_count": final_report["contradiction_count"],
        "stale_active_run_detected": stale_active_run_detected,
        "truth_compile_stale": False,
        "projection_paths": projection_paths,
        "external_source_warning_count": final_report["external_source_warning_count"],
    }

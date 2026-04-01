"""Evidence adapters for the compiled current-state truth layer."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.accepted_execution_view import load_accepted_quest_details, load_completed_quest_details
from synapse_runtime.live_memory_common import _slugify
from synapse_runtime.promotion_engine import load_working_records
from synapse_runtime.quest_plans import list_plan_artifacts, load_execution_plan
from synapse_runtime.repo_onboarding import (
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
)
from synapse_runtime.repo_state import _run_git
from synapse_runtime.semantic_intake import load_capture_batches
from synapse_runtime.sidecar_store import live_root
from synapse_runtime.truth_statements import StatementKind, TruthLayer, normalize_confidence, normalize_summary_text, normalize_topic_key


class TruthSourceError(RuntimeError):
    """Raised when source evidence cannot be normalized."""

    def __init__(self, message: str, *, canonical: bool, source_type: str, path: str | None = None):
        super().__init__(message)
        self.canonical = canonical
        self.source_type = source_type
        self.path = path


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    source_type: str
    statement_kind_hint: str
    summary: str
    detail: str
    confidence_hint: str
    operator_confirmed: bool
    effective_time: str
    topic_key_hint: str
    truth_layer_hint: str | None
    path_ref: str
    supersession_hint: str | None
    implemented_hint: bool | None
    needs_expansion_hint: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EvidenceWarning:
    source_type: str
    path: str | None
    message: str


def _canonical_yaml(path: Path, *, source_type: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TruthSourceError(str(exc), canonical=True, source_type=source_type, path=str(path)) from exc
    if not isinstance(payload, dict):
        raise TruthSourceError("Expected YAML object.", canonical=True, source_type=source_type, path=str(path))
    return payload


def _safe_markdown(path: Path, *, source_type: str, canonical: bool) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise TruthSourceError(str(exc), canonical=canonical, source_type=source_type, path=str(path)) from exc


def _parse_time(value: Any, *, fallback: str | None = None) -> str:
    text = str(value or "").strip()
    if text:
        try:
            return dt.datetime.fromisoformat(text).astimezone().isoformat()
        except Exception:
            pass
        for fmt in ("%Y%m%d-%H%M%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                return parsed.replace(tzinfo=dt.timezone.utc).astimezone().isoformat()
            except Exception:
                continue
    if fallback:
        return fallback
    return dt.datetime.now(tz=dt.timezone.utc).astimezone().isoformat()


def _file_time(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).astimezone().isoformat()


def _make_evidence(
    *,
    source_type: str,
    source_id: str,
    statement_kind_hint: StatementKind,
    summary: str,
    detail: str,
    confidence_hint: str,
    operator_confirmed: bool,
    effective_time: str,
    topic_key_hint: str,
    truth_layer_hint: TruthLayer | None,
    path_ref: str,
    supersession_hint: str | None = None,
    implemented_hint: bool | None = None,
    needs_expansion_hint: bool = False,
    metadata: dict[str, Any] | None = None,
) -> EvidenceRecord:
    normalized_summary = normalize_summary_text(summary)
    topic_key = normalize_topic_key(topic_key_hint)
    evidence_id = f"EVID-{source_type}-{_slugify(source_id or normalized_summary)}"
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=source_type,
        statement_kind_hint=statement_kind_hint.value,
        summary=normalized_summary,
        detail=str(detail or "").strip(),
        confidence_hint=normalize_confidence(confidence_hint),
        operator_confirmed=bool(operator_confirmed),
        effective_time=_parse_time(effective_time),
        topic_key_hint=topic_key,
        truth_layer_hint=truth_layer_hint.value if truth_layer_hint else None,
        path_ref=path_ref,
        supersession_hint=str(supersession_hint or "").strip() or None,
        implemented_hint=implemented_hint,
        needs_expansion_hint=bool(needs_expansion_hint),
        metadata=dict(metadata or {}),
    )


def _capture_statement_kind(kind: str) -> StatementKind:
    return {
        "idea": StatementKind.CAPABILITY,
        "repo_fact": StatementKind.CAPABILITY,
        "constraint": StatementKind.CONSTRAINT,
        "risk": StatementKind.PROBLEM,
        "question": StatementKind.PROBLEM,
        "unknown": StatementKind.PROBLEM,
        "dependency": StatementKind.ARCHITECTURE,
        "non_goal": StatementKind.NON_GOAL,
        "milestone": StatementKind.WORKFLOW,
        "decision": StatementKind.DECISION_SUMMARY,
    }.get(kind, StatementKind.CAPABILITY)


def _capture_truth_layer(kind: str, blocking: bool) -> TruthLayer:
    if kind in {"repo_fact"}:
        return TruthLayer.PARTIAL
    if kind in {"constraint", "non_goal", "dependency", "milestone"}:
        return TruthLayer.INTENDED
    if kind in {"risk", "question", "unknown"}:
        return TruthLayer.PARTIAL if blocking else TruthLayer.SPECULATIVE
    if kind == "decision":
        return TruthLayer.INTENDED
    return TruthLayer.INTENDED


def semantic_capture_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []
    try:
        batches = load_capture_batches(data_root)
    except Exception as exc:
        raise TruthSourceError(str(exc), canonical=True, source_type="semantic_capture") from exc
    for batch in batches:
        batch_id = str(batch.get("capture_batch_id") or "").strip()
        batch_time = _parse_time(batch.get("captured_at"))
        path_ref = str(batch.get("artifact_path") or batch.get("capture_artifact_path") or "")
        if not path_ref:
            title = str(batch.get("title") or batch_id or "capture")
            stamp = dt.datetime.fromisoformat(batch_time).strftime("%Y%m%d-%H%M%S")
            path_ref = str((live_root(data_root) / "CAPTURES" / "BATCHES" / f"CAPTURE__{stamp}__{_slugify(title)}.yaml").resolve())
        for item in batch.get("captures") or []:
            if not isinstance(item, dict):
                raise TruthSourceError("Malformed capture item.", canonical=True, source_type="semantic_capture", path=path_ref)
            kind = str(item.get("kind") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not kind or not summary:
                raise TruthSourceError("Capture item missing kind or summary.", canonical=True, source_type="semantic_capture", path=path_ref)
            records.append(
                _make_evidence(
                    source_type="semantic_capture",
                    source_id=str(item.get("capture_id") or batch_id or summary),
                    statement_kind_hint=_capture_statement_kind(kind),
                    summary=summary,
                    detail=str(item.get("detail") or batch.get("raw_text") or "").strip(),
                    confidence_hint=str(item.get("confidence") or "low"),
                    operator_confirmed=bool(batch.get("source_role") == "user"),
                    effective_time=batch_time,
                    topic_key_hint=str((item.get("related_paths") or [summary])[0]),
                    truth_layer_hint=_capture_truth_layer(kind, bool(item.get("blocking"))),
                    path_ref=path_ref,
                    needs_expansion_hint=kind in {"question", "unknown", "idea"},
                    metadata={
                        "capture_kind": kind,
                        "capture_batch_id": batch_id,
                        "blocking": bool(item.get("blocking")),
                    },
                )
            )
    return records, warnings


def _ledger_entries(directory: Path, *, source_type: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.glob("*.yaml")):
        payload = _canonical_yaml(path, source_type=source_type)
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise TruthSourceError("Ledger entries must be a list.", canonical=True, source_type=source_type, path=str(path))
        for item in raw_entries:
            if not isinstance(item, dict):
                raise TruthSourceError("Ledger entry must be an object.", canonical=True, source_type=source_type, path=str(path))
            cloned = dict(item)
            cloned.setdefault("_ledger_path", str(path.resolve()))
            entries.append(cloned)
    return entries


def decision_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    for entry in _ledger_entries(live_root(data_root) / "DECISIONS", source_type="decision"):
        summary = str(entry.get("summary") or entry.get("title") or "").strip()
        title = str(entry.get("title") or summary).strip()
        if not summary:
            raise TruthSourceError("Decision entry missing summary.", canonical=True, source_type="decision", path=entry.get("_ledger_path"))
        records.append(
            _make_evidence(
                source_type="decision",
                source_id=str(entry.get("decision_id") or title),
                statement_kind_hint=StatementKind.DECISION_SUMMARY,
                summary=summary,
                detail=str(entry.get("why") or "").strip(),
                confidence_hint="high" if entry.get("binding") else "medium",
                operator_confirmed=True,
                effective_time=_parse_time(entry.get("logged_at")),
                topic_key_hint=title,
                truth_layer_hint=TruthLayer.INTENDED,
                path_ref=str(entry.get("artifact_path") or entry.get("_ledger_path") or ""),
                implemented_hint=bool(re.search(r"\b(implemented|completed|shipped|landed)\b", summary, re.I)),
                metadata={"related_runs": list(entry.get("related_runs") or []), "related_quests": list(entry.get("related_quests") or [])},
            )
        )
    return records, []


def disclosure_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    for entry in _ledger_entries(live_root(data_root) / "DISCLOSURES", source_type="disclosure"):
        trigger = str(entry.get("trigger") or "").strip()
        if not trigger:
            raise TruthSourceError("Disclosure entry missing trigger.", canonical=True, source_type="disclosure", path=entry.get("_ledger_path"))
        labels = [str(item).strip().upper() for item in entry.get("status_labels") or [] if str(item).strip()]
        records.append(
            _make_evidence(
                source_type="disclosure",
                source_id=str(entry.get("disclosure_id") or trigger),
                statement_kind_hint=StatementKind.PROBLEM if any(item in {"RISK", "UNKNOWN", "BLOCKED", "UNVERIFIED"} for item in labels) else StatementKind.CONSTRAINT,
                summary=trigger,
                detail=str(entry.get("impact") or entry.get("provable") or "").strip(),
                confidence_hint="high",
                operator_confirmed=True,
                effective_time=_parse_time(entry.get("logged_at")),
                topic_key_hint=trigger,
                truth_layer_hint=TruthLayer.PARTIAL,
                path_ref=str(entry.get("artifact_path") or entry.get("_ledger_path") or ""),
                needs_expansion_hint=True,
                metadata={"status_labels": labels, "related_quests": list(entry.get("related_quests") or [])},
            )
        )
    return records, []


def onboarding_publication_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    model_path = canonical_project_model_path(data_root)
    story_path = canonical_project_story_path(data_root)
    vision_path = canonical_vision_path(data_root)
    codex_current_path = canonical_codex_current_path(data_root)
    codex_future_path = canonical_codex_future_path(data_root)
    if not model_path.exists():
        return records, []
    model = _canonical_yaml(model_path, source_type="onboarding_publication")
    if not str(model.get("onboarding_id") or "").strip():
        raise TruthSourceError("Published project model missing onboarding_id.", canonical=True, source_type="onboarding_publication", path=str(model_path))
    confirmed_at = _parse_time(model.get("confirmed_at"), fallback=_file_time(model_path))
    project_identity = str(model.get("project_identity") or "").strip() or data_root.name[:-5]
    purpose = str(model.get("purpose") or "").strip()
    vision_text = str(model.get("current_vision") or model.get("vision") or "").strip() or (
        _safe_markdown(vision_path, source_type="onboarding_publication", canonical=True).strip() if vision_path.exists() else ""
    )
    codex_current_text = _safe_markdown(codex_current_path, source_type="onboarding_publication", canonical=True).strip() if codex_current_path.exists() else ""
    codex_future_text = _safe_markdown(codex_future_path, source_type="onboarding_publication", canonical=True).strip() if codex_future_path.exists() else ""
    if purpose:
        records.append(
            _make_evidence(
                source_type="onboarding_publication",
                source_id=f"{project_identity}-purpose",
                statement_kind_hint=StatementKind.PROJECT_PURPOSE,
                summary=purpose,
                detail=vision_text or codex_future_text,
                confidence_hint="high",
                operator_confirmed=True,
                effective_time=confirmed_at,
                topic_key_hint=f"{project_identity}-purpose",
                truth_layer_hint=TruthLayer.IMPLEMENTED,
                path_ref=str(model_path.resolve()),
                metadata={
                    "published_story_path": str(story_path.resolve()) if story_path.exists() else None,
                    "published_codex_future_path": str(codex_future_path.resolve()) if codex_future_path.exists() else None,
                },
            )
        )
    records.append(
        _make_evidence(
            source_type="onboarding_publication",
            source_id=f"{project_identity}-identity",
            statement_kind_hint=StatementKind.IDENTITY_CLAIM,
            summary=project_identity,
            detail=purpose or codex_current_text,
            confidence_hint="high",
            operator_confirmed=True,
            effective_time=confirmed_at,
            topic_key_hint="project-identity",
            truth_layer_hint=TruthLayer.IMPLEMENTED,
            path_ref=str(model_path.resolve()),
        )
    )
    for item in model.get("implemented_truths") or model.get("confirmed_capabilities") or []:
        if isinstance(item, dict) and str(item.get("summary") or "").strip():
            records.append(
                _make_evidence(
                    source_type="onboarding_publication",
                    source_id=str(item.get("id") or item.get("summary")),
                    statement_kind_hint=StatementKind.CAPABILITY,
                    summary=str(item.get("summary")),
                    detail=str(item.get("detail") or codex_current_text).strip(),
                    confidence_hint="high",
                    operator_confirmed=True,
                    effective_time=confirmed_at,
                    topic_key_hint=str(item.get("id") or item.get("summary")),
                    truth_layer_hint=TruthLayer.IMPLEMENTED,
                    path_ref=str(model_path.resolve()),
                )
            )
    for item in list(model.get("partial_truths") or []) + list(model.get("intended_capabilities") or []) + list(
        model.get("partial_or_intended_capabilities") or []
    ):
        if isinstance(item, dict) and str(item.get("summary") or "").strip():
            status = str(item.get("status") or "").strip().lower()
            layer = TruthLayer.PARTIAL if status == "partial" else TruthLayer.INTENDED if status == "intended" else TruthLayer.SPECULATIVE
            records.append(
                _make_evidence(
                    source_type="onboarding_publication",
                    source_id=str(item.get("id") or item.get("summary")),
                    statement_kind_hint=StatementKind.CAPABILITY,
                    summary=str(item.get("summary")),
                    detail=str(item.get("detail") or codex_future_text or codex_current_text).strip(),
                    confidence_hint="high",
                    operator_confirmed=True,
                    effective_time=confirmed_at,
                    topic_key_hint=str(item.get("id") or item.get("summary")),
                    truth_layer_hint=layer,
                    path_ref=str(model_path.resolve()),
                    needs_expansion_hint=layer != TruthLayer.PARTIAL or bool(item.get("needs_expansion")),
                )
            )
    for item in model.get("future_ideas_needing_expansion") or []:
        if isinstance(item, dict) and str(item.get("summary") or "").strip():
            records.append(
                _make_evidence(
                    source_type="onboarding_publication",
                    source_id=str(item.get("id") or item.get("summary")),
                    statement_kind_hint=StatementKind.CAPABILITY,
                    summary=str(item.get("summary")),
                    detail=str(item.get("detail") or codex_future_text).strip(),
                    confidence_hint="medium",
                    operator_confirmed=True,
                    effective_time=confirmed_at,
                    topic_key_hint=str(item.get("id") or item.get("summary")),
                    truth_layer_hint=TruthLayer.SPECULATIVE,
                    path_ref=str(model_path.resolve()),
                    needs_expansion_hint=True,
                )
            )
    for item in model.get("constraints") or []:
        if isinstance(item, dict) and str(item.get("summary") or "").strip():
            records.append(
                _make_evidence(
                    source_type="onboarding_publication",
                    source_id=str(item.get("id") or item.get("summary")),
                    statement_kind_hint=StatementKind.CONSTRAINT,
                    summary=str(item.get("summary")),
                    detail=str(item.get("detail") or "").strip(),
                    confidence_hint="high",
                    operator_confirmed=True,
                    effective_time=confirmed_at,
                    topic_key_hint=str(item.get("id") or item.get("summary")),
                    truth_layer_hint=TruthLayer.IMPLEMENTED,
                    path_ref=str(model_path.resolve()),
                )
            )
    for item in model.get("superseded_directions") or model.get("stale_or_superseded_directions") or []:
        if isinstance(item, dict) and str(item.get("summary") or "").strip():
            records.append(
                _make_evidence(
                    source_type="onboarding_publication",
                    source_id=str(item.get("id") or item.get("summary")),
                    statement_kind_hint=StatementKind.HISTORY_TURN,
                    summary=str(item.get("summary")),
                    detail=str(item.get("detail") or "").strip(),
                    confidence_hint="high",
                    operator_confirmed=True,
                    effective_time=confirmed_at,
                    topic_key_hint=str(item.get("id") or item.get("summary")),
                    truth_layer_hint=TruthLayer.SUPERSEDED,
                    path_ref=str(model_path.resolve()),
                )
            )
    return records, []


def active_run_evidence(*, subject: str, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning], dict[str, Any] | None]:
    path = live_root(data_root) / "ACTIVE_RUN.yaml"
    if not path.exists():
        return [], [], None
    payload = _canonical_yaml(path, source_type="active_run")
    if not isinstance(payload.get("plan"), dict):
        raise TruthSourceError("Active run missing plan object.", canonical=True, source_type="active_run", path=str(path))
    if not payload.get("run_id"):
        return [], [], payload
    focus = str(payload.get("result_summary") or payload.get("goal") or payload.get("title") or "").strip()
    if not focus:
        focus = f"Active run {payload.get('run_id')}"
    records = [
        _make_evidence(
            source_type="active_run",
            source_id=str(payload.get("run_id")),
            statement_kind_hint=StatementKind.CURRENT_FOCUS,
            summary=focus,
            detail=str(payload.get("title") or "").strip(),
            confidence_hint="medium",
            operator_confirmed=True,
            effective_time=_parse_time(payload.get("updated_at") or payload.get("started_at"), fallback=_file_time(path)),
            topic_key_hint=str(payload.get("run_id")),
            truth_layer_hint=TruthLayer.PARTIAL,
            path_ref=str(path.resolve()),
            metadata={
                "run_id": payload.get("run_id"),
                "status": payload.get("status"),
                "goal": payload.get("goal"),
                "title": payload.get("title"),
                "open_plan_items": [
                    item for item in (payload.get("plan") or {}).get("items") or []
                    if isinstance(item, dict) and str(item.get("status") or "").strip().upper() not in {"DONE", "COMPLETE", "COMPLETED", "CANCELLED", "BLOCKED"}
                ],
            },
        )
    ]
    return records, [], payload


def derived_state_context(*, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state = _canonical_yaml(live / "STATE.yaml", source_type="active_run")
    manifold = _canonical_yaml(live / "MANIFOLD.yaml", source_type="active_run")
    rehydrate_path = live / "REHYDRATE.md"
    rehydrate_text = _safe_markdown(rehydrate_path, source_type="active_run", canonical=True) if rehydrate_path.exists() else ""
    return {
        "state": state,
        "manifold": manifold,
        "rehydrate_text": rehydrate_text,
    }


def quest_and_audit_evidence(*, subject: str, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning], dict[str, Any]]:
    records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []
    accepted = load_accepted_quest_details(subject, data_root)
    completed = load_completed_quest_details(subject, data_root)
    for item in accepted:
        summary = str(item.get("title") or item.get("quest_id") or "").strip()
        if not summary:
            continue
        records.append(_make_evidence(source_type="quest_state", source_id=str(item.get("quest_id") or summary), statement_kind_hint=StatementKind.CURRENT_FOCUS, summary=summary, detail="Accepted governed work is active.", confidence_hint="high", operator_confirmed=True, effective_time=_file_time(Path(str(item.get("path")))), topic_key_hint=str(item.get("quest_id") or summary), truth_layer_hint=TruthLayer.PARTIAL, path_ref=str(item.get("path") or ""), metadata={"quest_state": "accepted"}))
    for item in completed:
        summary = str(item.get("title") or item.get("quest_id") or "").strip()
        if not summary:
            continue
        path = Path(str(item.get("path")))
        bundle_path = Path(str(item.get("audit_bundle_path"))) if str(item.get("audit_bundle_path") or "").strip() else None
        if bundle_path and bundle_path.exists():
            records.append(_make_evidence(source_type="audit_bundle", source_id=str(item.get("quest_id") or summary), statement_kind_hint=StatementKind.CAPABILITY, summary=summary, detail="Completed governed work with audit bundle.", confidence_hint="high", operator_confirmed=True, effective_time=_file_time(bundle_path), topic_key_hint=str(item.get("quest_id") or summary), truth_layer_hint=TruthLayer.IMPLEMENTED, path_ref=str(bundle_path.resolve()), implemented_hint=True, metadata={"quest_id": item.get("quest_id"), "completion_like": True}))
        else:
            records.append(_make_evidence(source_type="quest_state", source_id=str(item.get("quest_id") or summary), statement_kind_hint=StatementKind.CAPABILITY, summary=summary, detail="Completed governed work recorded on quest board.", confidence_hint="high", operator_confirmed=True, effective_time=_file_time(path), topic_key_hint=str(item.get("quest_id") or summary), truth_layer_hint=TruthLayer.IMPLEMENTED, path_ref=str(path.resolve()), implemented_hint=True, metadata={"quest_id": item.get("quest_id"), "completion_like": True}))
    return records, warnings, {"accepted": accepted, "completed": completed}


def plan_revision_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []
    for path in list_plan_artifacts(data_root):
        payload = load_execution_plan(path)
        summary = str(payload.get("summary") or payload.get("title") or "").strip()
        if not summary:
            continue
        records.append(
            _make_evidence(
                source_type="plan_revision",
                source_id=str(payload.get("revision_id") or payload.get("plan_id") or summary),
                statement_kind_hint=StatementKind.WORKFLOW,
                summary=summary,
                detail=str(payload.get("objective") or payload.get("coherent_outcome") or "").strip(),
                confidence_hint="medium",
                operator_confirmed=False,
                effective_time=_parse_time(payload.get("updated_at") or payload.get("created_at"), fallback=_file_time(path)),
                topic_key_hint=str(payload.get("plan_id") or summary),
                truth_layer_hint=TruthLayer.INTENDED,
                path_ref=str(path.resolve()),
                metadata={
                    "revision_id": payload.get("revision_id"),
                    "lineage_family_id": payload.get("lineage_family_id"),
                    "scope_campaign_refs": list(payload.get("scope_campaign_refs") or []),
                    "semantic_topics": list(payload.get("semantic_topics") or []),
                },
            )
        )
    return records, warnings


def governed_working_record_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []
    for item in load_working_records(data_root):
        family = str(item.get("family") or "").strip()
        summary = str(item.get("summary") or item.get("title") or "").strip()
        if not family or not summary:
            continue
        statement_kind = {
            "DECISION_GRAPH": StatementKind.DECISION_SUMMARY,
            "ARCHITECTURE_EVOLUTION": StatementKind.ARCHITECTURE,
            "FAILURE_CHAINS": StatementKind.PROBLEM,
            "PROJECT_IDENTITY_CLAIMS": StatementKind.IDENTITY_CLAIM,
            "NARRATIVE_CLAIMS": StatementKind.PROJECT_PURPOSE,
            "SCOPE_CAMPAIGNS": StatementKind.WORKFLOW,
            "IMPORTED_EVIDENCE": StatementKind.HISTORY_TURN,
        }.get(family, StatementKind.CAPABILITY)
        truth_layer = {
            "DECISION_GRAPH": TruthLayer.INTENDED,
            "ARCHITECTURE_EVOLUTION": TruthLayer.PARTIAL,
            "FAILURE_CHAINS": TruthLayer.PARTIAL,
            "PROJECT_IDENTITY_CLAIMS": TruthLayer.PARTIAL,
            "NARRATIVE_CLAIMS": TruthLayer.INTENDED,
            "SCOPE_CAMPAIGNS": TruthLayer.INTENDED,
            "IMPORTED_EVIDENCE": TruthLayer.SPECULATIVE,
        }.get(family, TruthLayer.PARTIAL)
        records.append(
            _make_evidence(
                source_type="governed_working_record",
                source_id=str(item.get("record_id") or summary),
                statement_kind_hint=statement_kind,
                summary=summary,
                detail=str(item.get("detail") or "").strip(),
                confidence_hint=str(item.get("confidence_band") or "medium"),
                operator_confirmed=False,
                effective_time=_parse_time(item.get("recorded_at"), fallback=_file_time(Path(str(item.get("path"))))),
                topic_key_hint=str(item.get("family_id") or summary),
                truth_layer_hint=truth_layer,
                path_ref=str(item.get("path") or ""),
                needs_expansion_hint=family == "IMPORTED_EVIDENCE",
                metadata={
                    "family": family,
                    "family_id": item.get("family_id"),
                    "source_semantic_event_ids": list(item.get("source_semantic_event_ids") or []),
                    "source_segment_ids": list(item.get("source_segment_ids") or []),
                },
            )
        )
    return records, warnings


def workspace_receipt_evidence(*, data_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning]]:
    records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []
    root = data_root.parent
    receipt_files = sorted(root.glob("*_Workspace/Receipts/**/*"))
    for path in receipt_files:
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = _safe_markdown(path, source_type="receipt", canonical=False)
        title = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                break
            if stripped.lower().startswith("title:"):
                title = stripped.split(":", 1)[1].strip()
                break
        if not title:
            warnings.append(EvidenceWarning(source_type="receipt", path=str(path.resolve()), message="Receipt missing clear heading/title; skipped."))
            continue
        filename = path.name.lower()
        completion_like = any(token in filename for token in ("complete", "completed", "closure", "closed", "done", "outcome"))
        records.append(_make_evidence(source_type="receipt", source_id=path.stem, statement_kind_hint=StatementKind.CAPABILITY, summary=title, detail="Workspace receipt.", confidence_hint="high" if completion_like else "medium", operator_confirmed=completion_like, effective_time=_file_time(path), topic_key_hint=title, truth_layer_hint=TruthLayer.IMPLEMENTED if completion_like else TruthLayer.PARTIAL, path_ref=str(path.resolve()), implemented_hint=completion_like, metadata={"completion_like": completion_like}))
    return records, warnings


def repo_state_evidence(*, engine_root: Path) -> tuple[list[EvidenceRecord], list[EvidenceWarning], dict[str, Any]]:
    warnings: list[EvidenceWarning] = []
    records: list[EvidenceRecord] = []
    try:
        branch = _run_git(engine_root, ["rev-parse", "--abbrev-ref", "HEAD"])
        status = _run_git(engine_root, ["status", "--porcelain"])
        head = _run_git(engine_root, ["log", "-1", "--format=%H|%cI"])
    except Exception as exc:
        warnings.append(EvidenceWarning(source_type="repo_state", path=str(engine_root), message=str(exc)))
        return records, warnings, {}
    branch_name = branch.stdout.strip() if branch.returncode == 0 else None
    head_text = head.stdout.strip() if head.returncode == 0 else ""
    head_commit, _, head_time = head_text.partition("|")
    payload = {
        "branch": branch_name,
        "worktree_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "head_commit": head_commit or None,
        "head_time": _parse_time(head_time) if head_time else None,
    }
    if branch_name:
        records.append(_make_evidence(source_type="repo_state", source_id=head_commit or branch_name, statement_kind_hint=StatementKind.CURRENT_FOCUS, summary=f"Repo state on branch {branch_name}", detail="Repo-state freshness signal only.", confidence_hint="medium", operator_confirmed=False, effective_time=payload.get("head_time") or dt.datetime.now(tz=dt.timezone.utc).astimezone().isoformat(), topic_key_hint="repo-state", truth_layer_hint=None, path_ref=str(engine_root.resolve()), needs_expansion_hint=False, metadata={"freshness_only": True, **payload}))
    return records, warnings, payload


def collect_evidence(*, subject: str, data_root: Path, engine_root: Path) -> dict[str, Any]:
    evidence_records: list[EvidenceRecord] = []
    warnings: list[EvidenceWarning] = []

    captures, capture_warnings = semantic_capture_evidence(data_root=data_root)
    evidence_records.extend(captures)
    warnings.extend(capture_warnings)

    decisions, decision_warnings = decision_evidence(data_root=data_root)
    evidence_records.extend(decisions)
    warnings.extend(decision_warnings)

    disclosures, disclosure_warnings = disclosure_evidence(data_root=data_root)
    evidence_records.extend(disclosures)
    warnings.extend(disclosure_warnings)

    onboarding, onboarding_warnings = onboarding_publication_evidence(data_root=data_root)
    evidence_records.extend(onboarding)
    warnings.extend(onboarding_warnings)

    active_run_records, active_run_warnings, active_run_payload = active_run_evidence(subject=subject, data_root=data_root)
    evidence_records.extend(active_run_records)
    warnings.extend(active_run_warnings)

    quest_records, quest_warnings, quest_payload = quest_and_audit_evidence(subject=subject, data_root=data_root)
    evidence_records.extend(quest_records)
    warnings.extend(quest_warnings)

    plan_records, plan_warnings = plan_revision_evidence(data_root=data_root)
    evidence_records.extend(plan_records)
    warnings.extend(plan_warnings)

    governed_records, governed_warnings = governed_working_record_evidence(data_root=data_root)
    evidence_records.extend(governed_records)
    warnings.extend(governed_warnings)

    receipt_records, receipt_warnings = workspace_receipt_evidence(data_root=data_root)
    evidence_records.extend(receipt_records)
    warnings.extend(receipt_warnings)

    repo_records, repo_warnings, repo_payload = repo_state_evidence(engine_root=engine_root)
    evidence_records.extend(repo_records)
    warnings.extend(repo_warnings)
    derived_state = derived_state_context(data_root=data_root)

    freshness_signals = [
        {
            "source_type": record.source_type,
            "effective_time": record.effective_time,
            "path_ref": record.path_ref,
            "summary": record.summary,
            "metadata": dict(record.metadata),
        }
        for record in evidence_records
    ]
    return {
        "evidence_records": evidence_records,
        "warnings": warnings,
        "freshness_signals": freshness_signals,
        "active_run": active_run_payload,
        "quest_state": quest_payload,
        "repo_state": repo_payload,
        "derived_state": derived_state,
    }

"""Retention checks for lawful archive/cooling decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from synapse_runtime.continuity_obligations import load_obligations
from synapse_runtime.lineage_store import load_lineage_edges


COMPACTION_POLICY_SCHEMA_VERSION = 1
ALLOWED_TARGET_TEMPERATURES = {"warm", "cold"}


class CompactionPolicyError(RuntimeError):
    """Raised when a compaction decision cannot be evaluated safely."""


def _normalize_refs(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        ref_id = str(item.get("id") or item.get("source_id") or "").strip()
        path = str(item.get("path") or item.get("artifact_path") or "").strip()
        key = (kind, ref_id, path)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        normalized.append({"kind": kind, "id": ref_id, "path": path})
    return normalized


def _normalize_ids(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _open_obligation_hits(
    *,
    data_root: Path,
    artifact_path: str,
    source_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    relevant_paths = {artifact_path, *[str(item.get("path") or "").strip() for item in source_refs]}
    hits: list[dict[str, Any]] = []
    for obligation in load_obligations(data_root):
        if str(obligation.get("state") or "open").strip().lower() != "open":
            continue
        obligation_paths = {
            str(item.get("path") or "").strip()
            for item in obligation.get("source_refs") or []
            if isinstance(item, dict)
        }
        if relevant_paths.intersection({path for path in obligation_paths if path}):
            hits.append(
                {
                    "obligation_id": str(obligation.get("obligation_id") or ""),
                    "obligation_kind": str(obligation.get("obligation_kind") or ""),
                    "severity": str(obligation.get("severity") or ""),
                    "summary": str(obligation.get("summary") or ""),
                }
            )
    return hits


def _lineage_dependents(
    *,
    data_root: Path,
    artifact_id: str,
) -> list[dict[str, Any]]:
    dependents: list[dict[str, Any]] = []
    for edge in load_lineage_edges(data_root):
        if str(edge.get("source_id") or "").strip() != artifact_id:
            continue
        dependents.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "relation": str(edge.get("relation") or ""),
                "target_kind": str(edge.get("target_kind") or ""),
                "target_id": str(edge.get("target_id") or ""),
            }
        )
    return dependents


def evaluate_compaction_candidate(
    *,
    data_root: Path,
    artifact_family: str,
    artifact_id: str,
    artifact_path: str,
    target_temperature: str = "cold",
    is_current: bool = False,
    is_canonical: bool = False,
    source_refs: Iterable[dict[str, Any]] = (),
    stronger_successor_ids: Iterable[str] = (),
) -> dict[str, Any]:
    normalized_target = str(target_temperature or "").strip().lower()
    if normalized_target not in ALLOWED_TARGET_TEMPERATURES:
        raise CompactionPolicyError(f"Unsupported target_temperature: {target_temperature}")

    normalized_family = str(artifact_family or "").strip()
    normalized_id = str(artifact_id or "").strip()
    normalized_path = str(artifact_path or "").strip()
    if not normalized_family:
        raise CompactionPolicyError("artifact_family is required.")
    if not normalized_id:
        raise CompactionPolicyError("artifact_id is required.")
    if not normalized_path:
        raise CompactionPolicyError("artifact_path is required.")

    source_ref_payload = _normalize_refs(source_refs)
    successor_ids = _normalize_ids(stronger_successor_ids)
    blockers: list[str] = []
    warnings: list[str] = []

    if is_canonical:
        blockers.append("canonical_artifact")
    if is_current:
        blockers.append("current_artifact")
    if not Path(normalized_path).exists():
        blockers.append("artifact_path_missing")

    obligation_hits = _open_obligation_hits(
        data_root=data_root,
        artifact_path=normalized_path,
        source_refs=source_ref_payload,
    )
    if obligation_hits:
        blockers.append("open_obligation_reference")

    lineage_dependents = _lineage_dependents(
        data_root=data_root,
        artifact_id=normalized_id,
    )
    if not successor_ids:
        blockers.append("no_stronger_successor")
    unresolved_dependents = [
        item for item in lineage_dependents if str(item.get("target_id") or "").strip() not in successor_ids
    ]
    if unresolved_dependents:
        blockers.append("uncovered_lineage_dependents")
    elif successor_ids and not lineage_dependents:
        warnings.append("successor_ids_unreferenced_in_lineage")

    allowed_to_cool = not blockers
    return {
        "schema_version": COMPACTION_POLICY_SCHEMA_VERSION,
        "artifact_family": normalized_family,
        "artifact_id": normalized_id,
        "artifact_path": normalized_path,
        "target_temperature": normalized_target,
        "allowed_to_cool": allowed_to_cool,
        "allowed_to_delete": False,
        "blockers": blockers,
        "warnings": warnings,
        "required_receipts": [
            "lineage_safe_supersession",
            "open_obligation_clear",
            "archive_manifest_entry",
        ] if allowed_to_cool else [],
        "lineage_dependents": lineage_dependents,
        "open_obligation_hits": obligation_hits,
        "stronger_successor_ids": successor_ids,
        "source_ref_paths": [str(item.get("path") or "") for item in source_ref_payload if str(item.get("path") or "").strip()],
    }

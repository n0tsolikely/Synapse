"""Retention checks for lawful archive/cooling decisions."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable

from synapse_runtime.continuity_obligations import load_obligations
from synapse_runtime.draftshots import draftshot_summary, list_draftshot_revisions
from synapse_runtime.publication_candidates import list_publication_candidate_revisions, publication_candidate_summary
from synapse_runtime.snapshot_candidates import list_snapshot_candidate_revisions, snapshot_candidate_summary
from synapse_runtime.truth_drafts import truth_draft_summary
from synapse_runtime.kernel_types import stable_kernel_id
from synapse_runtime.lineage_store import load_lineage_edges


COMPACTION_POLICY_SCHEMA_VERSION = 1
ALLOWED_TARGET_TEMPERATURES = {"warm", "cold"}


class CompactionPolicyError(RuntimeError):
    """Raised when a compaction decision cannot be evaluated safely."""


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).astimezone().isoformat()


def compaction_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "COMPACTION"


def compaction_manifest_dir(data_root: Path, artifact_family: str) -> Path:
    return compaction_root(data_root) / str(artifact_family or "unknown").strip().lower()


def ensure_compaction_scaffold(data_root: Path) -> list[str]:
    root = compaction_root(data_root)
    if root.exists():
        return []
    root.mkdir(parents=True, exist_ok=True)
    return [str(root.resolve())]


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


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


def _latest_revision_by_family(revisions: Iterable[dict[str, Any]], family_key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in revisions:
        family_id = str(item.get(family_key) or "").strip()
        if not family_id:
            continue
        current = latest.get(family_id)
        if current is None or int(item.get("revision_number") or 0) > int(current.get("revision_number") or 0):
            latest[family_id] = item
    return latest


def _manifest_path(data_root: Path, artifact_family: str, artifact_id: str) -> Path:
    manifest_id = stable_kernel_id("COMPACTION", artifact_family, artifact_id)
    return compaction_manifest_dir(data_root, artifact_family) / f"COMPACTION__{manifest_id}.yaml"


def _record_manifest(
    *,
    data_root: Path,
    artifact_family: str,
    artifact_id: str,
    artifact_path: str,
    companion_paths: Iterable[str],
    stronger_successor_ids: Iterable[str],
    stronger_successor_paths: Iterable[str],
    source_refs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    ensure_compaction_scaffold(data_root)
    decision = evaluate_compaction_candidate(
        data_root=data_root,
        artifact_family=artifact_family,
        artifact_id=artifact_id,
        artifact_path=artifact_path,
        target_temperature="cold",
        source_refs=source_refs,
        stronger_successor_ids=stronger_successor_ids,
    )
    payload = {
        "schema_version": COMPACTION_POLICY_SCHEMA_VERSION,
        "recorded_at": _now_iso(),
        "artifact_family": artifact_family,
        "artifact_id": artifact_id,
        "artifact_path": artifact_path,
        "companion_paths": _normalize_ids(companion_paths),
        "target_temperature": decision["target_temperature"],
        "decision_status": "eligible" if decision["allowed_to_cool"] else "blocked",
        "decision": decision,
        "stronger_successor_ids": _normalize_ids(stronger_successor_ids),
        "stronger_successor_paths": _normalize_ids(stronger_successor_paths),
    }
    path = _manifest_path(data_root, artifact_family, artifact_id)
    _write_yaml(path, payload)
    return {**payload, "manifest_path": str(path.resolve())}


def list_compaction_manifests(data_root: Path) -> list[dict[str, Any]]:
    root = compaction_root(data_root)
    if not root.exists():
        return []
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/COMPACTION__*.yaml")):
        payload = _read_yaml(path)
        if not payload:
            continue
        payload["manifest_path"] = str(path.resolve())
        manifests.append(payload)
    return manifests


def refresh_superseded_revision_manifests(data_root: Path) -> dict[str, Any]:
    draftshot_revisions = list_draftshot_revisions(data_root)
    snapshot_revisions = list_snapshot_candidate_revisions(data_root)
    publication_revisions = list_publication_candidate_revisions(data_root)
    receipts: list[dict[str, Any]] = []

    latest_draftshots = _latest_revision_by_family(draftshot_revisions, "draftshot_family_id")
    for revision in draftshot_revisions:
        family_id = str(revision.get("draftshot_family_id") or "").strip()
        latest = latest_draftshots.get(family_id)
        if not latest or str(latest.get("revision_id") or "") == str(revision.get("revision_id") or ""):
            continue
        companion_paths = [str(revision.get("body_path") or "")]
        receipts.append(
            _record_manifest(
                data_root=data_root,
                artifact_family="draftshot_revision",
                artifact_id=str(revision.get("revision_id") or ""),
                artifact_path=str(revision.get("path") or ""),
                companion_paths=companion_paths,
                stronger_successor_ids=[str(latest.get("revision_id") or "")],
                stronger_successor_paths=[str(latest.get("path") or ""), str(latest.get("body_path") or "")],
                source_refs=[
                    {
                        "kind": "draftshot_body",
                        "id": str(revision.get("revision_id") or ""),
                        "path": str(revision.get("body_path") or ""),
                    }
                ],
            )
        )

    latest_snapshots = _latest_revision_by_family(snapshot_revisions, "candidate_family_id")
    for revision in snapshot_revisions:
        family_id = str(revision.get("candidate_family_id") or "").strip()
        latest = latest_snapshots.get(family_id)
        if not latest or str(latest.get("revision_id") or "") == str(revision.get("revision_id") or ""):
            continue
        receipts.append(
            _record_manifest(
                data_root=data_root,
                artifact_family="snapshot_candidate_revision",
                artifact_id=str(revision.get("revision_id") or ""),
                artifact_path=str(revision.get("path") or revision.get("manifest_path") or ""),
                companion_paths=[str(revision.get("body_path") or "")],
                stronger_successor_ids=[str(latest.get("revision_id") or "")],
                stronger_successor_paths=[str(latest.get("path") or latest.get("manifest_path") or ""), str(latest.get("body_path") or "")],
                source_refs=[
                    {
                        "kind": "snapshot_candidate_body",
                        "id": str(revision.get("revision_id") or ""),
                        "path": str(revision.get("body_path") or ""),
                    }
                ],
            )
        )

    latest_publications = _latest_revision_by_family(publication_revisions, "candidate_family_id")
    for revision in publication_revisions:
        family_id = str(revision.get("candidate_family_id") or "").strip()
        latest = latest_publications.get(family_id)
        if not latest or str(latest.get("revision_id") or "") == str(revision.get("revision_id") or ""):
            continue
        primary_path = str(revision.get("path") or revision.get("manifest_path") or revision.get("body_path") or "")
        latest_primary_path = str(latest.get("path") or latest.get("manifest_path") or latest.get("body_path") or "")
        body_path = str(revision.get("body_path") or "")
        receipts.append(
            _record_manifest(
                data_root=data_root,
                artifact_family="publication_candidate_revision",
                artifact_id=str(revision.get("revision_id") or ""),
                artifact_path=primary_path,
                companion_paths=[body_path] if body_path and body_path != primary_path else [],
                stronger_successor_ids=[str(latest.get("revision_id") or "")],
                stronger_successor_paths=[latest_primary_path, str(latest.get("body_path") or "")],
                source_refs=[
                    {
                        "kind": "publication_candidate_body",
                        "id": str(revision.get("revision_id") or ""),
                        "path": body_path or primary_path,
                    }
                ],
            )
        )

    return {
        "schema_version": COMPACTION_POLICY_SCHEMA_VERSION,
        "manifest_count": len(receipts),
        "manifest_paths": [str(item.get("manifest_path") or "") for item in receipts],
        "receipts": receipts,
    }


def compaction_summary(data_root: Path) -> dict[str, Any]:
    manifests = list_compaction_manifests(data_root)
    eligible = [item for item in manifests if str(item.get("decision_status") or "") == "eligible"]
    blocked = [item for item in manifests if str(item.get("decision_status") or "") == "blocked"]
    family_counts: dict[str, int] = {}
    for item in manifests:
        family = str(item.get("artifact_family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1

    draftshots = draftshot_summary(data_root)
    snapshots = snapshot_candidate_summary(data_root)
    publications = publication_candidate_summary(data_root)
    truth_drafts = truth_draft_summary(data_root)
    hot_memory_counts = {
        "draftshots": int(draftshots.get("active_draftshot_count") or 0),
        "snapshot_candidates": int(bool(snapshots.get("current_eod_candidate_path"))) + int(bool(snapshots.get("current_control_sync_candidate_path"))),
        "publication_candidates": int(bool(publications.get("current_story_candidate_path")))
        + int(bool(publications.get("current_vision_candidate_path")))
        + len(list(publications.get("current_codex_candidate_paths") or [])),
        "truth_drafts": int(truth_drafts.get("truth_draft_count") or 0),
    }
    warm_memory_counts = {
        "draftshot_revisions": len(list(draftshots.get("recent_draftshot_details") or [])),
        "snapshot_candidate_revisions": len(list(snapshots.get("recent_eod_candidate_details") or []))
        + len(list(snapshots.get("recent_control_sync_candidate_details") or [])),
        "publication_candidate_revisions": len(list(publications.get("recent_story_candidate_details") or []))
        + len(list(publications.get("recent_vision_candidate_details") or []))
        + len(list(publications.get("recent_codex_candidate_details") or [])),
        "compaction_candidates": len(manifests),
    }
    recent_details = [
        {
            "artifact_family": item.get("artifact_family"),
            "artifact_id": item.get("artifact_id"),
            "decision_status": item.get("decision_status"),
            "target_temperature": item.get("target_temperature"),
            "manifest_path": item.get("manifest_path"),
        }
        for item in manifests[-10:]
    ]
    return {
        "schema_version": COMPACTION_POLICY_SCHEMA_VERSION,
        "compaction_manifest_count": len(manifests),
        "eligible_cooling_manifest_count": len(eligible),
        "blocked_cooling_manifest_count": len(blocked),
        "compaction_family_counts": family_counts,
        "hot_memory_counts": hot_memory_counts,
        "warm_memory_counts": warm_memory_counts,
        "cold_memory_artifact_count": 0,
        "recent_compaction_manifest_details": recent_details,
    }

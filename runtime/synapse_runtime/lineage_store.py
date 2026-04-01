"""Source-linked lineage edge storage for governed working records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.kernel_types import LineageEdgeEnvelope, stable_kernel_id


LINEAGE_SCHEMA_VERSION = 1


class LineageStoreError(RuntimeError):
    """Raised when lineage edges cannot be stored or loaded safely."""


def lineage_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "LINEAGE"


def lineage_edges_dir(data_root: Path) -> Path:
    return lineage_root(data_root) / "EDGES"


def ensure_lineage_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    for path in (lineage_root(data_root), lineage_edges_dir(data_root)):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.resolve()))
    return created


def lineage_edge_filename(*, edge_id: str, relation: str) -> str:
    relation_slug = str(relation or "derived_from").strip().replace(" ", "_").replace("/", "_")
    return f"EDGE__{edge_id}__{relation_slug}.yaml"


def persist_lineage_edge(data_root: Path, edge: LineageEdgeEnvelope | dict[str, Any]) -> dict[str, Any]:
    ensure_lineage_scaffold(data_root)
    payload = edge.to_dict() if isinstance(edge, LineageEdgeEnvelope) else dict(edge)
    edge_id = str(payload.get("edge_id") or "").strip()
    if not edge_id:
        raise LineageStoreError("Lineage edge is missing edge_id.")
    relation = str(payload.get("relation") or "derived_from").strip() or "derived_from"
    path = lineage_edges_dir(data_root) / lineage_edge_filename(edge_id=edge_id, relation=relation)
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(payload)
            payload = merged
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {**payload, "path": str(path.resolve())}


def persist_lineage_edges(data_root: Path, edges: Iterable[LineageEdgeEnvelope | dict[str, Any]]) -> list[dict[str, Any]]:
    return [persist_lineage_edge(data_root, edge) for edge in edges]


def load_lineage_edges(data_root: Path) -> list[dict[str, Any]]:
    root = lineage_edges_dir(data_root)
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("EDGE__*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["path"] = str(path.resolve())
            records.append(payload)
    return records


def lineage_summary(data_root: Path) -> dict[str, Any]:
    edges = load_lineage_edges(data_root)
    by_relation: dict[str, int] = {}
    for edge in edges:
        relation = str(edge.get("relation") or "unknown")
        by_relation[relation] = by_relation.get(relation, 0) + 1
    return {
        "lineage_edge_count": len(edges),
        "lineage_relation_counts": by_relation,
        "recent_lineage_edge_ids": [str(item.get("edge_id")) for item in edges[-10:]],
    }


def build_lineage_edge(
    *,
    subject: str,
    recorded_at: str,
    source_kind: str,
    source_id: str,
    target_kind: str,
    target_id: str,
    relation: str,
    metadata: dict[str, Any] | None = None,
) -> LineageEdgeEnvelope:
    return LineageEdgeEnvelope(
        edge_id=stable_kernel_id("EDGE", subject, source_kind, source_id, relation, target_kind, target_id),
        schema_version=LINEAGE_SCHEMA_VERSION,
        recorded_at=recorded_at,
        subject=subject,
        source_kind=source_kind,
        source_id=source_id,
        target_kind=target_kind,
        target_id=target_id,
        relation=relation,
        metadata=dict(metadata or {}),
    )

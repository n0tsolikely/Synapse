"""Derived codex section packet storage and summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.kernel_types import stable_kernel_id


CODEX_PACKET_SCHEMA_VERSION = 1
SECTION_TITLES = {
    "ACTIVE_PLAN": "Active Plan",
    "ACTIVE_SCOPE": "Active Scope",
    "OPEN_OBLIGATIONS": "Open Continuity Obligations",
    "ARCHITECTURE_DELTA": "Architecture Delta",
    "IDENTITY_DELTA": "Identity Delta",
    "NARRATIVE_DELTA": "Narrative Delta",
}


class CodexPacketError(RuntimeError):
    """Raised when codex packets cannot be stored safely."""


def codex_packets_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "CODEX_SECTION_PACKETS"


def ensure_codex_packets_scaffold(data_root: Path) -> list[str]:
    root = codex_packets_root(data_root)
    if root.exists():
        return []
    root.mkdir(parents=True, exist_ok=True)
    return [str(root.resolve())]


def packet_filename(section_key: str) -> str:
    normalized = str(section_key or "").strip().upper()
    if not normalized:
        raise CodexPacketError("section_key must not be empty")
    return f"PACKET__{normalized}.yaml"


def packet_path(data_root: Path, section_key: str) -> Path:
    return codex_packets_root(data_root) / packet_filename(section_key)


def _normalize_source_refs(source_refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        source_id = str(item.get("id") or "").strip()
        path = str(item.get("path") or "").strip()
        key = (kind, source_id, path)
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        payload = {k: v for k, v in item.items() if v is not None}
        normalized.append(payload)
    return normalized


def _normalize_detail_lines(detail_lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in detail_lines:
        text = " ".join(str(raw or "").split()).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def build_codex_packet(
    *,
    subject: str,
    section_key: str,
    refreshed_at: str,
    summary: str,
    detail_lines: Iterable[str],
    source_refs: Iterable[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    section_title: str | None = None,
) -> dict[str, Any]:
    normalized_key = str(section_key or "").strip().upper()
    if not normalized_key:
        raise CodexPacketError("section_key must not be empty")
    normalized_summary = " ".join(str(summary or "").split()).strip()
    if not normalized_summary:
        raise CodexPacketError(f"summary must not be empty for codex packet {normalized_key}")
    normalized_source_refs = _normalize_source_refs(source_refs)
    if not normalized_source_refs:
        raise CodexPacketError(f"codex packet {normalized_key} requires at least one source ref")
    title = str(section_title or SECTION_TITLES.get(normalized_key) or normalized_key.title()).strip()
    source_signature = stable_kernel_id(
        "PACKSRC",
        subject,
        normalized_key,
        *(
            f"{item.get('kind')}|{item.get('id')}|{item.get('path')}"
            for item in normalized_source_refs
        ),
    )
    return {
        "packet_id": stable_kernel_id("PACKET", subject, normalized_key),
        "schema_version": CODEX_PACKET_SCHEMA_VERSION,
        "subject": subject,
        "section_key": normalized_key,
        "section_title": title,
        "canonical_status": "derived_noncanonical",
        "refreshed_at": str(refreshed_at or "").strip(),
        "summary": normalized_summary,
        "detail_lines": _normalize_detail_lines(detail_lines),
        "source_signature": source_signature,
        "source_ref_count": len(normalized_source_refs),
        "source_refs": normalized_source_refs,
        "metadata": dict(metadata or {}),
    }


def sync_codex_packets(data_root: Path, packets: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ensure_codex_packets_scaffold(data_root)
    root = codex_packets_root(data_root)
    written_paths: list[str] = []
    active_names: set[str] = set()
    for packet in packets:
        normalized = dict(packet)
        section_key = str(normalized.get("section_key") or "").strip().upper()
        if not section_key:
            raise CodexPacketError("codex packet missing section_key")
        path = packet_path(data_root, section_key)
        active_names.add(path.name)
        path.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
        written_paths.append(str(path.resolve()))

    removed_paths: list[str] = []
    for existing in sorted(root.glob("PACKET__*.yaml")):
        if existing.name in active_names:
            continue
        removed_paths.append(str(existing.resolve()))
        existing.unlink()

    return {
        "written_paths": written_paths,
        "removed_paths": removed_paths,
    }


def load_codex_packets(data_root: Path) -> list[dict[str, Any]]:
    root = codex_packets_root(data_root)
    if not root.exists():
        return []
    packets: list[dict[str, Any]] = []
    for path in sorted(root.glob("PACKET__*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        payload["path"] = str(path.resolve())
        packets.append(payload)
    return packets


def codex_packet_summary(data_root: Path) -> dict[str, Any]:
    packets = load_codex_packets(data_root)
    details = [
        {
            "packet_id": item.get("packet_id"),
            "section_key": item.get("section_key"),
            "section_title": item.get("section_title"),
            "summary": item.get("summary"),
            "refreshed_at": item.get("refreshed_at"),
            "source_ref_count": item.get("source_ref_count"),
            "path": item.get("path"),
        }
        for item in packets
    ]
    refreshed = [
        str(item.get("refreshed_at") or "").strip()
        for item in packets
        if str(item.get("refreshed_at") or "").strip()
    ]
    return {
        "codex_packet_count": len(packets),
        "last_codex_packet_refreshed_at": max(refreshed) if refreshed else None,
        "recent_codex_packet_details": details[-10:],
        "packet_section_keys": [str(item.get("section_key")) for item in packets if item.get("section_key")],
    }

"""Noncanonical publication candidate drafting and summaries."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable

import yaml

from synapse_runtime.codex_packets import load_codex_packets
from synapse_runtime.kernel_types import stable_kernel_id
from synapse_runtime.project_model import (
    render_draft_codex_current,
    render_draft_codex_future,
    render_project_story,
    render_published_vision,
)
from synapse_runtime.repo_onboarding import (
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
)
PUBLICATION_CANDIDATE_SCHEMA_VERSION = 1
STORY_KIND = "STORY"
VISION_KIND = "VISION"
CODEX_KIND = "CODEX"
PUBLICATION_CANDIDATE_KINDS = (STORY_KIND, VISION_KIND, CODEX_KIND)


class PublicationCandidateError(RuntimeError):
    """Raised when publication candidates cannot be stored safely."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc).astimezone()


def _now_iso() -> str:
    return _now().isoformat()


def _file_time(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).astimezone().isoformat()


def _parse_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text).astimezone().isoformat()
    except Exception:
        return None


def _normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip().upper()
    if normalized not in PUBLICATION_CANDIDATE_KINDS:
        raise PublicationCandidateError(f"Unsupported publication candidate kind: {kind}")
    return normalized


def publication_candidates_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "PUBLICATION_CANDIDATES"


def publication_candidate_kind_root(data_root: Path, kind: str) -> Path:
    return publication_candidates_root(data_root) / _normalize_kind(kind)


def publication_candidate_index_path(data_root: Path) -> Path:
    return publication_candidates_root(data_root) / "INDEX.yaml"


def ensure_publication_candidate_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    root = publication_candidates_root(data_root)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        created.append(str(root.resolve()))
    for kind in PUBLICATION_CANDIDATE_KINDS:
        kind_root = publication_candidate_kind_root(data_root, kind)
        if not kind_root.exists():
            kind_root.mkdir(parents=True, exist_ok=True)
            created.append(str(kind_root.resolve()))
    index_path = publication_candidate_index_path(data_root)
    if not index_path.exists():
        index_path.write_text(yaml.safe_dump(_default_index(), sort_keys=False), encoding="utf-8")
        created.append(str(index_path.resolve()))
    return created


def _default_index() -> dict[str, Any]:
    return {
        "schema_version": PUBLICATION_CANDIDATE_SCHEMA_VERSION,
        "current": {},
        "updated_at": None,
    }


def _read_yaml(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        return default
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if payload is None else payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _load_index(data_root: Path) -> dict[str, Any]:
    ensure_publication_candidate_scaffold(data_root)
    payload = _read_yaml(publication_candidate_index_path(data_root), default={})
    if not isinstance(payload, dict):
        return _default_index()
    merged = _default_index()
    merged.update(payload)
    merged["current"] = dict(payload.get("current") or {})
    return merged


def _write_index(data_root: Path, payload: dict[str, Any]) -> Path:
    normalized = dict(payload)
    normalized["schema_version"] = PUBLICATION_CANDIDATE_SCHEMA_VERSION
    normalized["updated_at"] = _now_iso()
    path = publication_candidate_index_path(data_root)
    _write_yaml(path, normalized)
    return path


def _candidate_family_id(subject: str, kind: str) -> str:
    return stable_kernel_id("PUBCAND", subject, _normalize_kind(kind))


def _candidate_revision_id(subject: str, kind: str, revision_number: int) -> str:
    return stable_kernel_id("PUBREV", subject, _normalize_kind(kind), f"REV{revision_number:03d}")


def _body_path(data_root: Path, kind: str, family_id: str, revision_number: int) -> Path:
    return publication_candidate_kind_root(data_root, kind) / f"CANDIDATE__{family_id}__REV{revision_number}.md"


def _manifest_path(data_root: Path, kind: str, family_id: str, revision_number: int) -> Path | None:
    if _normalize_kind(kind) != CODEX_KIND:
        return None
    return publication_candidate_kind_root(data_root, kind) / f"CANDIDATE__{family_id}__REV{revision_number}.yaml"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_refs(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        ref_id = str(item.get("id") or "").strip()
        path = str(item.get("path") or item.get("body_path") or "").strip()
        key = (kind, ref_id, path)
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return normalized


def _summary_item(summary: str) -> dict[str, Any]:
    return {"summary": _normalize_text(summary)}


def _dedupe_summary_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = _normalize_text(item.get("summary"))
        if not summary or summary in seen:
            continue
        seen.add(summary)
        payload = dict(item)
        payload["summary"] = summary
        normalized.append(payload)
    return normalized


def _load_baseline_model(data_root: Path) -> dict[str, Any]:
    payload = _read_yaml(canonical_project_model_path(data_root), default={})
    return payload if isinstance(payload, dict) else {}


def _baseline_ref(path: Path, *, baseline_kind: str, confirmed_at: str | None = None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return {
        "kind": "canonical_publication",
        "baseline_kind": baseline_kind,
        "path": str(path.resolve()),
        "confirmed_at": confirmed_at or _file_time(path),
    }


def _baseline_refs(data_root: Path, kind: str) -> list[dict[str, Any]]:
    baseline_model = _load_baseline_model(data_root)
    confirmed_at = _parse_time(baseline_model.get("confirmed_at")) if baseline_model else None
    refs: list[dict[str, Any]] = []
    model_ref = _baseline_ref(
        canonical_project_model_path(data_root),
        baseline_kind="PROJECT_MODEL",
        confirmed_at=confirmed_at,
    )
    if model_ref:
        refs.append(model_ref)
    if kind == STORY_KIND:
        ref = _baseline_ref(canonical_project_story_path(data_root), baseline_kind="PROJECT_STORY")
        if ref:
            refs.append(ref)
    elif kind == VISION_KIND:
        ref = _baseline_ref(canonical_vision_path(data_root), baseline_kind="VISION")
        if ref:
            refs.append(ref)
    else:
        current_ref = _baseline_ref(canonical_codex_current_path(data_root), baseline_kind="CODEX_CURRENT")
        future_ref = _baseline_ref(canonical_codex_future_path(data_root), baseline_kind="CODEX_FUTURE")
        if current_ref:
            refs.append(current_ref)
        if future_ref:
            refs.append(future_ref)
    return refs


def _packet_ref(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "codex_packet",
        "id": str(packet.get("packet_id") or ""),
        "path": str(packet.get("path") or ""),
        "section_key": str(packet.get("section_key") or ""),
    }


def _load_continuity_inputs(data_root: Path) -> dict[str, Any]:
    manifold = _read_yaml(data_root / ".synapse" / "MANIFOLD.yaml", default={})
    if not isinstance(manifold, dict):
        manifold = {}
    return {
        "active_plan_delta": dict(manifold.get("current_active_plan_delta") or {}),
        "active_scope_delta": dict(manifold.get("current_active_scope_delta") or {}),
        "obligation_delta": dict(manifold.get("current_obligation_delta") or {}),
        "architecture_delta": dict(manifold.get("current_architecture_delta") or {}),
        "identity_delta": dict(manifold.get("current_identity_delta") or {}),
        "narrative_delta": dict(manifold.get("current_narrative_delta") or {}),
        "last_synthesis_refresh_at": manifold.get("last_synthesis_refresh_at"),
    }


def _delta_summary(payload: dict[str, Any]) -> str:
    return _normalize_text(payload.get("summary"))


def _candidate_model(data_root: Path, continuity: dict[str, Any], packets: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_model = _load_baseline_model(data_root)
    active_plan = _delta_summary(continuity.get("active_plan_delta") or {})
    active_scope = _delta_summary(continuity.get("active_scope_delta") or {})
    obligation = _delta_summary(continuity.get("obligation_delta") or {})
    architecture = _delta_summary(continuity.get("architecture_delta") or {})
    identity = _delta_summary(continuity.get("identity_delta") or {})
    narrative = _delta_summary(continuity.get("narrative_delta") or {})

    implemented = list(baseline_model.get("implemented_truths") or baseline_model.get("confirmed_capabilities") or [])
    partial = list(baseline_model.get("partial_truths") or [])
    intended = list(baseline_model.get("intended_capabilities") or [])
    future = list(baseline_model.get("future_ideas_needing_expansion") or [])
    constraints = list(baseline_model.get("constraints") or [])
    superseded = list(baseline_model.get("superseded_directions") or baseline_model.get("stale_or_superseded_directions") or [])

    if active_scope:
        partial.append(_summary_item(active_scope))
    if architecture:
        partial.append(_summary_item(architecture))
    if active_plan:
        intended.append(_summary_item(active_plan))
    if narrative:
        future.append(_summary_item(narrative))
    if obligation:
        constraints.append(_summary_item(obligation))

    for packet in packets:
        summary = _normalize_text(packet.get("summary"))
        if not summary:
            continue
        section_key = str(packet.get("section_key") or "").strip().upper()
        if section_key == "ACTIVE_PLAN":
            intended.append(_summary_item(summary))
        elif section_key in {"ACTIVE_SCOPE", "ARCHITECTURE_DELTA"}:
            partial.append(_summary_item(summary))
        elif section_key == "OPEN_OBLIGATIONS":
            constraints.append(_summary_item(summary))
        elif section_key in {"IDENTITY_DELTA", "NARRATIVE_DELTA"}:
            future.append(_summary_item(summary))

    project_identity = _normalize_text(
        baseline_model.get("project_identity")
        or baseline_model.get("summary_hypothesis")
        or identity
        or active_scope
    ) or "Project identity candidate still forming."
    purpose = _normalize_text(
        baseline_model.get("purpose")
        or baseline_model.get("purpose_hypothesis")
        or active_plan
        or narrative
        or active_scope
    ) or "Purpose candidate still depends on current continuity evidence."
    current_vision = _normalize_text(
        narrative
        or baseline_model.get("vision")
        or baseline_model.get("current_vision")
        or baseline_model.get("vision_hypothesis")
        or identity
    ) or "Vision candidate still depends on current continuity evidence."

    return {
        "project_identity": project_identity,
        "purpose": purpose,
        "current_vision": current_vision,
        "implemented_truths": _dedupe_summary_items(implemented),
        "confirmed_capabilities": _dedupe_summary_items(implemented),
        "partial_truths": _dedupe_summary_items(partial),
        "intended_capabilities": _dedupe_summary_items(intended),
        "future_ideas_needing_expansion": _dedupe_summary_items(future),
        "constraints": _dedupe_summary_items(constraints),
        "superseded_directions": _dedupe_summary_items(superseded),
        "unresolved_nonblocking_questions": [],
    }


def _candidate_draft_view(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary_hypothesis": model.get("project_identity"),
        "purpose_hypothesis": model.get("purpose"),
        "vision_hypothesis": model.get("current_vision"),
        "maturity_hypothesis": "engaged_continuity_candidate",
        "implemented_truths": list(model.get("implemented_truths") or []),
        "partial_truths": list(model.get("partial_truths") or []),
        "intended_capabilities": list(model.get("intended_capabilities") or []),
        "future_ideas_needing_expansion": list(model.get("future_ideas_needing_expansion") or []),
        "superseded_directions": list(model.get("superseded_directions") or []),
        "constraint_hypotheses": list(model.get("constraints") or []),
        "non_goal_hypotheses": [],
        "open_unknowns": [],
        "component_hypotheses": [],
        "capability_hypotheses": [],
        "history_and_supersession_hypotheses": [],
    }


def _story_source_refs(continuity: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key in ("identity_delta", "narrative_delta", "active_scope_delta", "architecture_delta", "active_plan_delta"):
        refs.extend(list(dict(continuity.get(key) or {}).get("source_refs") or []))
    return _normalize_refs(refs)


def _codex_source_refs(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for packet in packets:
        refs.append(_packet_ref(packet))
        refs.extend(list(packet.get("source_refs") or []))
    return _normalize_refs(refs)


def _story_summary(model: dict[str, Any]) -> str:
    return _normalize_text(model.get("project_identity") or model.get("purpose")) or "Story candidate pending."


def _vision_summary(model: dict[str, Any]) -> str:
    return _normalize_text(model.get("current_vision") or model.get("project_identity")) or "Vision candidate pending."


def _codex_summary(packets: list[dict[str, Any]], model: dict[str, Any]) -> str:
    packet_sections = [str(item.get("section_key") or "").strip() for item in packets if item.get("section_key")]
    if packet_sections:
        return f"Codex candidate grounded in packets: {', '.join(packet_sections[:4])}"
    return _normalize_text(model.get("project_identity") or model.get("purpose")) or "Codex candidate pending."


def _candidate_signature(kind: str, source_refs: list[dict[str, Any]], baseline_refs: list[dict[str, Any]]) -> str:
    return stable_kernel_id(
        "PUBSIG",
        _normalize_kind(kind),
        *(
            f"{item.get('kind')}|{item.get('id')}|{item.get('path') or item.get('body_path')}"
            for item in _normalize_refs(list(source_refs) + list(baseline_refs))
        ),
    )


def _candidate_allowed(kind: str, *, continuity: dict[str, Any], packets: list[dict[str, Any]]) -> bool:
    normalized = _normalize_kind(kind)
    if normalized == CODEX_KIND:
        return bool(packets)
    relevant = (
        _delta_summary(continuity.get("identity_delta") or {}),
        _delta_summary(continuity.get("narrative_delta") or {}),
        _delta_summary(continuity.get("active_scope_delta") or {}),
        _delta_summary(continuity.get("active_plan_delta") or {}),
        _delta_summary(continuity.get("architecture_delta") or {}),
    )
    return any(relevant) or bool(packets)


def _frontmatter_text(manifest: dict[str, Any], body: str) -> str:
    return f"---\n{yaml.safe_dump(manifest, sort_keys=False).strip()}\n---\n\n{body.rstrip()}\n"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise PublicationCandidateError("Candidate markdown file is missing YAML frontmatter.")
    marker = "\n---\n"
    end = text.find(marker, 4)
    if end == -1:
        raise PublicationCandidateError("Candidate markdown file has malformed YAML frontmatter.")
    frontmatter = yaml.safe_load(text[4:end])
    if not isinstance(frontmatter, dict):
        raise PublicationCandidateError("Candidate markdown frontmatter must be a mapping.")
    body = text[end + len(marker) :]
    return frontmatter, body


def _load_story_or_vision_candidate(path: Path) -> dict[str, Any]:
    manifest, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    manifest["body_path"] = str(path.resolve())
    manifest["path"] = str(path.resolve())
    return manifest


def _load_codex_candidate_manifest(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path, default={})
    if not isinstance(payload, dict):
        raise PublicationCandidateError(f"Malformed codex candidate manifest: {path}")
    payload["path"] = str(path.resolve())
    return payload


def _candidate_detail(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_kind": manifest.get("candidate_kind"),
        "candidate_family_id": manifest.get("candidate_family_id"),
        "revision_id": manifest.get("revision_id"),
        "revision_number": manifest.get("revision_number"),
        "summary": manifest.get("summary"),
        "refreshed_at": manifest.get("refreshed_at"),
        "body_path": manifest.get("body_path"),
        "manifest_path": manifest.get("path"),
        "source_ref_count": len(list(manifest.get("source_refs") or [])),
        "baseline_ref_count": len(list(manifest.get("baseline_refs") or [])),
        "baseline_refs": list(manifest.get("baseline_refs") or []),
        "source_refs": list(manifest.get("source_refs") or []),
    }


def list_publication_candidate_revisions(data_root: Path, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_publication_candidate_scaffold(data_root)
    manifests: list[dict[str, Any]] = []
    kinds = [_normalize_kind(kind)] if kind else list(PUBLICATION_CANDIDATE_KINDS)
    for item_kind in kinds:
        root = publication_candidate_kind_root(data_root, item_kind)
        if item_kind == CODEX_KIND:
            for path in sorted(root.glob("CANDIDATE__*.yaml")):
                manifests.append(_load_codex_candidate_manifest(path))
        else:
            for path in sorted(root.glob("CANDIDATE__*.md")):
                manifests.append(_load_story_or_vision_candidate(path))
    return manifests


def load_current_publication_candidate(data_root: Path, kind: str) -> dict[str, Any] | None:
    current = dict(_load_index(data_root).get("current") or {}).get(_normalize_kind(kind)) or {}
    manifest_path = str(current.get("manifest_path") or "").strip()
    body_path = str(current.get("body_path") or "").strip()
    if _normalize_kind(kind) == CODEX_KIND:
        if not manifest_path:
            return None
        path = Path(manifest_path)
        if not path.exists():
            return None
        return _load_codex_candidate_manifest(path)
    if not body_path:
        return None
    path = Path(body_path)
    if not path.exists():
        return None
    return _load_story_or_vision_candidate(path)


def publication_candidate_summary(data_root: Path) -> dict[str, Any]:
    story = load_current_publication_candidate(data_root, STORY_KIND)
    vision = load_current_publication_candidate(data_root, VISION_KIND)
    codex = load_current_publication_candidate(data_root, CODEX_KIND)
    revisions = list_publication_candidate_revisions(data_root)
    refreshed = [
        str(item.get("refreshed_at") or "").strip()
        for item in (story, vision, codex)
        if item and str(item.get("refreshed_at") or "").strip()
    ]
    return {
        "publication_candidate_schema_version": PUBLICATION_CANDIDATE_SCHEMA_VERSION,
        "current_story_candidate_path": story.get("body_path") if story else None,
        "current_vision_candidate_path": vision.get("body_path") if vision else None,
        "current_codex_candidate_paths": [codex.get("body_path")] if codex and codex.get("body_path") else [],
        "current_story_candidate_summary": story.get("summary") if story else None,
        "current_vision_candidate_summary": vision.get("summary") if vision else None,
        "current_codex_candidate_summary": codex.get("summary") if codex else None,
        "current_story_candidate_refreshed_at": story.get("refreshed_at") if story else None,
        "current_vision_candidate_refreshed_at": vision.get("refreshed_at") if vision else None,
        "current_codex_candidate_refreshed_at": codex.get("refreshed_at") if codex else None,
        "current_publication_candidate_refreshed_at": max(refreshed) if refreshed else None,
        "recent_story_candidate_details": [
            _candidate_detail(item)
            for item in revisions
            if str(item.get("candidate_kind") or "").strip().upper() == STORY_KIND
        ][-5:],
        "recent_vision_candidate_details": [
            _candidate_detail(item)
            for item in revisions
            if str(item.get("candidate_kind") or "").strip().upper() == VISION_KIND
        ][-5:],
        "recent_codex_candidate_details": [
            _candidate_detail(item)
            for item in revisions
            if str(item.get("candidate_kind") or "").strip().upper() == CODEX_KIND
        ][-5:],
        "index_path": str(publication_candidate_index_path(data_root).resolve()),
        "current_index": dict(_load_index(data_root).get("current") or {}),
    }


def _story_body(*, summary: str, rendered_story: str, baseline_refs: list[dict[str, Any]], source_refs: list[dict[str, Any]]) -> str:
    lines = [
        "# Project Story Candidate",
        "",
        "## Candidate Summary",
        summary,
        "",
        "## Canonical Baseline Refs",
    ]
    lines.extend(
        [
            f"- [{item.get('baseline_kind')}] {item.get('path')} (confirmed_at={item.get('confirmed_at') or 'unknown'})"
            for item in baseline_refs
        ]
        or ["- none"]
    )
    lines.extend(
        [
            "",
            "## Rendered Candidate",
            rendered_story.replace("# Project Story", "### Story View", 1).rstrip(),
            "",
            "## Source Refs",
        ]
    )
    lines.extend(
        [
            f"- [{item.get('kind')}] {item.get('id')} :: {item.get('path') or item.get('body_path') or 'n/a'}"
            for item in source_refs
        ]
        or ["- none"]
    )
    lines.append("")
    return "\n".join(lines)


def _vision_body(*, summary: str, rendered_vision: str, baseline_refs: list[dict[str, Any]], source_refs: list[dict[str, Any]]) -> str:
    lines = [
        "# Vision Candidate",
        "",
        "## Candidate Summary",
        summary,
        "",
        "## Canonical Baseline Refs",
    ]
    lines.extend(
        [
            f"- [{item.get('baseline_kind')}] {item.get('path')} (confirmed_at={item.get('confirmed_at') or 'unknown'})"
            for item in baseline_refs
        ]
        or ["- none"]
    )
    lines.extend(
        [
            "",
            "## Rendered Candidate",
            rendered_vision.replace("# Vision (Published)", "### Vision View", 1).rstrip(),
            "",
            "## Source Refs",
        ]
    )
    lines.extend(
        [
            f"- [{item.get('kind')}] {item.get('id')} :: {item.get('path') or item.get('body_path') or 'n/a'}"
            for item in source_refs
        ]
        or ["- none"]
    )
    lines.append("")
    return "\n".join(lines)


def _codex_body(
    *,
    summary: str,
    rendered_current: str,
    rendered_future: str,
    baseline_refs: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    packets: list[dict[str, Any]],
) -> str:
    lines = [
        "# Codex Candidate",
        "",
        "## Candidate Summary",
        summary,
        "",
        "## Canonical Baseline Refs",
    ]
    lines.extend(
        [
            f"- [{item.get('baseline_kind')}] {item.get('path')} (confirmed_at={item.get('confirmed_at') or 'unknown'})"
            for item in baseline_refs
        ]
        or ["- none"]
    )
    lines.extend(
        [
            "",
            "## Current Codex View",
            rendered_current.replace("# Current Codex", "### Current Codex", 1).rstrip(),
            "",
            "## Future Codex View",
            rendered_future.replace("# Future Codex", "### Future Codex", 1).rstrip(),
            "",
            "## Packet Inputs",
        ]
    )
    lines.extend(
        [
            f"- [{item.get('section_key')}] {item.get('summary')}"
            for item in packets
            if _normalize_text(item.get("summary"))
        ]
        or ["- none"]
    )
    lines.extend(["", "## Source Refs"])
    lines.extend(
        [
            f"- [{item.get('kind')}] {item.get('id')} :: {item.get('path') or item.get('body_path') or 'n/a'}"
            for item in source_refs
        ]
        or ["- none"]
    )
    lines.append("")
    return "\n".join(lines)


def _write_story_or_vision_candidate(
    *,
    path: Path,
    manifest: dict[str, Any],
    body: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_frontmatter_text(manifest, body), encoding="utf-8")


def refresh_publication_candidates(
    *,
    subject: str,
    data_root: Path,
    candidate_kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    ensure_publication_candidate_scaffold(data_root)
    continuity = _load_continuity_inputs(data_root)
    packets = load_codex_packets(data_root)
    model = _candidate_model(data_root, continuity, packets)
    refreshed_at = str(continuity.get("last_synthesis_refresh_at") or _now_iso())
    index = _load_index(data_root)
    current = dict(index.get("current") or {})
    results: list[dict[str, Any]] = []

    for kind in [_normalize_kind(kind) for kind in (candidate_kinds or PUBLICATION_CANDIDATE_KINDS)]:
        if not _candidate_allowed(kind, continuity=continuity, packets=packets):
            results.append({"candidate_kind": kind, "status": "noop", "reason": "threshold_not_met"})
            continue

        baseline_refs = _baseline_refs(data_root, kind)
        if kind == CODEX_KIND:
            source_refs = _codex_source_refs(packets)
            summary = _codex_summary(packets, model)
        else:
            source_refs = _story_source_refs(continuity)
            summary = _story_summary(model) if kind == STORY_KIND else _vision_summary(model)

        if not source_refs:
            results.append({"candidate_kind": kind, "status": "noop", "reason": "no_material_sources"})
            continue

        source_signature = _candidate_signature(kind, source_refs, baseline_refs)
        current_manifest = load_current_publication_candidate(data_root, kind)
        if current_manifest and str(current_manifest.get("source_signature") or "") == source_signature:
            results.append(
                {
                    "candidate_kind": kind,
                    "status": "noop",
                    "reason": "unchanged_source_signature",
                    "revision_id": current_manifest.get("revision_id"),
                    "body_path": current_manifest.get("body_path"),
                    "manifest_path": current_manifest.get("path"),
                }
            )
            continue

        family_id = _candidate_family_id(subject, kind)
        revision_number = int(current_manifest.get("revision_number") or 0) + 1 if current_manifest else 1
        revision_id = _candidate_revision_id(subject, kind, revision_number)
        body_path = _body_path(data_root, kind, family_id, revision_number)
        manifest_path = _manifest_path(data_root, kind, family_id, revision_number)

        manifest = {
            "schema_version": PUBLICATION_CANDIDATE_SCHEMA_VERSION,
            "candidate_kind": kind,
            "subject": subject,
            "candidate_family_id": family_id,
            "revision_id": revision_id,
            "revision_number": revision_number,
            "status": "DRAFT",
            "canonical_status": "noncanonical_candidate",
            "refreshed_at": refreshed_at,
            "summary": summary,
            "body_path": str(body_path.resolve()),
            "source_signature": source_signature,
            "source_refs": source_refs,
            "baseline_refs": baseline_refs,
        }

        if kind == STORY_KIND:
            body = _story_body(
                summary=summary,
                rendered_story=render_project_story(model),
                baseline_refs=baseline_refs,
                source_refs=source_refs,
            )
            _write_story_or_vision_candidate(path=body_path, manifest=manifest, body=body)
            entry = {
                "candidate_family_id": family_id,
                "revision_id": revision_id,
                "body_path": str(body_path.resolve()),
                "manifest_path": None,
                "refreshed_at": refreshed_at,
                "summary": summary,
                "source_signature": source_signature,
            }
        elif kind == VISION_KIND:
            body = _vision_body(
                summary=summary,
                rendered_vision=render_published_vision(model),
                baseline_refs=baseline_refs,
                source_refs=source_refs,
            )
            _write_story_or_vision_candidate(path=body_path, manifest=manifest, body=body)
            entry = {
                "candidate_family_id": family_id,
                "revision_id": revision_id,
                "body_path": str(body_path.resolve()),
                "manifest_path": None,
                "refreshed_at": refreshed_at,
                "summary": summary,
                "source_signature": source_signature,
            }
        else:
            body = _codex_body(
                summary=summary,
                rendered_current=render_draft_codex_current(_candidate_draft_view(model)),
                rendered_future=render_draft_codex_future(_candidate_draft_view(model)),
                baseline_refs=baseline_refs,
                source_refs=source_refs,
                packets=packets,
            )
            body_path.write_text(body, encoding="utf-8")
            _write_yaml(manifest_path, manifest)
            entry = {
                "candidate_family_id": family_id,
                "revision_id": revision_id,
                "body_path": str(body_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "refreshed_at": refreshed_at,
                "summary": summary,
                "source_signature": source_signature,
            }

        current[kind] = entry
        results.append(
            {
                "candidate_kind": kind,
                "status": "written",
                "revision_id": revision_id,
                "body_path": str(body_path.resolve()),
                "manifest_path": str(manifest_path.resolve()) if manifest_path else None,
                "summary": summary,
            }
        )

    index["current"] = current
    index_path = _write_index(data_root, index)
    summary = publication_candidate_summary(data_root)
    return {
        "status": "written" if any(item.get("status") == "written" for item in results) else "noop",
        "candidates": results,
        "summary": summary,
        "index_path": str(index_path.resolve()),
    }

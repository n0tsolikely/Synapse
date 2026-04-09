"""Typed noncanonical snapshot candidate runtime owner."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.canonizer import CANONIZER_SCHEMA_VERSION, render_snapshot_candidate_body
from synapse_runtime.draftshots import load_active_draftshot
from synapse_runtime.kernel_types import stable_kernel_id
from synapse_runtime.sidecar_store import live_root


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
SNAPSHOT_CANDIDATE_SCHEMA_VERSION = 1
EOD_KIND = "EOD"
CONTROL_SYNC_KIND = "CONTROL_SYNC"
SNAPSHOT_CANDIDATE_KINDS = (EOD_KIND, CONTROL_SYNC_KIND)


class SnapshotCandidateError(RuntimeError):
    """Raised when typed snapshot candidates cannot be refreshed safely."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _read_yaml(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else dict(default or {})


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def snapshot_candidate_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "SNAPSHOT_CANDIDATES"


def snapshot_candidate_kind_root(data_root: Path, kind: str) -> Path:
    normalized = _normalize_kind(kind)
    return snapshot_candidate_root(data_root) / normalized


def snapshot_candidate_index_path(data_root: Path) -> Path:
    return snapshot_candidate_root(data_root) / "INDEX.yaml"


def ensure_snapshot_candidate_scaffold(data_root: Path) -> list[str]:
    created: list[str] = []
    for path in (
        snapshot_candidate_root(data_root),
        snapshot_candidate_kind_root(data_root, EOD_KIND),
        snapshot_candidate_kind_root(data_root, CONTROL_SYNC_KIND),
    ):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.resolve()))
    return created


def _normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip().upper().replace("-", "_")
    if normalized not in SNAPSHOT_CANDIDATE_KINDS:
        raise SnapshotCandidateError(f"Unknown snapshot candidate kind: {kind}")
    return normalized


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
        if not any(key) or key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return normalized


def _normalize_lines(lines: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = " ".join(str(raw or "").split()).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _target_day(payload: dict[str, Any]) -> str:
    refreshed_at = str(payload.get("refreshed_at") or "").strip()
    if refreshed_at and "T" in refreshed_at:
        return refreshed_at.split("T", 1)[0]
    return _now().date().isoformat()


def _family_id(subject: str, kind: str, target_day: str) -> str:
    return stable_kernel_id("SNAPSHOTCAND", subject, kind, target_day)


def _revision_id(subject: str, kind: str, target_day: str, revision_number: int) -> str:
    return stable_kernel_id("SNAPSHOTREV", subject, kind, target_day, revision_number)


def _manifest_path(data_root: Path, kind: str, family_id: str, revision_number: int) -> Path:
    return snapshot_candidate_kind_root(data_root, kind) / f"CANDIDATE__{family_id}__REV{revision_number}.yaml"


def _body_path(data_root: Path, kind: str, family_id: str, revision_number: int) -> Path:
    return snapshot_candidate_kind_root(data_root, kind) / f"CANDIDATE__{family_id}__REV{revision_number}.md"


def _record_time(payload: dict[str, Any]) -> str:
    text = str(payload.get("refreshed_at") or payload.get("created_at") or "").strip()
    return text or _now_iso()


def _load_index(data_root: Path) -> dict[str, Any]:
    return _read_yaml(
        snapshot_candidate_index_path(data_root),
        default={
            "schema_version": SNAPSHOT_CANDIDATE_SCHEMA_VERSION,
            "current": {},
            "latest_revision": None,
        },
    )


def _save_index(data_root: Path, payload: dict[str, Any]) -> None:
    _write_yaml(snapshot_candidate_index_path(data_root), payload)


def _load_manifest(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = _read_yaml(Path(str(path)))
    if not payload:
        return None
    payload["path"] = str(Path(str(path)).resolve())
    return payload


def list_snapshot_candidate_revisions(data_root: Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    kinds = (_normalize_kind(kind),) if kind else SNAPSHOT_CANDIDATE_KINDS
    revisions: list[dict[str, Any]] = []
    for candidate_kind in kinds:
        root = snapshot_candidate_kind_root(data_root, candidate_kind)
        if not root.exists():
            continue
        for path in sorted(root.glob("CANDIDATE__*.yaml")):
            payload = _load_manifest(path)
            if payload is None:
                continue
            revisions.append(payload)
    return sorted(revisions, key=_record_time)


def load_current_snapshot_candidate(data_root: Path, kind: str) -> dict[str, Any] | None:
    current = dict(_load_index(data_root).get("current") or {})
    pointer = current.get(_normalize_kind(kind))
    if not isinstance(pointer, dict):
        return None
    return _load_manifest(pointer.get("manifest_path"))


def _load_synthesis_from_projection(data_root: Path) -> dict[str, Any]:
    manifold = _read_yaml(
        live_root(data_root) / "MANIFOLD.yaml",
        default={},
    )
    return {
        "refreshed_at": str(manifold.get("last_synthesis_refresh_at") or "").strip() or _now_iso(),
        "active_plan_delta": dict(manifold.get("current_active_plan_delta") or {}),
        "active_scope_delta": dict(manifold.get("current_active_scope_delta") or {}),
        "obligation_delta": dict(manifold.get("current_obligation_delta") or {}),
        "architecture_delta": dict(manifold.get("current_architecture_delta") or {}),
        "identity_delta": dict(manifold.get("current_identity_delta") or {}),
        "narrative_delta": dict(manifold.get("current_narrative_delta") or {}),
        "imported_continuity_delta": dict(manifold.get("current_imported_continuity_delta") or {}),
    }


def _load_active_run(data_root: Path) -> dict[str, Any]:
    return _read_yaml(live_root(data_root) / "ACTIVE_RUN.yaml", default={})


def _imported_candidate_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    metadata = dict(data.get("metadata") or {})
    source_refs = [
        dict(item)
        for item in data.get("source_refs") or []
        if isinstance(item, dict) and bool(item.get("requires_import_review")) is not None
    ]
    return {
        "imported_evidence_refs": source_refs,
        "imported_confidence_band": metadata.get("imported_confidence_band"),
        "requires_import_review": bool(metadata.get("requires_import_review")),
        "imported_source_count": int(metadata.get("imported_source_count") or 0),
        "snapshot_candidate_eligible": bool(metadata.get("snapshot_candidate_eligible")),
    }


def _collect_candidate_sources(
    *,
    kind: str,
    draftshot: dict[str, Any],
    synthesis: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], str, dict[str, Any], dict[str, list[str]]]:
    refs: list[dict[str, Any]] = []
    detail_lines: list[str] = []
    authored_sections = {
        "truths": [],
        "visions": [],
        "unresolved": [],
    }

    draftshot_ref = {
        "kind": "draftshot_revision",
        "id": str(draftshot.get("revision_id") or ""),
        "path": str(draftshot.get("path") or ""),
        "body_path": str(draftshot.get("body_path") or ""),
        "session_id": str(draftshot.get("session_id") or ""),
    }
    refs.append(draftshot_ref)

    delta_keys = {
        EOD_KIND: (
            ("active_plan_delta", "Plan"),
            ("active_scope_delta", "Scope"),
            ("obligation_delta", "Obligations"),
            ("architecture_delta", "Architecture"),
        ),
        CONTROL_SYNC_KIND: (
            ("active_scope_delta", "Scope"),
            ("architecture_delta", "Architecture"),
            ("identity_delta", "Identity"),
            ("narrative_delta", "Narrative"),
            ("obligation_delta", "Governance"),
        ),
    }[_normalize_kind(kind)]

    summary_parts: list[str] = []
    for key, label in delta_keys:
        payload = synthesis.get(key)
        if not isinstance(payload, dict):
            continue
        summary = " ".join(str(payload.get("summary") or "").split()).strip()
        if summary:
            summary_parts.append(f"{label}: {summary}")
            detail_lines.append(f"{label}: {summary}")
            if label in {"Identity", "Narrative"}:
                authored_sections["visions"].append(f"{label}: {summary}")
            elif label in {"Obligations", "Governance"}:
                authored_sections["unresolved"].append(f"{label}: {summary}")
            else:
                authored_sections["truths"].append(f"{label}: {summary}")
        for line in list(payload.get("detail_lines") or [])[:4]:
            text = " ".join(str(line or "").split()).strip()
            if text:
                detail_lines.append(f"{label}: {text}")
                if label in {"Identity", "Narrative"}:
                    authored_sections["visions"].append(f"{label}: {text}")
                elif label in {"Obligations", "Governance"}:
                    authored_sections["unresolved"].append(f"{label}: {text}")
                else:
                    authored_sections["truths"].append(f"{label}: {text}")
        refs.extend(payload.get("source_refs") or [])

    if not summary_parts:
        summary_parts.append("Draftshot continuity is present but synthesis deltas are still thin.")

    imported_delta = dict(synthesis.get("imported_continuity_delta") or {})
    imported_metadata = _imported_candidate_metadata(imported_delta)
    if imported_metadata.get("snapshot_candidate_eligible"):
        imported_summary = " ".join(str(imported_delta.get("summary") or "").split()).strip()
        if imported_summary:
            summary_parts.append(f"Imported Continuity: {imported_summary}")
            detail_lines.append(f"Imported Continuity: {imported_summary}")
            target = "unresolved" if imported_metadata.get("requires_import_review") else "truths"
            authored_sections[target].append(f"Imported Continuity: {imported_summary}")
        for line in list(imported_delta.get("detail_lines") or [])[:4]:
            text = " ".join(str(line or "").split()).strip()
            if text:
                detail_lines.append(f"Imported Continuity: {text}")
                target = "unresolved" if imported_metadata.get("requires_import_review") else "truths"
                authored_sections[target].append(f"Imported Continuity: {text}")
        refs.extend(imported_metadata.get("imported_evidence_refs") or [])

    summary = summary_parts[0] if len(summary_parts) == 1 else " | ".join(summary_parts[:3])
    return _normalize_source_refs(refs), _normalize_lines(detail_lines), summary, imported_metadata, authored_sections


def _candidate_signature(kind: str, target_day: str, source_refs: Iterable[dict[str, Any]]) -> str:
    normalized = _normalize_source_refs(source_refs)
    return stable_kernel_id(
        "SNAPSHOTSRC",
        kind,
        target_day,
        *(
            f"{item.get('kind')}|{item.get('id')}|{item.get('path') or item.get('body_path')}"
            for item in normalized
        ),
    )


def _candidate_allowed(kind: str, synthesis: dict[str, Any], active_run: dict[str, Any]) -> bool:
    normalized = _normalize_kind(kind)
    if normalized == EOD_KIND:
        return any(
            str(dict(synthesis.get(key) or {}).get("summary") or "").strip()
            for key in ("active_plan_delta", "active_scope_delta", "obligation_delta", "architecture_delta")
        ) or bool(dict(dict(synthesis.get("imported_continuity_delta") or {}).get("metadata") or {}).get("snapshot_candidate_eligible"))
    session_mode = str(active_run.get("session_mode") or "").strip()
    if session_mode == "control_sync":
        return True
    return any(
        str(dict(synthesis.get(key) or {}).get("summary") or "").strip()
        for key in ("active_scope_delta", "architecture_delta", "identity_delta", "narrative_delta", "obligation_delta")
    ) or bool(dict(dict(synthesis.get("imported_continuity_delta") or {}).get("metadata") or {}).get("snapshot_candidate_eligible"))


def _candidate_detail(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not manifest:
        return None
    return {
        "candidate_kind": manifest.get("candidate_kind"),
        "candidate_family_id": manifest.get("candidate_family_id"),
        "revision_id": manifest.get("revision_id"),
        "revision_number": manifest.get("revision_number"),
        "target_day": manifest.get("target_day"),
        "status": manifest.get("status"),
        "summary": manifest.get("summary"),
        "refreshed_at": manifest.get("refreshed_at"),
        "manifest_path": manifest.get("path") or manifest.get("manifest_path"),
        "body_path": manifest.get("body_path"),
        "draftshot_revision_id": manifest.get("draftshot_revision_id"),
        "source_ref_count": manifest.get("source_ref_count"),
        "imported_confidence_band": manifest.get("imported_confidence_band"),
        "requires_import_review": manifest.get("requires_import_review"),
        "imported_source_count": manifest.get("imported_source_count"),
        "truth_state_counts": dict(dict(manifest.get("canonizer_sections") or {}).get("truth_state_counts") or {}),
    }


def snapshot_candidate_summary(data_root: Path) -> dict[str, Any]:
    index = _load_index(data_root)
    current = dict(index.get("current") or {})
    eod = load_current_snapshot_candidate(data_root, EOD_KIND)
    control_sync = load_current_snapshot_candidate(data_root, CONTROL_SYNC_KIND)
    revisions = list_snapshot_candidate_revisions(data_root)
    latest_manifest = max(revisions, key=_record_time) if revisions else None
    latest_active_draftshot = load_active_draftshot(data_root, session_id=None)
    latest_draftshot_day = str(latest_active_draftshot.get("refreshed_at") or "").split("T", 1)[0] if latest_active_draftshot else None
    current_eod_target_day = str(eod.get("target_day") or "").strip() or None if eod else None
    current_control_sync_target_day = str(control_sync.get("target_day") or "").strip() or None if control_sync else None
    stale_prior_day_candidate_required = bool(
        latest_draftshot_day
        and latest_draftshot_day < _now().date().isoformat()
        and current_eod_target_day != latest_draftshot_day
    )

    open_obligations = []
    try:
        from synapse_runtime.continuity_obligations import load_obligations

        open_obligations = [
            item
            for item in load_obligations(data_root)
            if str(item.get("state") or "open").strip().lower() == "open"
            and str(item.get("obligation_kind") or "").strip().lower().startswith("snapshot.")
        ]
    except Exception:
        open_obligations = []

    return {
        "snapshot_candidate_schema_version": SNAPSHOT_CANDIDATE_SCHEMA_VERSION,
        "current_eod_candidate_path": eod.get("body_path") if eod else None,
        "current_control_sync_candidate_path": control_sync.get("body_path") if control_sync else None,
        "current_eod_candidate_manifest_path": eod.get("path") if eod else None,
        "current_control_sync_candidate_manifest_path": control_sync.get("path") if control_sync else None,
        "current_eod_candidate_refreshed_at": eod.get("refreshed_at") if eod else None,
        "current_control_sync_candidate_refreshed_at": control_sync.get("refreshed_at") if control_sync else None,
        "current_eod_candidate_target_day": current_eod_target_day,
        "current_control_sync_candidate_target_day": current_control_sync_target_day,
        "current_eod_candidate_summary": eod.get("summary") if eod else None,
        "current_control_sync_candidate_summary": control_sync.get("summary") if control_sync else None,
        "current_eod_candidate_truth_state_counts": dict(dict(eod.get("canonizer_sections") or {}).get("truth_state_counts") or {}) if eod else {},
        "current_control_sync_candidate_truth_state_counts": dict(dict(control_sync.get("canonizer_sections") or {}).get("truth_state_counts") or {}) if control_sync else {},
        "current_snapshot_candidate_path": latest_manifest.get("body_path") if latest_manifest else None,
        "current_snapshot_candidate_manifest_path": latest_manifest.get("path") if latest_manifest else None,
        "current_snapshot_candidate_kind": latest_manifest.get("candidate_kind") if latest_manifest else None,
        "stale_prior_day_candidate_required": stale_prior_day_candidate_required,
        "candidate_obligation_count": len(open_obligations),
        "recent_eod_candidate_details": [
            item
            for item in (_candidate_detail(manifest) for manifest in revisions if str(manifest.get("candidate_kind")) == EOD_KIND)
            if item is not None
        ][-5:],
        "recent_control_sync_candidate_details": [
            item
            for item in (
                _candidate_detail(manifest)
                for manifest in revisions
                if str(manifest.get("candidate_kind")) == CONTROL_SYNC_KIND
            )
            if item is not None
        ][-5:],
        "index_path": str(snapshot_candidate_index_path(data_root).resolve()),
        "current_index": current,
    }


def refresh_snapshot_candidates(
    *,
    subject: str,
    data_root: Path,
    session_id: str | None = None,
    synthesis: dict[str, Any] | None = None,
    candidate_kinds: Iterable[str] | None = None,
    target_day: str | None = None,
    prefer_latest_active_draftshot: bool = False,
) -> dict[str, Any]:
    ensure_snapshot_candidate_scaffold(data_root)
    synthesis_payload = dict(synthesis or _load_synthesis_from_projection(data_root))
    refreshed_at = str(synthesis_payload.get("refreshed_at") or _now_iso())
    active_run = _load_active_run(data_root)
    effective_session_id = str(session_id or active_run.get("session_id") or "").strip() or None
    draftshot = load_active_draftshot(data_root, session_id=effective_session_id) if effective_session_id else None
    if draftshot is None and prefer_latest_active_draftshot:
        draftshot = load_active_draftshot(data_root, session_id=None)
    if draftshot is not None and not effective_session_id:
        effective_session_id = str(draftshot.get("session_id") or "").strip() or None
    if not effective_session_id and draftshot is None:
        return {
            "status": "noop",
            "reason": "missing_session_id",
            "summary": snapshot_candidate_summary(data_root),
            "candidates": [],
        }

    if draftshot is None:
        return {
            "status": "noop",
            "reason": "no_active_draftshot",
            "session_id": effective_session_id,
            "summary": snapshot_candidate_summary(data_root),
            "candidates": [],
        }

    target_day = str(target_day or "").strip() or _target_day({"refreshed_at": draftshot.get("refreshed_at") or refreshed_at})
    requested_kinds = [_normalize_kind(kind) for kind in (candidate_kinds or SNAPSHOT_CANDIDATE_KINDS)]
    index = _load_index(data_root)
    current = dict(index.get("current") or {})
    candidate_results: list[dict[str, Any]] = []

    for kind in requested_kinds:
        if not _candidate_allowed(kind, synthesis_payload, active_run):
            candidate_results.append({"candidate_kind": kind, "status": "noop", "reason": "threshold_not_met"})
            continue

        source_refs, detail_lines, summary, imported_metadata, authored_sections = _collect_candidate_sources(
            kind=kind,
            draftshot=draftshot,
            synthesis=synthesis_payload,
        )
        if not source_refs:
            candidate_results.append({"candidate_kind": kind, "status": "noop", "reason": "no_material_sources"})
            continue

        source_signature = _candidate_signature(kind, target_day, source_refs)
        family_id = _family_id(subject, kind, target_day)
        current_manifest = load_current_snapshot_candidate(data_root, kind)
        if current_manifest and str(current_manifest.get("source_signature") or "") == source_signature:
            candidate_results.append(
                {
                    "candidate_kind": kind,
                    "status": "noop",
                    "reason": "unchanged_source_signature",
                    "revision_id": current_manifest.get("revision_id"),
                    "manifest_path": current_manifest.get("path"),
                    "body_path": current_manifest.get("body_path"),
                }
            )
            continue

        revision_number = int(current_manifest.get("revision_number") or 0) + 1 if current_manifest else 1
        revision_id = _revision_id(subject, kind, target_day, revision_number)
        manifest_path = _manifest_path(data_root, kind, family_id, revision_number)
        body_path = _body_path(data_root, kind, family_id, revision_number)
        body_text, canonizer_sections = render_snapshot_candidate_body(
            kind=kind,
            subject=subject,
            session_id=effective_session_id,
            target_day=target_day,
            revision_number=revision_number,
            refreshed_at=refreshed_at,
            summary=summary,
            truths=authored_sections["truths"],
            visions=authored_sections["visions"],
            unresolved=authored_sections["unresolved"],
            draftshot=draftshot,
            source_refs=source_refs,
        )
        body_path.write_text(body_text, encoding="utf-8")
        manifest_payload = {
            "schema_version": SNAPSHOT_CANDIDATE_SCHEMA_VERSION,
            "candidate_kind": kind,
            "subject": subject,
            "session_id": effective_session_id,
            "candidate_family_id": family_id,
            "revision_id": revision_id,
            "revision_number": revision_number,
            "target_day": target_day,
            "status": "DRAFT",
            "created_at": refreshed_at,
            "refreshed_at": refreshed_at,
            "manifest_path": str(manifest_path.resolve()),
            "body_path": str(body_path.resolve()),
            "source_signature": source_signature,
            "source_ref_count": len(source_refs),
            "source_refs": source_refs,
            "imported_evidence_refs": list(imported_metadata.get("imported_evidence_refs") or []),
            "imported_confidence_band": imported_metadata.get("imported_confidence_band"),
            "requires_import_review": bool(imported_metadata.get("requires_import_review")),
            "imported_source_count": int(imported_metadata.get("imported_source_count") or 0),
            "summary": summary,
            "detail_lines": detail_lines,
            "canonizer_schema_version": CANONIZER_SCHEMA_VERSION,
            "canonizer_sections": canonizer_sections,
            "draftshot_revision_id": draftshot.get("revision_id"),
            "draftshot_body_path": draftshot.get("body_path"),
            "draftshot_session_id": draftshot.get("session_id"),
            "previous_revision_id": current_manifest.get("revision_id") if current_manifest else None,
            "previous_manifest_path": current_manifest.get("path") if current_manifest else None,
        }
        _write_yaml(manifest_path, manifest_payload)
        current[kind] = {
            "candidate_family_id": family_id,
            "revision_id": revision_id,
            "manifest_path": str(manifest_path.resolve()),
            "body_path": str(body_path.resolve()),
            "refreshed_at": refreshed_at,
            "target_day": target_day,
            "source_signature": source_signature,
        }
        index["latest_revision"] = {
            "candidate_kind": kind,
            "revision_id": revision_id,
            "manifest_path": str(manifest_path.resolve()),
            "body_path": str(body_path.resolve()),
            "refreshed_at": refreshed_at,
            "target_day": target_day,
        }
        candidate_results.append(
            {
                "candidate_kind": kind,
                "status": "updated" if current_manifest else "written",
                "revision_id": revision_id,
                "revision_number": revision_number,
                "manifest_path": str(manifest_path.resolve()),
                "body_path": str(body_path.resolve()),
                "summary": summary,
            }
        )

    index.update(
        {
            "schema_version": SNAPSHOT_CANDIDATE_SCHEMA_VERSION,
            "current": current,
        }
    )
    _save_index(data_root, index)
    overall_status = "noop"
    if any(item.get("status") in {"written", "updated"} for item in candidate_results):
        overall_status = "updated" if any(item.get("status") == "updated" for item in candidate_results) else "written"
    return {
        "status": overall_status,
        "session_id": effective_session_id,
        "target_day": target_day,
        "candidates": candidate_results,
        "summary": snapshot_candidate_summary(data_root),
    }

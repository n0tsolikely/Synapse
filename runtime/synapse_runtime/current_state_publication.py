"""Publication rendering for compiled current-state truth."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml


class CurrentStatePublicationError(RuntimeError):
    """Raised when truth publication rendering or swapping fails."""


PUBLICATION_FILENAMES = {
    "current_state": "CURRENT_STATE.md",
    "implemented_capabilities": "IMPLEMENTED_CAPABILITIES.md",
    "intended_capabilities": "INTENDED_CAPABILITIES.md",
    "superseded_directions": "SUPERSEDED_DIRECTIONS.md",
    "active_work": "ACTIVE_WORK.md",
}


def _metadata_block(*, compile_cycle_id: str, compiled_at: str) -> str:
    return "---\n" + yaml.safe_dump(
        {
            "compile_cycle_id": compile_cycle_id,
            "compiled_at": compiled_at,
        },
        sort_keys=False,
    ) + "---\n\n"


def _statement_summary(statement: dict[str, Any]) -> str:
    detail = str(statement.get("detail") or "").strip()
    if detail:
        return f"- {statement.get('summary')} :: {detail}"
    return f"- {statement.get('summary')}"


def read_publication_metadata(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise CurrentStatePublicationError(f"Publication metadata block missing: {path}")
    marker = "\n---\n"
    end = text.find(marker, 4)
    if end == -1:
        raise CurrentStatePublicationError(f"Publication metadata block malformed: {path}")
    payload = yaml.safe_load(text[4:end])
    if not isinstance(payload, dict):
        raise CurrentStatePublicationError(f"Publication metadata block malformed: {path}")
    return payload


def render_current_state(*, statements: list[dict[str, Any]], report: dict[str, Any]) -> str:
    identity = [item for item in statements if item.get("statement_kind") in {"identity_claim", "project_purpose"} and item.get("active")]
    active = [item for item in statements if item.get("active") and item.get("truth_layer") in {"implemented", "intended"}]
    partial = [item for item in statements if item.get("active") and item.get("truth_layer") == "partial"]
    contradictions = list(report.get("unresolved_contradictions") or [])
    current_work = report.get("current_work_summary") or {}
    lines = [
        _metadata_block(compile_cycle_id=report["compile_cycle_id"], compiled_at=report["compiled_at"]),
        "# Current State",
        "",
        "## Identity / Purpose",
    ]
    lines.extend([_statement_summary(item) for item in identity] or ["- No compiled identity or purpose statements yet."])
    lines.extend(["", "## Active Current Truths"])
    lines.extend([_statement_summary(item) for item in active] or ["- No active current truths compiled."])
    lines.extend(["", "## Partial Truths"])
    lines.extend([_statement_summary(item) for item in partial] or ["- No partial truths compiled."])
    lines.extend(["", "## Contradictions Requiring Attention"])
    if contradictions:
        for item in contradictions:
            lines.append(f"- topic={item.get('topic_key')}: {', '.join(item.get('statement_ids') or [])}")
    else:
        lines.append("- None.")
    lines.extend([
        "",
        "## Freshness / Compile Status",
        f"- truth_compile_stale: {'YES' if report.get('truth_compile_stale') else 'NO'}",
        f"- stale_active_run_detected: {'YES' if report.get('stale_active_run_detected') else 'NO'}",
        f"- contradiction_count: {report.get('contradiction_count')}",
        f"- compiled_at: {report.get('compiled_at')}",
        "",
        "## Current Work Summary",
        f"- current_focus: {current_work.get('current_focus') or 'none'}",
        f"- accepted_governed_work: {current_work.get('accepted_governed_work') or 'none'}",
        f"- recently_completed: {', '.join(current_work.get('recently_completed') or []) or 'none'}",
        f"- blocked_state: {current_work.get('blocked_state') or 'none'}",
        f"- next: {current_work.get('next_hint') or 'none'}",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_implemented_capabilities(*, statements: list[dict[str, Any]], report: dict[str, Any]) -> str:
    items = [item for item in statements if item.get("active") and item.get("statement_kind") == "capability" and item.get("truth_layer") == "implemented"]
    lines = [_metadata_block(compile_cycle_id=report["compile_cycle_id"], compiled_at=report["compiled_at"]), "# Implemented Capabilities", ""]
    lines.extend([_statement_summary(item) for item in items] or ["- No implemented capability statements compiled."])
    return "\n".join(lines).rstrip() + "\n"


def render_intended_capabilities(*, statements: list[dict[str, Any]], report: dict[str, Any]) -> str:
    intended = [item for item in statements if item.get("active") and item.get("statement_kind") == "capability" and item.get("truth_layer") == "intended"]
    speculative = [item for item in statements if item.get("active") and item.get("statement_kind") == "capability" and item.get("truth_layer") == "speculative"]
    lines = [
        _metadata_block(compile_cycle_id=report["compile_cycle_id"], compiled_at=report["compiled_at"]),
        "# Intended Capabilities",
        "",
        "## Intended",
    ]
    lines.extend([_statement_summary(item) for item in intended] or ["- None."])
    lines.extend(["", "## Speculative"])
    lines.extend([_statement_summary(item) for item in speculative] or ["- None."])
    return "\n".join(lines).rstrip() + "\n"


def render_superseded_directions(*, statements: list[dict[str, Any]], report: dict[str, Any]) -> str:
    items = [item for item in statements if item.get("truth_layer") == "superseded"]
    lines = [_metadata_block(compile_cycle_id=report["compile_cycle_id"], compiled_at=report["compiled_at"]), "# Superseded Directions", ""]
    if not items:
        lines.append("- No superseded directions compiled.")
    else:
        for item in items:
            replacement_summaries = []
            by_id = {str(statement.get("statement_id")): statement for statement in statements}
            for statement_id in item.get("superseded_by") or []:
                replacement = by_id.get(str(statement_id))
                if replacement and str(replacement.get("summary") or "").strip():
                    replacement_summaries.append(str(replacement.get("summary")))
            replacement = ", ".join(replacement_summaries) or ", ".join(item.get("superseded_by") or []) or "none"
            provenance = ", ".join(ref.get("source_type") for ref in item.get("provenance_refs") or []) or "none"
            lines.append(f"- {item.get('summary')} | replacement={replacement} | provenance={provenance}")
    return "\n".join(lines).rstrip() + "\n"


def render_active_work(*, report: dict[str, Any]) -> str:
    current_work = report.get("current_work_summary") or {}
    lines = [
        _metadata_block(compile_cycle_id=report["compile_cycle_id"], compiled_at=report["compiled_at"]),
        "# Active Work",
        "",
        f"- Current focus: {current_work.get('current_focus') or 'none'}",
        f"- Accepted governed work: {current_work.get('accepted_governed_work') or 'none'}",
        f"- Recently completed: {', '.join(current_work.get('recently_completed') or []) or 'none'}",
        f"- Blocked state: {current_work.get('blocked_state') or 'none'}",
        f"- Next: {current_work.get('next_hint') or 'none'}",
    ]
    if report.get("stale_active_run_detected"):
        lines.append("- WARNING: stale active run detected")
    return "\n".join(lines).rstrip() + "\n"


def render_publication_set(*, statement_store: dict[str, Any], compiler_report: dict[str, Any]) -> dict[str, str]:
    statements = list(statement_store.get("statements") or [])
    return {
        PUBLICATION_FILENAMES["current_state"]: render_current_state(statements=statements, report=compiler_report),
        PUBLICATION_FILENAMES["implemented_capabilities"]: render_implemented_capabilities(statements=statements, report=compiler_report),
        PUBLICATION_FILENAMES["intended_capabilities"]: render_intended_capabilities(statements=statements, report=compiler_report),
        PUBLICATION_FILENAMES["superseded_directions"]: render_superseded_directions(statements=statements, report=compiler_report),
        PUBLICATION_FILENAMES["active_work"]: render_active_work(report=compiler_report),
    }


def write_publication_set_atomic(*, publications_dir: Path, rendered: dict[str, str]) -> dict[str, str]:
    publications_dir.parent.mkdir(parents=True, exist_ok=True)
    suffix = f"{os.getpid()}"
    staging_dir = publications_dir.parent / f".{publications_dir.name}.{suffix}.tmp"
    backup_dir = publications_dir.parent / f".{publications_dir.name}.{suffix}.bak"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in rendered.items():
        (staging_dir / filename).write_text(content, encoding="utf-8")
    try:
        if publications_dir.exists():
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            os.replace(publications_dir, backup_dir)
        os.replace(staging_dir, publications_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception as exc:
        if publications_dir.exists() and backup_dir.exists():
            shutil.rmtree(publications_dir, ignore_errors=True)
            os.replace(backup_dir, publications_dir)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise CurrentStatePublicationError(str(exc)) from exc
    paths = {filename: str((publications_dir / filename).resolve()) for filename in rendered}
    return paths

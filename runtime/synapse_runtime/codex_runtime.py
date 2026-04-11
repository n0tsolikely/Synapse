"""Bounded continuous Codex growth runtime."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.codex_packets import SECTION_TITLES
from synapse_runtime.live_memory_common import LiveMemoryError, _normalize_relpaths, _slugify


class CodexRuntimeError(LiveMemoryError):
    """Raised when Codex growth cannot proceed safely."""


class CodexWritePosture(str, Enum):
    CANONICAL_SECTION_UPDATE = "canonical_section_update"
    DRAFT_ANCHOR_ONLY = "draft_anchor_only"
    CANDIDATE_ONLY = "candidate_only"
    BLOCKED = "blocked"


class CodexTruthLayer(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    INTENDED = "intended"
    SPECULATIVE = "speculative"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class CodexGrowthDecision:
    section_key: str | None
    unresolved_section_target: str | None
    truth_layer: str
    write_posture: str
    threshold_class: str
    anchor_posture: str
    supporting_evidence_refs: tuple[str, ...]
    build_state_actions: tuple[str, ...]
    anchor_index_actions: tuple[str, ...]


def codex_root(data_root: Path) -> Path:
    return data_root / "Codex"


def codex_sections_root(data_root: Path) -> Path:
    return codex_root(data_root) / "Sections"


def codex_candidates_root(data_root: Path) -> Path:
    return codex_root(data_root) / "Candidates"


def codex_receipts_root(data_root: Path) -> Path:
    return codex_root(data_root) / "Receipts"


def codex_build_state_path(data_root: Path) -> Path:
    return codex_root(data_root) / "CODEX_BUILD_STATE.yaml"


def codex_anchor_index_path(data_root: Path) -> Path:
    return codex_root(data_root) / "ANCHOR_INDEX.yaml"


def codex_toc_path(data_root: Path) -> Path:
    return codex_root(data_root) / "TOC.md"


def codex_toc_draft_path(data_root: Path) -> Path:
    return codex_root(data_root) / "TOC_DRAFT.md"


def ensure_codex_runtime_scaffold(data_root: Path) -> None:
    codex_sections_root(data_root).mkdir(parents=True, exist_ok=True)
    codex_candidates_root(data_root).mkdir(parents=True, exist_ok=True)
    codex_receipts_root(data_root).mkdir(parents=True, exist_ok=True)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=ZoneInfo("America/Toronto"))


def _today_toronto() -> str:
    return _now().date().isoformat()


def _now_iso() -> str:
    return _now().isoformat()


def _normalize_section_key(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    text = re.sub(r"[^A-Z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or None


def _normalize_anchor_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _toc_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            entries.append(match.group(1).strip())
    return entries


def _resolve_anchor_posture(data_root: Path, section_key: str) -> tuple[str, str | None]:
    title = SECTION_TITLES.get(section_key, section_key.replace("_", " ").title())
    candidates = {
        _normalize_anchor_text(section_key),
        _normalize_anchor_text(section_key.replace("_", " ")),
        _normalize_anchor_text(title),
    }
    for path, posture in ((codex_toc_path(data_root), "canonical"), (codex_toc_draft_path(data_root), "draft")):
        for entry in _toc_entries(path):
            if _normalize_anchor_text(entry) in candidates:
                return posture, entry
    return "unresolved", None


def _coerce_truth_layer(proposal: dict[str, Any]) -> str:
    requested = str(
        proposal.get("codex_truth_layer")
        or proposal.get("truth_layer")
        or CodexTruthLayer.PARTIAL.value
    ).strip().lower()
    if requested not in {item.value for item in CodexTruthLayer}:
        return CodexTruthLayer.PARTIAL.value
    return requested


def _proposal_evidence(data_root: Path, proposal: dict[str, Any]) -> list[str]:
    return _normalize_relpaths(data_root, [str(item) for item in proposal.get("evidence") or [] if str(item).strip()])


def classify_codex_growth(*, data_root: Path, proposal: dict[str, Any]) -> CodexGrowthDecision:
    evidence = tuple(_proposal_evidence(data_root, proposal))
    section_key = _normalize_section_key(proposal.get("codex_section_key") or proposal.get("section_key"))
    truth_layer = _coerce_truth_layer(proposal)
    require_target = bool(proposal.get("codex_target_required"))

    if not evidence:
        return CodexGrowthDecision(
            section_key=section_key,
            unresolved_section_target="missing_supporting_evidence",
            truth_layer=truth_layer,
            write_posture=CodexWritePosture.BLOCKED.value,
            threshold_class="insufficient_blocked",
            anchor_posture="unresolved",
            supporting_evidence_refs=(),
            build_state_actions=("no_build_state_change",),
            anchor_index_actions=("no_anchor_change",),
        )

    if not section_key:
        posture = CodexWritePosture.BLOCKED if require_target else CodexWritePosture.CANDIDATE_ONLY
        return CodexGrowthDecision(
            section_key=None,
            unresolved_section_target="missing_section_key",
            truth_layer=truth_layer,
            write_posture=posture.value,
            threshold_class="insufficient_blocked" if posture is CodexWritePosture.BLOCKED else "sufficient_for_candidate_only",
            anchor_posture="unresolved",
            supporting_evidence_refs=evidence,
            build_state_actions=("no_build_state_change",),
            anchor_index_actions=("no_anchor_change",),
        )

    anchor_posture, _ = _resolve_anchor_posture(data_root, section_key)
    if anchor_posture == "canonical":
        return CodexGrowthDecision(
            section_key=section_key,
            unresolved_section_target=None,
            truth_layer=truth_layer,
            write_posture=CodexWritePosture.CANONICAL_SECTION_UPDATE.value,
            threshold_class="sufficient_for_canonical_section_movement",
            anchor_posture=anchor_posture,
            supporting_evidence_refs=evidence,
            build_state_actions=("section_record_upserted", "spec_gate_write_state", "consistency_gate_write_state"),
            anchor_index_actions=("consistency_gate_update_anchor",),
        )
    if anchor_posture == "draft":
        return CodexGrowthDecision(
            section_key=section_key,
            unresolved_section_target=None,
            truth_layer=truth_layer,
            write_posture=CodexWritePosture.DRAFT_ANCHOR_ONLY.value,
            threshold_class="sufficient_for_draft_anchor_only",
            anchor_posture=anchor_posture,
            supporting_evidence_refs=evidence,
            build_state_actions=("section_record_upserted", "spec_gate_write_state", "consistency_gate_write_state"),
            anchor_index_actions=("consistency_gate_update_anchor",),
        )
    posture = CodexWritePosture.BLOCKED if require_target else CodexWritePosture.CANDIDATE_ONLY
    return CodexGrowthDecision(
        section_key=section_key,
        unresolved_section_target=f"section_anchor_not_found:{section_key}",
        truth_layer=truth_layer,
        write_posture=posture.value,
        threshold_class="insufficient_blocked" if posture is CodexWritePosture.BLOCKED else "sufficient_for_candidate_only",
        anchor_posture="unresolved",
        supporting_evidence_refs=evidence,
        build_state_actions=("no_build_state_change",),
        anchor_index_actions=("no_anchor_change",),
    )


def _ensure_build_state(data_root: Path) -> Path:
    path = codex_build_state_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            (
                "schema_version: 1\n"
                "overall_status: NOT_STARTED\n"
                "spec_completeness_gate:\n"
                "  status: NEEDS_DECISIONS\n"
                "  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]\n"
                "consistency_gate:\n"
                "  status: NEEDS_DECISIONS\n"
                "  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]\n"
                "sections: []\n"
                "notes: []\n"
            ),
            encoding="utf-8",
        )
    return path


def _load_build_state(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, dict) else {}


def _write_build_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _upsert_build_state_section(
    *,
    data_root: Path,
    section_key: str,
    section_title: str,
    section_path: Path,
    proposal_id: str,
    truth_layer: str,
    write_posture: str,
) -> Path:
    path = _ensure_build_state(data_root)
    build_state = _load_build_state(path)
    sections = build_state.get("sections")
    if not isinstance(sections, list):
        sections = []
    record = {
        "section_key": section_key,
        "section_title": section_title,
        "section_path": str(section_path.resolve().relative_to(data_root.resolve()).as_posix()),
        "status": "CANONICAL" if write_posture == CodexWritePosture.CANONICAL_SECTION_UPDATE.value else "DRAFT_ANCHORED",
        "source_proposal_id": proposal_id,
        "truth_layer": truth_layer,
        "updated_at": _now_iso(),
    }
    sections = [item for item in sections if not (isinstance(item, dict) and str(item.get("section_key") or "").upper() == section_key)]
    sections.append(record)
    build_state["sections"] = sections
    build_state["overall_status"] = "IN_PROGRESS"
    _write_build_state(path, build_state)
    return path


def _candidate_artifact_path(data_root: Path, proposal: dict[str, Any]) -> Path:
    slug = _slugify(str(proposal.get("title") or "codex"))
    return codex_candidates_root(data_root) / f"CANDIDATE__{slug}__{_today_toronto()}.md"


def _section_artifact_path(data_root: Path, section_key: str) -> Path:
    return codex_sections_root(data_root) / f"SECTION__{section_key}.md"


def _receipt_path(data_root: Path, proposal: dict[str, Any]) -> Path:
    slug = _slugify(str(proposal.get("proposal_id") or proposal.get("title") or "codex"))
    return codex_receipts_root(data_root) / f"CODEX_GROWTH__{slug}__{_now().strftime('%Y-%m-%d__%H%M%S')}.yaml"


def _candidate_body(decision: CodexGrowthDecision, proposal: dict[str, Any]) -> str:
    lines = [
        f"# Codex Candidate - {proposal.get('title')}",
        "",
        f"Write Posture: {decision.write_posture}",
        f"Truth Layer: {decision.truth_layer}",
        f"Unresolved Section Target: {decision.unresolved_section_target or 'N/A'}",
        f"Source Proposal ID: {proposal.get('proposal_id')}",
        f"Formalized On: {_today_toronto()}",
        "",
        "## Summary",
        str(proposal.get("summary") or ""),
        "",
        "## Reason",
        str(proposal.get("reason") or ""),
        "",
        "## Codex Implications",
        *(f"- {item}" for item in proposal.get("codex_implications") or []),
        "",
        "## Evidence",
        *(f"- {item}" for item in decision.supporting_evidence_refs),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _section_body(decision: CodexGrowthDecision, proposal: dict[str, Any]) -> str:
    assert decision.section_key
    section_title = SECTION_TITLES.get(decision.section_key, decision.section_key.replace("_", " ").title())
    lines = [
        f"# {section_title}",
        "",
        f"Section Key: {decision.section_key}",
        f"Anchor Posture: {decision.anchor_posture.upper()}",
        f"Write Posture: {decision.write_posture}",
        f"Truth Layer: {decision.truth_layer}",
        f"Source Proposal ID: {proposal.get('proposal_id')}",
        f"Updated At: {_now_iso()}",
        "",
        "## Summary",
        str(proposal.get("summary") or ""),
        "",
        "## Reason",
        str(proposal.get("reason") or ""),
        "",
        "## Codex Implications",
        *(f"- {item}" for item in proposal.get("codex_implications") or []),
        "",
        "## Evidence",
        *(f"- {item}" for item in decision.supporting_evidence_refs),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _run_codex_gate(*, subject: str, data_root: Path, cmd: str, section_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "tools" / "synapse_codex_gate.py"
    args = [sys.executable, str(script), "--subject", subject, "--data-root", str(data_root), cmd, "--write-state"]
    if cmd == "consistency":
        if section_path is None:
            raise CodexRuntimeError("consistency gate requires a section path")
        args.extend(["--section", str(section_path), "--update-anchor"])
    env = dict(os.environ)
    env.pop("SYNAPSE_SESSION_ID", None)
    env.pop("SUBJECT", None)
    env["HOME"] = str(data_root.parent)
    return subprocess.run(args, capture_output=True, text=True, cwd=str(data_root.parent), env=env)


def _receipt_payload(
    *,
    subject: str,
    data_root: Path,
    proposal: dict[str, Any],
    decision: CodexGrowthDecision,
    artifact_path: Path | None,
    build_state_path: Path | None,
    gate_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    anchor_path = codex_anchor_index_path(data_root)
    return {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "subject": subject,
        "proposal_id": str(proposal.get("proposal_id") or "").strip(),
        "proposal_title": str(proposal.get("title") or "").strip(),
        "artifact_path": str(artifact_path.resolve()) if artifact_path else None,
        "decision": {
            "section_key": decision.section_key,
            "unresolved_section_target": decision.unresolved_section_target,
            "truth_layer": decision.truth_layer,
            "write_posture": decision.write_posture,
            "threshold_class": decision.threshold_class,
            "anchor_posture": decision.anchor_posture,
            "supporting_evidence_refs": list(decision.supporting_evidence_refs),
            "build_state_actions": list(decision.build_state_actions),
            "anchor_index_actions": list(decision.anchor_index_actions),
        },
        "build_state_path": str(build_state_path.resolve()) if build_state_path else None,
        "anchor_index_path": str(anchor_path.resolve()) if anchor_path.exists() else None,
        "gate_outputs": gate_outputs,
    }


def formalize_codex_from_proposal(*, subject: str, data_root: Path, proposal: dict[str, Any]) -> dict[str, Any]:
    ensure_codex_runtime_scaffold(data_root)
    decision = classify_codex_growth(data_root=data_root, proposal=proposal)
    receipt_path = _receipt_path(data_root, proposal)
    gate_outputs: list[dict[str, Any]] = []
    build_state_path: Path | None = None

    if decision.write_posture == CodexWritePosture.CANDIDATE_ONLY.value:
        artifact_path = _candidate_artifact_path(data_root, proposal)
        artifact_path.write_text(_candidate_body(decision, proposal), encoding="utf-8")
    elif decision.write_posture == CodexWritePosture.BLOCKED.value:
        artifact_path = None
    else:
        assert decision.section_key
        artifact_path = _section_artifact_path(data_root, decision.section_key)
        artifact_path.write_text(_section_body(decision, proposal), encoding="utf-8")
        build_state_path = _upsert_build_state_section(
            data_root=data_root,
            section_key=decision.section_key,
            section_title=SECTION_TITLES.get(decision.section_key, decision.section_key.replace("_", " ").title()),
            section_path=artifact_path,
            proposal_id=str(proposal.get("proposal_id") or "").strip(),
            truth_layer=decision.truth_layer,
            write_posture=decision.write_posture,
        )
        spec_result = _run_codex_gate(subject=subject, data_root=data_root, cmd="spec")
        gate_outputs.append({"gate": "spec", "returncode": spec_result.returncode, "stdout": spec_result.stdout, "stderr": spec_result.stderr})
        if spec_result.returncode != 0:
            raise CodexRuntimeError(spec_result.stdout + spec_result.stderr)
        consistency_result = _run_codex_gate(subject=subject, data_root=data_root, cmd="consistency", section_path=artifact_path)
        gate_outputs.append(
            {
                "gate": "consistency",
                "returncode": consistency_result.returncode,
                "stdout": consistency_result.stdout,
                "stderr": consistency_result.stderr,
            }
        )
        if consistency_result.returncode != 0:
            raise CodexRuntimeError(consistency_result.stdout + consistency_result.stderr)

    payload = _receipt_payload(
        subject=subject,
        data_root=data_root,
        proposal=proposal,
        decision=decision,
        artifact_path=artifact_path,
        build_state_path=build_state_path,
        gate_outputs=gate_outputs,
    )
    receipt_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {
        "artifact_path": str((artifact_path or receipt_path).resolve()),
        "receipt_path": str(receipt_path.resolve()),
        "decision": payload["decision"],
        "raw_output": "".join(item.get("stdout", "") + item.get("stderr", "") for item in gate_outputs),
    }

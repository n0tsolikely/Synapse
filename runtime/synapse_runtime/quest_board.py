"""Canonical Quest Board drafting helpers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from synapse_runtime.governance_pack import resolve_governance_asset

DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
DEFAULT_TESTING_LEVEL = "DEFERRED TO 01_PREQUEST.md"
DEFAULT_VERIFICATION_PLAN = "DEFERRED TO 01_PREQUEST.md"
DEFAULT_CODEX_ANCHORS = "BLOCKED - CODEX_ANCHORS_MISSING"
DEFAULT_REPO_ORIENTATION_BLOCKER = "BLOCKED — REPO_ORIENTATION_REQUIRED"


def today_toronto() -> str:
    try:
        return dt.datetime.now(tz=DEFAULT_TIMEZONE).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def _slugify(value: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = slug.strip("-")
    if not slug:
        return "task"
    return slug[:max_len].strip("-") or "task"


def load_quest_template(cwt: Path | None = None) -> str:
    _ = cwt
    template_path = resolve_governance_asset("Quest Board", "QUEST_TEMPLATE.txt")
    if not template_path.exists():
        raise FileNotFoundError(f"Quest template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def _template_metadata(template: str) -> dict[str, str]:
    metadata: dict[str, str] = {
        "version": "v1.5",
        "last_updated": "",
        "status": "Generated quest artifact",
    }
    for line in template.splitlines():
        if line.startswith("Version:"):
            metadata["version"] = line.split(":", 1)[1].strip() or metadata["version"]
        elif line.startswith("Last Updated:"):
            metadata["last_updated"] = line.split(":", 1)[1].strip()
        elif line.startswith("Status:"):
            metadata["status"] = line.split(":", 1)[1].strip() or metadata["status"]
    return metadata


def _render_labeled_block(label: str, value: str) -> list[str]:
    raw = str(value or "").rstrip()
    if not raw:
        return [f"{label}:", ""]
    if "\n" not in raw:
        return [f"{label}: {raw}", ""]
    lines = [f"{label}:"]
    lines.extend(raw.splitlines())
    lines.append("")
    return lines


def _render_static_section(title: str) -> list[str]:
    return [
        "=" * 80,
        title,
        "=" * 80,
    ]


def _render_quest_document(template: str, values: dict[str, str]) -> str:
    metadata = _template_metadata(template)
    lines: list[str] = [
        "QUEST — SYNAPSE OS",
        f"Version: {metadata['version']}",
    ]
    if metadata["last_updated"]:
        lines.append(f"Template Last Updated: {metadata['last_updated']}")
    lines.append("Status: Generated Quest Artifact")
    lines.append("")

    lines.extend(_render_static_section("IDENTITY (REQUIRED)"))
    lines.extend(_render_labeled_block("Quest ID", values["quest_id"]))
    lines.extend(_render_labeled_block("Title", values["title"]))
    lines.extend(_render_labeled_block("Subject", values["subject"]))
    lines.extend(_render_labeled_block("Origin", values["origin"]))
    lines.extend(_render_labeled_block("Priority", values["priority"]))
    lines.extend(_render_labeled_block("Links", values["links"]))

    lines.extend(_render_static_section("CODEX ANCHORS + CONSTRAINT SUMMARY (DRAFT)"))
    lines.extend(_render_labeled_block("Codex Anchors (DRAFT)", values["codex_anchors"]))
    lines.extend(_render_labeled_block("Codex Constraint Summary (DRAFT)", values["codex_constraints"]))

    lines.extend(_render_static_section("QUEST CREATION VISION ALIGNMENT (REQUIRED)"))
    lines.extend(_render_labeled_block("Change Class", values["change_class"]))
    lines.extend(_render_labeled_block("Vision Delta", values["vision_delta"]))
    lines.extend(_render_labeled_block("System Context Statement", values["system_context"]))
    lines.extend(_render_labeled_block("Anti-Duplication Plan", values["anti_dup"]))
    lines.extend(_render_labeled_block("Placement Intent", values["placement_intent"]))

    lines.extend(_render_static_section("ATOMICITY CHECK (REQUIRED)"))
    lines.extend(_render_labeled_block("Atomicity Statement", values["atomicity"]))

    lines.extend(_render_static_section("RISK + CONSENT GATE (CONDITIONAL)"))
    lines.extend(_render_labeled_block("Risk", values["risk"]))
    lines.extend(_render_labeled_block("R2 Confirmation Artifact (REQUIRED if Risk = R2)", values.get("r2_confirmation_artifact", "")))

    lines.extend(_render_static_section("DESCRIPTION (REQUIRED)"))
    lines.extend(_render_labeled_block("Description", values["description"]))

    lines.extend(_render_static_section("SCOPE / OBJECTIVE (REQUIRED)"))
    lines.extend(_render_labeled_block("Scope / Objective", values["objective"]))

    lines.extend(_render_static_section("OUT OF SCOPE (REQUIRED)"))
    lines.extend(_render_labeled_block("Out of Scope", values["out_of_scope"]))

    lines.extend(_render_static_section("DEPENDENCIES (REQUIRED: LIST OR EXPLICIT NONE)"))
    lines.extend(_render_labeled_block("Dependencies", values["dependencies"]))

    lines.extend(_render_static_section("DOORS + TESTING LEVEL (CONDITIONAL: CODE/SOFTWARE)"))
    lines.extend(_render_labeled_block("Door Impact", values["door_impact"]))
    lines.extend(_render_labeled_block("Testing Level (TL)", values["testing_level"]))

    lines.extend(_render_static_section("VERIFICATION PLAN (REQUIRED BEFORE EXECUTION)"))
    lines.extend(_render_labeled_block("Verification Plan", values["verification_plan"]))

    lines.extend(_render_static_section("TALENT POINTS (REQUIRED: YES/NO)"))
    lines.extend(_render_labeled_block("Talent Point Awarded", values["talent_awarded"]))

    lines.extend(_render_static_section("EXECUTION AUDIT BUNDLE (REQUIRED ONCE ACCEPTED)"))
    lines.extend(_render_labeled_block("Audit Bundle Folder Path (required once ACCEPTED)", values.get("audit_bundle_path", "")))
    return "\n".join(lines).rstrip() + "\n"


def fill_quest_template(template: str, values: dict[str, str]) -> str:
    return _render_quest_document(template, values)


def next_quest_number(data_root: Path, prefix: str) -> int:
    quest_dirs = [
        data_root / "Quest Board",
        data_root / "Quest Board" / "Accepted",
        data_root / "Quest Board" / "Completed",
        data_root / "Quest Board" / "Abandoned",
    ]
    pattern = re.compile(rf"{re.escape(prefix)}_(\d{{3}})")
    highest = 0
    for qdir in quest_dirs:
        if not qdir.exists():
            continue
        for path in qdir.glob("*.txt"):
            match = pattern.search(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def _top_level_targets(paths: list[str]) -> list[str]:
    targets: list[str] = []
    for raw in paths:
        text = str(raw).strip()
        if not text:
            continue
        path = Path(text)
        if path.is_absolute():
            token = path.name or path.parent.name
        else:
            token = path.parts[0] if path.parts else text
        if token and token not in targets:
            targets.append(token)
    return targets


def _build_system_context(kind: str, paths: list[str], summary: str) -> str:
    targets = _top_level_targets(paths)
    if targets:
        joined = ", ".join(targets[:3])
        return (
            f"Ambiently detected {kind} work inside the current subject; recorded execution signals "
            f"currently concentrate in {joined}. {summary}".strip()
        )
    return (
        f"Ambiently detected {kind} work inside the current subject; recorded execution signals "
        f"show a bounded work unit rather than a greenfield build. {summary}".strip()
    )


def _build_placement_intent(paths: list[str]) -> str:
    targets = _top_level_targets(paths)
    if not targets:
        return DEFAULT_REPO_ORIENTATION_BLOCKER
    return f"Intended layer: runtime | Intended target path(s): {', '.join(targets[:3])}."


def _build_anti_dup(title: str, paths: list[str]) -> str:
    targets = _top_level_targets(paths)
    query = _slugify(title).replace("-", "|")
    if targets:
        return f"Run rg -n \"{query}\" {' '.join(targets[:3])} {targets[0]}_Data if present."
    return DEFAULT_REPO_ORIENTATION_BLOCKER


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def draft_quest_from_proposal(*, subject: str, data_root: Path, proposal: dict[str, Any], prefix: str) -> dict[str, str]:
    template = load_quest_template()
    today = today_toronto()
    qid = f"{prefix}_{next_quest_number(data_root, prefix):03d}"
    title = str(proposal.get("title") or qid).strip() or qid
    slug = _slugify(title)
    board_dir = data_root / "Quest Board"
    board_dir.mkdir(parents=True, exist_ok=True)
    quest_path = board_dir / f"{qid}__{slug}__{today}.txt"

    evidence = _string_list(proposal.get("evidence"))
    related_files = _string_list(proposal.get("related_files"))
    links = ", ".join(evidence[:8] or related_files[:8]) or "None"
    summary = str(proposal.get("summary") or proposal.get("reason") or title).strip()
    description = str(proposal.get("description") or summary).strip()
    objective = str(proposal.get("objective") or summary).strip()
    candidate_kind = str(proposal.get("kind") or "quest").replace("_", " ")
    values = {
        "quest_id": qid,
        "title": title,
        "subject": subject,
        "origin": str(proposal.get("origin") or f"Ambient proposal {proposal.get('proposal_id')}"),
        "priority": str(proposal.get("priority") or "P1"),
        "links": links,
        "codex_anchors": str(proposal.get("codex_anchors") or DEFAULT_CODEX_ANCHORS),
        "codex_constraints": str(proposal.get("codex_constraints") or proposal.get("reason") or "TBD - derive from proposal evidence"),
        "change_class": str(proposal.get("change_class") or "STRUCTURAL"),
        "vision_delta": str(proposal.get("vision_delta") or "ALIGNED"),
        "system_context": str(proposal.get("system_context") or _build_system_context(candidate_kind, related_files, summary)),
        "anti_dup": str(proposal.get("anti_dup") or _build_anti_dup(title, related_files)),
        "placement_intent": str(proposal.get("placement_intent") or _build_placement_intent(related_files)),
        "atomicity": str(proposal.get("atomicity") or "Atomic: yes - single independently verifiable outcome."),
        "risk": str(proposal.get("risk") or "R0"),
        "door_impact": str(proposal.get("door_impact") or "NONE"),
        "testing_level": str(proposal.get("testing_level") or DEFAULT_TESTING_LEVEL),
        "talent_awarded": str(proposal.get("talent_awarded") or "NO"),
        "description": description,
        "objective": objective,
        "out_of_scope": str(proposal.get("out_of_scope") or "Any work beyond the ambiently clustered candidate scope."),
        "dependencies": str(proposal.get("dependencies") or "None"),
        "verification_plan": str(proposal.get("verification_plan") or DEFAULT_VERIFICATION_PLAN),
        "audit_bundle_path": str(proposal.get("audit_bundle_path") or ""),
    }
    quest_path.write_text(fill_quest_template(template, values), encoding="utf-8")
    return {
        "quest_id": qid,
        "artifact_path": str(quest_path),
    }

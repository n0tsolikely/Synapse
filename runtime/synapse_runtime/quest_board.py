"""Canonical Quest Board drafting helpers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from synapse_runtime.cwt import detect_canonical_working_tree

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
    root = cwt or detect_canonical_working_tree()
    template_path = root / "governance" / "Quest Board" / "QUEST_TEMPLATE.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"Quest template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def _replace_line(lines: list[str], prefix: str, value: str) -> None:
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = f"{prefix} {value}".rstrip()
            return


def _insert_after_contains(lines: list[str], needle: str, content: str) -> None:
    for idx, line in enumerate(lines):
        if needle in line:
            lines.insert(idx + 1, content)
            return


def fill_quest_template(template: str, values: dict[str, str]) -> str:
    lines = template.splitlines()

    _replace_line(lines, "Quest ID:", values["quest_id"])
    _replace_line(lines, "Title:", values["title"])
    _replace_line(lines, "Subject:", values["subject"])
    _replace_line(lines, "Origin:", values["origin"])
    _replace_line(lines, "Priority:", values["priority"])
    _replace_line(lines, "Links:", values["links"])
    _replace_line(lines, "Codex Anchors (DRAFT):", values["codex_anchors"])
    _replace_line(lines, "Codex Constraint Summary (DRAFT):", values["codex_constraints"])
    _replace_line(lines, "Change Class:", values["change_class"])
    _replace_line(lines, "Vision Delta:", values["vision_delta"])
    _replace_line(lines, "System Context Statement:", values["system_context"])
    _replace_line(lines, "Anti-Duplication Plan:", values["anti_dup"])
    _replace_line(lines, "Placement Intent:", values["placement_intent"])
    _replace_line(lines, "Atomicity Statement:", values["atomicity"])
    _replace_line(lines, "Risk:", values["risk"])
    _replace_line(lines, "Door Impact:", values["door_impact"])
    _replace_line(lines, "Testing Level (TL):", values["testing_level"])
    _replace_line(lines, "Talent Point Awarded:", values["talent_awarded"])

    _insert_after_contains(lines, "Brief, concrete description", f"Description: {values['description']}")
    _insert_after_contains(lines, "Avoid vague outcomes", f"Scope / Objective: {values['objective']}")
    _insert_after_contains(lines, "Explicitly list what this Quest does NOT include", f"Out of Scope: {values['out_of_scope']}")
    _insert_after_contains(lines, "If there are none, write: None", f"Dependencies: {values['dependencies']}")
    _insert_after_contains(lines, "OR write: DEFERRED TO 01_PREQUEST.md", f"Verification Plan: {values['verification_plan']}")

    return "\n".join(lines).rstrip() + "\n"


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
    }
    quest_path.write_text(fill_quest_template(template, values), encoding="utf-8")
    return {
        "quest_id": qid,
        "artifact_path": str(quest_path),
    }

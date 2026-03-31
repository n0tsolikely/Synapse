"""Canonical Quest Board drafting helpers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from synapse_runtime.governance_pack import resolve_governance_asset
from synapse_runtime.quest_plans import normalize_milestones, persist_execution_plan

DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
DEFAULT_TESTING_LEVEL = "TL2"
DEFAULT_VERIFICATION_PLAN = (
    "Run the scope-appropriate commands/checks for this quest, record the exact commands and receipts in the "
    "completion audit, and do not close the quest without a clean PASS."
)
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
    created_at = values.get("created_at") or dt.datetime.now(tz=DEFAULT_TIMEZONE).isoformat()
    quest_state = values.get("quest_state") or "BOARD"
    effective = {
        **values,
        "quest_state": quest_state,
        "created_at": created_at,
        "accepted_at": values.get("accepted_at", ""),
        "completed_at": values.get("completed_at", ""),
        "last_audit_at": values.get("last_audit_at", ""),
        "guild_orders_ref": values.get("guild_orders_ref", "N/A"),
        "dungeon_ref": values.get("dungeon_ref", "N/A"),
        "dungeon_coverage": values.get("dungeon_coverage", "N/A"),
        "coherent_outcome": values.get("coherent_outcome") or values.get("atomicity") or values.get("objective") or values.get("title") or "",
        "closure_statement": values.get("closure_statement") or values.get("objective") or values.get("description") or values.get("title") or "",
        "split_triggers": values.get("split_triggers") or "- Split if the work reveals more than one independently closable outcome.",
        "r2_confirmation_artifact": values.get("r2_confirmation_artifact", ""),
        "milestones": values.get("milestones") or "- MILESTONE-001 :: Close the bounded coherent outcome and record a clean completion audit PASS.",
        "verification_plan": values.get("verification_plan", DEFAULT_VERIFICATION_PLAN),
        "plan_artifact_refs": values.get("plan_artifact_refs", ""),
        "audit_state": values.get("audit_state", "not_started"),
        "audit_bundle_path": values.get("audit_bundle_path", ""),
        "state_history": values.get("state_history", _state_history_text(quest_state, created_at)),
    }
    lines: list[str] = [
        "QUEST — SYNAPSE OS",
        f"Version: {metadata['version']}",
    ]
    if metadata["last_updated"]:
        lines.append(f"Template Last Updated: {metadata['last_updated']}")
    lines.append("Status: Generated Quest Artifact")
    lines.append("")

    lines.extend(_render_static_section("IDENTITY (REQUIRED)"))
    lines.extend(_render_labeled_block("Quest ID", effective["quest_id"]))
    lines.extend(_render_labeled_block("Title", effective["title"]))
    lines.extend(_render_labeled_block("Subject", effective["subject"]))
    lines.extend(_render_labeled_block("Origin", effective["origin"]))
    lines.extend(_render_labeled_block("Priority", effective["priority"]))
    lines.extend(_render_labeled_block("Links", effective["links"]))
    lines.extend(_render_labeled_block("Quest State", effective["quest_state"]))
    lines.extend(_render_labeled_block("Created At", effective["created_at"]))
    lines.extend(_render_labeled_block("Accepted At", effective["accepted_at"]))
    lines.extend(_render_labeled_block("Completed At", effective["completed_at"]))
    lines.extend(_render_labeled_block("Last Audit At", effective["last_audit_at"]))

    lines.extend(_render_static_section("CODEX ANCHORS + CONSTRAINT SUMMARY (DRAFT)"))
    lines.extend(_render_labeled_block("Codex Anchors (DRAFT)", effective["codex_anchors"]))
    lines.extend(_render_labeled_block("Codex Constraint Summary (DRAFT)", effective["codex_constraints"]))

    lines.extend(_render_static_section("QUEST CREATION VISION ALIGNMENT (REQUIRED)"))
    lines.extend(_render_labeled_block("Change Class", effective["change_class"]))
    lines.extend(_render_labeled_block("Vision Delta", effective["vision_delta"]))
    lines.extend(_render_labeled_block("System Context Statement", effective["system_context"]))
    lines.extend(_render_labeled_block("Anti-Duplication Plan", effective["anti_dup"]))
    lines.extend(_render_labeled_block("Placement Intent", effective["placement_intent"]))

    lines.extend(_render_static_section("SCOPE LINKS (CONDITIONAL)"))
    lines.extend(_render_labeled_block("Guild Orders Ref", effective["guild_orders_ref"]))
    lines.extend(_render_labeled_block("Dungeon Ref", effective["dungeon_ref"]))
    lines.extend(_render_labeled_block("Dungeon Coverage", effective["dungeon_coverage"]))

    lines.extend(_render_static_section("QUEST OUTCOME CONTRACT (REQUIRED)"))
    lines.extend(_render_labeled_block("Coherent Outcome", effective["coherent_outcome"]))
    lines.extend(_render_labeled_block("Closure Statement", effective["closure_statement"]))
    lines.extend(_render_labeled_block("Split Triggers", effective["split_triggers"]))

    lines.extend(_render_static_section("RISK + CONSENT GATE (CONDITIONAL)"))
    lines.extend(_render_labeled_block("Risk", effective["risk"]))
    lines.extend(_render_labeled_block("R2 Confirmation Artifact (REQUIRED if Risk = R2)", effective["r2_confirmation_artifact"]))

    lines.extend(_render_static_section("DESCRIPTION (REQUIRED)"))
    lines.extend(_render_labeled_block("Description", effective["description"]))

    lines.extend(_render_static_section("SCOPE / OBJECTIVE (REQUIRED)"))
    lines.extend(_render_labeled_block("Scope / Objective", effective["objective"]))
    lines.extend(_render_labeled_block("Stretch Plan / Milestones", effective["milestones"]))

    lines.extend(_render_static_section("OUT OF SCOPE (REQUIRED)"))
    lines.extend(_render_labeled_block("Out of Scope", effective["out_of_scope"]))

    lines.extend(_render_static_section("DEPENDENCIES (REQUIRED: LIST OR EXPLICIT NONE)"))
    lines.extend(_render_labeled_block("Dependencies", effective["dependencies"]))

    lines.extend(_render_static_section("DOORS + TESTING LEVEL (CONDITIONAL: CODE/SOFTWARE)"))
    lines.extend(_render_labeled_block("Door Impact", effective["door_impact"]))
    lines.extend(_render_labeled_block("Testing Level (TL)", effective["testing_level"]))

    lines.extend(_render_static_section("VERIFICATION PLAN (REQUIRED BEFORE EXECUTION)"))
    lines.extend(_render_labeled_block("Verification Plan", effective["verification_plan"]))

    lines.extend(_render_static_section("PLAN + AUDIT LINKS (REQUIRED)"))
    lines.extend(_render_labeled_block("Plan Artifact Refs", effective["plan_artifact_refs"]))
    lines.extend(_render_labeled_block("Audit State", effective["audit_state"]))
    lines.extend(_render_labeled_block("Audit Bundle Folder Path (required once ACCEPTED)", effective["audit_bundle_path"]))
    lines.extend(_render_labeled_block("State History", effective["state_history"]))
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


def _milestones_text(values: list[dict[str, str]]) -> str:
    if not values:
        return "- MILESTONE-001 :: Close the bounded outcome and record a clean completion audit PASS."
    return "\n".join(f"- {item['id']} :: {item['text']}" for item in values)


def _state_history_text(state: str, created_at: str) -> str:
    return f"- {created_at} :: {state}"


def write_quest_document(*, quest_path: Path, values: dict[str, str]) -> None:
    template = load_quest_template()
    quest_path.parent.mkdir(parents=True, exist_ok=True)
    quest_path.write_text(fill_quest_template(template, values), encoding="utf-8")


def draft_quest_from_proposal(*, subject: str, data_root: Path, proposal: dict[str, Any], prefix: str) -> dict[str, str]:
    today = today_toronto()
    qid = f"{prefix}_{next_quest_number(data_root, prefix):03d}"
    title = str(proposal.get("title") or qid).strip() or qid
    slug = _slugify(title)
    board_dir = data_root / "Quest Board"
    board_dir.mkdir(parents=True, exist_ok=True)
    quest_path = board_dir / f"{qid}__{slug}__{today}.txt"
    created_at = dt.datetime.now(tz=DEFAULT_TIMEZONE).isoformat()

    evidence = _string_list(proposal.get("evidence"))
    related_files = _string_list(proposal.get("related_files"))
    links = ", ".join(evidence[:8] or related_files[:8]) or "None"
    summary = str(proposal.get("summary") or proposal.get("reason") or title).strip()
    description = str(proposal.get("description") or summary).strip()
    objective = str(proposal.get("objective") or summary).strip()
    candidate_kind = str(proposal.get("kind") or "quest").replace("_", " ")
    milestones = normalize_milestones(
        proposal.get("milestones")
        or [summary]
    )
    coherent_outcome = str(proposal.get("coherent_outcome") or objective).strip() or objective
    plan_payload = persist_execution_plan(
        subject=subject,
        data_root=data_root,
        title=title,
        summary=summary,
        origin=str(proposal.get("origin") or f"Ambient proposal {proposal.get('proposal_id')}"),
        objective=objective,
        coherent_outcome=coherent_outcome,
        closure_statement=str(proposal.get("closure_statement") or f"Close only when {coherent_outcome.lower()} is honestly satisfied and the completion audit returns PASS."),
        out_of_scope=str(proposal.get("out_of_scope") or "Any work beyond this clustered candidate scope."),
        dependencies=_string_list(proposal.get("dependencies") if isinstance(proposal.get("dependencies"), list) else [proposal.get("dependencies") or "None"]),
        risk=str(proposal.get("risk") or "R0"),
        verification_plan=str(proposal.get("verification_plan") or DEFAULT_VERIFICATION_PLAN),
        milestones=milestones,
        split_triggers=_string_list(
            proposal.get("split_triggers")
            if isinstance(proposal.get("split_triggers"), list)
            else [proposal.get("split_triggers") or "Split if the work reveals more than one independently closable outcome."]
        ),
        guild_orders_ref=str(proposal.get("guild_orders_ref") or ""),
        dungeon_ref=str(proposal.get("dungeon_ref") or ""),
        dungeon_coverage=str(proposal.get("dungeon_coverage") or "N/A"),
        links=evidence[:8] or related_files[:8],
        quest_refs=[str(quest_path.resolve())],
        related_run_ids=_string_list(proposal.get("related_run_ids")),
        source="quest-candidate-formalize",
        plan_id=str(proposal.get("plan_id") or "").strip() or None,
    )
    values = {
        "quest_id": qid,
        "title": title,
        "subject": subject,
        "origin": str(proposal.get("origin") or f"Ambient proposal {proposal.get('proposal_id')}"),
        "priority": str(proposal.get("priority") or "P1"),
        "links": links,
        "quest_state": "BOARD",
        "created_at": created_at,
        "codex_anchors": str(proposal.get("codex_anchors") or DEFAULT_CODEX_ANCHORS),
        "codex_constraints": str(proposal.get("codex_constraints") or proposal.get("reason") or "TBD - derive from proposal evidence"),
        "change_class": str(proposal.get("change_class") or "STRUCTURAL"),
        "vision_delta": str(proposal.get("vision_delta") or "ALIGNED"),
        "system_context": str(proposal.get("system_context") or _build_system_context(candidate_kind, related_files, summary)),
        "anti_dup": str(proposal.get("anti_dup") or _build_anti_dup(title, related_files)),
        "placement_intent": str(proposal.get("placement_intent") or _build_placement_intent(related_files)),
        "guild_orders_ref": str(proposal.get("guild_orders_ref") or "N/A"),
        "dungeon_ref": str(proposal.get("dungeon_ref") or "N/A"),
        "dungeon_coverage": str(proposal.get("dungeon_coverage") or "N/A"),
        "coherent_outcome": coherent_outcome,
        "closure_statement": str(proposal.get("closure_statement") or f"Close only when {coherent_outcome.lower()} is honestly satisfied and the completion audit returns PASS."),
        "split_triggers": "\n".join(_string_list(proposal.get("split_triggers")) or ["- Split if the work reveals more than one independently closable outcome."]),
        "risk": str(proposal.get("risk") or "R0"),
        "door_impact": str(proposal.get("door_impact") or "NONE"),
        "testing_level": str(proposal.get("testing_level") or DEFAULT_TESTING_LEVEL),
        "description": description,
        "objective": objective,
        "milestones": _milestones_text(milestones),
        "out_of_scope": str(proposal.get("out_of_scope") or "Any work beyond the ambiently clustered candidate scope."),
        "dependencies": "\n".join(_string_list(proposal.get("dependencies")) or ["None"]),
        "verification_plan": str(proposal.get("verification_plan") or DEFAULT_VERIFICATION_PLAN),
        "plan_artifact_refs": f"- {plan_payload['path']}",
        "audit_state": "not_started",
        "audit_bundle_path": str(proposal.get("audit_bundle_path") or ""),
        "state_history": _state_history_text("BOARD", created_at),
    }
    write_quest_document(quest_path=quest_path, values=values)
    return {
        "quest_id": qid,
        "artifact_path": str(quest_path),
        "plan_artifact_path": plan_payload["path"],
        "plan_id": plan_payload["plan_id"],
        "plan_revision_id": plan_payload["revision_id"],
    }

"""Quest completion-audit recording and closure helpers."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from synapse_runtime.quest_acceptance import (
    QuestAcceptanceError,
    parse_quest_document,
    resolve_active_quest,
)


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
COMPLETION_AUDIT_FILENAME = "01_COMPLETION_AUDIT.md"
COMPLETION_AUDIT_HISTORY_GLOB = "01_COMPLETION_AUDIT__ATTEMPT-*.md"
_ATTEMPT_RX = re.compile(r"01_COMPLETION_AUDIT__ATTEMPT-(\d{3})\.md$", re.IGNORECASE)
_STATUS_VALUES = {"DONE", "PASS", "PARTIAL", "PENDING", "BLOCKED", "SKIPPED"}


class QuestCompletionError(RuntimeError):
    """Raised when quest completion cannot be recorded lawfully."""


@dataclass(frozen=True)
class CompletionAuditAttempt:
    attempt_number: int
    overall_verdict: str
    final_state_decision: str
    milestone_statuses: list[dict[str, str]]
    check_results: list[dict[str, str]]
    skipped_items: list[str]
    unresolved_gaps: list[str]
    known_bugs: list[str]
    blockers: list[str]
    changed_files: list[str]
    receipt_refs: list[str]
    commands_run: list[str]
    disclosures: list[str]


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _normalize_text_list(values: Iterable[str]) -> list[str]:
    results: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in results:
            results.append(text)
    return results


def _history_attempt_number(path: Path) -> int | None:
    match = _ATTEMPT_RX.search(path.name)
    if not match:
        return None
    return int(match.group(1))


def next_attempt_number(bundle_path: Path) -> int:
    current = 1 if (bundle_path / COMPLETION_AUDIT_FILENAME).exists() else 0
    history = max(
        (_history_attempt_number(path) or 0 for path in bundle_path.glob(COMPLETION_AUDIT_HISTORY_GLOB)),
        default=0,
    )
    return max(current, history) + 1


def parse_status_entries(entries: Iterable[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for raw in entries:
        text = str(raw).strip()
        if not text:
            continue
        parts = [part.strip() for part in text.split(":", 2)]
        if len(parts) < 2:
            raise QuestCompletionError(
                f"Invalid status entry '{text}'. Use KEY:STATUS or KEY:STATUS:DETAIL."
            )
        key, status = parts[0], parts[1].upper()
        detail = parts[2] if len(parts) == 3 else ""
        if not key or status not in _STATUS_VALUES:
            raise QuestCompletionError(
                f"Invalid status entry '{text}'. Status must be one of {sorted(_STATUS_VALUES)}."
            )
        results.append({"key": key, "status": status, "detail": detail})
    return results


def parse_check_entries(entries: Iterable[str]) -> list[dict[str, str]]:
    results = parse_status_entries(entries)
    for item in results:
        if item["status"] not in {"PASS", "FAIL", "BLOCKED"}:
            raise QuestCompletionError(
                f"Check '{item['key']}' must use PASS, FAIL, or BLOCKED, got {item['status']}."
            )
    return results


def compute_completion_verdict(
    *,
    milestone_statuses: list[dict[str, str]],
    check_results: list[dict[str, str]],
    skipped_items: list[str],
    unresolved_gaps: list[str],
    known_bugs: list[str],
    blockers: list[str],
    receipt_refs: list[str],
) -> tuple[str, str]:
    if not receipt_refs:
        return "FAIL", "ACTIVE"
    milestone_values = [item["status"] for item in milestone_statuses]
    check_values = [item["status"] for item in check_results]
    if blockers or "BLOCKED" in milestone_values or "BLOCKED" in check_values:
        return "BLOCKED", "ACTIVE"
    if (
        skipped_items
        or unresolved_gaps
        or known_bugs
        or any(value in {"PENDING", "PARTIAL", "SKIPPED"} for value in milestone_values)
        or "FAIL" in check_values
    ):
        return "FAIL", "ACTIVE"
    if not milestone_statuses or not check_results:
        return "FAIL", "ACTIVE"
    if all(value in {"DONE", "PASS"} for value in milestone_values) and all(value == "PASS" for value in check_values):
        return "PASS", "COMPLETED"
    return "FAIL", "ACTIVE"


def _render_status_section(title: str, entries: list[dict[str, str]]) -> list[str]:
    lines = [title]
    if not entries:
        lines.append("- none")
        lines.append("")
        return lines
    for entry in entries:
        detail = f" :: {entry['detail']}" if entry.get("detail") else ""
        lines.append(f"- {entry['key']}: {entry['status']}{detail}")
    lines.append("")
    return lines


def _render_text_section(title: str, values: list[str]) -> list[str]:
    lines = [title]
    if not values:
        lines.append("- none")
        lines.append("")
        return lines
    lines.extend(f"- {value}" for value in values)
    lines.append("")
    return lines


def build_completion_audit(
    *,
    quest_id: str,
    quest_title: str,
    bundle_path: Path,
    plan_revision_refs: list[str],
    milestone_statuses: list[dict[str, str]],
    check_results: list[dict[str, str]],
    commands_run: list[str],
    changed_files: list[str],
    receipt_refs: list[str],
    skipped_items: list[str],
    unresolved_gaps: list[str],
    known_bugs: list[str],
    blockers: list[str],
    disclosures: list[str],
    notes: list[str],
    attempt_number: int,
) -> str:
    verdict, final_state = compute_completion_verdict(
        milestone_statuses=milestone_statuses,
        check_results=check_results,
        skipped_items=skipped_items,
        unresolved_gaps=unresolved_gaps,
        known_bugs=known_bugs,
        blockers=blockers,
        receipt_refs=receipt_refs,
    )
    lines: list[str] = [
        "# 01_COMPLETION_AUDIT.md",
        "",
        f"- Attempt Number: {attempt_number}",
        f"- Recorded At: {_now_iso()}",
        f"- Quest ID: {quest_id}",
        f"- Quest Title: {quest_title}",
        f"- Audit Bundle: {bundle_path}",
        f"- Plan Revision Refs: {', '.join(plan_revision_refs) if plan_revision_refs else 'none'}",
        f"- Overall Verdict: {verdict}",
        f"- Final State Decision: {final_state}",
        "",
    ]
    lines.extend(_render_status_section("## Milestone Status", milestone_statuses))
    lines.extend(_render_status_section("## Check Results", check_results))
    lines.extend(_render_text_section("## Commands Actually Run", commands_run))
    lines.extend(_render_text_section("## Files / Artifacts Touched", changed_files))
    lines.extend(_render_text_section("## Receipt References", receipt_refs))
    lines.extend(_render_text_section("## Skipped Items", skipped_items))
    lines.extend(_render_text_section("## Unresolved Gaps", unresolved_gaps))
    lines.extend(_render_text_section("## Known Bugs / Regressions In Scope", known_bugs))
    lines.extend(_render_text_section("## Blockers", blockers))
    lines.extend(_render_text_section("## Disclosure Events", disclosures))
    lines.extend(_render_text_section("## Next Actions", blockers or unresolved_gaps or skipped_items or known_bugs))
    lines.extend(_render_text_section("## Notes", notes))
    return "\n".join(lines).rstrip() + "\n"


def _extract_list_entries(raw: str) -> list[str]:
    values: list[str] = []
    for line in str(raw or "").splitlines():
        text = re.sub(r"^[-*]\s*", "", line.strip())
        if text:
            values.append(text)
    return values


def _parse_defined_milestones(raw: str, objective: str) -> list[dict[str, str]]:
    lines = _extract_list_entries(raw)
    if not lines and objective.strip():
        return [{"id": "MILESTONE-001", "text": objective.strip()}]
    results: list[dict[str, str]] = []
    for index, line in enumerate(lines, start=1):
        left, _, right = line.partition("::")
        milestone_id = left.strip() if right else f"MILESTONE-{index:03d}"
        text = right.strip() if right else left.strip()
        results.append({"id": milestone_id or f"MILESTONE-{index:03d}", "text": text})
    return results


def _materialize_milestone_statuses(
    defined: list[dict[str, str]],
    supplied: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not defined and supplied:
        return supplied
    supplied_by_key = {item["key"]: item for item in supplied}
    results: list[dict[str, str]] = []
    for item in defined:
        match = supplied_by_key.get(item["id"]) or supplied_by_key.get(item["text"])
        if match:
            results.append({"key": item["id"], "status": match["status"], "detail": match.get("detail") or item["text"]})
        else:
            results.append({"key": item["id"], "status": "PENDING", "detail": f"{item['text']} (not reported)"})
    return results


def _replace_labeled_value(text: str, label: str, value: str) -> str:
    lines = text.splitlines()
    needle = f"{label}:"
    for idx, raw in enumerate(lines):
        if raw.strip().startswith(needle):
            prefix = raw.split(":", 1)[0] + ":"
            rendered_lines = [line.rstrip() for line in str(value or "").splitlines()]
            if len(rendered_lines) <= 1:
                lines[idx] = f"{prefix} {rendered_lines[0] if rendered_lines else ''}".rstrip()
                j = idx + 1
            else:
                lines[idx] = prefix
                lines[idx + 1 : idx + 1] = rendered_lines
                j = idx + 1 + len(rendered_lines)
            while j < len(lines):
                stripped = lines[j].strip()
                if not stripped:
                    break
                if stripped.startswith("#"):
                    j += 1
                    continue
                if stripped.startswith("===") or re.match(r"^[A-Za-z0-9_ /().-]+:\s*(?:.*)?$", stripped):
                    break
                del lines[j]
            return "\n".join(lines).rstrip() + "\n"
    return text.rstrip() + f"\n{label}: {value}\n"


def _replace_multi_value(text: str, label: str, values: list[str]) -> str:
    return _replace_labeled_value(text, label, "\n".join(values))


def _update_summary(
    *,
    summary_path: Path,
    quest_id: str,
    title: str,
    quest_path: Path,
    bundle_path: Path,
    audit_state: str,
    plan_revision_refs: list[str],
    coherent_outcome: str,
    closure_statement: str,
    milestones: list[dict[str, str]],
    verification_plan: str,
    latest_audit_path: Path,
) -> None:
    lines = [
        "# 00_SUMMARY.md",
        "",
        f"- Quest ID: {quest_id}",
        f"- Title: {title}",
        f"- Quest Path: {quest_path}",
        f"- Audit Bundle: {bundle_path}",
        f"- Audit State: {audit_state}",
        f"- Latest Completion Audit: {latest_audit_path}",
        f"- Plan Artifact Refs: {', '.join(plan_revision_refs) if plan_revision_refs else 'none'}",
        "",
        "## Coherent Outcome",
        coherent_outcome,
        "",
        "## Closure Statement",
        closure_statement,
        "",
        "## Milestones",
    ]
    if milestones:
        lines.extend(f"- {item['key']}: {item['status']} :: {item.get('detail') or ''}".rstrip() for item in milestones)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Verification Plan",
            verification_plan,
            "",
        ]
    )
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def complete_quest(
    *,
    subject: str,
    data_root: Path,
    quest_ref: str,
    milestone_entries: Iterable[str],
    check_entries: Iterable[str],
    commands_run: Iterable[str],
    changed_files: Iterable[str],
    receipt_refs: Iterable[str],
    skipped_items: Iterable[str],
    unresolved_gaps: Iterable[str],
    known_bugs: Iterable[str],
    blockers: Iterable[str],
    disclosures: Iterable[str],
    notes: Iterable[str],
) -> dict[str, Any]:
    try:
        quest_path = resolve_active_quest(data_root, quest_ref)
    except QuestAcceptanceError as exc:
        raise QuestCompletionError(str(exc)) from exc
    doc = parse_quest_document(subject=subject, data_root=data_root, path=quest_path)
    bundle_path = doc.audit_bundle_path
    if bundle_path is None:
        raise QuestCompletionError("Accepted/completed quest is missing its audit bundle path.")
    bundle_path.mkdir(parents=True, exist_ok=True)

    defined_milestones = _parse_defined_milestones(doc.milestones_raw, doc.objective)
    milestone_statuses = _materialize_milestone_statuses(defined_milestones, parse_status_entries(milestone_entries))
    check_results = parse_check_entries(check_entries)
    commands = _normalize_text_list(commands_run)
    changed = _normalize_text_list(changed_files)
    receipts = _normalize_text_list(receipt_refs)
    skipped = _normalize_text_list(skipped_items)
    gaps = _normalize_text_list(unresolved_gaps)
    bugs = _normalize_text_list(known_bugs)
    blocked = _normalize_text_list(blockers)
    disclosure_values = _normalize_text_list(disclosures)
    note_values = _normalize_text_list(notes)

    attempt_number = next_attempt_number(bundle_path)
    archived_audit = archive_existing_completion_audit(bundle_path)
    latest_path = bundle_path / COMPLETION_AUDIT_FILENAME
    audit_text = build_completion_audit(
        quest_id=doc.quest_id,
        quest_title=doc.title,
        bundle_path=bundle_path,
        plan_revision_refs=doc.plan_artifact_refs,
        milestone_statuses=milestone_statuses,
        check_results=check_results,
        commands_run=commands,
        changed_files=changed,
        receipt_refs=receipts,
        skipped_items=skipped,
        unresolved_gaps=gaps,
        known_bugs=bugs,
        blockers=blocked,
        disclosures=disclosure_values,
        notes=note_values,
        attempt_number=attempt_number,
    )
    latest_path.write_text(audit_text, encoding="utf-8")
    if changed:
        (bundle_path / "06_CHANGED_FILES.txt").write_text("\n".join(changed).rstrip() + "\n", encoding="utf-8")
    if commands or receipts:
        test_lines = [*commands, *[f"RECEIPT: {item}" for item in receipts]]
        (bundle_path / "06_TESTS.txt").write_text("\n".join(test_lines).rstrip() + "\n", encoding="utf-8")

    parsed = parse_completion_audit(latest_path)
    if parsed is None:
        raise QuestCompletionError(f"Failed to parse completion audit: {latest_path}")

    updated_at = _now_iso()
    state_history = _extract_list_entries(doc.state_history_raw)
    next_state = "COMPLETED" if parsed.final_state_decision == "COMPLETED" else "ACCEPTED"
    state_history.append(f"{updated_at} :: {next_state} ({parsed.overall_verdict})")
    updated_text = doc.raw_text
    updated_text = _replace_labeled_value(updated_text, "Quest State", next_state)
    updated_text = _replace_labeled_value(updated_text, "Audit State", parsed.overall_verdict.lower())
    updated_text = _replace_labeled_value(updated_text, "Last Audit At", updated_at)
    updated_text = _replace_labeled_value(
        updated_text,
        "Completed At",
        updated_at if parsed.final_state_decision == "COMPLETED" else "",
    )
    updated_text = _replace_multi_value(updated_text, "State History", [f"- {item}" for item in state_history])

    board_root = data_root / "Quest Board"
    accepted_path = board_root / "Accepted" / quest_path.name
    completed_path = board_root / "Completed" / quest_path.name
    if parsed.final_state_decision == "COMPLETED":
        target_path = completed_path
    else:
        target_path = accepted_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if quest_path.resolve() != target_path.resolve():
        if target_path.exists():
            target_path.unlink()
        quest_path.unlink(missing_ok=True)
    target_path.write_text(updated_text, encoding="utf-8")

    _update_summary(
        summary_path=bundle_path / "00_SUMMARY.md",
        quest_id=doc.quest_id,
        title=doc.title,
        quest_path=target_path,
        bundle_path=bundle_path,
        audit_state=parsed.overall_verdict.lower(),
        plan_revision_refs=doc.plan_artifact_refs,
        coherent_outcome=doc.coherent_outcome,
        closure_statement=doc.closure_statement,
        milestones=milestone_statuses,
        verification_plan=doc.verification_plan,
        latest_audit_path=latest_path,
    )

    return {
        "quest_id": doc.quest_id,
        "quest_title": doc.title,
        "source_path": str(quest_path.resolve()),
        "active_path": str(target_path.resolve()),
        "audit_bundle_path": str(bundle_path.resolve()),
        "latest_completion_audit_path": str(latest_path.resolve()),
        "archived_completion_audit_path": str(archived_audit.resolve()) if archived_audit else None,
        "overall_verdict": parsed.overall_verdict,
        "final_state_decision": parsed.final_state_decision,
        "audit_state": parsed.overall_verdict.lower(),
    }


def parse_completion_audit(path: Path) -> CompletionAuditAttempt | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    def _value(label: str) -> str:
        match = re.search(rf"(?im)^- {re.escape(label)}:\s*(.+)$", text)
        return match.group(1).strip() if match else ""

    def _section(title: str) -> list[str]:
        match = re.search(rf"(?ims)^## {re.escape(title)}\n(?P<body>.*?)(?:^\s*## |\Z)", text)
        if not match:
            return []
        values: list[str] = []
        for line in match.group("body").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                values.append(stripped[2:].strip())
        return [value for value in values if value != "none"]

    def _parse_statuses(title: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for value in _section(title):
            key, _, rest = value.partition(":")
            status, _, detail = rest.strip().partition("::")
            if key and status:
                results.append({"key": key.strip(), "status": status.strip().upper(), "detail": detail.strip()})
        return results

    attempt_text = _value("Attempt Number")
    try:
        attempt_number = int(attempt_text)
    except Exception:
        attempt_number = 0
    return CompletionAuditAttempt(
        attempt_number=attempt_number,
        overall_verdict=_value("Overall Verdict").upper(),
        final_state_decision=_value("Final State Decision").upper(),
        milestone_statuses=_parse_statuses("Milestone Status"),
        check_results=_parse_statuses("Check Results"),
        skipped_items=_section("Skipped Items"),
        unresolved_gaps=_section("Unresolved Gaps"),
        known_bugs=_section("Known Bugs / Regressions In Scope"),
        blockers=_section("Blockers"),
        changed_files=_section("Files / Artifacts Touched"),
        receipt_refs=_section("Receipt References"),
        commands_run=_section("Commands Actually Run"),
        disclosures=_section("Disclosure Events"),
    )


def completion_audit_is_clean_pass(path: Path) -> bool:
    attempt = parse_completion_audit(path)
    return bool(attempt and attempt.overall_verdict == "PASS" and attempt.final_state_decision == "COMPLETED")


def archive_existing_completion_audit(bundle_path: Path) -> Path | None:
    latest = bundle_path / COMPLETION_AUDIT_FILENAME
    if not latest.exists():
        return None
    attempt_number = next_attempt_number(bundle_path) - 1
    archived = bundle_path / f"01_COMPLETION_AUDIT__ATTEMPT-{attempt_number:03d}.md"
    latest.rename(archived)
    return archived

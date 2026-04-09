"""Pure authored continuity renderers for working-canon artifacts."""

from __future__ import annotations

from typing import Any, Iterable


CANONIZER_SCHEMA_VERSION = 1

TRUTH_LABEL = "TRUTH"
VISION_LABEL = "VISION"
UNRESOLVED_LABEL = "UNRESOLVED"

_WORKING_RECORD_VISION_FAMILIES = {"NARRATIVE_CLAIMS", "PROJECT_IDENTITY_CLAIMS"}
_WORKING_RECORD_RISK_FAMILIES = {"FAILURE_CHAINS"}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_lines(lines: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = _normalize_text(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def normalize_source_refs(source_refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        kind = _normalize_text(item.get("kind"))
        source_id = _normalize_text(item.get("id"))
        path = _normalize_text(item.get("path") or item.get("body_path"))
        key = (kind, source_id, path)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        normalized.append({k: v for k, v in item.items() if v is not None})
    return normalized


def compose_authored_sections(
    *,
    truths: Iterable[Any] = (),
    visions: Iterable[Any] = (),
    unresolved: Iterable[Any] = (),
    source_refs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    normalized_refs = normalize_source_refs(source_refs)
    sections = {
        "schema_version": CANONIZER_SCHEMA_VERSION,
        "implemented_truths": _normalize_lines(truths),
        "intended_directions": _normalize_lines(visions),
        "unresolved_items": _normalize_lines(unresolved),
        "source_ref_count": len(normalized_refs),
        "source_refs": normalized_refs,
    }
    sections["truth_state_lines"] = authored_detail_lines(sections)
    sections["truth_state_counts"] = truth_state_counts(sections)
    return sections


def truth_state_counts(sections: dict[str, Any]) -> dict[str, int]:
    return {
        TRUTH_LABEL: len(list(sections.get("implemented_truths") or [])),
        VISION_LABEL: len(list(sections.get("intended_directions") or [])),
        UNRESOLVED_LABEL: len(list(sections.get("unresolved_items") or [])),
    }


def authored_detail_lines(sections: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in sections.get("implemented_truths") or []:
        lines.append(f"[{TRUTH_LABEL}] {item}")
    for item in sections.get("intended_directions") or []:
        lines.append(f"[{VISION_LABEL}] {item}")
    for item in sections.get("unresolved_items") or []:
        lines.append(f"[{UNRESOLVED_LABEL}] {item}")
    source_ref_count = int(sections.get("source_ref_count") or 0)
    if source_ref_count:
        lines.append(f"[EVIDENCE] {source_ref_count} source refs")
    return _normalize_lines(lines)


def _bullet_lines(items: Iterable[Any], *, empty: str = "- none") -> list[str]:
    normalized = _normalize_lines(items)
    if not normalized:
        return [empty]
    return [f"- {item}" for item in normalized]


def render_source_refs_section(source_refs: Iterable[dict[str, Any]]) -> list[str]:
    normalized_refs = normalize_source_refs(source_refs)
    if not normalized_refs:
        return ["- none"]
    lines: list[str] = []
    for item in normalized_refs:
        path = _normalize_text(item.get("path") or item.get("body_path") or "n/a")
        lines.append(f"- [{_normalize_text(item.get('kind')) or 'unknown'}] {_normalize_text(item.get('id')) or 'unknown'} :: {path}")
    return lines


def author_decision_body(
    *,
    subject: str,
    logged_at: str,
    title: str,
    summary: str,
    why: str | None,
    constraints: Iterable[str],
    tradeoffs: Iterable[str],
    related_runs: Iterable[str],
    related_quests: Iterable[str],
    source_refs: Iterable[dict[str, Any]] = (),
    intended_directions: Iterable[str] = (),
    unresolved_items: Iterable[str] = (),
) -> tuple[str, dict[str, Any]]:
    sections = compose_authored_sections(
        truths=[summary, f"Rationale: {why}" if _normalize_text(why) else None],
        visions=intended_directions,
        unresolved=unresolved_items,
        source_refs=source_refs,
    )
    lines = [
        f"# {_normalize_text(title) or 'Decision'}",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {logged_at}",
        "",
        "## Decision Summary",
        _normalize_text(summary) or "- none",
        "",
        "## Implemented Truths",
        *_bullet_lines(sections["implemented_truths"]),
        "",
        "## Intended Direction",
        *_bullet_lines(sections["intended_directions"]),
        "",
        "## Unresolved / Review",
        *_bullet_lines(sections["unresolved_items"]),
        "",
    ]
    normalized_constraints = _normalize_lines(constraints)
    if normalized_constraints:
        lines.extend(["## Constraints", *[f"- {item}" for item in normalized_constraints], ""])
    normalized_tradeoffs = _normalize_lines(tradeoffs)
    if normalized_tradeoffs:
        lines.extend(["## Tradeoffs", *[f"- {item}" for item in normalized_tradeoffs], ""])
    related_lines = [f"- Run: {item}" for item in _normalize_lines(related_runs)] + [
        f"- Quest: {item}" for item in _normalize_lines(related_quests)
    ]
    if related_lines:
        lines.extend(["## Related", *related_lines, ""])
    lines.extend(["## Source Refs", *render_source_refs_section(source_refs), ""])
    return "\n".join(lines).rstrip() + "\n", sections


def author_disclosure_body(
    *,
    subject: str,
    logged_at: str,
    trigger: str,
    expected: str,
    provable: str,
    status_labels: Iterable[str],
    impact: str,
    safe_options: Iterable[str],
    decision_needed: str,
    related_runs: Iterable[str],
    related_quests: Iterable[str],
    source_refs: Iterable[dict[str, Any]] = (),
) -> tuple[str, dict[str, Any]]:
    normalized_labels = [item.upper() for item in _normalize_lines(status_labels)]
    normalized_options = _normalize_lines(safe_options) or ["HALT until Brains chooses the next legal action."]
    sections = compose_authored_sections(
        truths=[provable],
        visions=[],
        unresolved=[decision_needed, *normalized_options],
        source_refs=source_refs,
    )
    label_lines = [f"- {item}" for item in normalized_labels] or ["- none"]
    lines = [
        "DISCLOSURE GATE -- EVENT",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {logged_at}",
        "",
        "Trigger:",
        _normalize_text(trigger) or "- none",
        "",
        "Expected:",
        _normalize_text(expected) or "- none",
        "",
        "Provable:",
        _normalize_text(provable) or "- none",
        "",
        "Status Labels:",
        *label_lines,
        "",
        "Impact:",
        _normalize_text(impact) or "- none",
        "",
        "Safe Options:",
        *[f"- {item}" for item in normalized_options],
        "",
        "Decision Needed From Brains:",
        _normalize_text(decision_needed) or "- none",
        "",
        "## Truths In Hand",
        *_bullet_lines(sections["implemented_truths"]),
        "",
        "## Unresolved / Review",
        *_bullet_lines(sections["unresolved_items"]),
        "",
    ]
    related_lines = [f"- Run: {item}" for item in _normalize_lines(related_runs)] + [
        f"- Quest: {item}" for item in _normalize_lines(related_quests)
    ]
    if related_lines:
        lines.extend(["Related:", *related_lines, ""])
    lines.extend(["## Source Refs", *render_source_refs_section(source_refs), ""])
    return "\n".join(lines).rstrip() + "\n", sections


def author_discovery_body(
    *,
    subject: str,
    logged_at: str,
    title: str,
    summary: str,
    truths: Iterable[str],
    visions: Iterable[str],
    unresolved: Iterable[str],
    related_runs: Iterable[str],
    related_quests: Iterable[str],
    source_refs: Iterable[dict[str, Any]] = (),
) -> tuple[str, dict[str, Any]]:
    sections = compose_authored_sections(
        truths=[summary, *truths],
        visions=visions,
        unresolved=unresolved,
        source_refs=source_refs,
    )
    lines = [
        f"# {_normalize_text(title) or 'Discovery'}",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {logged_at}",
        "",
        "## Discovery Summary",
        _normalize_text(summary) or "- none",
        "",
        "## Implemented Truths",
        *_bullet_lines(sections["implemented_truths"]),
        "",
        "## Intended Direction",
        *_bullet_lines(sections["intended_directions"]),
        "",
        "## Unresolved / Review",
        *_bullet_lines(sections["unresolved_items"]),
        "",
    ]
    related_lines = [f"- Run: {item}" for item in _normalize_lines(related_runs)] + [
        f"- Quest: {item}" for item in _normalize_lines(related_quests)
    ]
    if related_lines:
        lines.extend(["## Related", *related_lines, ""])
    lines.extend(["## Source Refs", *render_source_refs_section(source_refs), ""])
    return "\n".join(lines).rstrip() + "\n", sections


def render_draftshot_body(
    *,
    subject: str,
    session_id: str,
    run_id: str | None,
    revision_number: int,
    refreshed_at: str,
    draftshot_context: str,
    capture_entries: list[dict[str, Any]],
    sections: dict[str, list[dict[str, Any]]],
    running_log: list[dict[str, Any]],
) -> str:
    def _capture_index_line(entry: dict[str, Any]) -> str:
        label = _normalize_text(entry.get("truth_state")) or TRUTH_LABEL
        return f"- {entry['capture_id']} :: {entry['section']} :: {label} :: {entry['summary']}"

    def _section_lines(entries: list[dict[str, Any]]) -> list[str]:
        if not entries:
            return ["- none"]
        lines: list[str] = []
        for entry in entries:
            label = _normalize_text(entry.get("truth_state")) or TRUTH_LABEL
            lines.append(f"- [{entry['capture_id']}] [{label}] {entry['summary']}")
        return lines

    lines = [
        "================================================================================",
        "DRAFTSHOT",
        "================================================================================",
        "A) Header",
        "- Status: ACTIVE",
        f"- Date: {str(refreshed_at).split('T', 1)[0]}",
        f"- Revision: REV{revision_number}",
        f"- Session Context: {draftshot_context}",
        f"- Session ID: {session_id}",
        f"- Subject: {subject}",
        f"- Run ID: {run_id or 'none'}",
        "",
        "B) Capture Index",
    ]
    if capture_entries:
        lines.extend([_capture_index_line(entry) for entry in capture_entries])
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "C) Decisions",
            *_section_lines(sections.get("DECISIONS") or []),
            "",
            "D) Findings / Observations",
            *_section_lines(sections.get("FINDINGS") or []),
            "",
            "E) TODO / Follow-ups",
            *_section_lines(sections.get("TODO") or []),
            "",
            "F) Risks / Blockers",
            *_section_lines(sections.get("RISKS") or []),
            "",
            "G) Open Questions",
            *_section_lines(sections.get("OPEN_QUESTIONS") or []),
            "",
            "H) Running Log",
        ]
    )
    if running_log:
        for entry in running_log:
            revision_label = _normalize_text(entry.get("revision_label")) or f"REV{revision_number}"
            refreshed_line = _normalize_text(entry.get("refreshed_at")) or refreshed_at
            change_type = _normalize_text(entry.get("change_type")) or "updated"
            summary = _normalize_text(entry.get("summary"))
            source_ref_count = int(entry.get("source_ref_count") or 0)
            lines.append(
                f"- {revision_label} @ {refreshed_line} :: {change_type} :: {source_ref_count} source refs :: {summary}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "END OF DRAFTSHOT", ""])
    return "\n".join(lines)


def render_snapshot_candidate_body(
    *,
    kind: str,
    subject: str,
    session_id: str | None,
    target_day: str,
    revision_number: int,
    refreshed_at: str,
    summary: str,
    truths: Iterable[str],
    visions: Iterable[str],
    unresolved: Iterable[str],
    draftshot: dict[str, Any],
    source_refs: Iterable[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    sections = compose_authored_sections(
        truths=[summary, *truths],
        visions=visions,
        unresolved=unresolved,
        source_refs=source_refs,
    )
    title = "End Of Day Snapshot Candidate" if kind == "EOD" else "Control Sync Snapshot Candidate"
    summary_heading = "## Candidate Summary" if kind == "EOD" else "## Control Sync Summary"
    lines = [
        f"# {title}",
        "",
        "- Status: DRAFT",
        f"- Candidate Kind: {kind}",
        f"- Target Day: {target_day}",
        f"- Revision: REV{revision_number}",
        f"- Subject: {subject}",
        f"- Session ID: {session_id or 'none'}",
        f"- Refreshed At: {refreshed_at}",
        f"- Draftshot Revision: {draftshot.get('revision_id') or 'none'}",
        f"- Draftshot Body: {draftshot.get('body_path') or 'none'}",
        "",
        summary_heading,
        _normalize_text(summary) or "- none",
        "",
        "## Truths In Hand",
        *_bullet_lines(sections["implemented_truths"]),
        "",
        "## Intended Direction",
        *_bullet_lines(sections["intended_directions"]),
        "",
        "## Unresolved / Review",
        *_bullet_lines(sections["unresolved_items"]),
        "",
        "## Source Refs",
        *render_source_refs_section(source_refs),
        "",
    ]
    return "\n".join(lines), sections


def render_publication_candidate_body(
    *,
    kind: str,
    summary: str,
    rendered_sections: list[tuple[str, str]],
    baseline_refs: Iterable[dict[str, Any]],
    source_refs: Iterable[dict[str, Any]],
    truths: Iterable[str],
    visions: Iterable[str],
    unresolved: Iterable[str],
    packet_inputs: Iterable[str] = (),
) -> tuple[str, dict[str, Any]]:
    sections = compose_authored_sections(
        truths=[summary, *truths],
        visions=visions,
        unresolved=unresolved,
        source_refs=source_refs,
    )
    title = {
        "STORY": "Project Story Candidate",
        "VISION": "Vision Candidate",
        "CODEX": "Codex Candidate",
    }.get(kind, "Publication Candidate")
    lines = [
        f"# {title}",
        "",
        "## Candidate Summary",
        _normalize_text(summary) or "- none",
        "",
        "## Truths In Hand",
        *_bullet_lines(sections["implemented_truths"]),
        "",
        "## Intended Direction",
        *_bullet_lines(sections["intended_directions"]),
        "",
        "## Unresolved / Review",
        *_bullet_lines(sections["unresolved_items"]),
        "",
        "## Canonical Baseline Refs",
    ]
    normalized_baseline_refs = normalize_source_refs(baseline_refs)
    if normalized_baseline_refs:
        lines.extend(
            [
                f"- [{item.get('baseline_kind')}] {item.get('path')} (confirmed_at={item.get('confirmed_at') or 'unknown'})"
                for item in normalized_baseline_refs
            ]
        )
    else:
        lines.append("- none")
    for section_title, rendered_text in rendered_sections:
        lines.extend(["", f"## {section_title}", rendered_text.rstrip()])
    normalized_packets = _normalize_lines(packet_inputs)
    if normalized_packets:
        lines.extend(["", "## Packet Inputs", *[f"- {item}" for item in normalized_packets]])
    lines.extend(["", "## Source Refs", *render_source_refs_section(source_refs), ""])
    return "\n".join(lines), sections


def working_record_authoring_metadata(
    *,
    family: str,
    summary: str,
    detail: str | None,
    source_refs: Iterable[dict[str, Any]],
    extra_truths: Iterable[str] = (),
    extra_visions: Iterable[str] = (),
    extra_unresolved: Iterable[str] = (),
) -> dict[str, Any]:
    normalized_summary = _normalize_text(summary)
    normalized_detail = _normalize_text(detail)
    if family in _WORKING_RECORD_VISION_FAMILIES:
        truths = list(extra_truths)
        visions = [normalized_summary, normalized_detail, *list(extra_visions)]
        unresolved = list(extra_unresolved)
    elif family in _WORKING_RECORD_RISK_FAMILIES:
        truths = [normalized_summary]
        visions = list(extra_visions)
        unresolved = [normalized_detail, *list(extra_unresolved)]
    else:
        truths = [normalized_summary, normalized_detail, *list(extra_truths)]
        visions = list(extra_visions)
        unresolved = list(extra_unresolved)
    sections = compose_authored_sections(
        truths=truths,
        visions=visions,
        unresolved=unresolved,
        source_refs=source_refs,
    )
    return {
        "canonizer": {
            "schema_version": CANONIZER_SCHEMA_VERSION,
            "implemented_truths": list(sections["implemented_truths"]),
            "intended_directions": list(sections["intended_directions"]),
            "unresolved_items": list(sections["unresolved_items"]),
            "truth_state_lines": list(sections["truth_state_lines"]),
            "truth_state_counts": dict(sections["truth_state_counts"]),
            "source_ref_count": int(sections["source_ref_count"]),
        }
    }

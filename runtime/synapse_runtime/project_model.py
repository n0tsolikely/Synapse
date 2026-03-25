"""Draft project model, question-set, and publication helpers for onboarding."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.live_memory_common import LiveMemoryError


class ProjectModelError(LiveMemoryError):
    """Raised when onboarding draft/question/publication content is invalid."""


DRAFT_ITEM_STATUSES = {"implemented", "partial", "intended", "stale", "superseded", "deprecated", "uncertain"}
CONFIDENCE_VALUES = {"low", "medium", "high"}
CLAIM_BASIS_VALUES = {"evidence_only", "user_only", "mixed"}
QUESTION_PRIORITIES = {"blocking", "important", "nice_to_have"}
QUESTION_STATUSES = {"open", "answered", "superseded", "deferred"}
QUESTION_CATEGORIES = {"purpose", "vision", "users", "capability", "history", "constraint", "status", "ownership"}

DRAFT_ITEM_LIST_FIELDS = (
    "user_or_stakeholder_hypotheses",
    "capability_hypotheses",
    "component_hypotheses",
    "interface_hypotheses",
    "constraint_hypotheses",
    "non_goal_hypotheses",
    "dependency_hypotheses",
    "history_and_supersession_hypotheses",
    "contradictions",
    "open_unknowns",
)
PART2_DRAFT_ITEM_LIST_FIELDS = (
    "implemented_truths",
    "partial_truths",
    "intended_capabilities",
    "future_ideas_needing_expansion",
    "superseded_directions",
)
ALL_DRAFT_ITEM_LIST_FIELDS = DRAFT_ITEM_LIST_FIELDS + PART2_DRAFT_ITEM_LIST_FIELDS
REQUIRED_NONEMPTY_TOP_LEVEL_FIELDS = (
    "summary_hypothesis",
    "purpose_hypothesis",
    "vision_hypothesis",
    "maturity_hypothesis",
)

_SCAN_REF_RE = re.compile(r"^scan:[^:]+:[^:]+:[^:]+$")
_CAPTURE_REF_RE = re.compile(r"^capture:[^:]+:[^:]+$")


def validate_draft_revision(
    draft: Any,
    *,
    onboarding_id: str,
    current_scan_id: str,
    unincorporated_capture_batch_ids: list[str],
    prior_draft: dict[str, Any] | None = None,
    scan_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise ProjectModelError("Draft project model must be an object.")
    normalized = dict(draft)
    if str(normalized.get("onboarding_id") or "").strip() != onboarding_id:
        raise ProjectModelError("Draft onboarding_id must match the current onboarding session.")
    if "ready_for_confirmation" in normalized:
        raise ProjectModelError("Drafts must not include a ready_for_confirmation field; readiness is runtime-derived.")
    for field in (
        "onboarding_id",
        "revision_id",
        "supersedes_revision_id",
        "created_at",
        "based_on_scan_ids",
        "based_on_capture_batch_ids",
        "summary_hypothesis",
        "purpose_hypothesis",
        "vision_hypothesis",
        "maturity_hypothesis",
        *ALL_DRAFT_ITEM_LIST_FIELDS,
        "next_question_ids",
    ):
        if field not in normalized:
            if field in PART2_DRAFT_ITEM_LIST_FIELDS:
                normalized[field] = []
            else:
                raise ProjectModelError(f"Draft project model missing required field: {field}")

    for field in REQUIRED_NONEMPTY_TOP_LEVEL_FIELDS:
        value = str(normalized.get(field) or "").strip()
        if not value:
            raise ProjectModelError(f"Draft field '{field}' must be non-empty.")
        normalized[field] = value

    based_on_scan_ids = _normalize_string_list(normalized.get("based_on_scan_ids"), field_name="based_on_scan_ids")
    if current_scan_id not in based_on_scan_ids:
        raise ProjectModelError("Draft must include current_scan_id in based_on_scan_ids.")
    normalized["based_on_scan_ids"] = based_on_scan_ids

    based_on_capture_batch_ids = _normalize_string_list(
        normalized.get("based_on_capture_batch_ids"),
        field_name="based_on_capture_batch_ids",
    )
    missing_capture_ids = [batch_id for batch_id in unincorporated_capture_batch_ids if batch_id not in based_on_capture_batch_ids]
    if missing_capture_ids:
        raise ProjectModelError(
            "Draft must incorporate every unincorporated clarification capture batch: "
            + ", ".join(missing_capture_ids)
        )
    normalized["based_on_capture_batch_ids"] = based_on_capture_batch_ids
    normalized["next_question_ids"] = _normalize_string_list(normalized.get("next_question_ids"), field_name="next_question_ids")

    prior_item_ids = set(flatten_draft_items(prior_draft).keys()) if prior_draft else set()
    normalized_items = flatten_draft_items(normalized)
    if not normalized_items:
        raise ProjectModelError("Draft must contain at least one hypothesis item.")
    if not normalized.get("capability_hypotheses") and not normalized.get("component_hypotheses"):
        raise ProjectModelError("Draft must contain at least one capability_hypothesis or component_hypothesis.")

    for field in ALL_DRAFT_ITEM_LIST_FIELDS:
        items = normalized.get(field)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ProjectModelError(f"Draft field '{field}' must be a list.")
        normalized[field] = [
            _normalize_draft_item(
                item,
                field_name=field,
                current_scan_ids=based_on_scan_ids,
                prior_item_ids=prior_item_ids,
            )
            for item in items
        ]

    _validate_draft_id_stability(normalized, prior_draft)
    _validate_draft_coverage(normalized, scan_artifact)
    return normalized


def validate_question_set(
    question_set: Any,
    *,
    onboarding_id: str,
    draft: dict[str, Any],
    linked_capture_batch_ids: list[str],
    prior_question_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(question_set, dict):
        raise ProjectModelError("Question set must be an object.")
    normalized = dict(question_set)
    for field in ("onboarding_id", "question_set_id", "draft_revision_id", "generated_at", "questions"):
        if field not in normalized:
            raise ProjectModelError(f"Question set missing required field: {field}")
    if str(normalized.get("onboarding_id") or "").strip() != onboarding_id:
        raise ProjectModelError("Question set onboarding_id must match the current onboarding session.")
    if str(normalized.get("draft_revision_id") or "").strip() != str(draft.get("revision_id") or "").strip():
        raise ProjectModelError("Question set draft_revision_id must match the submitted draft revision.")
    raw_questions = normalized.get("questions")
    if not isinstance(raw_questions, list):
        raise ProjectModelError("Question set field 'questions' must be a list.")
    if len(raw_questions) > 15:
        raise ProjectModelError("Question sets may contain at most 15 questions.")

    draft_item_ids = set(flatten_draft_items(draft).keys())
    normalized_questions = [
        _normalize_question_item(
            item,
            draft_item_ids=draft_item_ids,
            linked_capture_batch_ids=linked_capture_batch_ids,
            prior_question_ids=set(_question_index(prior_question_set).keys()),
        )
        for item in raw_questions
    ]
    priority_counts = {
        "blocking": sum(1 for item in normalized_questions if item["priority"] == "blocking"),
        "important": sum(1 for item in normalized_questions if item["priority"] == "important"),
    }
    if priority_counts["blocking"] > 5:
        raise ProjectModelError("Question set may contain at most 5 blocking questions.")
    if priority_counts["important"] > 10:
        raise ProjectModelError("Question set may contain at most 10 important questions.")
    normalized["questions"] = normalized_questions
    _validate_question_id_stability(normalized, prior_question_set)
    return normalized


def compute_revision_delta(
    draft: dict[str, Any],
    prior_draft: dict[str, Any] | None,
    *,
    reason_summary: str,
) -> dict[str, Any] | None:
    if prior_draft is None:
        return None
    current = flatten_draft_items(draft)
    previous = flatten_draft_items(prior_draft)
    new_item_ids = sorted(item_id for item_id in current if item_id not in previous)
    removed_item_ids = sorted(item_id for item_id in previous if item_id not in current)
    changed_item_ids = sorted(item_id for item_id, item in current.items() if item_id in previous and item != previous[item_id])
    unchanged_item_ids = sorted(item_id for item_id, item in current.items() if item_id in previous and item == previous[item_id])
    superseded_item_ids = sorted(
        item_id
        for item_id, item in current.items()
        if item_id in changed_item_ids and item.get("status") == "superseded"
    )
    return {
        "onboarding_id": draft["onboarding_id"],
        "revision_id": draft["revision_id"],
        "supersedes_revision_id": draft.get("supersedes_revision_id"),
        "generated_at": draft["created_at"],
        "new_item_ids": new_item_ids,
        "changed_item_ids": changed_item_ids,
        "removed_item_ids": removed_item_ids,
        "superseded_item_ids": superseded_item_ids,
        "unchanged_item_ids": unchanged_item_ids,
        "reason_summary": str(reason_summary or "").strip() or "Draft revision updated onboarding theory.",
    }


def evaluate_confirmation_readiness(
    *,
    onboarding_state: str,
    current_scan_id: str | None,
    unincorporated_capture_batch_ids: list[str],
    draft: dict[str, Any] | None,
    question_set: dict[str, Any] | None,
    required_artifact_paths: dict[str, str | None] | None = None,
    workplan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    warning_reasons: list[str] = []
    missing_artifacts: list[str] = []
    open_question_ids: list[str] = []
    if onboarding_state != "awaiting_confirmation":
        blocking_reasons.append("Onboarding state must be awaiting_confirmation.")
    if draft is None:
        blocking_reasons.append("Current draft revision is missing.")
    if question_set is None:
        blocking_reasons.append("Current question set is missing.")
    if required_artifact_paths:
        missing_artifacts = sorted(
            name
            for name, path_text in required_artifact_paths.items()
            if not str(path_text or "").strip() or not Path(str(path_text)).expanduser().exists()
        )
        if missing_artifacts:
            blocking_reasons.append("Required draft artifact family is incomplete.")
    if workplan:
        incomplete_steps = [
            str(item.get("step_id") or item.get("step") or "")
            for item in list(workplan.get("steps") or [])
            if bool(item.get("blocking", True)) and str(item.get("status") or "").strip() not in {"complete", "completed"}
        ]
        if incomplete_steps:
            blocking_reasons.append("Blocking onboarding workplan steps remain incomplete.")
    if draft is None or question_set is None:
        return {
            "ready": False,
            "blocking_reasons": blocking_reasons,
            "warning_reasons": warning_reasons,
            "missing_artifacts": missing_artifacts,
            "open_question_ids": open_question_ids,
            "unincorporated_clarification_batch_ids": list(unincorporated_capture_batch_ids),
        }
    if current_scan_id and current_scan_id not in list(draft.get("based_on_scan_ids") or []):
        blocking_reasons.append("Current draft does not incorporate current_scan_id.")
    if unincorporated_capture_batch_ids:
        blocking_reasons.append("Current draft does not incorporate all clarification capture batches.")
    open_questions = [
        question
        for question in question_set.get("questions") or []
        if str(question.get("status") or "") == "open"
    ]
    open_question_ids = [str(item.get("question_id") or "") for item in open_questions if str(item.get("question_id") or "").strip()]
    if _blocking_open_question_count(question_set) != 0:
        blocking_reasons.append("Blocking onboarding questions remain open.")
    for field in REQUIRED_NONEMPTY_TOP_LEVEL_FIELDS:
        if not str(draft.get(field) or "").strip():
            blocking_reasons.append(f"Draft field '{field}' must be non-empty.")
    if not draft.get("capability_hypotheses") and not draft.get("component_hypotheses"):
        blocking_reasons.append("Draft must include at least one capability or component hypothesis.")
    for item in flatten_draft_items(draft).values():
        if item.get("confidence") == "high" and item.get("claim_basis") != "user_only" and not item.get("evidence_refs"):
            blocking_reasons.append(f"High-confidence claim {item.get('id')} is missing evidence refs.")
            break
    for question in question_set.get("questions") or []:
        if str(question.get("status") or "") == "answered" and not list(question.get("answer_capture_batch_ids") or []):
            blocking_reasons.append(f"Answered question {question.get('question_id')} is missing answer_capture_batch_ids.")
            break
        if str(question.get("status") or "") == "deferred":
            warning_reasons.append(f"Question {question.get('question_id')} is deferred.")
    return {
        "ready": not blocking_reasons and not missing_artifacts,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "missing_artifacts": missing_artifacts,
        "open_question_ids": open_question_ids,
        "unincorporated_clarification_batch_ids": list(unincorporated_capture_batch_ids),
    }


def render_analysis_brief(*, session: dict[str, Any], scan_artifact_path: str, active_session_mode: str) -> str:
    return "\n".join(
        [
            "# Onboarding Analysis Brief",
            "",
            f"- Evidence bundle path: {scan_artifact_path}",
            f"- Current onboarding session id: {session.get('onboarding_id')}",
            f"- Current onboarding state: {session.get('state')}",
            f"- Active session posture: {active_session_mode}",
            "",
            "## What the executor must figure out",
            "- What the repo seems to be.",
            "- What capabilities are implemented.",
            "- What appears half-built.",
            "- What appears intended.",
            "- What looks stale or superseded.",
            "- What the code cannot answer.",
            "",
            "## How to treat user corrections",
            "- Patch, don't restart.",
            "- Preserve superseded beliefs explicitly.",
            "",
            "## Final publication rule",
            "- Do not publish until the user explicitly confirms.",
            "",
            "## Quality rules for the draft",
            "- Claims must be status-tagged.",
            "- Claims must carry evidence or answer refs.",
            "- Low-confidence uncertain claims should become questions instead of fake certainty.",
        ]
    ).rstrip() + "\n"


def build_published_project_model(
    *,
    onboarding_id: str,
    confirmed_at: str,
    confirmed_by: str,
    draft: dict[str, Any],
    question_set: dict[str, Any],
) -> dict[str, Any]:
    items = flatten_draft_items(draft)
    implemented_truths = _draft_section_items(draft, "implemented_truths", fallback_statuses={"implemented"})
    partial_truths = _draft_section_items(draft, "partial_truths", fallback_statuses={"partial"})
    intended_truths = _draft_section_items(
        draft,
        "intended_capabilities",
        fallback_statuses={"intended"},
        fallback_fields=("capability_hypotheses", "component_hypotheses"),
    )
    future_expansion = _draft_section_items(
        draft,
        "future_ideas_needing_expansion",
        fallback_statuses={"uncertain"},
        fallback_fields=("capability_hypotheses", "component_hypotheses", "open_unknowns"),
    )
    superseded_truths = _draft_section_items(
        draft,
        "superseded_directions",
        fallback_statuses={"stale", "superseded", "deprecated"},
        fallback_fields=("history_and_supersession_hypotheses", "capability_hypotheses", "component_hypotheses"),
    )
    capabilities = [item for item in draft.get("capability_hypotheses") or [] if item.get("status") not in {"superseded", "deprecated"}]
    components = [item for item in draft.get("component_hypotheses") or [] if item.get("status") not in {"superseded", "deprecated"}]
    project_model = {
        "onboarding_id": onboarding_id,
        "draft_revision_id": draft.get("revision_id"),
        "source_scan_ids": list(draft.get("based_on_scan_ids") or []),
        "source_capture_batch_ids": list(draft.get("based_on_capture_batch_ids") or []),
        "confirmed_at": confirmed_at,
        "confirmed_by": confirmed_by,
        "project_identity": str(draft.get("summary_hypothesis") or "").strip(),
        "purpose": str(draft.get("purpose_hypothesis") or "").strip(),
        "current_vision": str(draft.get("vision_hypothesis") or "").strip(),
        "users_or_stakeholders": list(draft.get("user_or_stakeholder_hypotheses") or []),
        "maturity_status": str(draft.get("maturity_hypothesis") or "").strip(),
        "implemented_truths": implemented_truths,
        "partial_truths": partial_truths,
        "intended_capabilities": intended_truths,
        "future_ideas_needing_expansion": future_expansion,
        "superseded_directions": superseded_truths,
        "confirmed_capabilities": [item for item in capabilities if item.get("status") == "implemented"],
        "partial_or_intended_capabilities": [item for item in capabilities if item.get("status") in {"partial", "intended", "uncertain"}],
        "stale_or_superseded_directions": [
            item
            for item in list(draft.get("history_and_supersession_hypotheses") or []) + capabilities + components
            if item.get("status") in {"stale", "superseded", "deprecated"}
        ],
        "components_or_subsystems": components,
        "interfaces_or_entrypoints": list(draft.get("interface_hypotheses") or []),
        "constraints": list(draft.get("constraint_hypotheses") or []),
        "non_goals": list(draft.get("non_goal_hypotheses") or []),
        "dependencies_or_integrations": list(draft.get("dependency_hypotheses") or []),
        "unresolved_nonblocking_questions": [
            question
            for question in question_set.get("questions") or []
            if question.get("priority") != "blocking" and question.get("status") == "open"
        ],
        "evidence_summary": {
            "claim_count": len(items),
            "scan_refs": sorted({ref for item in items.values() for ref in item.get("evidence_refs") or []}),
            "answer_refs": sorted({ref for item in items.values() for ref in item.get("answer_refs") or []}),
        },
        "confirmation_metadata": {
            "confirmed_at": confirmed_at,
            "confirmed_by": confirmed_by,
            "onboarding_id": onboarding_id,
            "draft_revision_id": draft.get("revision_id"),
            "source_scan_ids": list(draft.get("based_on_scan_ids") or []),
            "source_capture_batch_ids": list(draft.get("based_on_capture_batch_ids") or []),
        },
    }
    return project_model


def build_draft_publication_view(
    *,
    draft: dict[str, Any],
    question_set: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "project_identity": str(draft.get("summary_hypothesis") or "").strip(),
        "purpose": str(draft.get("purpose_hypothesis") or "").strip(),
        "current_vision": str(draft.get("vision_hypothesis") or "").strip(),
        "implemented_truths": _draft_section_items(draft, "implemented_truths", fallback_statuses={"implemented"}),
        "partial_truths": _draft_section_items(draft, "partial_truths", fallback_statuses={"partial"}),
        "intended_capabilities": _draft_section_items(
            draft,
            "intended_capabilities",
            fallback_statuses={"intended"},
            fallback_fields=("capability_hypotheses", "component_hypotheses"),
        ),
        "future_ideas_needing_expansion": _draft_section_items(
            draft,
            "future_ideas_needing_expansion",
            fallback_statuses={"uncertain"},
            fallback_fields=("capability_hypotheses", "component_hypotheses", "open_unknowns"),
        ),
        "superseded_directions": _draft_section_items(
            draft,
            "superseded_directions",
            fallback_statuses={"stale", "superseded", "deprecated"},
            fallback_fields=("history_and_supersession_hypotheses", "capability_hypotheses", "component_hypotheses"),
        ),
        "constraints": list(draft.get("constraint_hypotheses") or []),
        "non_goals": list(draft.get("non_goal_hypotheses") or []),
        "unresolved_nonblocking_questions": [
            question
            for question in (question_set or {}).get("questions") or []
            if question.get("status") == "open" and question.get("priority") != "blocking"
        ],
    }


def render_draft_story(draft: dict[str, Any], question_set: dict[str, Any] | None = None) -> str:
    return render_project_story(build_draft_publication_view(draft=draft, question_set=question_set)).replace(
        "# Project Story",
        "# Project Story Draft",
        1,
    )


def render_draft_vision(draft: dict[str, Any], question_set: dict[str, Any] | None = None) -> str:
    return render_published_vision(build_draft_publication_view(draft=draft, question_set=question_set)).replace(
        "# Vision (Published)",
        "# Vision Draft",
        1,
    )


def render_project_story(model: dict[str, Any]) -> str:
    confirmed = [f"- {item.get('summary')}" for item in model.get("implemented_truths") or model.get("confirmed_capabilities") or []] or [
        "- No confirmed capabilities recorded."
    ]
    partial = [f"- {item.get('summary')}" for item in model.get("partial_truths") or model.get("partial_or_intended_capabilities") or []] or [
        "- None recorded."
    ]
    historical = [f"- {item.get('summary')}" for item in model.get("superseded_directions") or model.get("stale_or_superseded_directions") or []] or [
        "- None recorded."
    ]
    future = [f"- {item.get('summary')}" for item in model.get("intended_capabilities") or []]
    constraints = [f"- Constraint: {item.get('summary')}" for item in model.get("constraints") or []]
    non_goals = [f"- Non-goal: {item.get('summary')}" for item in model.get("non_goals") or []]
    unresolved = [f"- {item.get('prompt')}" for item in model.get("unresolved_nonblocking_questions") or []] or [
        "- No unresolved nonblocking questions recorded."
    ]
    lines = [
        "# Project Story",
        "",
        "## What this project is",
        str(model.get("project_identity") or ""),
        "",
        "## Why it exists",
        str(model.get("purpose") or ""),
        "",
        "## What it currently appears to do",
        *confirmed,
        "",
        "## What is partial or still being built",
        *partial,
        "",
        "## What is intended but not built yet",
        *(future or ["- None recorded."]),
        "",
        "## What changed direction historically",
        *historical,
        "",
        "## What constraints and non-goals matter",
        *(constraints or ["- Constraint: none recorded."]),
        *(non_goals or ["- Non-goal: none recorded."]),
        "",
        "## What remains unresolved",
        *unresolved,
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_published_vision(model: dict[str, Any]) -> str:
    confirmed = [f"- {item.get('summary')}" for item in model.get("implemented_truths") or model.get("confirmed_capabilities") or []] or [
        "- No confirmed capabilities recorded."
    ]
    partial = [f"- {item.get('summary')}" for item in model.get("partial_truths") or []] or [
        "- None recorded."
    ]
    intended = [f"- {item.get('summary')}" for item in model.get("intended_capabilities") or []] or ["- None recorded."]
    future = [f"- {item.get('summary')}" for item in model.get("future_ideas_needing_expansion") or []] or ["- None recorded."]
    constraints = [f"- {item.get('summary')}" for item in model.get("constraints") or []] or ["- None recorded."]
    historical = [f"- {item.get('summary')}" for item in model.get("superseded_directions") or model.get("stale_or_superseded_directions") or []] or [
        "- None recorded."
    ]
    lines = [
        "# Vision (Published)",
        "",
        "## Project",
        f"- Name: {model.get('project_identity')}",
        "",
        "## Purpose",
        f"- Why this exists: {model.get('purpose')}",
        "",
        "## Core experience / feel",
        f"- Current vision: {model.get('current_vision')}",
        "",
        "## What exists now",
        *confirmed,
        "",
        "## What does not exist yet",
        *partial,
        "",
        "## What is intended next",
        *intended,
        "",
        "## What still needs expansion",
        *future,
        "",
        "## Non-negotiables",
        *constraints,
        "",
        "## Recent important shifts",
        *historical,
        "",
    ]
    return "\n".join(lines)


def render_draft_codex_current(model: dict[str, Any]) -> str:
    model = build_draft_publication_view(draft=model, question_set=None)
    stable_current = [f"- {item.get('summary')}" for item in model.get("implemented_truths") or model.get("confirmed_capabilities") or []]
    partial_current = [f"- {item.get('summary')}" for item in model.get("partial_truths") or []]
    constraints = [f"- {item.get('summary')}" for item in model.get("constraints") or []]
    lines = [
        "# Current Codex Draft",
        "",
        "## Project identity",
        f"- {model.get('project_identity') or model.get('summary_hypothesis') or ''}",
        "",
        "## Stable current truths",
        *(stable_current or ["- None recorded."]),
        "",
        "## Partial / in-progress truths",
        *(partial_current or ["- None recorded."]),
        "",
        "## Current constraints",
        *(constraints or ["- None recorded."]),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_draft_codex_future(model: dict[str, Any]) -> str:
    model = build_draft_publication_view(draft=model, question_set=None)
    intended = [f"- {item.get('summary')}" for item in model.get("intended_capabilities") or []]
    expansion = [f"- {item.get('summary')}" for item in model.get("future_ideas_needing_expansion") or []]
    superseded = [
        f"- {item.get('summary')}"
        for item in model.get("superseded_directions") or model.get("stale_or_superseded_directions") or []
    ]
    lines = [
        "# Future Codex Draft",
        "",
        "## Intended capabilities",
        *(intended or ["- None recorded."]),
        "",
        "## Ideas needing expansion",
        *(expansion or ["- None recorded."]),
        "",
        "## Superseded directions",
        *(superseded or ["- None recorded."]),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_published_codex_current(model: dict[str, Any]) -> str:
    return render_draft_codex_current(model).replace("# Current Codex Draft", "# Current Codex", 1)


def render_published_codex_future(model: dict[str, Any]) -> str:
    return render_draft_codex_future(model).replace("# Future Codex Draft", "# Future Codex", 1)


def project_model_projection(model: dict[str, Any], question_set: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "project_summary": str(model.get("project_identity") or "").strip() or None,
        "project_purpose_summary": str(model.get("purpose") or "").strip() or None,
        "project_capability_summary": [item.get("summary") for item in model.get("implemented_truths") or model.get("confirmed_capabilities") or []][:8],
        "project_constraint_summary": [item.get("summary") for item in model.get("constraints") or []][:8],
        "project_history_summary": [item.get("summary") for item in model.get("superseded_directions") or model.get("stale_or_superseded_directions") or []][:8],
        "project_open_question_details": [
            {
                "question_id": item.get("question_id"),
                "prompt": item.get("prompt"),
                "priority": item.get("priority"),
                "status": item.get("status"),
            }
            for item in (question_set or {}).get("questions") or []
            if item.get("status") == "open"
        ],
        "project_model_open_questions_count": sum(1 for item in (question_set or {}).get("questions") or [] if item.get("status") == "open"),
        "project_model_blocking_questions_count": sum(
            1
            for item in (question_set or {}).get("questions") or []
            if item.get("status") == "open" and item.get("priority") == "blocking"
        ),
    }


def load_yaml_artifact(path: Path, *, required_field: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProjectModelError(f"Unable to read onboarding artifact: {path}") from exc
    if not isinstance(payload, dict) or not payload.get(required_field):
        raise ProjectModelError(f"Malformed onboarding artifact: {path}")
    return payload


def flatten_draft_items(draft: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(draft, dict):
        return {}
    items: dict[str, dict[str, Any]] = {}
    for field in ALL_DRAFT_ITEM_LIST_FIELDS:
        for item in draft.get(field) or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                items[str(item["id"])] = item
    return items


def _draft_section_items(
    draft: dict[str, Any],
    field_name: str,
    *,
    fallback_statuses: set[str],
    fallback_fields: tuple[str, ...] = DRAFT_ITEM_LIST_FIELDS,
) -> list[dict[str, Any]]:
    explicit = [item for item in draft.get(field_name) or [] if isinstance(item, dict)]
    if explicit:
        return explicit
    derived: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fallback_fields:
        for item in draft.get(field) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") not in fallback_statuses:
                continue
            item_id = str(item.get("id") or "")
            if item_id and item_id not in seen:
                derived.append(item)
                seen.add(item_id)
    return derived


def _normalize_draft_item(
    item: Any,
    *,
    field_name: str,
    current_scan_ids: list[str],
    prior_item_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ProjectModelError(f"Draft item in {field_name} must be an object.")
    normalized = dict(item)
    item_id = str(normalized.get("id") or "").strip()
    if not item_id:
        raise ProjectModelError(f"Draft item in {field_name} is missing id.")
    summary = str(normalized.get("summary") or "").strip()
    if not summary:
        raise ProjectModelError(f"Draft item {item_id} summary must be non-empty.")
    status = str(normalized.get("status") or "").strip()
    if status not in DRAFT_ITEM_STATUSES:
        raise ProjectModelError(f"Draft item {item_id} has invalid status: {status}")
    confidence = str(normalized.get("confidence") or "").strip()
    if confidence not in CONFIDENCE_VALUES:
        raise ProjectModelError(f"Draft item {item_id} has invalid confidence: {confidence}")
    claim_basis = normalized.get("claim_basis")
    if claim_basis is not None:
        claim_basis = str(claim_basis).strip()
        if claim_basis not in CLAIM_BASIS_VALUES:
            raise ProjectModelError(f"Draft item {item_id} has invalid claim_basis: {claim_basis}")
    evidence_refs = _normalize_string_list(normalized.get("evidence_refs"), field_name=f"{item_id}.evidence_refs")
    if claim_basis != "user_only" and not evidence_refs:
        raise ProjectModelError(f"Draft item {item_id} requires evidence_refs unless claim_basis is user_only.")
    for ref in evidence_refs:
        if not _SCAN_REF_RE.match(ref):
            raise ProjectModelError(f"Draft item {item_id} has invalid evidence ref: {ref}")
        if current_scan_ids and ref.split(":", 3)[1] not in current_scan_ids:
            raise ProjectModelError(f"Draft item {item_id} references a scan not included in based_on_scan_ids: {ref}")
    answer_refs = _normalize_string_list(normalized.get("answer_refs"), field_name=f"{item_id}.answer_refs")
    for ref in answer_refs:
        if not _CAPTURE_REF_RE.match(ref):
            raise ProjectModelError(f"Draft item {item_id} has invalid answer ref: {ref}")
    supersedes = normalized.get("supersedes")
    if supersedes is not None:
        supersedes = str(supersedes).strip()
        if not supersedes:
            supersedes = None
        elif supersedes not in prior_item_ids:
            raise ProjectModelError(f"Draft item {item_id} supersedes unknown prior item id: {supersedes}")
    return {
        "id": item_id,
        "summary": summary,
        "status": status,
        "confidence": confidence,
        "evidence_refs": evidence_refs,
        "answer_refs": answer_refs,
        "related_paths": _normalize_string_list(normalized.get("related_paths"), field_name=f"{item_id}.related_paths"),
        "supersedes": supersedes,
        "notes": str(normalized.get("notes") or "").strip() or None,
        "claim_basis": claim_basis,
    }


def _normalize_question_item(
    item: Any,
    *,
    draft_item_ids: set[str],
    linked_capture_batch_ids: list[str],
    prior_question_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ProjectModelError("Question items must be objects.")
    normalized = dict(item)
    question_id = str(normalized.get("question_id") or "").strip()
    if not question_id:
        raise ProjectModelError("Question item missing question_id.")
    prompt = str(normalized.get("prompt") or "").strip()
    if not prompt:
        raise ProjectModelError(f"Question {question_id} prompt must be non-empty.")
    category = str(normalized.get("category") or "").strip()
    if category not in QUESTION_CATEGORIES:
        raise ProjectModelError(f"Question {question_id} has invalid category: {category}")
    priority = str(normalized.get("priority") or "").strip()
    if priority not in QUESTION_PRIORITIES:
        raise ProjectModelError(f"Question {question_id} has invalid priority: {priority}")
    status = str(normalized.get("status") or "").strip()
    if status not in QUESTION_STATUSES:
        raise ProjectModelError(f"Question {question_id} has invalid status: {status}")
    why_asked = str(normalized.get("why_asked") or "").strip()
    if not why_asked:
        raise ProjectModelError(f"Question {question_id} why_asked must be non-empty.")
    evidence_refs = _normalize_string_list(normalized.get("evidence_refs"), field_name=f"{question_id}.evidence_refs")
    for ref in evidence_refs:
        if not _SCAN_REF_RE.match(ref):
            raise ProjectModelError(f"Question {question_id} has invalid evidence ref: {ref}")
    target_item_ids = _normalize_string_list(normalized.get("target_item_ids"), field_name=f"{question_id}.target_item_ids")
    for item_id in target_item_ids:
        if item_id not in draft_item_ids:
            raise ProjectModelError(f"Question {question_id} targets unknown draft item id: {item_id}")
    answer_capture_batch_ids = _normalize_string_list(
        normalized.get("answer_capture_batch_ids"),
        field_name=f"{question_id}.answer_capture_batch_ids",
    )
    if status == "answered" and not answer_capture_batch_ids:
        raise ProjectModelError(f"Question {question_id} is answered but has no answer_capture_batch_ids.")
    if status == "answered":
        missing = [batch_id for batch_id in answer_capture_batch_ids if batch_id not in linked_capture_batch_ids]
        if missing:
            raise ProjectModelError(
                f"Question {question_id} references answer capture batches not linked to this onboarding session: {', '.join(missing)}"
            )
    if status == "superseded" and question_id not in prior_question_ids:
        raise ProjectModelError(f"Question {question_id} cannot be marked superseded without a prior matching question id.")
    return {
        "question_id": question_id,
        "prompt": prompt,
        "category": category,
        "priority": priority,
        "why_asked": why_asked,
        "evidence_refs": evidence_refs,
        "target_item_ids": target_item_ids,
        "status": status,
        "answer_capture_batch_ids": answer_capture_batch_ids,
    }


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectModelError(f"{field_name} must be a list.")
    items: list[str] = []
    seen: set[str] = set()
    for raw in value:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _draft_signature(item: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...], str | None]:
    return (
        str(item.get("summary") or ""),
        tuple(item.get("evidence_refs") or []),
        tuple(item.get("answer_refs") or []),
        item.get("claim_basis"),
    )


def _validate_draft_id_stability(draft: dict[str, Any], prior_draft: dict[str, Any] | None) -> None:
    if not prior_draft:
        return
    current_items = flatten_draft_items(draft)
    prior_items = flatten_draft_items(prior_draft)
    signature_to_prior_id = {
        _draft_signature(item): item_id
        for item_id, item in prior_items.items()
    }
    for item_id, item in current_items.items():
        prior_id = signature_to_prior_id.get(_draft_signature(item))
        if prior_id and prior_id != item_id:
            raise ProjectModelError(
                f"Draft item '{item_id}' appears materially unchanged from prior item '{prior_id}' and must keep a stable id."
            )


def _validate_draft_coverage(draft: dict[str, Any], scan_artifact: dict[str, Any] | None) -> None:
    if not scan_artifact:
        return
    if scan_artifact.get("entrypoint_inventory") and not list(draft.get("interface_hypotheses") or []):
        raise ProjectModelError("Draft is incomplete: entrypoint evidence exists but interface_hypotheses is empty.")
    if scan_artifact.get("manifest_inventory") and not list(draft.get("dependency_hypotheses") or []):
        raise ProjectModelError("Draft is incomplete: manifest evidence exists but dependency_hypotheses is empty.")
    if scan_artifact.get("existing_continuity_inventory") and not list(draft.get("history_and_supersession_hypotheses") or []):
        raise ProjectModelError(
            "Draft is incomplete: existing continuity evidence exists but history_and_supersession_hypotheses is empty."
        )


def _question_index(question_set: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(question_set, dict):
        return {}
    return {
        str(item.get("question_id")): item
        for item in question_set.get("questions") or []
        if isinstance(item, dict) and str(item.get("question_id") or "").strip()
    }


def _validate_question_id_stability(question_set: dict[str, Any], prior_question_set: dict[str, Any] | None) -> None:
    if not prior_question_set:
        return
    prior_index = _question_index(prior_question_set)
    prompt_signature_to_id = {
        (str(item.get("prompt") or ""), str(item.get("category") or "")): question_id
        for question_id, item in prior_index.items()
    }
    for question in question_set.get("questions") or []:
        signature = (str(question.get("prompt") or ""), str(question.get("category") or ""))
        prior_id = prompt_signature_to_id.get(signature)
        if prior_id and prior_id != question.get("question_id"):
            raise ProjectModelError(
                f"Question '{question.get('question_id')}' appears materially unchanged from prior question '{prior_id}' and must keep a stable id."
            )


def _blocking_open_question_count(question_set: dict[str, Any]) -> int:
    return sum(
        1
        for item in question_set.get("questions") or []
        if item.get("priority") == "blocking" and item.get("status") == "open"
    )

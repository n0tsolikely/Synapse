"""Pydantic input schemas for Synapse MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    engine_root: str | None = None
    data_root: str | None = None
    session_id: str | None = None
    allow_switch: bool = False


class BootstrapSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    session_mode: str | None = None
    title: str | None = None
    goal: str | None = None
    plan_items: list[str] = Field(default_factory=list)
    adopt_current_repo: bool = True


class GetCurrentContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    include_rehydrate: bool = False
    include_project_story: bool = False


class GetSessionDigestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    style: Literal["concise", "expanded"] = "concise"


class TransitionSessionModeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    target_mode: str
    reason: str


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    why: str | None = None


class RecordActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    summary: str
    title: str | None = None
    goal: str | None = None
    plan_items: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    discoveries: list[str] = Field(default_factory=list)
    verifications: list[str] = Field(default_factory=list)
    related_quest_ids: list[str] = Field(default_factory=list)
    related_sidequest_ids: list[str] = Field(default_factory=list)
    status: str | None = None
    decision: DecisionInput | None = None
    capture_git: bool = False


class RecordDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    title: str
    summary: str
    why: str | None = None
    constraints: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    related_run_ids: list[str] = Field(default_factory=list)
    related_quest_ids: list[str] = Field(default_factory=list)


class RecordDisclosureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    trigger: str
    expected: str
    provable: str
    status_labels: list[str] = Field(default_factory=list)
    impact: str
    safe_options: list[str] = Field(default_factory=list)
    decision_needed: str
    related_run_ids: list[str] = Field(default_factory=list)
    related_quest_ids: list[str] = Field(default_factory=list)


class CaptureChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    text: str
    captures: dict[str, Any]
    title: str | None = None
    source_role: str = "agent"


class RunRepoOnboardingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    depth: Literal["quick", "deep"] = "deep"
    rescan: bool = False
    restart: bool = False


class SubmitOnboardingDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    draft_model: dict[str, Any]
    question_set: dict[str, Any]


class SubmitOnboardingResponsesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    text: str
    captures: dict[str, Any]
    title: str | None = None
    source_role: str = "user"
    linked_question_ids: list[str] = Field(default_factory=list)


class ConfirmOnboardingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    confirm: bool


class AbandonOnboardingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    reason: str | None = None


class ListFormalizationCandidatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    proposal_kind: str | None = None
    limit: int = 50


class FormalizeCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    proposal_id: str
    dry_run: bool = False


class AcceptQuestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    quest_id: str | None = None
    quest_path: str | None = None

    @model_validator(mode="after")
    def validate_one_of(self) -> "AcceptQuestInput":
        if bool(self.quest_id) == bool(self.quest_path):
            raise ValueError("Provide exactly one of quest_id or quest_path.")
        return self


class RefreshContinuityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    seal_rehydration_pack: bool = True


class FinalizeRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: ContextInput | None = None
    outcome_summary: str | None = None
    status: str | None = None

"""Tool registration for the Synapse MCP server."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from synapse_mcp.connection_state import ConnectionState
from synapse_mcp import result_mapping
from synapse_mcp.runtime_bridge import (
    abandon_onboarding_tool,
    accept_quest_tool,
    bootstrap_session,
    build_current_context_bundle,
    build_session_digest,
    capture_chunk,
    complete_quest_tool,
    confirm_onboarding_tool,
    finalize_run_tool,
    formalize_candidate_tool,
    get_provenance_status_tool,
    import_continuity_tool,
    install_git_hooks_tool,
    install_local_integration_tool,
    list_formalization_candidates_tool,
    map_runtime_exception,
    plan_quests_tool,
    record_activity,
    record_decision,
    record_disclosure,
    record_raw_execution_tool,
    record_raw_turn_tool,
    refresh_draftshot_tool,
    refresh_continuity_tool,
    run_repo_onboarding_tool,
    submit_onboarding_draft,
    submit_onboarding_responses,
    transition_session_mode,
    verify_git_hooks_tool,
)
from synapse_mcp.schemas import ContextInput


def _handle_exception(exc: Exception) -> dict[str, Any]:
    failure = map_runtime_exception(exc)
    return result_mapping.from_failure(None, failure)


def _handle_mutation_result(
    ctx: dict[str, Any],
    payload: dict[str, Any],
    event_info: dict[str, Any] | None,
    status: str = result_mapping.STATUS_OK,
) -> dict[str, Any]:
    runtime_status = event_info.get("runtime_status") if isinstance(event_info, dict) else None
    if runtime_status and str(runtime_status.get("operation_status") or "").lower() == "partial":
        return result_mapping.from_runtime_status(
            subject_context=ctx,
            data=payload,
            runtime_status=runtime_status,
        )
    if status == result_mapping.STATUS_NOOP:
        return result_mapping.noop(ctx, data=payload)
    return result_mapping.ok(ctx, data=payload)


def register_tools(mcp: FastMCP, state: ConnectionState) -> None:
    @mcp.tool(name="bootstrap_session", structured_output=True)
    def _bootstrap_session(
        context: ContextInput | None = None,
        session_mode: str | None = None,
        title: str | None = None,
        goal: str | None = None,
        plan_items: list[str] | None = None,
        adopt_current_repo: bool = True,
    ) -> dict[str, Any]:
        try:
            ctx, payload, status, event_info = bootstrap_session(
                state=state,
                context=context,
                session_mode=session_mode,
                title=title,
                goal=goal,
                plan_items=list(plan_items or []),
                adopt_current_repo=adopt_current_repo,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="get_current_context", structured_output=True)
    def _get_current_context(
        context: ContextInput | None = None,
        include_rehydrate: bool = False,
        include_project_story: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, data = build_current_context_bundle(
                state=state,
                context=context,
                include_rehydrate=include_rehydrate,
                include_project_story=include_project_story,
            )
            return result_mapping.ok(
                ctx,
                data={
                    "context": data["context"],
                    "rehydrate_text": data.get("rehydrate_text"),
                    "project_story_text": data.get("project_story_text"),
                },
            )
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="get_session_digest", structured_output=True)
    def _get_session_digest(
        context: ContextInput | None = None,
        style: Literal["concise", "expanded"] = "concise",
    ) -> dict[str, Any]:
        try:
            ctx, data = build_session_digest(state=state, context=context, style=style)
            return result_mapping.ok(ctx, data=data)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="get_provenance_status", structured_output=True)
    def _get_provenance_status(
        context: ContextInput | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, data, status = get_provenance_status_tool(
                state=state,
                context=context,
                strict=strict,
            )
            if status == result_mapping.STATUS_BLOCKED:
                return result_mapping.blocked(
                    ctx,
                    code="PROVENANCE_BLOCKED",
                    message="Current provenance status is blocked.",
                    data=data,
                )
            return result_mapping.ok(ctx, data=data)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="transition_session_mode", structured_output=True)
    def _transition_session_mode(
        target_mode: str,
        reason: str,
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, status, event_info = transition_session_mode(
                state=state,
                context=context,
                target_mode=target_mode,
                reason=reason,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="record_activity", structured_output=True)
    def _record_activity(
        summary: str,
        context: ContextInput | None = None,
        title: str | None = None,
        goal: str | None = None,
        plan_items: list[str] | None = None,
        commands: list[str] | None = None,
        files: list[str] | None = None,
        notes: list[str] | None = None,
        discoveries: list[str] | None = None,
        verifications: list[str] | None = None,
        related_quest_ids: list[str] | None = None,
        related_sidequest_ids: list[str] | None = None,
        status: str | None = None,
        decision: dict[str, Any] | None = None,
        capture_git: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = record_activity(
                state=state,
                context=context,
                summary=summary,
                title=title,
                goal=goal,
                plan_items=list(plan_items or []),
                commands=list(commands or []),
                files=list(files or []),
                notes=list(notes or []),
                discoveries=list(discoveries or []),
                verifications=list(verifications or []),
                related_quest_ids=list(related_quest_ids or []),
                related_sidequest_ids=list(related_sidequest_ids or []),
                status=status,
                decision=decision,
                capture_git=capture_git,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="record_raw_turn", structured_output=True)
    def _record_raw_turn(
        role: Literal["user", "executor"],
        text: str,
        context: ContextInput | None = None,
        source_surface: str = "mcp",
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = record_raw_turn_tool(
                state=state,
                context=context,
                role=role,
                text=text,
                source_surface=source_surface,
                run_id=run_id,
                metadata=metadata,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="record_raw_execution", structured_output=True)
    def _record_raw_execution(
        family: Literal["execution", "tool", "import"],
        context: ContextInput | None = None,
        source_surface: str = "mcp",
        phase: str | None = None,
        command_text: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        changed_files: list[str] | None = None,
        payload: Any | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, result_payload, event_info, result_status = record_raw_execution_tool(
                state=state,
                context=context,
                family=family,
                source_surface=source_surface,
                phase=phase,
                command_text=command_text,
                tool_name=tool_name,
                status=status,
                changed_files=list(changed_files or []),
                payload=payload,
                run_id=run_id,
                metadata=metadata,
            )
            return _handle_mutation_result(ctx, result_payload, event_info, result_status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="refresh_draftshot", structured_output=True)
    def _refresh_draftshot(
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = refresh_draftshot_tool(
                state=state,
                context=context,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="import_continuity", structured_output=True)
    def _import_continuity(
        source_file: str,
        context: ContextInput | None = None,
        kind: Literal["auto", "transcript", "note", "pdf"] = "auto",
        source_surface: str = "mcp_import",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, result_payload, event_info, result_status = import_continuity_tool(
                state=state,
                context=context,
                source_file=source_file,
                kind=kind,
                source_surface=source_surface,
                run_id=run_id,
            )
            return _handle_mutation_result(ctx, result_payload, event_info, result_status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="record_decision", structured_output=True)
    def _record_decision(
        title: str,
        summary: str,
        context: ContextInput | None = None,
        why: str | None = None,
        constraints: list[str] | None = None,
        tradeoffs: list[str] | None = None,
        related_run_ids: list[str] | None = None,
        related_quest_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = record_decision(
                state=state,
                context=context,
                title=title,
                summary=summary,
                why=why,
                constraints=list(constraints or []),
                tradeoffs=list(tradeoffs or []),
                related_run_ids=list(related_run_ids or []),
                related_quest_ids=list(related_quest_ids or []),
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="record_disclosure", structured_output=True)
    def _record_disclosure(
        trigger: str,
        expected: str,
        provable: str,
        impact: str,
        decision_needed: str,
        context: ContextInput | None = None,
        status_labels: list[str] | None = None,
        safe_options: list[str] | None = None,
        related_run_ids: list[str] | None = None,
        related_quest_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = record_disclosure(
                state=state,
                context=context,
                trigger=trigger,
                expected=expected,
                provable=provable,
                status_labels=list(status_labels or []),
                impact=impact,
                safe_options=list(safe_options or []),
                decision_needed=decision_needed,
                related_run_ids=list(related_run_ids or []),
                related_quest_ids=list(related_quest_ids or []),
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="capture_chunk", structured_output=True)
    def _capture_chunk(
        text: str,
        captures: dict[str, Any],
        context: ContextInput | None = None,
        title: str | None = None,
        source_role: str = "agent",
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = capture_chunk(
                state=state,
                context=context,
                text=text,
                captures=captures,
                title=title,
                source_role=source_role,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="install_git_hooks", structured_output=True)
    def _install_git_hooks(
        context: ContextInput | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = install_git_hooks_tool(
                state=state,
                context=context,
                force=force,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="install_local_integration", structured_output=True)
    def _install_local_integration(
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = install_local_integration_tool(
                state=state,
                context=context,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="verify_git_hooks", structured_output=True)
    def _verify_git_hooks(
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = verify_git_hooks_tool(
                state=state,
                context=context,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="run_repo_onboarding", structured_output=True)
    def _run_repo_onboarding(
        context: ContextInput | None = None,
        depth: Literal["quick", "deep"] = "deep",
        rescan: bool = False,
        restart: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = run_repo_onboarding_tool(
                state=state,
                context=context,
                depth=depth,
                rescan=rescan,
                restart=restart,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="submit_onboarding_draft", structured_output=True)
    def _submit_onboarding_draft(
        draft_model: dict[str, Any],
        question_set: dict[str, Any],
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = submit_onboarding_draft(
                state=state,
                context=context,
                draft_model=draft_model,
                question_set=question_set,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="submit_onboarding_responses", structured_output=True)
    def _submit_onboarding_responses(
        text: str,
        captures: dict[str, Any],
        context: ContextInput | None = None,
        title: str | None = None,
        source_role: str = "user",
        linked_question_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = submit_onboarding_responses(
                state=state,
                context=context,
                text=text,
                captures=captures,
                title=title,
                source_role=source_role,
                linked_question_ids=list(linked_question_ids or []),
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="confirm_onboarding", structured_output=True)
    def _confirm_onboarding(
        confirm: bool,
        context: ContextInput | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = confirm_onboarding_tool(
                state=state,
                context=context,
                confirm=confirm,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="abandon_onboarding", structured_output=True)
    def _abandon_onboarding(
        context: ContextInput | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = abandon_onboarding_tool(
                state=state,
                context=context,
                reason=reason,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="list_formalization_candidates", structured_output=True)
    def _list_formalization_candidates(
        context: ContextInput | None = None,
        proposal_kind: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        try:
            ctx, data = list_formalization_candidates_tool(
                state=state,
                context=context,
                proposal_kind=proposal_kind,
                limit=limit,
            )
            return result_mapping.ok(ctx, data=data)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="formalize_candidate", structured_output=True)
    def _formalize_candidate(
        proposal_id: str,
        context: ContextInput | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info, status = formalize_candidate_tool(
                state=state,
                context=context,
                proposal_id=proposal_id,
                dry_run=dry_run,
            )
            return _handle_mutation_result(ctx, payload, event_info, status)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="accept_quest", structured_output=True)
    def _accept_quest(
        context: ContextInput | None = None,
        quest_id: str | None = None,
        quest_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = accept_quest_tool(
                state=state,
                context=context,
                quest_id=quest_id,
                quest_path=quest_path,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="complete_quest", structured_output=True)
    def _complete_quest(
        context: ContextInput | None = None,
        quest_id: str | None = None,
        quest_path: str | None = None,
        milestone_statuses: list[str] | None = None,
        checks: list[str] | None = None,
        commands_run: list[str] | None = None,
        changed_files: list[str] | None = None,
        receipt_refs: list[str] | None = None,
        skipped_items: list[str] | None = None,
        unresolved_gaps: list[str] | None = None,
        known_bugs: list[str] | None = None,
        blockers: list[str] | None = None,
        disclosures: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = complete_quest_tool(
                state=state,
                context=context,
                quest_id=quest_id,
                quest_path=quest_path,
                milestone_statuses=list(milestone_statuses or []),
                checks=list(checks or []),
                commands_run=list(commands_run or []),
                changed_files=list(changed_files or []),
                receipt_refs=list(receipt_refs or []),
                skipped_items=list(skipped_items or []),
                unresolved_gaps=list(unresolved_gaps or []),
                known_bugs=list(known_bugs or []),
                blockers=list(blockers or []),
                disclosures=list(disclosures or []),
                notes=list(notes or []),
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="plan_quests", structured_output=True)
    def _plan_quests(
        items: list[str],
        context: ContextInput | None = None,
        title: str | None = None,
        goal: str | None = None,
        coherent_outcome: str | None = None,
        closure_statement: str | None = None,
        split_triggers: list[str] | None = None,
        separate_outcomes: list[str] | None = None,
        dependencies: list[str] | None = None,
        out_of_scope: str | None = None,
        verification_plan: str | None = None,
        guild_orders_ref: str | None = None,
        dungeon_ref: str | None = None,
        dungeon_coverage: str = "N/A",
        plan_id: str | None = None,
        priority: Literal["P0", "P1", "P2"] = "P1",
        risk: str = "R0",
        change_class: Literal["TRIVIAL", "FEATURE", "STRUCTURAL"] = "FEATURE",
        vision_delta: Literal["ALIGNED", "VARIATION", "SHIFT"] = "ALIGNED",
        door_impact: str = "NONE",
        testing_level: str = "TL2",
        origin: str | None = None,
        anchors: list[str] | None = None,
        constraints: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = plan_quests_tool(
                state=state,
                context=context,
                items=list(items or []),
                title=title,
                goal=goal,
                coherent_outcome=coherent_outcome,
                closure_statement=closure_statement,
                split_triggers=list(split_triggers or []),
                separate_outcomes=list(separate_outcomes or []),
                dependencies=list(dependencies or []),
                out_of_scope=out_of_scope,
                verification_plan=verification_plan,
                guild_orders_ref=guild_orders_ref,
                dungeon_ref=dungeon_ref,
                dungeon_coverage=dungeon_coverage,
                plan_id=plan_id,
                priority=priority,
                risk=risk,
                change_class=change_class,
                vision_delta=vision_delta,
                door_impact=door_impact,
                testing_level=testing_level,
                origin=origin,
                anchors=list(anchors or []),
                constraints=list(constraints or []),
                dry_run=dry_run,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="refresh_continuity", structured_output=True)
    def _refresh_continuity(
        context: ContextInput | None = None,
        seal_rehydration_pack: bool = True,
    ) -> dict[str, Any]:
        try:
            ctx, data = refresh_continuity_tool(
                state=state,
                context=context,
                seal_rehydration_pack=seal_rehydration_pack,
            )
            return result_mapping.ok(ctx, data=data)
        except Exception as exc:
            return _handle_exception(exc)

    @mcp.tool(name="finalize_run", structured_output=True)
    def _finalize_run(
        context: ContextInput | None = None,
        outcome_summary: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        try:
            ctx, payload, event_info = finalize_run_tool(
                state=state,
                context=context,
                outcome_summary=outcome_summary,
                status=status,
            )
            return _handle_mutation_result(ctx, payload, event_info)
        except Exception as exc:
            return _handle_exception(exc)

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml


if importlib.util.find_spec("mcp") is None:
    raise unittest.SkipTest("mcp SDK is not installed in the active interpreter.")

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.repo_archaeology import evidence_ref
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.repo_onboarding import (
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
)
from synapse_runtime.sidecar_store import canonical_open_questions_path, ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


SERVER_PATH = REPO_ROOT / "runtime" / "synapse_mcp" / "server.py"
SNAPSHOT_WRITER = REPO_ROOT / "runtime" / "tools" / "synapse_snapshot_writer.py"
FIXED_TOOL_CATALOG = [
    "bootstrap_session",
    "get_current_context",
    "get_session_digest",
    "get_provenance_status",
    "transition_session_mode",
    "record_activity",
    "record_raw_turn",
    "record_raw_execution",
    "refresh_snapshot_candidates",
    "refresh_publication_candidates",
    "refresh_draftshot",
    "import_continuity",
    "record_decision",
    "record_disclosure",
    "capture_chunk",
    "install_git_hooks",
    "install_local_integration",
    "verify_git_hooks",
    "run_repo_onboarding",
    "submit_onboarding_draft",
    "submit_onboarding_responses",
    "confirm_onboarding",
    "abandon_onboarding",
    "list_formalization_candidates",
    "formalize_candidate",
    "accept_quest",
    "complete_quest",
    "plan_quests",
    "refresh_continuity",
    "finalize_run",
]
FIXED_RESOURCES = {
    "synapse://current/context.json",
    "synapse://current/state.json",
    "synapse://current/manifold.json",
    "synapse://current/active-run.json",
    "synapse://current/semantic-summary.json",
    "synapse://current/semantic-events.json",
    "synapse://current/plan-events.json",
    "synapse://current/draftshot-state.json",
    "synapse://current/snapshot-candidates.json",
    "synapse://current/publication-candidates.json",
    "synapse://current/governing-artifacts.json",
    "synapse://current/checkpoint-posture.json",
    "synapse://current/current-state-publications.json",
    "synapse://current/rehydrate.md",
    "synapse://current/open-questions.md",
    "synapse://current/onboarding/status.json",
    "synapse://current/provenance-status",
    "synapse://current/provenance-anomalies",
}


class McpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_workspace(self, name: str) -> Path:
        workspace = self.root / name
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        (workspace / "src").mkdir(parents=True, exist_ok=True)
        (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (workspace / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        return workspace

    def _write_codex_freeze(self, data_root: Path) -> None:
        freeze = data_root / "Codex" / "CODEX_FREEZE.md"
        freeze.parent.mkdir(parents=True, exist_ok=True)
        freeze.write_text(
            "\n".join(
                [
                    "# CODEX FREEZE",
                    "",
                    "Brains Approval: YES",
                    "Date: 2026-03-21",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _open_control_sync(self, subject: str, data_root: Path) -> None:
        env = {**os.environ, "HOME": str(self.home)}
        result = subprocess.run(
            [
                sys.executable,
                str(SNAPSHOT_WRITER),
                "--subject",
                subject,
                "--data-root",
                str(data_root),
                "--allow-switch",
                "control-open",
                "--participants",
                "Brains, Hands",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _write_ready_board_quest(self, subject: str, data_root: Path, *, quest_id: str = "QUEST_001") -> Path:
        filename = f"{quest_id}__runtime-governed-bridge__2026-03-21.txt"
        plan_payload = persist_execution_plan(
            subject=subject,
            data_root=data_root,
            title="Runtime governed bridge",
            summary="Persist the governed MCP acceptance path.",
            origin="Control Sync 2026-03-21",
            objective="Successful acceptance moves the quest into Accepted/ with a canonical audit bundle and explicit readiness.",
            coherent_outcome="Accept a board quest into governed execution through the MCP bridge without bypassing the canonical runtime.",
            closure_statement="Close only when governed acceptance is proven and the completion audit passes cleanly.",
            out_of_scope="Completing the quest or writing execution receipts.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Verification Commands: python3 -m unittest tests.test_mcp_integration -v | PASS when exit code is 0 | FAIL otherwise | Receipts: 01_COMPLETION_AUDIT.md + 06_TESTS.txt",
            milestones=[
                "Accept the quest into governed execution through MCP.",
                "Preserve the canonical completion-audit closure path.",
            ],
            split_triggers=["Split if MCP transport work and governed execution work become independently closable outcomes."],
            guild_orders_ref="",
            dungeon_ref="",
            dungeon_coverage="N/A",
            links=[],
            quest_refs=[],
            related_run_ids=[],
            source="test-mcp-fixture",
        )
        lines = [
            f"Quest ID: {quest_id}",
            "",
            "Title: Runtime governed bridge",
            "",
            f"Subject: {subject}",
            "",
            "Origin: Control Sync 2026-03-21",
            "",
            "Priority: P1",
            "",
            "Links: None",
            "",
            "Codex Anchors (DRAFT): 6.5, 9.2",
            "",
            "Codex Constraint Summary (DRAFT): Keep the MCP transport thin; no shell-outs or proofless claims.",
            "",
            "Change Class: FEATURE",
            "",
            "Vision Delta: ALIGNED",
            "",
            "System Context Statement: Synapse MCP integration extends the existing governed runtime instead of creating a parallel executor.",
            "",
            'Anti-Duplication Plan: rg -n "accept_quest|accept-quest|runtime/synapse_mcp" runtime tests governance',
            "",
            "Placement Intent: Intended layer: runtime transport | Intended target path(s): runtime/synapse_mcp/, runtime/synapse.py",
            "",
            "Coherent Outcome: Accept a board quest into governed execution through the MCP bridge without bypassing the canonical runtime.",
            "",
            "Closure Statement: Close only when governed acceptance is proven and the completion audit passes cleanly.",
            "",
            "Split Triggers: Split if MCP transport work and governed execution work become independently closable outcomes.",
            "",
            "Risk: R1",
            "",
            "R2 Confirmation Artifact (REQUIRED if Risk = R2):",
            "",
            "Description: Accept a board quest into governed execution through the MCP bridge.",
            "",
            "Scope / Objective: Successful acceptance moves the quest into Accepted/ with a canonical audit bundle and explicit readiness.",
            "",
            "Stretch Plan / Milestones:",
            "- MILESTONE-001 :: Accept the quest into governed execution through MCP.",
            "- MILESTONE-002 :: Preserve the canonical completion-audit closure path.",
            "",
            "Out of Scope: Completing the quest or writing execution receipts.",
            "",
            "Dependencies: None",
            "",
            "Door Impact: MCP",
            "",
            "Testing Level (TL): TL2",
            "",
            "Verification Plan: Verification Commands: python3 -m unittest tests.test_mcp_integration -v | PASS when exit code is 0 | FAIL otherwise | Receipts: 01_COMPLETION_AUDIT.md + 06_TESTS.txt",
            "",
            f"Plan Artifact Refs: {plan_payload['path']}",
            "",
            "Audit State: not_started",
            "",
            "Talent Point Awarded: NO",
            "",
            f"Audit Bundle Folder Path (required once ACCEPTED): {subject}_Data/Audits/Execution/{quest_id}__2026-03-21__runtime-governed-bridge",
            "",
        ]
        path = data_root / "Quest Board" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _server_params(
        self,
        workspace: Path,
        *,
        home: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> StdioServerParameters:
        target_home = home or self.home
        return StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            cwd=str(workspace),
            env={
                **os.environ,
                "HOME": str(target_home),
                "SYNAPSE_ROOT": str(REPO_ROOT),
                **(extra_env or {}),
            },
        )

    @asynccontextmanager
    async def _session(
        self,
        workspace: Path,
        *,
        home: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ):
        async with stdio_client(self._server_params(workspace, home=home, extra_env=extra_env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _call(self, session: ClientSession, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await session.call_tool(name, arguments or {})
        self.assertFalse(result.isError, result)
        return result.structuredContent

    async def _read_text_resource(self, session: ClientSession, uri: str) -> str:
        result = await session.read_resource(uri)
        self.assertEqual(len(result.contents), 1)
        return result.contents[0].text

    def _event_entries(self, data_root: Path) -> list[dict[str, Any]]:
        events_root = data_root / ".synapse" / "EVENTS"
        entries: list[dict[str, Any]] = []
        for path in sorted(events_root.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def _base_draft(
        self,
        *,
        onboarding_id: str,
        revision_id: str,
        supersedes_revision_id: str | None,
        scan_id: str,
        capture_batch_ids: list[str],
        next_question_ids: list[str],
        answer_refs: list[str],
    ) -> dict[str, Any]:
        capability = {
            "id": "CAP-1" if supersedes_revision_id is None else "CAP-2",
            "summary": (
                "CLI can onboard an existing repo."
                if not answer_refs
                else "CLI can onboard repos and preserve agent continuity."
            ),
            "status": "partial",
            "confidence": "high",
            "evidence_refs": [evidence_ref(scan_id=scan_id, section="entrypoint_inventory", item_id="cap1")],
            "answer_refs": list(answer_refs),
        }
        if supersedes_revision_id is not None:
            capability["supersedes"] = "CAP-1"
        return {
            "onboarding_id": onboarding_id,
            "revision_id": revision_id,
            "supersedes_revision_id": supersedes_revision_id,
            "created_at": "2026-03-21T10:00:00-04:00",
            "based_on_scan_ids": [scan_id],
            "based_on_capture_batch_ids": list(capture_batch_ids),
            "summary_hypothesis": "Repo-local continuity runtime.",
            "purpose_hypothesis": "Preserve machine-readable execution continuity.",
            "vision_hypothesis": "Future agents resume from runtime truth, not chat memory.",
            "maturity_hypothesis": "Active development.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [capability],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="tree_inventory", item_id="comp1")],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="entrypoint_inventory", item_id="int1")],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="manifest_inventory", item_id="dep1")],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="existing_continuity_inventory", item_id="hist1")],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": list(next_question_ids),
        }

    def _base_questions(self, *, onboarding_id: str, draft_revision_id: str) -> dict[str, Any]:
        return {
            "onboarding_id": onboarding_id,
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": draft_revision_id,
            "generated_at": "2026-03-21T10:00:00-04:00",
            "questions": [
                {
                    "question_id": "Q-1",
                    "prompt": "What is the core operator workflow?",
                    "category": "purpose",
                    "priority": "blocking",
                    "why_asked": "The scan alone cannot prove intent.",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-PLACEHOLDER", section="docs_inventory", item_id="q-1")],
                    "target_item_ids": ["CAP-1"],
                    "status": "open",
                    "answer_capture_batch_ids": [],
                }
            ],
        }

    async def test_server_starts_and_lists_frozen_catalog(self) -> None:
        workspace = self._make_workspace("mcp-discovery")
        async with self._session(workspace) as session:
            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            self.assertEqual(tool_names, FIXED_TOOL_CATALOG)

            resources = await session.list_resources()
            resource_uris = {str(item.uri) for item in resources.resources}
            self.assertTrue(FIXED_RESOURCES.issubset(resource_uris))
            self.assertFalse({"synapse://current/project-model.json", "synapse://current/project-story.md", "synapse://current/vision.md"} & resource_uris)

    async def test_bootstrap_generates_session_id_and_reuses_it(self) -> None:
        workspace = self._make_workspace("mcp-bootstrap")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "MCP session"})
            self.assertEqual(bootstrap["status"], "ok")
            session_id = bootstrap["subject_context"]["session_id"]
            self.assertTrue(session_id.startswith("mcp-"))
            current_context = bootstrap["data"]["current_context"]
            self.assertEqual(current_context["resolved_subject_context"]["session_id"], session_id)
            self.assertEqual(current_context["connection_defaults"]["session_id"], session_id)
            self.assertEqual(current_context["connection_defaults"]["workspace_root"], str(workspace))

            follow_up = await self._call(session, "get_current_context")
            self.assertEqual(follow_up["subject_context"]["session_id"], session_id)
            self.assertEqual(
                follow_up["data"]["context"]["resolved_subject_context"]["session_id"],
                session_id,
            )

    async def test_current_context_includes_automation_readiness_truth(self) -> None:
        workspace = self._make_workspace("mcp-automation-context")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Automation context"})
            self.assertEqual(bootstrap["status"], "ok")
            current = await self._call(session, "get_current_context")
            automation = current["data"]["context"]["automation"]
            self.assertTrue(automation["onboarding_required"])
            self.assertFalse(automation["continuity_ready"])
            self.assertEqual(automation["automation_status"], "onboarding_required")
            self.assertEqual(
                automation["automation_pending_gate"],
                "adopted_existing_repo_missing_confirmed_project_identity",
            )

    async def test_mcp_raw_capture_tools_write_append_only_artifacts(self) -> None:
        workspace = self._make_workspace("mcp-raw-capture")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Raw capture"})
            self.assertEqual(bootstrap["status"], "ok")
            data_root = Path(bootstrap["data"]["current_context"]["resolved_subject_context"]["data_root"])

            turn = await self._call(
                session,
                "record_raw_turn",
                {
                    "role": "user",
                    "text": "Need installable packaging and account support.",
                },
            )
            execution = await self._call(
                session,
                "record_raw_execution",
                {
                    "family": "tool",
                    "tool_name": "exec_command",
                    "status": "ok",
                    "payload": {"stdout": "green", "exit_code": 0},
                },
            )

            self.assertTrue(Path(turn["data"]["raw_turn_path"]).exists())
            self.assertTrue(Path(execution["data"]["raw_event_path"]).exists())
            self.assertEqual(turn["data"]["kernel_posture"]["posture"], "degraded")
            self.assertEqual(execution["data"]["family"], "TOOL_EVENTS")
            self.assertTrue((data_root / ".synapse" / "RAW" / "CONVERSATION_TURNS").is_dir())

    async def test_import_continuity_tool_updates_semantic_resources(self) -> None:
        workspace = self._make_workspace("mcp-imported-continuity")
        note = workspace / "brainstorm.txt"
        note.write_text(
            "We need a plan for installable web apps.\n\nSupport separate user accounts.\n",
            encoding="utf-8",
        )
        async with self._session(
            workspace,
            extra_env={"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture"},
        ) as session:
            await self._call(session, "bootstrap_session", {"title": "Imported continuity"})
            imported = await self._call(
                session,
                "import_continuity",
                {"source_file": str(note), "kind": "transcript"},
            )
            self.assertEqual(imported["status"], "ok")
            self.assertEqual(imported["data"]["family"], "IMPORT_EVENTS")
            observer = imported["data"]["continuity_observer"]
            self.assertEqual(observer["observer_status"], "ok")
            self.assertEqual(observer["observer_backend"], "fixture")
            self.assertIn("semantic_capture", observer["observer_action_kinds"])
            self.assertTrue(Path(observer["observer_capture_artifact_path"]).exists())

            summary = json.loads(await self._read_text_resource(session, "synapse://current/semantic-summary.json"))
            recent_events = json.loads(await self._read_text_resource(session, "synapse://current/semantic-events.json"))
            self.assertGreaterEqual(summary["conversation_segment_count"], 1)
            self.assertGreaterEqual(summary["semantic_event_count"], 1)
            self.assertTrue(recent_events)

    async def test_unsupported_import_surfaces_review_debt_in_current_context(self) -> None:
        workspace = self._make_workspace("mcp-imported-review")
        pdf = workspace / "brainstorm.pdf"
        pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
        async with self._session(workspace) as session:
            await self._call(session, "bootstrap_session", {"title": "Imported review"})
            imported = await self._call(
                session,
                "import_continuity",
                {"source_file": str(pdf), "kind": "pdf"},
            )
            self.assertEqual(imported["status"], "ok")
            self.assertEqual(imported["data"]["status"], "unsupported")

            context = await self._call(session, "get_current_context")
            provenance = context["data"]["context"]["provenance"]
            self.assertEqual(provenance["import_review_required_count"], 1)
            self.assertEqual(len(provenance["recent_import_review_details"]), 1)

            status_text = await self._read_text_resource(session, "synapse://current/provenance-status")
            self.assertIn("\"import_review_required_count\": 1", status_text)

    async def test_refresh_draftshot_tool_writes_active_draftshot_state(self) -> None:
        workspace = self._make_workspace("mcp-refresh-draftshot")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Draftshot refresh"})
            self.assertEqual(bootstrap["status"], "ok")
            subject_context = bootstrap["subject_context"]
            subject = subject_context["subject"]
            data_root = Path(subject_context["data_root"])
            session_id = subject_context["session_id"]

            persist_execution_plan(
                subject=subject,
                data_root=data_root,
                title="Installable workflow foundation",
                summary="Plan the installable workflow foundation.",
                origin="test-mcp-refresh-draftshot",
                objective="Support account-backed installable flows.",
                coherent_outcome="A persisted installable workflow foundation exists.",
                closure_statement="The installable workflow foundation is captured and testable.",
                out_of_scope="Payments.",
                dependencies=["Auth service"],
                risk="R1",
                verification_plan="Run installability and auth checks.",
                milestones=["Installable shell", "Signed-in workflow"],
                split_triggers=["Split when payments are introduced."],
                source_segment_ids=["SEG-PLAN"],
                source_semantic_event_ids=["SEMEVT-PLAN"],
                source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
            )

            refreshed = await self._call(session, "refresh_draftshot")
            self.assertEqual(refreshed["status"], "ok")
            self.assertIn(refreshed["data"]["status"], {"written", "updated"})
            self.assertEqual(
                refreshed["data"]["draftshot"]["current_active_draftshot_session_id"],
                session_id,
            )
            self.assertTrue(Path(refreshed["data"]["body_path"]).exists())

            draftshot_payload = json.loads(
                await self._read_text_resource(session, "synapse://current/draftshot-state.json")
            )
            self.assertEqual(draftshot_payload["current_active_draftshot_session_id"], session_id)
            self.assertTrue(draftshot_payload["current_active_draftshot_path"])

    async def test_refresh_snapshot_candidates_tool_writes_typed_candidate_state(self) -> None:
        workspace = self._make_workspace("mcp-refresh-snapshot-candidates")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Snapshot candidates"})
            self.assertEqual(bootstrap["status"], "ok")
            subject_context = bootstrap["subject_context"]
            subject = subject_context["subject"]
            data_root = Path(subject_context["data_root"])
            session_id = subject_context["session_id"]

            persist_execution_plan(
                subject=subject,
                data_root=data_root,
                title="Installable workflow foundation",
                summary="Plan the installable workflow foundation.",
                origin="test-mcp-refresh-snapshot-candidates",
                objective="Support account-backed installable flows.",
                coherent_outcome="A persisted installable workflow foundation exists.",
                closure_statement="The installable workflow foundation is captured and testable.",
                out_of_scope="Payments.",
                dependencies=["Auth service"],
                risk="R1",
                verification_plan="Run installability and auth checks.",
                milestones=["Installable shell", "Signed-in workflow"],
                split_triggers=["Split when payments are introduced."],
                source_segment_ids=["SEG-PLAN"],
                source_semantic_event_ids=["SEMEVT-PLAN"],
                source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
            )
            promote_semantic_events(
                subject=subject,
                data_root=data_root,
                semantic_events=[
                    {
                        "semantic_event_id": "SEMEVT-SCOPE",
                        "schema_version": 1,
                        "classifier_version": "v1-phase2",
                        "recorded_at": "2026-04-04T12:00:00-04:00",
                        "subject": subject,
                        "class_label": "project.scope",
                        "topic_key": "project.scope",
                        "confidence_band": "high",
                        "materiality_band": "high",
                        "summary": "Scope the project around continuity-safe daily closeout.",
                        "transient_noise": False,
                        "imported_limited": False,
                        "source_segment_ids": ["SEG-SCOPE"],
                        "source_refs": [{"kind": "conversation_segment", "id": "SEG-SCOPE", "path": "/tmp/SEG-SCOPE.json"}],
                        "related_paths": [],
                    }
                ],
            )

            refreshed_draftshot = await self._call(session, "refresh_draftshot")
            self.assertEqual(refreshed_draftshot["status"], "ok")

            refreshed = await self._call(session, "refresh_snapshot_candidates")
            self.assertEqual(refreshed["status"], "ok")
            self.assertIn(refreshed["data"]["status"], {"written", "updated"})
            candidates = list(refreshed["data"]["candidates"])
            self.assertEqual({item["candidate_kind"] for item in candidates}, {"EOD", "CONTROL_SYNC"})
            self.assertTrue(all(Path(item["body_path"]).exists() for item in candidates))
            self.assertEqual(
                refreshed["data"]["current_context"]["draftshot"]["current_active_draftshot_session_id"],
                session_id,
            )

            snapshot_candidates_payload = json.loads(
                await self._read_text_resource(session, "synapse://current/snapshot-candidates.json")
            )
            self.assertTrue(snapshot_candidates_payload["current_eod_candidate_path"])
            self.assertTrue(snapshot_candidates_payload["current_control_sync_candidate_path"])

    async def test_refresh_publication_candidates_tool_writes_noncanonical_candidate_state(self) -> None:
        workspace = self._make_workspace("mcp-refresh-publication-candidates")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Publication candidates"})
            self.assertEqual(bootstrap["status"], "ok")
            subject_context = bootstrap["subject_context"]
            subject = subject_context["subject"]
            data_root = Path(subject_context["data_root"])

            canonical_project_model_path(data_root).write_text(
                yaml.safe_dump(
                    {
                        "project_identity": "Baseline installable website system",
                        "purpose": "Help operators ship installable customer web systems.",
                        "vision": "Become the reusable baseline for installable client delivery.",
                        "confirmed_at": "2026-04-04T10:00:00-04:00",
                        "implemented_truths": [{"summary": "The repo already tracks governed continuity."}],
                        "partial_truths": [],
                        "intended_capabilities": [],
                        "future_ideas_needing_expansion": [],
                        "superseded_directions": [],
                        "constraints": [],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            canonical_project_story_path(data_root).write_text("# Project Story\n\nBaseline story.\n", encoding="utf-8")
            canonical_vision_path(data_root).write_text("# Vision\n\nBaseline vision.\n", encoding="utf-8")
            canonical_codex_current_path(data_root).write_text("# Current Codex\n\nBaseline current codex.\n", encoding="utf-8")
            canonical_codex_future_path(data_root).write_text("# Future Codex\n\nBaseline future codex.\n", encoding="utf-8")

            persist_execution_plan(
                subject=subject,
                data_root=data_root,
                title="Publication candidate foundation",
                summary="Capture current continuity as publication candidates.",
                origin="test-mcp-refresh-publication-candidates",
                objective="Expose story, vision, and codex candidate state without mutating canon.",
                coherent_outcome="Publication candidates exist as durable noncanonical records.",
                closure_statement="Candidate state is readable and source-linked.",
                out_of_scope="Canonical publication.",
                dependencies=["Continuity synthesis"],
                risk="R1",
                verification_plan="Refresh publication candidates and inspect the current-context bundle.",
                milestones=["Story candidate", "Vision candidate", "Codex candidate"],
                split_triggers=["Split if publication candidate storage requires compatibility hardening."],
                source_segment_ids=["SEG-PLAN"],
                source_semantic_event_ids=["SEMEVT-PLAN"],
                source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
            )
            promote_semantic_events(
                subject=subject,
                data_root=data_root,
                semantic_events=[
                    {
                        "semantic_event_id": "SEMEVT-VISION",
                        "schema_version": 1,
                        "classifier_version": "v1-phase3",
                        "recorded_at": "2026-04-04T12:00:00-04:00",
                        "subject": subject,
                        "class_label": "project.vision",
                        "topic_key": "project.vision",
                        "confidence_band": "high",
                        "materiality_band": "high",
                        "summary": "The product becomes a reusable website business system.",
                        "transient_noise": False,
                        "imported_limited": False,
                        "source_segment_ids": ["SEG-VISION"],
                        "source_refs": [{"kind": "conversation_segment", "id": "SEG-VISION", "path": "/tmp/SEG-VISION.json"}],
                        "related_paths": [],
                    }
                ],
            )

            refreshed = await self._call(session, "refresh_publication_candidates")
            self.assertEqual(refreshed["status"], "ok")
            self.assertEqual(
                {item["candidate_kind"] for item in refreshed["data"]["candidates"] if item["status"] == "written"},
                {"STORY", "VISION", "CODEX"},
            )
            self.assertTrue(refreshed["data"]["current_context"]["publication_candidates"]["current_story_candidate_path"])
            self.assertTrue(refreshed["data"]["current_context"]["publication_candidates"]["current_vision_candidate_path"])
            self.assertTrue(refreshed["data"]["current_context"]["publication_candidates"]["current_codex_candidate_paths"])

            publication_candidates_payload = json.loads(
                await self._read_text_resource(session, "synapse://current/publication-candidates.json")
            )
            self.assertTrue(publication_candidates_payload["current_story_candidate_path"])
            self.assertTrue(publication_candidates_payload["current_vision_candidate_path"])
            self.assertTrue(publication_candidates_payload["current_codex_candidate_paths"])
            resources = await session.list_resources()
            uris = {str(item.uri) for item in resources.resources}
            self.assertIn("synapse://current/publication-candidates/story.md", uris)
            self.assertIn("synapse://current/publication-candidates/vision.md", uris)
            self.assertIn("synapse://current/publication-candidates/codex.md", uris)
            self.assertIn("# Project Story Candidate", await self._read_text_resource(session, "synapse://current/publication-candidates/story.md"))
            self.assertIn("# Vision Candidate", await self._read_text_resource(session, "synapse://current/publication-candidates/vision.md"))
            self.assertIn("# Codex Candidate", await self._read_text_resource(session, "synapse://current/publication-candidates/codex.md"))

    async def test_formalize_candidate_tool_publishes_story_candidate_via_candidate_handle(self) -> None:
        workspace = self._make_workspace("mcp-formalize-publication-candidate")
        subject = "PublicationFormalizeSubject"
        data_root = self.root / f"{subject}_Data"
        initialize_subject_state(subject, data_root, workspace)
        ensure_live_scaffold(subject, data_root)
        async with self._session(workspace) as session:
            bootstrap = await self._call(
                session,
                "bootstrap_session",
                {
                    "title": "Formalize publication candidate",
                    "session_mode": "scope_planning",
                    "adopt_current_repo": False,
                    "context": {
                        "subject": subject,
                        "engine_root": str(workspace),
                        "data_root": str(data_root),
                    },
                },
            )
            self.assertEqual(bootstrap["status"], "ok")
            subject_context = bootstrap["subject_context"]
            data_root = Path(subject_context["data_root"])

            canonical_project_model_path(data_root).write_text(
                yaml.safe_dump(
                    {
                        "project_identity": "Baseline installable website system",
                        "purpose": "Help operators ship installable client websites cleanly.",
                        "vision": "Become the reusable baseline for installable customer-facing web systems.",
                        "confirmed_at": "2026-04-04T10:00:00-04:00",
                        "implemented_truths": [{"summary": "The repo already tracks governed continuity."}],
                        "partial_truths": [],
                        "intended_capabilities": [],
                        "future_ideas_needing_expansion": [],
                        "superseded_directions": [],
                        "constraints": [],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            canonical_project_story_path(data_root).write_text("# Project Story\n\nBaseline story.\n", encoding="utf-8")
            canonical_vision_path(data_root).write_text("# Vision\n\nBaseline vision.\n", encoding="utf-8")
            canonical_codex_current_path(data_root).write_text("# Current Codex\n\nBaseline current codex.\n", encoding="utf-8")
            canonical_codex_future_path(data_root).write_text("# Future Codex\n\nBaseline future codex.\n", encoding="utf-8")

            persist_execution_plan(
                subject=subject,
                data_root=data_root,
                title="Publication candidate publish path",
                summary="Refresh then publish a publication candidate canonically.",
                origin="test-mcp-formalize-publication-candidate",
                objective="Verify formalize_candidate can publish a story candidate through the canonical owner.",
                coherent_outcome="Canonical story updates while pending publication candidate state clears.",
                closure_statement="Story publish happens without bypassing repo_onboarding.py.",
                out_of_scope="Automatic canonical publication.",
                dependencies=["Continuity synthesis"],
                risk="R1",
                verification_plan="Refresh publication candidates and formalize the story candidate handle.",
                milestones=["Candidate refresh", "Story publish"],
                split_triggers=["Split if publication handoff needs separate compatibility work."],
                source_segment_ids=["SEG-PLAN"],
                source_semantic_event_ids=["SEMEVT-PLAN"],
                source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
            )
            promote_semantic_events(
                subject=subject,
                data_root=data_root,
                semantic_events=[
                    {
                        "semantic_event_id": "SEMEVT-VISION",
                        "schema_version": 1,
                        "classifier_version": "v1-phase3",
                        "recorded_at": "2026-04-04T12:00:00-04:00",
                        "subject": subject,
                        "class_label": "project.vision",
                        "topic_key": "project.vision",
                        "confidence_band": "high",
                        "materiality_band": "high",
                        "summary": "The product becomes a reusable website business system.",
                        "transient_noise": False,
                        "imported_limited": False,
                        "source_segment_ids": ["SEG-VISION"],
                        "source_refs": [{"kind": "conversation_segment", "id": "SEG-VISION", "path": "/tmp/SEG-VISION.json"}],
                        "related_paths": [],
                    }
                ],
            )

            refreshed = await self._call(session, "refresh_publication_candidates")
            self.assertEqual(refreshed["status"], "ok")
            self.assertTrue(refreshed["data"]["current_context"]["publication_candidates"]["current_story_candidate_path"])

            dry_run = await self._call(session, "formalize_candidate", {"candidate_handle": "story", "dry_run": True})
            self.assertEqual(dry_run["status"], "ok")
            self.assertEqual(dry_run["data"]["publication_candidate"]["candidate_kind"], "STORY")

            formalized = await self._call(session, "formalize_candidate", {"candidate_handle": "story"})
            self.assertEqual(formalized["status"], "ok")
            self.assertEqual(formalized["data"]["result"]["candidate_kind"], "STORY")
            self.assertTrue(Path(formalized["data"]["result"]["publication_receipt_path"]).exists())
            self.assertIn(
                "Baseline installable website system",
                canonical_project_story_path(data_root).read_text(encoding="utf-8"),
            )
            after = await self._call(session, "get_current_context")
            self.assertIsNone(after["data"]["context"]["publication_candidates"]["current_story_candidate_path"])

    async def test_explicit_context_override_does_not_mutate_defaults(self) -> None:
        workspace = self._make_workspace("mcp-default-a")
        other_engine = self.root / "OtherSubject"
        other_data = self.root / "OtherSubject_Data"
        initialize_subject_state("OtherSubject", other_data, other_engine)
        ensure_live_scaffold("OtherSubject", other_data)

        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Primary"})
            default_subject = bootstrap["subject_context"]["subject"]

            override = await self._call(
                session,
                "get_current_context",
                {
                    "context": {
                        "subject": "OtherSubject",
                        "engine_root": str(other_engine),
                        "data_root": str(other_data),
                    }
                },
            )
            self.assertEqual(override["subject_context"]["subject"], "OtherSubject")

            after = await self._call(session, "get_current_context")
            self.assertEqual(after["subject_context"]["subject"], default_subject)
            self.assertEqual(
                after["data"]["context"]["connection_defaults"]["subject"],
                default_subject,
            )

    async def test_incoherent_context_fails_without_mutating_defaults(self) -> None:
        workspace = self._make_workspace("mcp-bad-context")
        second_engine = self.root / "MismatchSubject"
        second_data = self.root / "MismatchSubject_Data"
        initialize_subject_state("MismatchSubject", second_data, second_engine)
        ensure_live_scaffold("MismatchSubject", second_data)

        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Primary"})
            default_subject = bootstrap["subject_context"]["subject"]

            failed = await self._call(
                session,
                "get_current_context",
                {
                    "context": {
                        "subject": default_subject,
                        "engine_root": str(workspace),
                        "data_root": str(second_data),
                    }
                },
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["code"], "CONTEXT_RESOLUTION_FAILED")

            after = await self._call(session, "get_current_context")
            self.assertEqual(after["subject_context"]["subject"], default_subject)

    async def test_two_server_instances_keep_independent_defaults(self) -> None:
        workspace_a = self._make_workspace("mcp-isolation-a")
        workspace_b = self._make_workspace("mcp-isolation-b")
        home_a = self.root / "home-a"
        home_b = self.root / "home-b"
        home_a.mkdir(parents=True, exist_ok=True)
        home_b.mkdir(parents=True, exist_ok=True)
        async with self._session(workspace_a, home=home_a) as session_a, self._session(workspace_b, home=home_b) as session_b:
            first = await self._call(session_a, "bootstrap_session", {"title": "A"})
            second = await self._call(session_b, "bootstrap_session", {"title": "B"})
            self.assertNotEqual(first["subject_context"]["subject"], second["subject_context"]["subject"])
            self.assertNotEqual(first["subject_context"]["session_id"], second["subject_context"]["session_id"])

            current_a = await self._call(session_a, "get_current_context")
            current_b = await self._call(session_b, "get_current_context")
            self.assertEqual(current_a["subject_context"]["subject"], first["subject_context"]["subject"])
            self.assertEqual(current_b["subject_context"]["subject"], second["subject_context"]["subject"])

    async def test_read_surfaces_are_non_mutating(self) -> None:
        workspace = self._make_workspace("mcp-read")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Read test"})
            data_root = Path(bootstrap["subject_context"]["data_root"])
            active_run_path = data_root / ".synapse" / "ACTIVE_RUN.yaml"
            active_run = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
            active_run["session_id"] = None
            active_run_path.write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")
            state_before = (data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8")
            context = await self._call(session, "get_current_context", {"include_rehydrate": True})
            digest = await self._call(session, "get_session_digest", {"style": "expanded"})
            resource_text = await self._read_text_resource(session, "synapse://current/context.json")
            rehydrate_text = await self._read_text_resource(session, "synapse://current/rehydrate.md")
            state_after = (data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8")
            active_run_after = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))

            self.assertEqual(context["status"], "ok")
            self.assertIn("context", context["data"])
            self.assertEqual(digest["status"], "ok")
            self.assertIn("digest_markdown", digest["data"])
            self.assertIn("\"resolved_subject_context\"", resource_text)
            self.assertIn("# Rehydrate", rehydrate_text)
            self.assertEqual(state_before, state_after)
            self.assertIsNone(active_run_after.get("session_id"))

    async def test_provenance_tools_and_resources_expose_runtime_summary(self) -> None:
        workspace = self._make_workspace("mcp-provenance")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Prov test"})
            self.assertEqual(bootstrap["status"], "ok")

            hooks = await self._call(session, "install_git_hooks")
            self.assertEqual(hooks["status"], "ok")
            self.assertEqual(hooks["data"]["git_hooks_status"], "installed")

            summary = await self._call(session, "get_provenance_status")
            self.assertEqual(summary["status"], "ok")
            self.assertIn("provenance_status", summary["data"])
            self.assertEqual(summary["data"]["git_hooks_status"], "installed")
            self.assertIn("integration_posture", summary["data"])
            self.assertIn("open_continuity_obligation_count", summary["data"])

            context = await self._call(session, "get_current_context")
            provenance = context["data"]["context"]["provenance"]
            self.assertIn("provenance_status", provenance)
            self.assertIn("blocker_count", provenance)
            self.assertIn("warning_count", provenance)
            self.assertIn("integration_posture", provenance)
            self.assertIn("blocker_continuity_obligation_count", provenance)

            digest = await self._call(session, "get_session_digest")
            self.assertIn("provenance_summary", digest["data"])

            status_text = await self._read_text_resource(session, "synapse://current/provenance-status")
            anomalies_text = await self._read_text_resource(session, "synapse://current/provenance-anomalies")
            self.assertIn("\"provenance_status\"", status_text)
            self.assertTrue(anomalies_text.strip().startswith("["))

    async def test_onboarding_read_surfaces_do_not_rebuild_pointer(self) -> None:
        workspace = self._make_workspace("mcp-onboarding-readonly")
        async with self._session(workspace) as session:
            started = await self._call(
                session,
                "run_repo_onboarding",
                {"context": {"allow_switch": True}, "depth": "quick"},
            )
            self.assertEqual(started["status"], "ok")
            data_root = Path(started["subject_context"]["data_root"])
            current_path = data_root / ".synapse" / "ONBOARDING" / "CURRENT.yaml"
            current_path.unlink()

            status_text = await self._read_text_resource(session, "synapse://current/onboarding/status.json")
            context_bundle = await self._call(session, "get_current_context")

            self.assertIn("\"onboarding_id\"", status_text)
            self.assertIn("onboarding", context_bundle["data"]["context"])
            self.assertFalse(current_path.exists())

    async def test_transition_session_mode_and_finalize_preserve_last_posture(self) -> None:
        workspace = self._make_workspace("mcp-finalize")
        subject = "FinalizeSubject"
        data_root = self.root / f"{subject}_Data"
        initialize_subject_state(subject, data_root, workspace)
        ensure_live_scaffold(subject, data_root)
        async with self._session(
            workspace,
            extra_env={"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture"},
        ) as session:
            bootstrap = await self._call(
                session,
                "bootstrap_session",
                {
                    "title": "Finalize test",
                    "adopt_current_repo": False,
                    "context": {
                        "subject": subject,
                        "engine_root": str(workspace),
                        "data_root": str(data_root),
                    },
                },
            )
            self.assertEqual(bootstrap["data"]["current_context"]["session_posture"]["active_session_mode"], "brainstorm_spec")

            changed = await self._call(
                session,
                "transition_session_mode",
                {"target_mode": "scope_planning", "reason": "Move into planning"},
            )
            self.assertEqual(changed["status"], "ok")
            self.assertTrue(changed["data"]["changed"])

            blocked = await self._call(
                session,
                "transition_session_mode",
                {"target_mode": "onboarding_existing_repo", "reason": "Illegal backtrack"},
            )
            self.assertEqual(blocked["status"], "blocked")

            finalized = await self._call(
                session,
                "finalize_run",
                {"outcome_summary": "Wrapped the run", "status": "completed"},
            )
            self.assertEqual(finalized["status"], "ok")
            observer = finalized["data"]["continuity_observer"]
            self.assertEqual(observer["observer_status"], "ok")
            self.assertEqual(observer["observer_backend"], "fixture")
            self.assertIn("semantic_capture", observer["observer_action_kinds"])
            self.assertTrue(Path(observer["observer_capture_artifact_path"]).exists())
            truth_compile = finalized["data"]["truth_compile"]
            self.assertTrue(truth_compile["compile_cycle_id"])
            truth_root = Path(finalized["subject_context"]["data_root"]) / ".synapse" / "TRUTH"
            self.assertTrue((truth_root / "COMPILER_REPORT.yaml").exists())
            self.assertTrue((truth_root / "PUBLICATIONS" / "ACTIVE_WORK.md").exists())
            current = finalized["data"]["current_context"]
            self.assertIsNone(current["active_run"]["run_id"])
            self.assertEqual(current["session_posture"]["last_session_mode"], "scope_planning")

    async def test_record_activity_requires_active_run_and_record_decision_disclosure_do_not(self) -> None:
        workspace = self._make_workspace("mcp-activity")
        subject = "Standalone"
        engine_root = self.root / "Standalone"
        data_root = self.root / "Standalone_Data"
        initialize_subject_state(subject, data_root, engine_root)
        ensure_live_scaffold(subject, data_root)
        context = {
            "subject": subject,
            "engine_root": str(engine_root),
            "data_root": str(data_root),
        }

        async with self._session(workspace) as session:
            no_run = await self._call(session, "record_activity", {"summary": "Should fail", "context": context})
            self.assertEqual(no_run["status"], "failed")
            self.assertEqual(no_run["error"]["code"], "ACTIVE_RUN_REQUIRED")
            self.assertIn("bootstrap_session", no_run["error"]["message"] + (no_run["error"].get("recovery_hint") or ""))

            decision = await self._call(
                session,
                "record_decision",
                {"context": context, "title": "Keep the bridge thin", "summary": "No shell-outs."},
            )
            self.assertIn(decision["status"], {"ok", "partial"})
            disclosure = await self._call(
                session,
                "record_disclosure",
                {
                    "context": context,
                    "trigger": "Uncertain replay seam",
                    "expected": "One bridge path",
                    "provable": "Current helpers cover the seam",
                    "impact": "Medium",
                    "decision_needed": "Confirm the bridge contract",
                },
            )
            self.assertIn(disclosure["status"], {"ok", "partial"})

    async def test_record_activity_reuses_runtime_automation_logic(self) -> None:
        workspace = self._make_workspace("mcp-automation-activity")
        async with self._session(
            workspace,
            extra_env={"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture"},
        ) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Automation activity"})
            data_root = Path(bootstrap["subject_context"]["data_root"])
            result = await self._call(
                session,
                "record_activity",
                {
                    "summary": "Mapped reducer replay seam",
                    "files": ["src/main.py"],
                    "notes": [
                        "question: who owns replay coordination?",
                        "risk: stale replay may hide automation deltas",
                    ],
                },
            )
            self.assertEqual(result["status"], "ok")
            automation = result["data"]["automation"]
            self.assertIn("semantic_capture", automation["automation_action_kinds"])
            self.assertIn("disclosure_log", automation["automation_action_kinds"])
            self.assertIn("continuity_refresh", automation["automation_action_kinds"])
            observer = result["data"]["continuity_observer"]
            self.assertEqual(observer["observer_status"], "ok")
            self.assertEqual(observer["observer_backend"], "fixture")
            self.assertIn("semantic_capture", observer["observer_action_kinds"])
            self.assertTrue(Path(observer["observer_capture_artifact_path"]).exists())

            latest_event = self._event_entries(data_root)[-1]
            self.assertTrue(latest_event["signals"]["automation_triggered"])
            self.assertEqual(latest_event["signals"]["automation_context"]["activity_source"], "mcp")
            self.assertEqual(latest_event["signals"]["automation_context"]["activity_kind"], "record-activity")
            self.assertEqual(latest_event["outputs"]["observer_backend"], "fixture")
            self.assertEqual(latest_event["signals"]["observer_action_kinds"], observer["observer_action_kinds"])
            self.assertIsNotNone(latest_event["outputs"]["capture_artifact_path"])
            self.assertIsNotNone(latest_event["outputs"]["disclosures_ledger_path"])

    async def test_capture_chunk_updates_continuity_without_leaking_raw_text(self) -> None:
        workspace = self._make_workspace("mcp-capture")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Capture test"})
            data_root = Path(bootstrap["subject_context"]["data_root"])
            result = await self._call(
                session,
                "capture_chunk",
                {
                    "text": "Need to figure out the reducer replay seam.",
                    "captures": {
                        "captures": [
                            {"kind": "question", "summary": "What owns replay?", "blocking": True},
                            {"kind": "idea", "summary": "Bridge directly to runtime helpers"},
                        ]
                    },
                    "title": "Capture batch",
                },
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["data"]["capture_artifact_path"]).exists())
            self.assertTrue(Path(result["data"]["capture_ledger_path"]).exists())

            context_json = json.loads(await self._read_text_resource(session, "synapse://current/context.json"))
            self.assertEqual(context_json["semantic_intake"]["open_question_count"], 1)

            latest_event = self._event_entries(data_root)[-1]
            self.assertEqual(latest_event["action_name"], "capture-chunk")
            event_blob = json.dumps(latest_event)
            self.assertNotIn("Need to figure out the reducer replay seam.", event_blob)

    async def test_run_repo_onboarding_end_to_end_and_resources(self) -> None:
        workspace = self._make_workspace("mcp-onboarding")
        async with self._session(workspace) as session:
            started = await self._call(
                session,
                "run_repo_onboarding",
                {"context": {"allow_switch": True}, "depth": "deep"},
            )
            self.assertEqual(started["status"], "ok")
            self.assertTrue(started["subject_context"]["session_id"])
            onboarding_status = started["data"]["onboarding_status"]
            onboarding_id = onboarding_status["onboarding_id"]
            scan_id = onboarding_status["current_scan_id"]
            self.assertTrue(scan_id)

            first_draft = self._base_draft(
                onboarding_id=onboarding_id,
                revision_id="REVISION-1",
                supersedes_revision_id=None,
                scan_id=scan_id,
                capture_batch_ids=[],
                next_question_ids=["Q-1"],
                answer_refs=[],
            )
            question_set = self._base_questions(onboarding_id=onboarding_id, draft_revision_id="REVISION-1")
            question_set["questions"][0]["evidence_refs"] = [evidence_ref(scan_id=scan_id, section="docs_inventory", item_id="q-1")]

            draft_result = await self._call(
                session,
                "submit_onboarding_draft",
                {"draft_model": first_draft, "question_set": question_set},
            )
            self.assertEqual(draft_result["status"], "ok")
            self.assertEqual(draft_result["data"]["revision_id"], "REVISION-1")

            response_result = await self._call(
                session,
                "submit_onboarding_responses",
                {
                    "text": "The operator workflow is: bootstrap, inspect context, mutate continuity, then finalize.",
                    "title": "Onboarding answer",
                    "linked_question_ids": ["Q-1"],
                    "captures": {
                        "captures": [
                            {"kind": "repo_fact", "summary": "Operators work through the runtime tool boundary."}
                        ]
                    },
                },
            )
            self.assertEqual(response_result["status"], "ok")
            capture_batch_id = response_result["data"]["capture_batch_id"]

            second_draft = self._base_draft(
                onboarding_id=onboarding_id,
                revision_id="REVISION-2",
                supersedes_revision_id="REVISION-1",
                scan_id=scan_id,
                capture_batch_ids=[capture_batch_id],
                next_question_ids=[],
                answer_refs=[f"capture:{capture_batch_id}:CAPTURE-001"],
            )
            confirmed_ready = await self._call(
                session,
                "submit_onboarding_draft",
                {
                    "draft_model": second_draft,
                    "question_set": {
                        "onboarding_id": onboarding_id,
                        "question_set_id": "QUESTION_SET-2",
                        "draft_revision_id": "REVISION-2",
                        "generated_at": "2026-03-21T10:30:00-04:00",
                        "questions": [
                            {
                                **question_set["questions"][0],
                                "target_item_ids": ["CAP-2"],
                                "status": "answered",
                                "answer_capture_batch_ids": [capture_batch_id],
                            }
                        ],
                    },
                },
            )
            self.assertEqual(confirmed_ready["status"], "ok")
            self.assertFalse(confirmed_ready["data"]["draft_is_stale"])

            confirmed = await self._call(session, "confirm_onboarding", {"confirm": True})
            self.assertEqual(confirmed["status"], "ok")
            self.assertEqual(confirmed["data"]["published_project_model_resource_uri"], "synapse://current/project-model.json")
            truth_compile = confirmed["data"]["truth_compile"]
            self.assertTrue(truth_compile["compile_cycle_id"])
            truth_root = Path(confirmed["subject_context"]["data_root"]) / ".synapse" / "TRUTH"
            self.assertTrue((truth_root / "COMPILER_REPORT.yaml").exists())
            self.assertTrue((truth_root / "PUBLICATIONS" / "CURRENT_STATE.md").exists())

            resources = await session.list_resources()
            uris = {str(item.uri) for item in resources.resources}
            self.assertIn("synapse://current/project-model.json", uris)
            self.assertIn("synapse://current/project-story.md", uris)
            self.assertIn("synapse://current/vision.md", uris)

    async def test_abandon_onboarding_marks_session_abandoned(self) -> None:
        workspace = self._make_workspace("mcp-onboarding-abandon")
        async with self._session(workspace) as session:
            await self._call(session, "bootstrap_session", {"title": "Onboarding bootstrap"})
            started = await self._call(
                session,
                "run_repo_onboarding",
                {"context": {"allow_switch": True}, "depth": "quick"},
            )
            self.assertIn(started["status"], {"ok", "noop"})
            abandoned = await self._call(session, "abandon_onboarding", {})
            self.assertEqual(abandoned["status"], "ok")
            status = json.loads(await self._read_text_resource(session, "synapse://current/onboarding/status.json"))
            self.assertIsNone(status["onboarding_id"])

    async def test_formalize_candidate_respects_posture_gates(self) -> None:
        workspace = self._make_workspace("mcp-governed")
        async with self._session(workspace) as session:
            await self._call(session, "bootstrap_session", {"title": "Governed bootstrap"})
            started = await self._call(
                session,
                "run_repo_onboarding",
                {"context": {"allow_switch": True}, "depth": "quick"},
            )
            onboarding_id = started["data"]["onboarding_status"]["onboarding_id"]
            scan_id = started["data"]["onboarding_status"]["current_scan_id"]
            confirmed_ready = await self._call(
                session,
                "submit_onboarding_draft",
                {
                    "draft_model": self._base_draft(
                        onboarding_id=onboarding_id,
                        revision_id="REVISION-1",
                        supersedes_revision_id=None,
                        scan_id=scan_id,
                        capture_batch_ids=[],
                        next_question_ids=[],
                        answer_refs=[],
                    ),
                    "question_set": {
                        "onboarding_id": onboarding_id,
                        "question_set_id": "QUESTION_SET-1",
                        "draft_revision_id": "REVISION-1",
                        "generated_at": "2026-03-21T11:00:00-04:00",
                        "questions": [],
                    },
                },
            )
            self.assertEqual(confirmed_ready["status"], "ok")
            confirmed = await self._call(session, "confirm_onboarding", {"confirm": True})
            self.assertEqual(confirmed["status"], "ok")

            candidates = await self._call(session, "list_formalization_candidates")
            quest_candidates = [item for item in candidates["data"]["proposals"] if item.get("kind") == "quest"]
            self.assertTrue(quest_candidates)
            proposal_id = quest_candidates[0]["proposal_id"]

            blocked = await self._call(session, "formalize_candidate", {"proposal_id": proposal_id})
            self.assertEqual(blocked["status"], "blocked")

            await self._call(
                session,
                "transition_session_mode",
                {"target_mode": "scope_planning", "reason": "Move into execution planning"},
            )
            dry_run = await self._call(session, "formalize_candidate", {"proposal_id": proposal_id, "dry_run": True})
            self.assertEqual(dry_run["status"], "ok")
            self.assertTrue(dry_run["data"]["dry_run"])

            formalized = await self._call(session, "formalize_candidate", {"proposal_id": proposal_id})
            self.assertEqual(formalized["status"], "ok")
            not_ready_acceptance = await self._call(
                session,
                "accept_quest",
                {"quest_path": formalized["data"]["result"]["artifact_path"]},
            )
            self.assertEqual(not_ready_acceptance["status"], "failed")
            self.assertEqual(not_ready_acceptance["error"]["code"], "QUEST_ACCEPTANCE_FAILED")

    async def test_accept_quest_resolves_quest_path_and_id(self) -> None:
        workspace = self._make_workspace("mcp-accept")
        subject = "AcceptSubject"
        data_root = self.root / f"{subject}_Data"
        initialize_subject_state(subject, data_root, workspace)
        ensure_live_scaffold(subject, data_root)
        async with self._session(workspace) as session:
            bootstrap = await self._call(
                session,
                "bootstrap_session",
                {
                    "title": "Governed accept bootstrap",
                    "session_mode": "scope_planning",
                    "adopt_current_repo": False,
                    "context": {
                        "subject": subject,
                        "engine_root": str(workspace),
                        "data_root": str(data_root),
                    },
                },
            )
            subject = bootstrap["subject_context"]["subject"]
            data_root = Path(bootstrap["subject_context"]["data_root"])
            self._write_codex_freeze(data_root)
            self._open_control_sync(subject, data_root)

            board_path = self._write_ready_board_quest(subject, data_root, quest_id="QUEST_001")
            accepted_by_path = await self._call(session, "accept_quest", {"quest_path": str(board_path)})
            self.assertEqual(accepted_by_path["status"], "ok")
            self.assertEqual(accepted_by_path["data"]["acceptance"]["quest_id"], "QUEST_001")

            board_path_two = self._write_ready_board_quest(subject, data_root, quest_id="QUEST_002")
            accepted_by_id = await self._call(session, "accept_quest", {"quest_id": "QUEST_002"})
            self.assertEqual(accepted_by_id["status"], "ok")
            self.assertEqual(accepted_by_id["data"]["acceptance"]["quest_id"], "QUEST_002")

    async def test_plan_quests_and_complete_quest_round_trip(self) -> None:
        workspace = self._make_workspace("mcp-plan-complete")
        subject = "QuestMcpSubject"
        data_root = self.root / f"{subject}_Data"
        initialize_subject_state(subject, data_root, workspace)
        ensure_live_scaffold(subject, data_root)
        async with self._session(workspace) as session:
            bootstrap = await self._call(
                session,
                "bootstrap_session",
                {
                    "title": "Quest runtime MCP flow",
                    "session_mode": "scope_planning",
                    "adopt_current_repo": False,
                    "context": {
                        "subject": subject,
                        "engine_root": str(workspace),
                        "data_root": str(data_root),
                    },
                },
            )
            subject = bootstrap["subject_context"]["subject"]
            data_root = Path(bootstrap["subject_context"]["data_root"])
            self._write_codex_freeze(data_root)
            self._open_control_sync(subject, data_root)

            planned = await self._call(
                session,
                "plan_quests",
                {
                    "title": "MCP quest flow",
                    "goal": "Draft, accept, and close one bounded coherent quest through the MCP bridge.",
                    "items": [
                        "Draft the quest from a persisted plan revision.",
                        "Accept the quest through the governed runtime.",
                        "Close the quest only with a clean completion audit PASS.",
                    ],
                    "anchors": ["6.5", "9.2"],
                    "constraints": ["Keep MCP transport thin and receipt-backed."],
                    "change_class": "FEATURE",
                    "vision_delta": "ALIGNED",
                    "door_impact": "MCP",
                    "testing_level": "TL2",
                },
            )
            self.assertEqual(planned["status"], "ok")
            quest_path = Path(planned["data"]["quests"][0]["path"])
            self.assertTrue(quest_path.exists())
            self.assertTrue(Path(planned["data"]["plan_artifact_path"]).exists())

            accepted = await self._call(session, "accept_quest", {"quest_path": str(quest_path)})
            self.assertEqual(accepted["status"], "ok")
            accepted_path = Path(accepted["data"]["acceptance"]["accepted_path"])
            bundle_path = Path(accepted["data"]["acceptance"]["audit_bundle_path"])
            self.assertTrue(accepted_path.exists())

            completed = await self._call(
                session,
                "complete_quest",
                {
                    "quest_path": str(accepted_path),
                    "milestone_statuses": [
                        "MILESTONE-001:DONE:Drafted from a persisted plan revision.",
                        "MILESTONE-002:DONE:Accepted through the governed runtime.",
                        "MILESTONE-003:DONE:Closed only with a clean completion audit PASS.",
                    ],
                    "checks": [
                        "MCP_FLOW:PASS:MCP quest lifecycle stayed on the governed runtime path.",
                        "AUDIT:PASS:Completion audit receipts were written.",
                    ],
                    "receipt_refs": [str(bundle_path / "06_TESTS.txt"), str(bundle_path / "06_CHANGED_FILES.txt")],
                    "commands_run": ["python3 -m unittest tests.test_mcp_integration -v"],
                    "changed_files": ["runtime/synapse_mcp/runtime_bridge.py"],
                },
            )
            self.assertEqual(completed["status"], "ok")
            self.assertEqual(completed["data"]["completion"]["overall_verdict"], "PASS")
            self.assertEqual(completed["data"]["completion"]["final_state_decision"], "COMPLETED")
            self.assertTrue(Path(completed["data"]["completion"]["latest_completion_audit_path"]).exists())
            self.assertIn("/Completed/", completed["data"]["completion"]["active_path"])

    async def test_capture_partial_preserves_runtime_status(self) -> None:
        workspace = self._make_workspace("mcp-partial")
        async with self._session(workspace) as session:
            bootstrap = await self._call(session, "bootstrap_session", {"title": "Partial test"})
            data_root = Path(bootstrap["subject_context"]["data_root"])
            open_questions = canonical_open_questions_path(data_root)
            open_questions.parent.mkdir(parents=True, exist_ok=True)
            open_questions.write_text("Unmanaged thread\n", encoding="utf-8")

            partial = await self._call(
                session,
                "capture_chunk",
                {
                    "text": "Question with a thread conflict",
                    "captures": {"captures": [{"kind": "question", "summary": "Who owns this?", "blocking": True}]},
                },
            )
            self.assertEqual(partial["status"], "partial")
            self.assertIsNotNone(partial["runtime_status"])
            self.assertEqual(partial["error"]["code"], "THREAD_CONFLICT")
            self.assertTrue(Path(partial["data"]["capture_artifact_path"]).exists())
            self.assertTrue(Path(partial["data"]["capture_ledger_path"]).exists())

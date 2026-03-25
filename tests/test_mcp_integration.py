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
    "record_decision",
    "record_disclosure",
    "capture_chunk",
    "install_git_hooks",
    "verify_git_hooks",
    "run_repo_onboarding",
    "submit_onboarding_draft",
    "submit_onboarding_responses",
    "confirm_onboarding",
    "abandon_onboarding",
    "list_formalization_candidates",
    "formalize_candidate",
    "accept_quest",
    "refresh_continuity",
    "finalize_run",
]
FIXED_RESOURCES = {
    "synapse://current/context.json",
    "synapse://current/state.json",
    "synapse://current/manifold.json",
    "synapse://current/active-run.json",
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
            "Atomicity Statement: Atomic: yes - one independently verifiable governed acceptance path.",
            "",
            "Risk: R1",
            "",
            "R2 Confirmation Artifact (REQUIRED if Risk = R2):",
            "",
            "Description: Accept a board quest into governed execution through the MCP bridge.",
            "",
            "Scope / Objective: Successful acceptance moves the quest into Accepted/ with a canonical audit bundle and explicit readiness.",
            "",
            "Out of Scope: Completing the quest or writing execution receipts.",
            "",
            "Dependencies: None",
            "",
            "Door Impact: MCP",
            "",
            "Testing Level (TL): TL2",
            "",
            "Verification Plan: Verification Commands: /tmp/synapse-mcp-venv/bin/python -m unittest tests.test_mcp_integration -v | PASS when exit code is 0 | FAIL otherwise | Receipts: 03_VERIFY.md + 06_TESTS.txt",
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

    def _server_params(self, workspace: Path, *, home: Path | None = None) -> StdioServerParameters:
        target_home = home or self.home
        return StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            cwd=str(workspace),
            env={
                **os.environ,
                "HOME": str(target_home),
                "SYNAPSE_ROOT": str(REPO_ROOT),
            },
        )

    @asynccontextmanager
    async def _session(self, workspace: Path, *, home: Path | None = None):
        async with stdio_client(self._server_params(workspace, home=home)) as (read, write):
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

            context = await self._call(session, "get_current_context")
            provenance = context["data"]["context"]["provenance"]
            self.assertIn("provenance_status", provenance)
            self.assertIn("blocker_count", provenance)
            self.assertIn("warning_count", provenance)

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
        async with self._session(workspace) as session:
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
        async with self._session(workspace) as session:
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

            latest_event = self._event_entries(data_root)[-1]
            self.assertTrue(latest_event["signals"]["automation_triggered"])
            self.assertEqual(latest_event["signals"]["automation_context"]["activity_source"], "mcp")
            self.assertEqual(latest_event["signals"]["automation_context"]["activity_kind"], "record-activity")
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

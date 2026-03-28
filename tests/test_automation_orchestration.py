import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.automation_orchestrator import automation_policy_for_context, automation_summary
from synapse_runtime.doctor import run_doctor
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.repo_archaeology import evidence_ref
from synapse_runtime.repo_onboarding import (
    current_onboarding_session,
    default_onboarding_session,
    mark_adopted_existing_repo,
    onboarding_current_path,
    save_onboarding_pointer,
    save_onboarding_session,
)
from synapse_runtime.sidecar_projection import refresh_onboarding_projection, refresh_session_posture_projection
from synapse_runtime.sidecar_store import _default_active_run, ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state

SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class AutomationOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.engine_root = self.root / "engine"
        self.data_root = self.root / "Subject_Data"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src").mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.data_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state("Subject", self.data_root, self.engine_root)
        ensure_live_scaffold("Subject", self.data_root)
        self.subject_receipt = {
            "subject": "Subject",
            "data_root": str(self.data_root.resolve()),
            "engine_root": str(self.engine_root.resolve()),
            "selected_at": "2026-03-23T09:00:00-04:00",
            "selected_by": "Tests",
            "selection_method": "flag",
            "source_detail": "tests",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_confirmed_onboarding(self) -> None:
        live = self.data_root / ".synapse"
        model_path = live / "PROJECT_MODEL.yaml"
        story_path = live / "PROJECT_STORY.md"
        vision_path = live / "VISION.md"
        model_path.write_text(
            "\n".join(
                [
                    "onboarding_id: ONBOARDING-1",
                    "confirmed_at: 2026-03-23T10:00:00-04:00",
                    "confirmed_by: SID-1",
                    "project_identity: Subject",
                    "purpose: Keep continuity truthful.",
                    "vision: Durable runtime context.",
                    "confirmed_capabilities:",
                    "  - summary: Runtime maintains sidecar truth.",
                    "constraints:",
                    "  - summary: Truth must stay on disk.",
                    "stale_or_superseded_directions: []",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        story_path.write_text("# Story\n", encoding="utf-8")
        vision_path.write_text("# Vision\n", encoding="utf-8")

        session = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-1",
            depth="deep",
            active_run_id="RUN-1",
            session_id="SID-1",
        )
        session["state"] = "confirmed"
        session["confirmed_at"] = "2026-03-23T10:00:00-04:00"
        session["published_project_model_path"] = str(model_path.resolve())
        session["published_project_story_path"] = str(story_path.resolve())
        session["published_vision_path"] = str(vision_path.resolve())
        save_onboarding_session(data_root=self.data_root, session=session)
        save_onboarding_pointer(
            data_root=self.data_root,
            pointer={
                "subject": "Subject",
                "adopted_existing_repo": True,
                "current_onboarding_id": None,
                "latest_confirmed_onboarding_id": "ONBOARDING-1",
                "updated_at": "2026-03-23T10:00:00-04:00",
            },
        )

    def test_adopted_repo_without_confirmed_onboarding_requires_readiness_gate(self) -> None:
        mark_adopted_existing_repo(subject="Subject", data_root=self.data_root)
        policy = automation_policy_for_context(data_root=self.data_root)
        self.assertTrue(policy.onboarding_required)
        self.assertFalse(policy.project_identity_ready)
        self.assertFalse(policy.continuity_ready)
        self.assertIn("latest_confirmed_onboarding_id", policy.missing_publication_fields)

    def test_confirmed_onboarding_clears_requirement_and_marks_identity_ready(self) -> None:
        self._write_confirmed_onboarding()
        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)
        policy = automation_policy_for_context(data_root=self.data_root)
        self.assertFalse(policy.onboarding_required)
        self.assertTrue(policy.onboarding_confirmed)
        self.assertTrue(policy.project_identity_ready)
        self.assertTrue(policy.continuity_ready)
        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertTrue(state["onboarding_confirmed"])
        self.assertTrue(manifold["onboarding_confirmed"])

    def test_doctor_fails_adopted_unconfirmed_repo_and_reports_missing_publications(self) -> None:
        mark_adopted_existing_repo(subject="Subject", data_root=self.data_root)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = run_doctor(str(REPO_ROOT / "governance"), self.subject_receipt)
        output = stream.getvalue()
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL_ONBOARDING_CONFIRMATION_REQUIRED", output)
        self.assertIn("latest_confirmed_onboarding_id: MISSING", output)
        self.assertIn("published_project_model_path: MISSING", output)
        self.assertIn("published_project_story_path: MISSING", output)
        self.assertIn("published_vision_path: MISSING", output)

    def test_rehydrate_renders_scaffold_vs_confirmed_truth(self) -> None:
        mark_adopted_existing_repo(subject="Subject", data_root=self.data_root)
        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)
        render_rehydrate(subject="Subject", data_root=self.data_root)
        text = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Repository readiness", text)
        self.assertIn("WARNING: project model missing", text)
        self.assertIn("WARNING: project story missing", text)
        self.assertIn("WARNING: vision missing", text)
        self.assertIn("WARNING: onboarding confirmation required before normal work", text)

        self._write_confirmed_onboarding()
        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)
        render_rehydrate(subject="Subject", data_root=self.data_root)
        confirmed_text = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Published project identity", confirmed_text)
        self.assertIn("- Onboarding confirmed: YES", confirmed_text)
        self.assertIn("Project model path:", confirmed_text)
        self.assertNotIn("WARNING: project model missing", confirmed_text)

    def test_automation_summary_projects_readiness_flags(self) -> None:
        mark_adopted_existing_repo(subject="Subject", data_root=self.data_root)
        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)
        summary = automation_summary(self.data_root)
        self.assertTrue(summary["onboarding_required"])
        self.assertFalse(summary["onboarding_confirmed"])
        self.assertFalse(summary["project_identity_ready"])
        self.assertFalse(summary["continuity_ready"])
        self.assertEqual(summary["automation_status"], "onboarding_required")
        self.assertEqual(
            (self.data_root / ".synapse" / "ONBOARDING" / "CURRENT.yaml"),
            onboarding_current_path(self.data_root),
        )

    def test_onboarding_projection_prefers_published_model_confirmed_at(self) -> None:
        self._write_confirmed_onboarding()
        onboarding_session = current_onboarding_session(
            subject="Subject",
            data_root=self.data_root,
            require_current=False,
        )
        onboarding_session["confirmed_at"] = "2026-03-23T09:55:00-04:00"
        save_onboarding_session(data_root=self.data_root, session=onboarding_session)

        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)

        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["project_model_confirmed_at"].isoformat(), "2026-03-23T10:00:00-04:00")
        self.assertEqual(manifold["project_model_confirmed_at"].isoformat(), "2026-03-23T10:00:00-04:00")

    def test_session_posture_projection_prefers_latest_finalized_run_over_stale_state(self) -> None:
        live = self.data_root / ".synapse"
        runs_dir = live / "RUNS"
        runs_dir.mkdir(parents=True, exist_ok=True)

        state_path = live / "STATE.yaml"
        manifold_path = live / "MANIFOLD.yaml"
        run_path = live / "ACTIVE_RUN.yaml"

        state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        manifold = yaml.safe_load(manifold_path.read_text(encoding="utf-8"))
        state["last_session_mode"] = "control_sync"
        state["last_session_mode_ended_at"] = "2026-03-25T23:45:24.317157-04:00"
        manifold["last_session_mode"] = "control_sync"
        manifold["last_session_mode_ended_at"] = "2026-03-25T23:45:24.317157-04:00"
        state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
        manifold_path.write_text(yaml.safe_dump(manifold, sort_keys=False), encoding="utf-8")

        idle_run = _default_active_run("Subject")
        run_path.write_text(yaml.safe_dump(idle_run, sort_keys=False), encoding="utf-8")

        archived_run = {
            "schema_version": 1,
            "active": False,
            "run_id": "RUN-20260328-140810",
            "subject": "Subject",
            "status": "completed",
            "last_session_mode": "control_sync",
            "last_session_mode_ended_at": "2026-03-28T14:15:16.455317-04:00",
            "updated_at": "2026-03-28T14:15:16.455317-04:00",
            "finalized_at": "2026-03-28T14:15:16.455317-04:00",
        }
        (runs_dir / "RUN-20260328-140810__sync.yaml").write_text(
            yaml.safe_dump(archived_run, sort_keys=False),
            encoding="utf-8",
        )

        projection = refresh_session_posture_projection(subject="Subject", data_root=self.data_root)
        refreshed_state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        refreshed_manifold = yaml.safe_load(manifold_path.read_text(encoding="utf-8"))

        self.assertEqual(projection["last_session_mode"], "control_sync")
        self.assertEqual(projection["last_session_mode_ended_at"], "2026-03-28T14:15:16.455317-04:00")
        self.assertEqual(refreshed_state["last_session_mode_ended_at"], "2026-03-28T14:15:16.455317-04:00")
        self.assertEqual(refreshed_manifold["last_session_mode_ended_at"], "2026-03-28T14:15:16.455317-04:00")


class AutomationCliGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.repo = self.root / "demo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        (self.repo / "src").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.engage = run_synapse(["engage", "--adopt-current-repo", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(self.engage.returncode, 0, self.engage.stdout + self.engage.stderr)
        self.engage_payload = json.loads(self.engage.stdout)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _data_root(self) -> Path:
        return Path(self.engage_payload["data_root"])

    def _confirm_current_onboarding(self) -> None:
        data_root = self._data_root()
        session = current_onboarding_session(
            subject=self.repo.name,
            data_root=data_root,
            require_current=True,
        )
        assert session is not None
        live = data_root / ".synapse"
        model_path = live / "PROJECT_MODEL.yaml"
        story_path = live / "PROJECT_STORY.md"
        vision_path = live / "VISION.md"
        model_path.write_text(
            "\n".join(
                [
                    f"onboarding_id: {session['onboarding_id']}",
                    "confirmed_at: 2026-03-23T11:00:00-04:00",
                    "confirmed_by: syn-confirmed",
                    f"project_identity: {self.repo.name}",
                    "purpose: Build continuity automatically during coding.",
                    "vision: Executor-parallel continuity runtime.",
                    "confirmed_capabilities:",
                    "  - summary: Runtime updates continuity without stopping coding.",
                    "constraints:",
                    "  - summary: Truth must remain draft-safe until explicitly published.",
                    "stale_or_superseded_directions: []",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        story_path.write_text("# Story\n\nConfirmed project story.\n", encoding="utf-8")
        vision_path.write_text("# Vision\n\nExecutor-parallel continuity.\n", encoding="utf-8")
        updated_session = dict(session)
        updated_session["state"] = "confirmed"
        updated_session["confirmed_at"] = "2026-03-23T11:00:00-04:00"
        updated_session["confirmed_by"] = "syn-confirmed"
        updated_session["published_project_model_path"] = str(model_path.resolve())
        updated_session["published_project_story_path"] = str(story_path.resolve())
        updated_session["published_vision_path"] = str(vision_path.resolve())
        save_onboarding_session(data_root=data_root, session=updated_session)
        save_onboarding_pointer(
            data_root=data_root,
            pointer={
                "subject": self.repo.name,
                "adopted_existing_repo": True,
                "current_onboarding_id": None,
                "latest_confirmed_onboarding_id": session["onboarding_id"],
                "updated_at": "2026-03-23T11:00:00-04:00",
            },
        )
        refresh_onboarding_projection(subject=self.repo.name, data_root=data_root)

    def _draft_payloads(self) -> tuple[dict[str, object], dict[str, object]]:
        session = current_onboarding_session(
            subject=self.repo.name,
            data_root=self._data_root(),
            require_current=True,
        )
        assert session is not None
        onboarding_id = str(session["onboarding_id"])
        scan_id = str(session["current_scan_id"])
        draft = {
            "onboarding_id": onboarding_id,
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-23T10:00:00-04:00",
            "based_on_scan_ids": [scan_id],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Executor-parallel continuity runtime",
            "purpose_hypothesis": "Keep project work moving while continuity stays current.",
            "vision_hypothesis": "Synapse updates story truth beside the executor.",
            "maturity_hypothesis": "Active development.",
            "user_or_stakeholder_hypotheses": [
                {
                    "id": "USER-1",
                    "summary": "Operators want coding flow without continuity babysitting.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="docs_inventory", item_id="user-1")],
                    "answer_refs": [],
                }
            ],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "Runtime can update continuity during execution.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="tree_inventory", item_id="cap-1")],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Automation orchestrator classifies meaningful work.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="tree_inventory", item_id="comp-1")],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "CLI and MCP share runtime automation helpers.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="entrypoint_inventory", item_id="int-1")],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [
                {
                    "id": "CONS-1",
                    "summary": "Automatic updates must stay draft-safe.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="docs_inventory", item_id="cons-1")],
                    "answer_refs": [],
                }
            ],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo continuity evolved through explicit governed phases.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="existing_continuity_inventory", item_id="hist-1")],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": ["Q-1"],
        }
        questions = {
            "onboarding_id": onboarding_id,
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-23T10:01:00-04:00",
            "questions": [
                {
                    "question_id": "Q-1",
                    "prompt": "What should the executor auto-capture during routine work?",
                    "category": "purpose",
                    "priority": "blocking",
                    "why_asked": "Automation must stay useful without spamming noise.",
                    "evidence_refs": [evidence_ref(scan_id=scan_id, section="docs_inventory", item_id="q-1")],
                    "target_item_ids": ["CAP-1"],
                    "status": "open",
                    "answer_capture_batch_ids": [],
                }
            ],
        }
        return draft, questions

    def test_engage_adopt_current_repo_auto_starts_onboarding(self) -> None:
        self.assertTrue(self.engage_payload["onboarding_required"])
        self.assertFalse(self.engage_payload["continuity_ready"])
        bootstrap = self.engage_payload["onboarding_bootstrap"]
        self.assertEqual(bootstrap["onboarding_state"], "needs_draft_submission")
        current_path = Path(self.engage_payload["data_root"]) / ".synapse" / "ONBOARDING" / "CURRENT.yaml"
        pointer = yaml.safe_load(current_path.read_text(encoding="utf-8"))
        self.assertTrue(pointer["adopted_existing_repo"])
        self.assertEqual(pointer["current_onboarding_id"], bootstrap["onboarding_id"])

    def test_attach_existing_repo_reuses_attach_and_bootstrap_substrate(self) -> None:
        workspace = self.root / "attach-demo"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "README.md").write_text("# attach demo\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        result = run_synapse(["attach-existing-repo", "--json"], cwd=workspace, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("onboarding_bootstrap", payload)
        self.assertEqual(payload["doctor_exit_code"], 1)
        self.assertEqual(payload["next_required_action"], "onboarding-update")
        self.assertTrue(payload["onboarding_required"])

    def test_unconfirmed_adopted_repo_blocks_ready_state_modes_but_not_inspect_reads(self) -> None:
        blocked_run = run_synapse(["run-start", "--title", "Build", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(blocked_run.returncode, 2, blocked_run.stdout + blocked_run.stderr)
        self.assertIn("has not been confirmed through onboarding", blocked_run.stdout + blocked_run.stderr)

        blocked_session = run_synapse(
            ["session-start", "--title", "Sync", "--session-mode", "control_sync", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(blocked_session.returncode, 2, blocked_session.stdout + blocked_session.stderr)
        self.assertIn("project identity/story/vision are not ready", blocked_session.stdout + blocked_session.stderr)

        blocked_transition = run_synapse(
            [
                "session-mode",
                "--set",
                "execution",
                "--reason",
                "skip ahead",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(blocked_transition.returncode, 2, blocked_transition.stdout + blocked_transition.stderr)
        self.assertIn("has not been confirmed through onboarding", blocked_transition.stdout + blocked_transition.stderr)

        finalized = run_synapse(
            ["run-finalize", "--status", "cancelled", "--summary", "close onboarding run", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)

        blocked_tick = run_synapse(
            ["session-tick", "--session-mode", "control_sync", "--summary", "tick", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(blocked_tick.returncode, 2, blocked_tick.stdout + blocked_tick.stderr)
        self.assertIn("onboarding-confirm", blocked_tick.stdout + blocked_tick.stderr)

        inspect = run_synapse(["onboarding-status", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(inspect.returncode, 0, inspect.stdout + inspect.stderr)
        inspect_payload = json.loads(inspect.stdout)
        self.assertEqual(inspect_payload["state"], "needs_draft_submission")

    def test_meaningful_code_mutation_triggers_automatic_continuity_refresh_metadata(self) -> None:
        result = run_synapse(
            ["run-update", "--summary", "Touched runtime bridge", "--file", "src/main.py", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        automation = payload["automation"]
        self.assertTrue(automation["automation_triggered"])
        self.assertEqual(automation["automation_action_kinds"], ["continuity_refresh"])
        self.assertEqual(automation["automation_context"]["activity_kind"], "run-update")
        self.assertEqual(payload["event"]["payload"]["signals"]["automation_action_kinds"], ["continuity_refresh"])
        self.assertTrue(payload["event"]["payload"]["signals"]["automation_triggered"])
        self.assertEqual(
            payload["event"]["payload"]["outputs"]["continuity_side_effects"],
            [{"action": "continuity_refresh", "status": "ok"}],
        )

    def test_risk_activity_triggers_automatic_disclosure_and_semantic_capture(self) -> None:
        result = run_synapse(
            [
                "run-update",
                "--summary",
                "Risk surfaced during migration prep",
                "--note",
                "risk: staging migration may corrupt data",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        automation = payload["automation"]
        self.assertIn("semantic_capture", automation["automation_action_kinds"])
        self.assertIn("disclosure_log", automation["automation_action_kinds"])
        self.assertIn("continuity_refresh", automation["automation_action_kinds"])
        self.assertIsNotNone(automation["capture_artifact_path"])
        self.assertIsNotNone(automation["disclosures_ledger_path"])
        self.assertTrue(payload["event"]["payload"]["truth_flags"]["disclosure_open"])
        self.assertIsNotNone(payload["event"]["payload"]["outputs"]["capture_artifact_path"])

    def test_decision_activity_triggers_automatic_decision_log(self) -> None:
        result = run_synapse(
            [
                "run-update",
                "--summary",
                "Closed persistence choice",
                "--note",
                "decision: use sqlite for the local continuity cache",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        automation = payload["automation"]
        self.assertIn("decision_log", automation["automation_action_kinds"])
        self.assertIsNotNone(automation["decision_path"])
        self.assertIsNotNone(automation["decisions_ledger_path"])
        self.assertEqual(
            payload["event"]["payload"]["outputs"]["decision_path"],
            automation["decision_path"],
        )

    def test_trivial_activity_does_not_emit_duplicate_automation_side_effects(self) -> None:
        result = run_synapse(["run-update", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        automation = payload["automation"]
        self.assertFalse(automation["automation_triggered"])
        self.assertEqual(automation["automation_action_kinds"], [])
        self.assertEqual(payload["event"]["payload"]["signals"]["automation_action_kinds"], [])
        self.assertFalse(payload["event"]["payload"]["signals"]["automation_triggered"])
        self.assertEqual(payload["event"]["payload"]["outputs"]["continuity_side_effects"], [])

    def test_repeated_meaningful_activity_suppresses_duplicate_automation_noise(self) -> None:
        first = run_synapse(
            [
                "run-update",
                "--summary",
                "Risk surfaced during migration prep",
                "--note",
                "risk: staging migration may corrupt data",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run_synapse(
            [
                "run-update",
                "--summary",
                "Risk surfaced during migration prep",
                "--note",
                "risk: staging migration may corrupt data",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        payload = json.loads(second.stdout)
        self.assertFalse(payload["automation"]["automation_triggered"])
        self.assertEqual(payload["automation"]["automation_action_kinds"], [])
        self.assertEqual(payload["event"]["payload"]["outputs"]["continuity_side_effects"], [])

    def test_onboarding_mode_coding_activity_updates_draft_continuity(self) -> None:
        before = current_onboarding_session(
            subject=self.repo.name,
            data_root=self._data_root(),
            require_current=True,
        )
        assert before is not None
        result = run_synapse(
            [
                "run-update",
                "--summary",
                "Mapped auth flow",
                "--file",
                "src/main.py",
                "--note",
                "question: how should auth providers be modeled?",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        automation = payload["automation"]
        self.assertIsNotNone(automation["capture_batch_id"])
        after = current_onboarding_session(
            subject=self.repo.name,
            data_root=self._data_root(),
            require_current=True,
        )
        assert after is not None
        self.assertEqual(after["state"], before["state"])
        self.assertIn(automation["capture_batch_id"], list(after.get("unincorporated_capture_batch_ids") or []))
        self.assertIsNone(payload["sidecar"]["published_project_model_path"])

    def test_onboarding_respond_keeps_clarification_in_draft_loop(self) -> None:
        draft, questions = self._draft_payloads()
        drafted = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(drafted.returncode, 0, drafted.stdout + drafted.stderr)

        responded = run_synapse(
            [
                "onboarding-respond",
                "--text",
                "The executor should auto-capture meaningful facts, risks, and decisions while coding continues.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "repo_fact", "summary": "Automation should stay executor-parallel."}]}),
                "--question-ids-json",
                json.dumps(["Q-1"]),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(responded.returncode, 0, responded.stdout + responded.stderr)
        payload = json.loads(responded.stdout)
        self.assertEqual(payload["automation"]["automation_action_kinds"], ["continuity_refresh"])
        session = current_onboarding_session(
            subject=self.repo.name,
            data_root=self._data_root(),
            require_current=True,
        )
        assert session is not None
        self.assertEqual(session["state"], "needs_draft_revision")
        self.assertIn(payload["capture_batch_id"], list(session.get("unincorporated_capture_batch_ids") or []))

    def test_onboarding_required_survives_resumed_sessions_until_confirmation(self) -> None:
        finalized = run_synapse(
            ["run-finalize", "--status", "cancelled", "--summary", "pause onboarding", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        resumed = run_synapse(
            ["session-start", "--title", "Resume onboarding", "--session-mode", "onboarding_existing_repo", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        state = yaml.safe_load((self._data_root() / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        self.assertTrue(state["onboarding_required"])
        self.assertEqual(state["active_session_mode"], "onboarding_existing_repo")

    def test_automation_updates_remain_draft_safe_and_do_not_publish(self) -> None:
        result = run_synapse(
            [
                "run-update",
                "--summary",
                "Captured architecture risk",
                "--note",
                "risk: current wrappers may skip continuity updates",
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        live = self._data_root() / ".synapse"
        self.assertFalse((live / "PROJECT_MODEL.yaml").exists())
        self.assertFalse((live / "PROJECT_STORY.md").exists())
        self.assertTrue((live / "VISION.md").exists())
        self.assertIsNone(payload["sidecar"]["published_project_model_path"])
        self.assertFalse(payload["event"]["payload"]["truth_flags"]["canon_mutated"])
        session = current_onboarding_session(
            subject=self.repo.name,
            data_root=self._data_root(),
            require_current=True,
        )
        assert session is not None
        self.assertNotEqual(session["state"], "confirmed")

    def test_confirmed_onboarding_reenables_ready_state_postures(self) -> None:
        self._confirm_current_onboarding()
        finalized = run_synapse(
            ["run-finalize", "--status", "completed", "--summary", "onboarding confirmed", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        started = run_synapse(
            ["session-start", "--title", "Control sync", "--session-mode", "control_sync", "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        payload = json.loads(started.stdout)
        self.assertEqual(payload["run"]["session_mode"], "control_sync")


if __name__ == "__main__":
    unittest.main()

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
from synapse_runtime.repo_onboarding import (
    default_onboarding_session,
    mark_adopted_existing_repo,
    onboarding_current_path,
    save_onboarding_pointer,
    save_onboarding_session,
)
from synapse_runtime.sidecar_projection import refresh_onboarding_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
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
        policy = automation_policy_for_context(data_root=self.data_root)
        self.assertFalse(policy.onboarding_required)
        self.assertTrue(policy.onboarding_confirmed)
        self.assertTrue(policy.project_identity_ready)
        self.assertTrue(policy.continuity_ready)

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
        self.assertIn("Project model path:", confirmed_text)
        self.assertNotIn("WARNING: project model missing", confirmed_text)

    def test_automation_summary_projects_readiness_flags(self) -> None:
        mark_adopted_existing_repo(subject="Subject", data_root=self.data_root)
        refresh_onboarding_projection(subject="Subject", data_root=self.data_root)
        summary = automation_summary(self.data_root)
        self.assertTrue(summary["onboarding_required"])
        self.assertFalse(summary["project_identity_ready"])
        self.assertFalse(summary["continuity_ready"])
        self.assertEqual(summary["automation_status"], "onboarding_required")
        self.assertEqual(
            (self.data_root / ".synapse" / "ONBOARDING" / "CURRENT.yaml"),
            onboarding_current_path(self.data_root),
        )


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


if __name__ == "__main__":
    unittest.main()

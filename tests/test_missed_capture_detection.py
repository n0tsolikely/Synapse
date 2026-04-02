import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_obligations import open_obligation
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def run_engine_command(command: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


class MissedCaptureDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "MissedCaptureRepo"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
        subprocess.run(["git", "config", "user.email", "missed@example.com"], cwd=self.engine_root, check=True)
        subprocess.run(["git", "config", "user.name", "Missed Capture"], cwd=self.engine_root, check=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        write_focus_lock(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            cwt=self.engine_root,
            home=self.home,
            selection_method="test",
            source_detail="test_missed_capture_detection",
        )
        install = run_synapse(["install-hooks", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        payload = json.loads(install.stdout)
        self.assertEqual(payload["git_hooks_status"], "installed")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _open_blocker(self) -> None:
        open_obligation(
            subject=self.subject,
            data_root=self.data_root,
            recorded_at="2026-04-01T11:00:00-04:00",
            obligation_kind="plan.capture.required",
            severity="blocker",
            summary="Execution-grade planning is still missing a lawful persisted plan revision.",
            required_record_families=["plan_revision"],
            source_segment_ids=["SEGMENT-003"],
            source_semantic_event_ids=["SEMANTIC-003"],
            source_refs=[{"kind": "semantic_event", "id": "SEMANTIC-003"}],
            metadata={"topic_key": "build.plan"},
        )

    def test_pre_commit_hook_fails_closed_on_blocker_class_continuity_violation(self) -> None:
        self._open_blocker()
        hook_path = self.engine_root / ".git" / "hooks" / "pre-commit"
        result = run_engine_command([str(hook_path)], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("provenance_status: blocked", result.stdout)
        self.assertIn("blocker_continuity_obligation_count: 1", result.stdout)

    def test_pre_push_hook_fails_closed_on_blocker_class_continuity_violation(self) -> None:
        self._open_blocker()
        hook_path = self.engine_root / ".git" / "hooks" / "pre-push"
        result = run_engine_command([str(hook_path)], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("provenance_status: blocked", result.stdout)
        self.assertIn("blocker_continuity_obligation_count: 1", result.stdout)


if __name__ == "__main__":
    unittest.main()

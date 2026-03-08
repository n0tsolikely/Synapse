import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_cmd(args):
    return subprocess.run(
        SYNAPSE + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class LiveMemoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name) / "TestSubject_Data"
        self.engine_root = Path(self.tmp.name) / "TestSubject_Engine"
        self.data_root.mkdir()
        self.engine_root.mkdir()
        self.subject_args = [
            "--subject",
            "TestSubject",
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _read_active_run(self):
        path = self.data_root / ".synapse" / "ACTIVE_RUN.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _run_start(self, title="Test run", plan_item="Do the thing"):
        result = run_cmd(["run-start", "--title", title, "--plan-item", plan_item, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_bootstrap_scaffold(self):
        result = run_cmd(["live-bootstrap", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        live_root = self.data_root / ".synapse"
        for name in ["VISION.md", "STATE.yaml", "REHYDRATE.md", "ACTIVE_RUN.yaml"]:
            self.assertTrue((live_root / name).exists())
        self.assertTrue((live_root / "THREADS" / "open_questions.md").exists())

    def test_run_update_command_records(self):
        self._run_start()
        cmd = "python3 runtime/synapse.py live-bootstrap --subject TestSubject"
        result = run_cmd(["run-update", "--command", cmd, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertIn(cmd, active.get("commands", []))

    def test_finalize_completed_requires_terminal_items(self):
        self._run_start()
        result = run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot finalize as completed", result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertTrue(active.get("run_id"))

    def test_finalize_completed_when_items_done(self):
        self._run_start()
        result = run_cmd(["run-update", "--set-item-status", "ITEM-001:DONE", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runs = list((self.data_root / ".synapse" / "RUNS").glob("RUN-*.yaml"))
        self.assertTrue(runs)

    def test_log_decision_and_rehydrate(self):
        self._run_start()
        run_cmd(["run-update", "--set-item-status", "ITEM-001:DONE", *self.subject_args])
        run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        result = run_cmd(
            [
                "log-decision",
                "--title",
                "Decision A",
                "--summary",
                "Because it is necessary.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["render-rehydrate", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        content = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("Active run: none", content)
        self.assertIn("Last run:", content)
        self.assertIn("Last decision:", content)


if __name__ == "__main__":
    unittest.main()

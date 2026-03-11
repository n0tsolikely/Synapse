import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.rehydration_pack import refresh_rehydration_pack
from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        SYNAPSE + args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


class RehydrationLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "LifecycleSubject"
        self.data_root = (self.root / f"{self.subject}_Data").resolve()
        self.engine_root = (self.root / f"{self.subject}_Engine").resolve()
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        self.subject_args = [
            "--subject",
            self.subject,
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _pack_dir(self) -> Path:
        return self.data_root / "Latest Rehydration Pack"

    def _archive_dir(self) -> Path:
        return self.data_root / "Archive" / "Latest Rehydration Pack"

    def _execution_pointer_dir(self) -> Path:
        return self._pack_dir() / "Execution Pack"

    def _load_subject_state(self) -> dict:
        return yaml.safe_load((self.data_root / "SUBJECT_STATE.yaml").read_text(encoding="utf-8"))

    def test_refresh_is_idempotent_without_material_change(self) -> None:
        first = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        second = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)

        self.assertEqual(second["bootstrap_prompt_path"], first["bootstrap_prompt_path"])
        self.assertEqual(second["continuity_lock_path"], first["continuity_lock_path"])
        self.assertFalse(second["bootstrap_changed"])
        self.assertFalse(second["continuity_changed"])
        self.assertEqual(len(list(self._pack_dir().glob("*BOOTSTRAP_PROMPT*.txt"))), 1)
        self.assertEqual(len(list(self._pack_dir().glob("*CONTINUITY_LOCK*.txt"))), 1)

        latest_pack = self._load_subject_state()["pointers"]["latest_rehydration_pack"]
        self.assertEqual(
            latest_pack["bootstrap_prompt"]["path"],
            f"Latest Rehydration Pack/{Path(first['bootstrap_prompt_path']).name}",
        )
        self.assertEqual(
            latest_pack["continuity_lock"]["path"],
            f"Latest Rehydration Pack/{Path(first['continuity_lock_path']).name}",
        )

    def test_state_transition_refreshes_and_archives_superseded_artifacts(self) -> None:
        baseline = run_synapse(["render-rehydrate", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        baseline_payload = json.loads(baseline.stdout)

        decision = run_synapse(
            [
                "log-decision",
                "--title",
                "Tighten continuity lifecycle",
                "--summary",
                "Continuity truth changed after a binding decision.",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(decision.returncode, 0, decision.stdout + decision.stderr)
        decision_payload = json.loads(decision.stdout)
        continuity = decision_payload["continuity"]

        self.assertTrue(continuity["bootstrap_changed"])
        self.assertTrue(continuity["continuity_changed"])
        self.assertNotEqual(
            continuity["bootstrap_prompt_path"],
            baseline_payload["continuity"]["bootstrap_prompt_path"],
        )
        self.assertNotEqual(
            continuity["continuity_lock_path"],
            baseline_payload["continuity"]["continuity_lock_path"],
        )
        self.assertEqual(len(list(self._pack_dir().glob("*BOOTSTRAP_PROMPT*.txt"))), 1)
        self.assertEqual(len(list(self._pack_dir().glob("*CONTINUITY_LOCK*.txt"))), 1)
        archived_names = {path.name for path in self._archive_dir().iterdir()}
        self.assertIn(Path(baseline_payload["continuity"]["bootstrap_prompt_path"]).name, archived_names)
        self.assertIn(Path(baseline_payload["continuity"]["continuity_lock_path"]).name, archived_names)

    def test_execution_pack_is_included_only_when_active_source_exists(self) -> None:
        baseline = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        self.assertIsNone(baseline["execution_pack_pointer_path"])
        self.assertIsNone(baseline["execution_pack_source_path"])

        source_dir = (
            self.data_root
            / "Docs"
            / "Execution Packs"
            / "Active"
            / "EXEC_PACK__LIFECYCLE__CONTINUITY_HARDENING__2026-03-11__v1"
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "INDEX.md").write_text("# Pack Index\n\nRead this first.\n", encoding="utf-8")
        (source_dir / "RUNBOOK.md").write_text("# Runbook\n\nDo not drift.\n", encoding="utf-8")

        first = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        second = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)

        self.assertIsNotNone(first["execution_pack_pointer_path"])
        self.assertEqual(first["execution_pack_source_path"], str(source_dir.resolve()))
        self.assertTrue(first["execution_pack_changed"])
        self.assertEqual(second["execution_pack_pointer_path"], first["execution_pack_pointer_path"])
        self.assertFalse(second["execution_pack_changed"])
        self.assertEqual(len(list(self._execution_pointer_dir().glob("ACTIVE_EXECUTION_PACK*.yaml"))), 1)

        pointer_path = Path(str(first["execution_pack_pointer_path"]))
        pointer_payload = yaml.safe_load(pointer_path.read_text(encoding="utf-8"))
        self.assertEqual(pointer_payload["source_path"], "Docs/Execution Packs/Active/EXEC_PACK__LIFECYCLE__CONTINUITY_HARDENING__2026-03-11__v1")
        latest_pack = self._load_subject_state()["pointers"]["latest_rehydration_pack"]
        self.assertEqual(latest_pack["execution_pack"]["path"], f"Latest Rehydration Pack/Execution Pack/{pointer_path.name}")
        self.assertEqual(latest_pack["execution_pack"]["source_path"], pointer_payload["source_path"])

    def test_execution_pack_pointer_is_archived_when_source_is_removed(self) -> None:
        source_dir = (
            self.data_root
            / "Docs"
            / "Execution Packs"
            / "Active"
            / "EXEC_PACK__LIFECYCLE__CONTINUITY_HARDENING__2026-03-11__v1"
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "INDEX.md").write_text("# Pack Index\n", encoding="utf-8")
        first = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        self.assertIsNotNone(first["execution_pack_pointer_path"])

        shutil.rmtree(source_dir)
        second = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)

        self.assertIsNone(second["execution_pack_pointer_path"])
        self.assertIsNone(second["execution_pack_source_path"])
        self.assertTrue(second["execution_pack_changed"])
        self.assertTrue(second["execution_pack_archived_paths"])
        self.assertEqual(len(list(self._execution_pointer_dir().glob("ACTIVE_EXECUTION_PACK*.yaml"))), 0)
        latest_pack = self._load_subject_state()["pointers"]["latest_rehydration_pack"]
        self.assertNotIn("execution_pack", latest_pack)

    def test_day_rollover_refreshes_without_session_boundary(self) -> None:
        baseline = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)

        with mock.patch("synapse_runtime.rehydration_pack._today", return_value="2099-01-01"):
            rolled = refresh_rehydration_pack(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)

        self.assertTrue(rolled["bootstrap_changed"])
        self.assertTrue(rolled["continuity_changed"])
        self.assertIn("2099-01-01", Path(rolled["bootstrap_prompt_path"]).name)
        self.assertIn("2099-01-01", Path(rolled["continuity_lock_path"]).name)
        archived_names = {path.name for path in self._archive_dir().iterdir()}
        self.assertIn(Path(baseline["bootstrap_prompt_path"]).name, archived_names)
        self.assertIn(Path(baseline["continuity_lock_path"]).name, archived_names)
        self.assertEqual(len(list(self._pack_dir().glob("*BOOTSTRAP_PROMPT*.txt"))), 1)
        self.assertEqual(len(list(self._pack_dir().glob("*CONTINUITY_LOCK*.txt"))), 1)


if __name__ == "__main__":
    unittest.main()

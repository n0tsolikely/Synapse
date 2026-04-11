import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class ExecutionPackRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "ExecutionPackSubject"
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

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return run_synapse([*extra, *self.subject_args], cwd=REPO_ROOT, home=self.home)

    def _active_root(self) -> Path:
        return self.data_root / "Docs" / "Execution Packs" / "Active"

    def _archived_root(self) -> Path:
        return self.data_root / "Docs" / "Execution Packs" / "Archived"

    def _pointer_root(self) -> Path:
        return self.data_root / "Latest Rehydration Pack" / "Execution Pack"

    def _refresh_args(self) -> list[str]:
        return [
            "execution-pack",
            "refresh",
            "--objective",
            "Harden continuity execution without drift.",
            "--out-of-scope",
            "Codex freeze work.",
            "--prerequisite",
            "Read the current governing dungeon first.",
            "--boundary",
            "Do not replace the pointer owner.",
            "--verification",
            "Run execution pack lifecycle tests.",
            "--archive-condition",
            "Archive when the bounded continuity-hardening window is complete.",
            "--scope-ref",
            "Docs/Plans/Master/Dungeons/DUNGEON_06__SYNAPSE__EXECUTION_PACK_RUNTIME_AND_REHYDRATION_BINDING__PAUSED__REV5.md",
            "--pack-key",
            "CONTINUITY_HARDENING",
            "--bounded-window",
            "--drift-sensitive",
            "--json",
        ]

    def test_evaluate_blocks_when_pack_not_warranted(self) -> None:
        result = self._run(
            "execution-pack",
            "evaluate",
            "--objective",
            "Routine work that should stay in quests.",
            "--out-of-scope",
            "Architecture changes.",
            "--prerequisite",
            "Read the current task.",
            "--boundary",
            "No broad refactors.",
            "--verification",
            "Run focused tests.",
            "--archive-condition",
            "Archive when done.",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertEqual(payload["warrant_posture"], "not_warranted")
        self.assertEqual(len(list(self._active_root().glob("EXEC_PACK__*"))), 0)
        self.assertEqual(len(list(self._pointer_root().glob("ACTIVE_EXECUTION_PACK*.yaml"))), 0)

    def test_refresh_create_noop_and_archive_lifecycle(self) -> None:
        first = self._run(*self._refresh_args())
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_payload = json.loads(first.stdout)
        self.assertEqual(first_payload["decision"], "create_active_pack")
        artifact_path = Path(first_payload["artifact_path"])
        self.assertTrue(artifact_path.is_dir())
        self.assertTrue((artifact_path / "PACK.yaml").exists())
        self.assertTrue((artifact_path / "INDEX.md").exists())
        self.assertTrue((artifact_path / "RUNBOOK.md").exists())
        pack_yaml = yaml.safe_load((artifact_path / "PACK.yaml").read_text(encoding="utf-8"))
        self.assertEqual(pack_yaml["pack_key"], "CONTINUITY_HARDENING")
        self.assertEqual(pack_yaml["status"], "ACTIVE")
        self.assertTrue(first_payload["continuity"]["execution_pack_pointer_path"])

        second = self._run(*self._refresh_args())
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_payload = json.loads(second.stdout)
        self.assertEqual(second_payload["decision"], "noop")
        self.assertEqual(second_payload["state"]["active_source_path"], str(artifact_path.resolve()))

        archived = self._run("execution-pack", "archive", "--json")
        self.assertEqual(archived.returncode, 0, archived.stdout + archived.stderr)
        archived_payload = json.loads(archived.stdout)
        self.assertEqual(archived_payload["decision"], "archive_active_pack")
        self.assertTrue(archived_payload["archived_source_paths"])
        archived_path = Path(archived_payload["archived_source_paths"][0])
        self.assertTrue(archived_path.exists())
        archived_yaml = yaml.safe_load((archived_path / "PACK.yaml").read_text(encoding="utf-8"))
        self.assertEqual(archived_yaml["status"], "ARCHIVED")
        self.assertEqual(len(list(self._pointer_root().glob("ACTIVE_EXECUTION_PACK*.yaml"))), 0)

    def test_refresh_blocks_when_mvep_fields_are_missing(self) -> None:
        result = self._run(
            "execution-pack",
            "refresh",
            "--objective",
            "Harden drift-sensitive execution.",
            "--out-of-scope",
            "Codex changes.",
            "--prerequisite",
            "Read current orders.",
            "--boundary",
            "Do not move authority into the pack.",
            "--archive-condition",
            "Archive when done.",
            "--bounded-window",
            "--drift-sensitive",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("missing_mvep_fields:verification", payload["reason"])
        self.assertEqual(len(list(self._active_root().glob("EXEC_PACK__*"))), 0)

    def test_status_fails_closed_on_ambiguous_active_sources(self) -> None:
        for name in (
            "EXEC_PACK__EXECUTIONPACKSUBJECT__FIRST__2026-04-10__v1",
            "EXEC_PACK__EXECUTIONPACKSUBJECT__SECOND__2026-04-10__v1",
        ):
            pack_dir = self._active_root() / name
            pack_dir.mkdir(parents=True, exist_ok=True)
            (pack_dir / "PACK.yaml").write_text("schema_version: 1\npack_id: test\n", encoding="utf-8")
            (pack_dir / "INDEX.md").write_text("# Index\n", encoding="utf-8")
            (pack_dir / "RUNBOOK.md").write_text("# Runbook\n", encoding="utf-8")

        result = self._run("execution-pack", "status", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Ambiguous active Execution Pack state", result.stdout)


if __name__ == "__main__":
    unittest.main()

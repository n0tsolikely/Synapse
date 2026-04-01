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

from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(
    args: list[str],
    *,
    cwd: Path,
    home: Path,
    extra_env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True, input=stdin)


class RawIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "RawIngestRepo"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
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
            source_detail="test_raw_ingest",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_entries(self) -> list[dict]:
        entries: list[dict] = []
        for path in sorted((self.data_root / ".synapse" / "EVENTS").glob("*.jsonl")):
            for raw in path.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    entries.append(json.loads(raw))
        return entries

    def test_live_scaffold_creates_raw_store_families(self) -> None:
        raw_root = self.data_root / ".synapse" / "RAW"
        self.assertTrue((raw_root / "CONVERSATION_TURNS").is_dir())
        self.assertTrue((raw_root / "EXECUTION_EVENTS").is_dir())
        self.assertTrue((raw_root / "TOOL_EVENTS").is_dir())
        self.assertTrue((raw_root / "IMPORT_EVENTS").is_dir())
        self.assertTrue((raw_root / "BLOBS").is_dir())

    def test_record_raw_turn_cli_writes_user_and_executor_turns(self) -> None:
        first = run_synapse(
            ["record-raw-turn", "--role", "user", "--text", "User wants installable web app.", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_payload = json.loads(first.stdout)
        self.assertTrue(Path(first_payload["raw_turn_path"]).exists())
        self.assertTrue(Path(first_payload["text_blob"]["path"]).exists())
        self.assertEqual(first_payload["role"], "user")

        second = run_synapse(
            ["record-raw-turn", "--role", "executor", "--stdin", "--source-surface", "cli-test", "--json"],
            cwd=self.engine_root,
            home=self.home,
            stdin="Executor responded with a build approach.\n",
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_payload = json.loads(second.stdout)
        self.assertTrue(Path(second_payload["raw_turn_path"]).exists())
        self.assertEqual(second_payload["role"], "executor")
        self.assertEqual(second_payload["source_surface"], "cli-test")

        events = self._event_entries()
        self.assertEqual([entry["action_name"] for entry in events], ["record-raw-turn", "record-raw-turn"])
        self.assertEqual(events[-1]["signals"]["raw_role"], "executor")

    def test_record_raw_execution_cli_writes_tool_receipt_and_blob(self) -> None:
        result = run_synapse(
            [
                "record-raw-execution",
                "--family",
                "tool",
                "--tool-name",
                "exec_command",
                "--phase",
                "post_tool_use",
                "--status",
                "ok",
                "--changed-file",
                "src/app.ts",
                "--payload-json",
                '{"stdout":"done","exit_code":0}',
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["raw_event_path"]).exists())
        self.assertEqual(payload["family"], "TOOL_EVENTS")
        self.assertEqual(payload["changed_files"], ["src/app.ts"])
        self.assertTrue(Path(payload["payload_blob"]["path"]).exists())

        events = self._event_entries()
        self.assertEqual(events[-1]["action_name"], "record-raw-execution")
        self.assertEqual(events[-1]["signals"]["raw_family"], "TOOL_EVENTS")
        self.assertEqual(events[-1]["outputs"]["raw_event_id"], payload["raw_event_id"])

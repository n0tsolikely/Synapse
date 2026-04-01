import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


USER_PROMPT_HOOK = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_hook_user_prompt_submit.py")]
PRE_TOOL_HOOK = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_hook_pre_tool.py")]
POST_TOOL_HOOK = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_hook_post_tool.py")]
STOP_HOOK = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_hook_stop.py")]


def run_hook(command: list[str], *, cwd: Path, home: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, input=stdin)


class HookEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "HookedRepo"
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
            source_detail="test_hook_entrypoints",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _raw_files(self, family: str) -> list[Path]:
        return sorted((self.data_root / ".synapse" / "RAW" / family).glob("*/*.json"))

    def test_user_prompt_submit_hook_records_raw_turn(self) -> None:
        result = run_hook(
            USER_PROMPT_HOOK + ["--repo-root", str(self.engine_root), "--stdin"],
            cwd=self.engine_root,
            home=self.home,
            stdin="Need to support separate user accounts.\n",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = self._raw_files("CONVERSATION_TURNS")
        self.assertEqual(len(records), 1)
        payload = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["role"], "user")
        self.assertEqual(payload["source_surface"], "codex_hook_user_prompt_submit")

    def test_tool_and_stop_hooks_record_raw_execution(self) -> None:
        pre = run_hook(
            PRE_TOOL_HOOK + ["--repo-root", str(self.engine_root), "--tool-name", "exec_command", "--command-text", "pytest -q"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(pre.returncode, 0, pre.stdout + pre.stderr)

        post = run_hook(
            POST_TOOL_HOOK
            + [
                "--repo-root",
                str(self.engine_root),
                "--tool-name",
                "exec_command",
                "--status",
                "ok",
                "--payload-json",
                '{"stdout":"green","exit_code":0}',
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(post.returncode, 0, post.stdout + post.stderr)

        stop = run_hook(
            STOP_HOOK + ["--repo-root", str(self.engine_root), "--payload-json", '{"reason":"session stop"}'],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)

        tool_records = self._raw_files("TOOL_EVENTS")
        execution_records = self._raw_files("EXECUTION_EVENTS")
        self.assertEqual(len(tool_records), 2)
        self.assertEqual(len(execution_records), 1)
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in tool_records]
        self.assertEqual({payload["tool_name"] for payload in payloads}, {"exec_command"})
        self.assertEqual({payload["phase"] for payload in payloads}, {"pre_tool_use", "post_tool_use"})
        self.assertIn("ok", {payload["status"] for payload in payloads})

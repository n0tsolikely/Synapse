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

from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True, input=stdin)


def load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if text:
            items.append(json.loads(text))
    return items


class ConversationSegmentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "SegmentationRepo"
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
            source_detail="test_conversation_segmentation",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_raw_turn_creates_deterministic_conversation_segments_and_semantic_events(self) -> None:
        text = "\n\n".join(
            [
                "I want this to become an installable web app with separate user accounts.",
                "- We need a transcription flow for audio files and links.",
                "- Okay that's the plan.",
            ]
        )
        result = run_synapse(
            ["record-raw-turn", "--role", "user", "--text", text, "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        day = str(payload["recorded_at"]).split("T", 1)[0]
        segment_path = self.data_root / ".synapse" / "SEGMENTS" / "CONVERSATION" / f"{day}.jsonl"
        semantic_path = self.data_root / ".synapse" / "SEMANTIC_EVENTS" / f"{day}.jsonl"
        self.assertTrue(segment_path.exists())
        self.assertTrue(semantic_path.exists())

        segments = load_jsonl(segment_path)
        semantic_events = load_jsonl(semantic_path)
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(str(item["segment_id"]).startswith("SEGCONV-") for item in segments))
        self.assertEqual([item["segment_index"] for item in segments], [0, 1, 2])
        self.assertTrue(any(item["topic_key"] == "project.scope" for item in semantic_events))
        self.assertTrue(any(item["topic_key"] == "build.plan" for item in semantic_events))
        self.assertTrue(all(item["source_segment_ids"] for item in semantic_events))

        reducer_summary = payload["reducer"]["sidecar"]["normalized_semantic"]
        self.assertEqual(reducer_summary["conversation_segment_count"], 3)
        self.assertGreaterEqual(reducer_summary["semantic_event_count"], 2)
        self.assertGreaterEqual(reducer_summary["plan_event_count"], 1)

    def test_raw_execution_creates_execution_segment_and_failure_semantic_event(self) -> None:
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
                "failed",
                "--command-text",
                "pytest -q",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        day = str(payload["recorded_at"]).split("T", 1)[0]
        segment_path = self.data_root / ".synapse" / "SEGMENTS" / "EXECUTION" / f"{day}.jsonl"
        semantic_path = self.data_root / ".synapse" / "SEMANTIC_EVENTS" / f"{day}.jsonl"
        segments = load_jsonl(segment_path)
        semantic_events = load_jsonl(semantic_path)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["segment_family"], "execution")
        self.assertTrue(any(item["topic_key"] == "verification.command" for item in semantic_events))
        self.assertTrue(any(item["topic_key"] == "execution.failure" for item in semantic_events))


if __name__ == "__main__":
    unittest.main()

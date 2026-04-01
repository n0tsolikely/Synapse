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

from synapse_runtime.imported_continuity import parse_imported_continuity_source
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if text:
            items.append(json.loads(text))
    return items


class ImportedContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "ImportedRepo"
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
            source_detail="test_imported_continuity",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_text_note_parse_preserves_provenance_without_overclaiming(self) -> None:
        note = self.root / "notes.txt"
        note.write_text(
            "I want the site builder to become a reusable business system.\n\nWe need accounts and installable web apps.\n",
            encoding="utf-8",
        )
        payload = parse_imported_continuity_source(source_path=note)
        self.assertEqual(payload["source_kind"], "note")
        self.assertEqual(payload["parser_status"], "parsed")
        self.assertEqual(payload["confidence_band"], "medium")
        self.assertIn("reusable business system", payload["extracted_text"])

    def test_pdf_parse_degrades_honestly_when_no_extractor_exists(self) -> None:
        pdf = self.root / "brainstorm.pdf"
        pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
        payload = parse_imported_continuity_source(source_path=pdf)
        self.assertEqual(payload["source_kind"], "pdf")
        self.assertEqual(payload["parser_status"], "unsupported")
        self.assertEqual(payload["confidence_band"], "low")
        self.assertFalse(payload["extracted_text"])
        self.assertTrue(payload["warnings"])

    def test_import_continuity_cli_records_raw_import_and_normalized_semantics(self) -> None:
        note = self.root / "transcript.txt"
        note.write_text(
            "We need a build plan for installable web apps.\n\nThe system should support account access.\n",
            encoding="utf-8",
        )
        result = run_synapse(
            ["import-continuity", "--source-file", str(note), "--kind", "transcript", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["family"], "IMPORT_EVENTS")
        self.assertEqual(payload["import_envelope"]["source_kind"], "transcript")

        day = str(payload["recorded_at"]).split("T", 1)[0]
        segment_path = self.data_root / ".synapse" / "SEGMENTS" / "CONVERSATION" / f"{day}.jsonl"
        semantic_path = self.data_root / ".synapse" / "SEMANTIC_EVENTS" / f"{day}.jsonl"
        self.assertTrue(segment_path.exists())
        self.assertTrue(semantic_path.exists())
        segments = load_jsonl(segment_path)
        semantic_events = load_jsonl(semantic_path)
        self.assertTrue(any(item["source_turn_id"] == payload["import_envelope"]["import_id"] for item in segments))
        self.assertTrue(any(item["imported_limited"] for item in semantic_events))


if __name__ == "__main__":
    unittest.main()

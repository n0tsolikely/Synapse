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


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class ExternalContinuityRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "ExternalRecoveryRepo"
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
            source_detail="test_external_continuity_recovery",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_medium_confidence_import_refreshes_noncanonical_candidates(self) -> None:
        started = run_synapse(
            ["session-start", "--title", "Imported recovery", "--session-mode", "scope_planning", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)

        transcript = self.root / "imported_transcript.txt"
        transcript.write_text(
            "This project becomes a reusable installable website business system.\n\n"
            "It needs separate user accounts and installable workflows.\n",
            encoding="utf-8",
        )
        result = run_synapse(
            ["import-continuity", "--source-file", str(transcript), "--kind", "transcript", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["snapshot_candidates"]["snapshot_candidates"]["status"], "written")
        self.assertTrue(payload["snapshot_candidates"]["summary"]["current_eod_candidate_path"])
        self.assertEqual(payload["publication_candidates"]["publication_candidates"]["status"], "written")
        self.assertTrue(payload["publication_candidates"]["summary"]["current_story_candidate_path"])

    def test_unsupported_import_opens_review_debt_without_publication_candidate(self) -> None:
        pdf = self.root / "imported_brainstorm.pdf"
        pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
        result = run_synapse(
            ["import-continuity", "--source-file", str(pdf), "--kind", "pdf", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["publication_candidates"]["publication_candidates"]["status"], "noop")
        self.assertEqual(payload["publication_candidates"]["publication_candidates"]["reason"], "import_confidence_not_permitted")
        self.assertEqual(len(payload["opened_import_review_obligations"]), 1)

        provenance = run_synapse(["provenance-status", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(provenance.returncode, 0, provenance.stdout + provenance.stderr)
        summary = json.loads(provenance.stdout)
        self.assertEqual(summary["import_review_required_count"], 1)
        self.assertEqual(len(summary["recent_import_review_details"]), 1)

        doctor = run_synapse(
            ["doctor", "--governance-root", str(REPO_ROOT / "governance"), "--subject", self.subject],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("OPEN_IMPORTED_CONTINUITY_REVIEW:1", doctor.stdout + doctor.stderr)


if __name__ == "__main__":
    unittest.main()

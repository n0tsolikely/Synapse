import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

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


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Synapse Tests"], cwd=path, check=True, capture_output=True, text=True)


class AmbientRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "project-beta"
        self.home.mkdir(parents=True, exist_ok=True)
        self.repo.mkdir(parents=True, exist_ok=True)
        init_git_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_start_auto_attaches_and_initializes_repo_subject(self):
        result = run_synapse(["run-start", "--title", "Auto init", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        payload = json.loads(result.stdout)
        expected_data = (self.repo.parent / f"{self.repo.name}_Data").resolve()
        self.assertTrue(expected_data.exists())
        self.assertEqual(Path(payload["run_path"]).resolve(), expected_data / ".synapse" / "ACTIVE_RUN.yaml")
        self.assertTrue((expected_data / "SUBJECT_STATE.yaml").exists())
        self.assertTrue((expected_data / ".synapse" / "MANIFOLD.yaml").exists())

    def test_session_start_writes_session_overlay(self):
        session_id = "sess-ambient"
        result = run_synapse(
            ["session-start", "--title", "Ambient", "--session-id", session_id, "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        overlay = self.home / ".synapse" / "sessions" / session_id / "ACTIVE_RUN.json"
        self.assertTrue(overlay.exists())
        self.assertEqual(payload["run"]["session_overlay_path"], str(overlay.resolve()))
        self.assertFalse((self.home / ".synapse" / "ACTIVE_SUBJECT.json").exists())

    def test_render_rehydrate_migrates_legacy_subject_without_sidecar(self):
        subject = "LegacySubject"
        data_root = (self.root / f"{subject}_Data").resolve()
        engine_root = self.repo.resolve()
        initialize_subject_state(subject, data_root, engine_root)
        shutil.rmtree(data_root / ".synapse")

        result = run_synapse(
            [
                "render-rehydrate",
                "--subject",
                subject,
                "--data-root",
                str(data_root),
                "--engine-root",
                str(engine_root),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue((data_root / ".synapse" / "STATE.yaml").exists())
        self.assertTrue((data_root / ".synapse" / "MANIFOLD.yaml").exists())
        self.assertEqual(Path(payload["rehydrate_path"]).resolve(), data_root / ".synapse" / "REHYDRATE.md")

    def test_doctor_reports_incubation_mode_for_fog_subject(self):
        subject = "IncubatingSubject"
        data_root = (self.root / f"{subject}_Data").resolve()
        engine_root = self.repo.resolve()
        initialize_subject_state(subject, data_root, engine_root)

        engage = run_synapse(
            [
                "engage",
                "--subject",
                subject,
                "--data-root",
                str(data_root),
                "--engine-root",
                str(engine_root),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(engage.returncode, 0, engage.stdout + engage.stderr)

        doctor = run_synapse(
            [
                "doctor",
                "--governance-root",
                str(REPO_ROOT / "governance"),
                "--subject",
                subject,
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("subject_mode: incubation_mode", doctor.stdout + doctor.stderr)

    def test_doctor_fails_illegal_fog_of_war_accepted_quest_state(self):
        subject = "FogViolation"
        data_root = (self.root / f"{subject}_Data").resolve()
        engine_root = self.repo.resolve()
        initialize_subject_state(subject, data_root, engine_root)
        accepted_dir = data_root / "Quest Board" / "Accepted"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        (accepted_dir / "QUEST_001__illegal__2026-03-10.txt").write_text("illegal accepted quest\n", encoding="utf-8")

        engage = run_synapse(
            [
                "engage",
                "--subject",
                subject,
                "--data-root",
                str(data_root),
                "--engine-root",
                str(engine_root),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(engage.returncode, 0, engage.stdout + engage.stderr)

        doctor = run_synapse(
            [
                "doctor",
                "--governance-root",
                str(REPO_ROOT / "governance"),
                "--subject",
                subject,
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertNotEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("FAIL_ACCEPTED_QUESTS_PRESENT:1", doctor.stdout + doctor.stderr)
        self.assertIn("Overall Status: FAIL", doctor.stdout + doctor.stderr)

    def test_governance_map_writes_inventory_file(self):
        output = self.root / "governance_map.json"
        result = run_synapse(
            [
                "governance-map",
                "--governance-root",
                str(REPO_ROOT / "governance"),
                "--output",
                str(output),
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.exists())
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertGreater(payload["summary"]["doc_count"], 10)
        self.assertIn("authority_model", payload)
        self.assertTrue(any(item["path"].endswith("Guild_Members.txt") for item in payload["contradictions"]))


if __name__ == "__main__":
    unittest.main()

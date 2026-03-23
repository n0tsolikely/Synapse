import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
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


def write_repo_lock(repo: Path, *, subject: str, data_root: Path, engine_root: Path) -> None:
    lock = {
        "subject": subject,
        "data_root": str(data_root.resolve()),
        "engine_root": str(engine_root.resolve()),
        "selected_at": "2026-03-09T00:00:00-04:00",
        "selected_by": "Tests",
        "selection_method": "flag",
        "source_detail": "tests",
    }
    lock_path = repo / ".synapse" / "ACTIVE_SUBJECT.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class EngageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "project-alpha"
        self.home.mkdir(parents=True, exist_ok=True)
        self.repo.mkdir(parents=True, exist_ok=True)
        init_git_repo(self.repo)

        self.old_data = self.root / "OldSubject_Data"
        self.old_engine = self.root / "OldSubject_Engine"
        self.old_data.mkdir(parents=True, exist_ok=True)
        self.old_engine.mkdir(parents=True, exist_ok=True)
        write_repo_lock(
            self.repo,
            subject="OldSubject",
            data_root=self.old_data,
            engine_root=self.old_engine,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_noninteractive_engage_requires_explicit_choice_when_active_lock_exists(self):
        result = run_synapse(["engage", "--shell"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        out = result.stdout + result.stderr
        self.assertIn("--continue-active", out)
        self.assertIn("--adopt-current-repo", out)

    def test_noninteractive_engage_continue_active_explicit(self):
        result = run_synapse(["engage", "--continue-active", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["subject"], "OldSubject")
        self.assertEqual(Path(payload["engine_root"]).resolve(), self.old_engine.resolve())
        self.assertEqual(Path(payload["data_root"]).resolve(), self.old_data.resolve())

    def test_noninteractive_engage_adopt_current_repo(self):
        result = run_synapse(["engage", "--adopt-current-repo", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        expected_subject = self.repo.name
        expected_engine = self.repo.resolve()
        expected_data = (self.repo.parent / f"{self.repo.name}_Data").resolve()

        self.assertEqual(payload["subject"], expected_subject)
        self.assertEqual(Path(payload["engine_root"]).resolve(), expected_engine)
        self.assertEqual(Path(payload["data_root"]).resolve(), expected_data)
        self.assertFalse(str(payload["engine_root"]).endswith("_Engine"))

    def test_resolve_subject_flag_defaults_to_repo_roots(self):
        # Remove active lock so `--subject` path uses resolver defaults.
        (self.repo / ".synapse" / "ACTIVE_SUBJECT.json").unlink()
        result = run_synapse(["resolve-subject", "--subject", "Whatever", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        expected_engine = self.repo.resolve()
        expected_data = (self.repo.parent / "Whatever_Data").resolve()
        self.assertEqual(Path(payload["engine_root"]).resolve(), expected_engine)
        self.assertEqual(Path(payload["data_root"]).resolve(), expected_data)
        self.assertFalse(str(payload["engine_root"]).endswith("_Engine"))

    def test_adopt_current_repo_auto_bootstraps_onboarding_and_doctor_fails_until_confirmed(self):
        target_data = (self.repo.parent / f"{self.repo.name}_Data").resolve()
        if target_data.exists():
            self.fail(f"expected missing data root before adopt: {target_data}")

        result = run_synapse(["engage", "--adopt-current-repo", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertTrue(target_data.exists())
        self.assertEqual(Path(payload["data_root"]).resolve(), target_data)
        self.assertTrue((target_data / "SUBJECT_STATE.yaml").exists())
        self.assertTrue((target_data / "Buffs").is_dir())
        self.assertTrue((target_data / "Latest Rehydration Pack").is_dir())
        self.assertTrue((target_data / ".synapse" / "STATE.yaml").exists())
        self.assertIsNotNone(payload.get("onboarding_bootstrap"))
        self.assertTrue(payload.get("onboarding_required"))
        self.assertFalse(payload.get("continuity_ready"))
        self.assertEqual(payload["onboarding_bootstrap"].get("onboarding_state"), "needs_draft_submission")
        self.assertIsNotNone(payload["onboarding_bootstrap"].get("onboarding_id"))

        buff_prefix = self.repo.name.upper()
        execution_buff = target_data / "Buffs" / f"{buff_prefix}_EXECUTION_PROTOCOL.txt"
        map_buff = target_data / "Buffs" / f"{buff_prefix}_DATA_DIRECTORY_MAP.txt"
        start_buff = target_data / "Buffs" / f"{buff_prefix}_SESSION_START_CHECK.txt"
        self.assertTrue(execution_buff.exists())
        self.assertTrue(map_buff.exists())
        self.assertTrue(start_buff.exists())

        bootstrap = sorted((target_data / "Latest Rehydration Pack").glob("*BOOTSTRAP_PROMPT*"))
        continuity = sorted((target_data / "Latest Rehydration Pack").glob("*CONTINUITY_LOCK*"))
        self.assertEqual(len(bootstrap), 1)
        self.assertEqual(len(continuity), 1)

        for buff_path in (execution_buff, map_buff, start_buff):
            text = buff_path.read_text(encoding="utf-8")
            self.assertIn("Version:", text)
            self.assertIn("Last Updated:", text)

        start_text = start_buff.read_text(encoding="utf-8")
        for field in (
            "VERIFY_SMOKE_CMD:",
            "VERIFY_FULL_CMD:",
            "VERIFY_E2E_CMD:",
            "NETWORK_POLICY:",
            "EXECUTION_SURFACE:",
        ):
            self.assertIn(field, start_text)

        bootstrap_text = bootstrap[0].read_text(encoding="utf-8")
        for heading in (
            "AUTHORITY ORDER:",
            "READ FIRST:",
            "EXECUTION POSTURE:",
            "FIRST ACTION:",
        ):
            self.assertIn(heading, bootstrap_text)

        continuity_text = continuity[0].read_text(encoding="utf-8")
        for heading in (
            "WORLD STATE:",
            "CURRENT PHASE:",
            "BINDING DECISIONS (LAW):",
            "RESUME POINT:",
        ):
            self.assertIn(heading, continuity_text)

        doctor = run_synapse(
            [
                "doctor",
                "--governance-root",
                str(REPO_ROOT / "governance"),
                "--subject",
                self.repo.name,
            ],
            cwd=self.repo,
            home=self.home,
        )
        self.assertNotEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("FAIL_ONBOARDING_CONFIRMATION_REQUIRED", doctor.stdout + doctor.stderr)
        self.assertIn("published_project_model_path: MISSING", doctor.stdout + doctor.stderr)

    def test_session_lock_precedence_does_not_stomp_legacy_lock(self):
        session_id = "session-alpha"
        result = run_synapse(
            ["engage", "--adopt-current-repo", "--session-id", session_id, "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        session_payload = json.loads(result.stdout)
        self.assertEqual(session_payload["subject"], self.repo.name)

        session_resolved = run_synapse(
            ["resolve-subject", "--session-id", session_id, "--json"],
            cwd=self.repo,
            home=self.home,
        )
        self.assertEqual(session_resolved.returncode, 0, session_resolved.stdout + session_resolved.stderr)
        self.assertEqual(json.loads(session_resolved.stdout)["subject"], self.repo.name)

        legacy_resolved = run_synapse(["resolve-subject", "--json"], cwd=self.repo, home=self.home)
        self.assertEqual(legacy_resolved.returncode, 0, legacy_resolved.stdout + legacy_resolved.stderr)
        self.assertEqual(json.loads(legacy_resolved.stdout)["subject"], "OldSubject")


if __name__ == "__main__":
    unittest.main()

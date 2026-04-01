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


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(
    args: list[str],
    *,
    cwd: Path,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class SubjectRepoCodexIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.engine_root = self.root / "FrontendPlayground"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_engage_adopt_repo_does_not_install_local_codex_integration_implicitly(self) -> None:
        result = run_synapse(["engage", "--adopt-current-repo", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("subject_repo_bridges", payload)
        self.assertFalse((self.engine_root / ".codex").exists())

    def test_install_local_integration_writes_codex_assets_and_doctor_reports_hooked(self) -> None:
        engage = run_synapse(["engage", "--adopt-current-repo", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(engage.returncode, 0, engage.stdout + engage.stderr)
        engage_payload = json.loads(engage.stdout)
        data_root = Path(engage_payload["data_root"])

        install = run_synapse(["install-local-integration", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        install_payload = json.loads(install.stdout)
        self.assertEqual(install_payload["integration_posture"], "hooked")
        self.assertEqual(install_payload["integration_health"], "installed")
        self.assertTrue((self.engine_root / ".codex" / "mcp.json").exists())
        self.assertTrue((self.engine_root / ".codex" / "hooks" / "user_prompt_submit.sh").exists())
        exclude_text = (self.engine_root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.codex", exclude_text)

        doctor = run_synapse(["doctor", "--governance-root", "governance"], cwd=self.engine_root, home=self.home)
        self.assertNotEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("RAW_HEALTHY", doctor.stdout)
        self.assertIn("LOCAL_INTEGRATION:HOOKED:INSTALLED", doctor.stdout)
        self.assertIn("FAIL_ONBOARDING_CONFIRMATION_REQUIRED", doctor.stdout)
        self.assertTrue((data_root / ".synapse" / "RAW" / "CONVERSATION_TURNS").is_dir())

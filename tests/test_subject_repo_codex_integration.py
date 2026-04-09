import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.subject_bridge import (
    ensure_synapse_runtime_environment,
    inspect_local_codex_integration,
    install_local_codex_integration,
)

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
        self.assertTrue(install_payload["engine_runtime_ready"])
        self.assertEqual(
            Path(install_payload["engine_python_path"]).absolute(),
            (REPO_ROOT / ".venv" / "bin" / "python").absolute(),
        )
        self.assertTrue((self.engine_root / ".codex" / "config.toml").exists())
        self.assertTrue((self.engine_root / ".codex" / "hooks.json").exists())
        self.assertTrue((self.engine_root / ".codex" / "mcp.json").exists())
        self.assertTrue((self.engine_root / ".codex" / "hooks" / "user_prompt_submit.sh").exists())
        config_text = (self.engine_root / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("codex_hooks = true", config_text)
        self.assertIn("[mcp_servers.synapse]", config_text)
        self.assertIn(f'command = "{(REPO_ROOT / ".venv" / "bin" / "python").absolute()}"', config_text)
        self.assertIn("SYNAPSE_PYTHON =", config_text)
        mcp_config = json.loads((self.engine_root / ".codex" / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            mcp_config["mcpServers"]["synapse"]["command"],
            str((REPO_ROOT / ".venv" / "bin" / "python").absolute()),
        )
        self.assertEqual(
            mcp_config["mcpServers"]["synapse"]["env"]["SYNAPSE_PYTHON"],
            str((REPO_ROOT / ".venv" / "bin" / "python").absolute()),
        )
        hooks_config = json.loads((self.engine_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("UserPromptSubmit", hooks_config["hooks"])
        self.assertIn("Stop", hooks_config["hooks"])
        hook_text = (self.engine_root / ".codex" / "hooks" / "user_prompt_submit.sh").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_SYNAPSE_PYTHON", hook_text)
        self.assertIn(str((REPO_ROOT / ".venv" / "bin" / "python").absolute()), hook_text)
        exclude_text = (self.engine_root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.codex", exclude_text)

        doctor = run_synapse(["doctor", "--governance-root", "governance"], cwd=self.engine_root, home=self.home)
        self.assertNotEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("RAW_HEALTHY", doctor.stdout)
        self.assertIn("LOCAL_INTEGRATION:HOOKED:INSTALLED", doctor.stdout)
        self.assertIn("FAIL_ONBOARDING_CONFIRMATION_REQUIRED", doctor.stdout)
        self.assertTrue((data_root / ".synapse" / "RAW" / "CONVERSATION_TURNS").is_dir())


class SubjectBridgeRuntimeBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.synapse_root = self.root / "Synapse"
        self.synapse_root.mkdir(parents=True, exist_ok=True)
        runtime_dir = self.synapse_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "requirements.txt").write_text("mcp[cli]>=1.26.0\n", encoding="utf-8")
        (runtime_dir / "synapse_mcp").mkdir(parents=True, exist_ok=True)
        (runtime_dir / "synapse_mcp" / "server.py").write_text("print('server')\n", encoding="utf-8")
        tools_dir = runtime_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for stem in ["user_prompt_submit", "pre_tool", "post_tool", "stop"]:
            (tools_dir / f"synapse_hook_{stem}.py").write_text("print('hook')\n", encoding="utf-8")
        (self.synapse_root / "EXECUTOR.md").write_text("# executor\n", encoding="utf-8")
        self.repo_root = self.root / "Repo"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        self.data_root = self.root / "Repo_Data"
        self.data_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ensure_synapse_runtime_environment_bootstraps_missing_venv(self) -> None:
        venv_python = self.synapse_root / ".venv" / "bin" / "python"
        calls: list[list[str]] = []

        def fake_run(args, capture_output=False, text=False, check=False):
            command = [str(item) for item in args]
            calls.append(command)
            if command[:3] == [sys.executable, "-m", "venv"]:
                venv_python.parent.mkdir(parents=True, exist_ok=True)
                venv_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:3] == [str(venv_python), "-m", "pip"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:2] == [str(venv_python), "-c"]:
                probe_count = sum(1 for item in calls if item[:2] == [str(venv_python), "-c"])
                payload = {"missing": ["mcp", "pydantic"]} if probe_count == 1 else {"missing": []}
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
            raise AssertionError(f"Unexpected subprocess invocation: {command}")

        with patch("synapse_runtime.subject_bridge.subprocess.run", side_effect=fake_run):
            receipt = ensure_synapse_runtime_environment(self.synapse_root)

        self.assertEqual(receipt["engine_runtime_bootstrap_status"], "created")
        self.assertTrue(receipt["engine_runtime_ready"])
        self.assertEqual(Path(receipt["engine_python_path"]).absolute(), venv_python.absolute())
        self.assertIn([sys.executable, "-m", "venv", str((self.synapse_root / ".venv").resolve())], calls)
        self.assertIn(
            [str(venv_python), "-m", "pip", "install", "-r", str((self.synapse_root / "runtime" / "requirements.txt").resolve())],
            calls,
        )

    def test_install_local_integration_uses_bootstrapped_engine_python(self) -> None:
        engine_python = self.synapse_root / ".venv" / "bin" / "python"
        engine_python.parent.mkdir(parents=True, exist_ok=True)
        engine_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

        with patch(
            "synapse_runtime.subject_bridge.ensure_synapse_runtime_environment",
            return_value={
                "engine_python_path": str(engine_python.resolve()),
                "engine_runtime_ready": True,
                "engine_runtime_missing_modules": [],
                "engine_runtime_probe_error": None,
                "engine_runtime_bootstrap_status": "noop",
                "engine_runtime_requirements_path": str((self.synapse_root / "runtime" / "requirements.txt").resolve()),
            },
        ), patch(
            "synapse_runtime.subject_bridge.inspect_synapse_runtime_environment",
            return_value={
                "engine_python_path": str(engine_python.resolve()),
                "engine_runtime_ready": True,
                "engine_runtime_missing_modules": [],
                "engine_runtime_probe_error": None,
                "engine_runtime_bootstrap_status": "unknown",
                "engine_runtime_requirements_path": str((self.synapse_root / "runtime" / "requirements.txt").resolve()),
            },
        ):
            receipt = install_local_codex_integration(
                subject="Repo",
                repo_root=self.repo_root,
                data_root=self.data_root,
                synapse_root=self.synapse_root,
            )

        self.assertEqual(receipt["integration_health"], "installed")
        self.assertEqual(Path(receipt["engine_python_path"]).absolute(), engine_python.absolute())
        config_text = (self.repo_root / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn(f'command = "{engine_python.absolute()}"', config_text)
        mcp_config = json.loads((self.repo_root / ".codex" / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp_config["mcpServers"]["synapse"]["command"], str(engine_python.absolute()))

    def test_inspect_local_integration_reports_stale_when_engine_runtime_is_broken(self) -> None:
        engine_python = self.synapse_root / ".venv" / "bin" / "python"
        engine_python.parent.mkdir(parents=True, exist_ok=True)
        engine_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

        ready_runtime = {
            "engine_python_path": str(engine_python.absolute()),
            "engine_runtime_ready": True,
            "engine_runtime_missing_modules": [],
            "engine_runtime_probe_error": None,
            "engine_runtime_bootstrap_status": "noop",
            "engine_runtime_requirements_path": str((self.synapse_root / "runtime" / "requirements.txt").resolve()),
        }
        broken_runtime = {
            "engine_python_path": str(engine_python.absolute()),
            "engine_runtime_ready": False,
            "engine_runtime_missing_modules": ["mcp", "pydantic"],
            "engine_runtime_probe_error": None,
            "engine_runtime_bootstrap_status": "unknown",
            "engine_runtime_requirements_path": str((self.synapse_root / "runtime" / "requirements.txt").resolve()),
        }

        with patch(
            "synapse_runtime.subject_bridge.ensure_synapse_runtime_environment",
            return_value=ready_runtime,
        ), patch(
            "synapse_runtime.subject_bridge.inspect_synapse_runtime_environment",
            return_value=ready_runtime,
        ):
            install_local_codex_integration(
                subject="Repo",
                repo_root=self.repo_root,
                data_root=self.data_root,
                synapse_root=self.synapse_root,
            )

        with patch(
            "synapse_runtime.subject_bridge.inspect_synapse_runtime_environment",
            return_value=broken_runtime,
        ):
            receipt = inspect_local_codex_integration(self.repo_root, synapse_root=self.synapse_root)

        self.assertEqual(receipt["integration_posture"], "degraded")
        self.assertEqual(receipt["integration_health"], "stale")
        self.assertIn("engine_runtime", receipt["missing_assets"])
        self.assertIn("engine_runtime_modules:mcp,pydantic", receipt["missing_assets"])

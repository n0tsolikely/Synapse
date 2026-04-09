"""Repo-local bridge files and optional local integration assets."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from typing import Any

from synapse_runtime.live_memory_common import LiveMemoryError

from synapse_runtime.governance_pack import resolve_synapse_root
from synapse_runtime.kernel_types import (
    LOCAL_CODEX_INTEGRATION_VERSION,
    LocalIntegrationHealth,
    LocalIntegrationPosture,
)


BRIDGE_START = "<!-- SYNAPSE SUBJECT BRIDGE: START -->"
BRIDGE_END = "<!-- SYNAPSE SUBJECT BRIDGE: END -->"
SHIM_FILENAMES = ("AGENTS.md", "CLAUDE.md")
LOCAL_CODEX_DIRNAME = ".codex"
LOCAL_CODEX_MANIFEST = "synapse_local_integration.json"
LOCAL_CODEX_CONFIG = "config.toml"
LOCAL_CODEX_HOOKS_CONFIG = "hooks.json"
LOCAL_CODEX_MCP = "mcp.json"
LOCAL_CODEX_HOOK_DIR = "hooks"
LOCAL_CODEX_HOOKS = {
    "UserPromptSubmit": "user_prompt_submit.sh",
    "PreToolUse": "pre_tool.sh",
    "PostToolUse": "post_tool.sh",
    "Stop": "stop.sh",
}
LOCAL_CODEX_README = "README.md"
RUNTIME_REQUIRED_MODULES = ("yaml", "jsonschema", "mcp", "pydantic")


def _managed_bridge_block(*, subject: str, data_root: Path, synapse_root: Path, shim_filename: str) -> str:
    executor_path = (synapse_root / "EXECUTOR.md").resolve()
    runtime_path = (synapse_root / "runtime" / "synapse.py").resolve()
    synapse_python = _preferred_synapse_python_path(synapse_root)
    lines = [
        BRIDGE_START,
        f"# Synapse Subject Bridge ({shim_filename})",
        "",
        "This repository is governed through an external Synapse engine.",
        "",
        "Synapse root:",
        f"- `{synapse_root}`",
        "",
        "Subject repo:",
        "- this repository",
        "",
        "Subject data root:",
        f"- `{data_root}`",
        "",
        "Do not treat the absence of a local `EXECUTOR.md` as absence of Synapse governance.",
        "The canonical execution contract lives in the Synapse engine repo:",
        "",
        f"- `{executor_path}`",
        "",
        "Required behavior:",
        "1. Use the Synapse runtime for subject resolution, onboarding, continuity, doctor, and governed execution.",
        f"2. Treat this repository as the subject repo for `{subject}`.",
        "3. If continuity state already exists, reload it and continue under Synapse law rather than reinitializing from scratch.",
        "4. If the target repo or subject is genuinely ambiguous, ask the user which repo Synapse should engage against before proceeding.",
        "5. If onboarding or readiness gates fail, do not bypass them.",
        "",
        "Bootstrap:",
        f"- `{synapse_python} {runtime_path} engage --adopt-current-repo --shell`",
        f"- if `{synapse_python}` is not ready yet, bootstrap the Synapse engine env under `{_synapse_venv_dir(synapse_root)}` and install `runtime/requirements.txt` there before relying on local integration",
        "",
        f"Canonical contract: now open `{executor_path}` and follow it exactly.",
        BRIDGE_END,
        "",
    ]
    return "\n".join(lines)


def _merge_bridge(existing: str, block: str) -> tuple[str, str]:
    if not existing.strip():
        return block, "written"
    if BRIDGE_START in existing and BRIDGE_END in existing:
        start = existing.index(BRIDGE_START)
        end = existing.index(BRIDGE_END) + len(BRIDGE_END)
        before = existing[:start].rstrip()
        after = existing[end:].lstrip("\n")
        merged_parts: list[str] = []
        if before:
            merged_parts.append(before)
        merged_parts.append(block.rstrip())
        if after:
            merged_parts.append(after.rstrip())
        return "\n\n".join(part for part in merged_parts if part).rstrip() + "\n", "updated"
    return block.rstrip() + "\n\n" + existing.lstrip(), "prepended"


def _resolve_git_dir(repo_root: Path) -> Path | None:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if dot_git.is_file():
        first_line = dot_git.read_text(encoding="utf-8").splitlines()[0].strip()
        if first_line.lower().startswith("gitdir:"):
            git_dir_raw = first_line.split(":", 1)[1].strip()
            git_dir = Path(git_dir_raw)
            if not git_dir.is_absolute():
                git_dir = (repo_root / git_dir).resolve()
            return git_dir.resolve()
    return None


def _ensure_git_exclude_entries(repo_root: Path, *, entries: list[str]) -> str:
    git_dir = _resolve_git_dir(repo_root.resolve())
    if git_dir is None:
        return "no_git_dir"

    exclude_path = git_dir / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    current = {line.strip() for line in existing.splitlines() if line.strip()}
    pending = [entry for entry in entries if entry not in current]
    if not pending:
        return "noop"
    with exclude_path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        for entry in pending:
            handle.write(f"{entry}\n")
    return "updated"


def local_codex_dir(repo_root: Path) -> Path:
    return repo_root.resolve() / LOCAL_CODEX_DIRNAME


def local_codex_manifest_path(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_MANIFEST


def local_codex_mcp_config_path(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_MCP


def local_codex_config_path(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_CONFIG


def local_codex_hooks_config_path(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_HOOKS_CONFIG


def local_codex_hook_dir(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_HOOK_DIR


def _absolute_path(path: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _synapse_venv_dir(synapse_root: Path) -> Path:
    return synapse_root.resolve() / ".venv"


def _synapse_python_candidates(synapse_root: Path) -> list[Path]:
    venv_root = _synapse_venv_dir(synapse_root)
    return [
        venv_root / "bin" / "python",
        venv_root / "Scripts" / "python.exe",
    ]


def _preferred_synapse_python_path(synapse_root: Path) -> Path:
    for candidate in _synapse_python_candidates(synapse_root):
        if candidate.exists():
            return _absolute_path(candidate)
    return _synapse_python_candidates(synapse_root)[0]


def _probe_synapse_runtime_python(python_path: Path) -> dict[str, Any]:
    resolved = _absolute_path(python_path)
    if not resolved.exists():
        return {
            "python_path": str(resolved),
            "runtime_ready": False,
            "missing_modules": list(RUNTIME_REQUIRED_MODULES),
            "probe_error": "engine runtime python is missing",
        }

    probe = subprocess.run(
        [
            str(resolved),
            "-c",
            (
                "import importlib.util, json; "
                f"mods={list(RUNTIME_REQUIRED_MODULES)!r}; "
                "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
                "print(json.dumps({'missing': missing}))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        error = (probe.stderr or probe.stdout or "").strip() or f"runtime probe failed with exit code {probe.returncode}"
        return {
            "python_path": str(resolved),
            "runtime_ready": False,
            "missing_modules": list(RUNTIME_REQUIRED_MODULES),
            "probe_error": error,
        }
    try:
        payload = json.loads((probe.stdout or "").strip() or "{}")
    except Exception as exc:
        return {
            "python_path": str(resolved),
            "runtime_ready": False,
            "missing_modules": list(RUNTIME_REQUIRED_MODULES),
            "probe_error": f"invalid runtime probe payload: {exc}",
        }
    missing = [str(item).strip() for item in payload.get("missing") or [] if str(item).strip()]
    return {
        "python_path": str(resolved),
        "runtime_ready": not missing,
        "missing_modules": missing,
        "probe_error": None,
    }


def ensure_synapse_runtime_environment(synapse_root: Path) -> dict[str, Any]:
    synapse_root = synapse_root.resolve()
    python_path = _preferred_synapse_python_path(synapse_root)
    requirements_path = (synapse_root / "runtime" / "requirements.txt").resolve()
    if not requirements_path.exists():
        raise LiveMemoryError(f"Synapse runtime requirements are missing: {requirements_path}")

    bootstrap_actions: list[str] = []
    venv_root = _synapse_venv_dir(synapse_root)
    if not python_path.exists():
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_root.resolve())],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            details = (created.stderr or created.stdout or "").strip() or "venv creation failed"
            raise LiveMemoryError(f"Could not create Synapse engine venv at {venv_root}: {details}")
        bootstrap_actions.append("created_venv")
        python_path = _preferred_synapse_python_path(synapse_root)

    probe = _probe_synapse_runtime_python(python_path)
    if not probe["runtime_ready"]:
        installed = subprocess.run(
            [str(python_path), "-m", "pip", "install", "-r", str(requirements_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if installed.returncode != 0:
            details = (installed.stderr or installed.stdout or "").strip() or "pip install failed"
            raise LiveMemoryError(f"Could not install Synapse runtime requirements into {python_path}: {details}")
        bootstrap_actions.append("installed_runtime_requirements")
        probe = _probe_synapse_runtime_python(python_path)

    if not probe["runtime_ready"]:
        missing = ",".join(probe.get("missing_modules") or []) or "unknown"
        details = probe.get("probe_error") or "runtime imports remain unresolved"
        raise LiveMemoryError(
            f"Synapse engine runtime is not ready at {python_path}. Missing modules: {missing}. {details}"
        )

    if "created_venv" in bootstrap_actions:
        bootstrap_status = "created"
    elif bootstrap_actions:
        bootstrap_status = "repaired"
    else:
        bootstrap_status = "noop"
    return {
        "engine_python_path": str(_absolute_path(Path(probe["python_path"]))),
        "engine_runtime_ready": True,
        "engine_runtime_missing_modules": [],
        "engine_runtime_probe_error": None,
        "engine_runtime_bootstrap_status": bootstrap_status,
        "engine_runtime_requirements_path": str(requirements_path),
    }


def inspect_synapse_runtime_environment(synapse_root: Path) -> dict[str, Any]:
    synapse_root = synapse_root.resolve()
    python_path = _preferred_synapse_python_path(synapse_root)
    probe = _probe_synapse_runtime_python(python_path)
    return {
        "engine_python_path": str(_absolute_path(python_path)),
        "engine_runtime_ready": bool(probe.get("runtime_ready")),
        "engine_runtime_missing_modules": list(probe.get("missing_modules") or []),
        "engine_runtime_probe_error": probe.get("probe_error"),
        "engine_runtime_bootstrap_status": "unknown",
        "engine_runtime_requirements_path": str((synapse_root / "runtime" / "requirements.txt").resolve()),
    }


def _hook_wrapper_source(hook_name: str, *, synapse_root: Path, synapse_python: Path) -> str:
    runtime_hook = f"synapse_hook_{hook_name}.py"
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"',
            f'DEFAULT_SYNAPSE_ROOT="{synapse_root.resolve()}"',
            f'DEFAULT_SYNAPSE_PYTHON="{_absolute_path(synapse_python)}"',
            'export SYNAPSE_ROOT="${SYNAPSE_ROOT:-$DEFAULT_SYNAPSE_ROOT}"',
            'export SYNAPSE_PYTHON="${SYNAPSE_PYTHON:-$DEFAULT_SYNAPSE_PYTHON}"',
            'exec "$SYNAPSE_PYTHON" "$SYNAPSE_ROOT/runtime/tools/%s" --repo-root "$REPO_ROOT" "$@"' % runtime_hook,
            "",
        ]
    )


def _write_text_if_changed(path: Path, text: str, *, executable: bool = False) -> str:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        if executable:
            current_mode = path.stat().st_mode
            path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return "noop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        current_mode = path.stat().st_mode
        path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return "updated" if path.exists() else "written"


def _local_codex_manifest(subject: str, data_root: Path, *, synapse_root: Path, synapse_python: Path) -> dict[str, Any]:
    hook_entries = {
        name: {
            "script": f"{LOCAL_CODEX_DIRNAME}/{LOCAL_CODEX_HOOK_DIR}/{filename}",
            "runtime_entrypoint": str(
                (synapse_root.resolve() / "runtime" / "tools" / f"synapse_hook_{filename.replace('.sh', '.py')}").resolve()
            ),
            "command_mode": "codex_hooks_json_stdin",
        }
        for name, filename in LOCAL_CODEX_HOOKS.items()
    }
    return {
        "schema_version": LOCAL_CODEX_INTEGRATION_VERSION,
        "integration": "synapse-phase0-local-codex",
        "subject": subject,
        "data_root": str(data_root.resolve()),
        "synapse_root_env": "SYNAPSE_ROOT",
        "synapse_python_env": "SYNAPSE_PYTHON",
        "default_synapse_root": str(synapse_root.resolve()),
        "default_synapse_python": str(_absolute_path(synapse_python)),
        "codex_config_path": f"{LOCAL_CODEX_DIRNAME}/{LOCAL_CODEX_CONFIG}",
        "hooks_config_path": f"{LOCAL_CODEX_DIRNAME}/{LOCAL_CODEX_HOOKS_CONFIG}",
        "legacy_mcp_config_path": f"{LOCAL_CODEX_DIRNAME}/{LOCAL_CODEX_MCP}",
        "mcp": {
            "command": str(_absolute_path(synapse_python)),
            "args": [str((synapse_root.resolve() / "runtime" / "synapse_mcp" / "server.py").resolve())],
            "cwd": "${REPO_ROOT:-.}",
            "env": {
                "SYNAPSE_ROOT": str(synapse_root.resolve()),
                "SYNAPSE_PYTHON": str(_absolute_path(synapse_python)),
            },
        },
        "hooks": hook_entries,
    }


def _local_codex_config(*, repo_root: Path, synapse_root: Path, synapse_python: Path) -> str:
    mcp_server = (synapse_root.resolve() / "runtime" / "synapse_mcp" / "server.py").resolve()
    lines = [
        "#:schema https://developers.openai.com/codex/config-schema.json",
        "# Synapse-managed repo-local Codex integration.",
        "[features]",
        "codex_hooks = true",
        "",
        "[mcp_servers.synapse]",
        f"command = {json.dumps(str(_absolute_path(synapse_python)))}",
        f"args = [{json.dumps(str(mcp_server))}]",
        f"cwd = {json.dumps(str(repo_root.resolve()))}",
        "startup_timeout_sec = 15",
        "",
        "[mcp_servers.synapse.env]",
        f"SYNAPSE_ROOT = {json.dumps(str(synapse_root.resolve()))}",
        f"SYNAPSE_PYTHON = {json.dumps(str(_absolute_path(synapse_python)))}",
        "",
    ]
    return "\n".join(lines)


def _local_codex_hook_command(path: Path) -> str:
    return f"{shlex.quote('/bin/bash')} {shlex.quote(str(path.resolve()))} --codex-hook-json-stdin"


def _local_codex_hooks_config(*, repo_root: Path) -> dict[str, Any]:
    hook_dir = local_codex_hook_dir(repo_root)
    return {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": _local_codex_hook_command(hook_dir / LOCAL_CODEX_HOOKS["UserPromptSubmit"]),
                            "statusMessage": "Synapse raw prompt capture",
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _local_codex_hook_command(hook_dir / LOCAL_CODEX_HOOKS["PreToolUse"]),
                            "statusMessage": "Synapse pre-tool capture",
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _local_codex_hook_command(hook_dir / LOCAL_CODEX_HOOKS["PostToolUse"]),
                            "statusMessage": "Synapse post-tool capture",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": _local_codex_hook_command(hook_dir / LOCAL_CODEX_HOOKS["Stop"]),
                            "statusMessage": "Synapse close-turn validation",
                            "timeout": 30,
                        }
                    ]
                }
            ],
        }
    }


def _local_codex_readme(subject: str) -> str:
    return "\n".join(
        [
            "# Synapse Local Codex Integration",
            "",
            "This directory contains optional local integration assets for repo-level Synapse engagement.",
            "It is intentionally excluded from git because it may rely on local runtime paths and client support.",
            "The generated MCP bridge and hook wrappers pin the Synapse engine interpreter instead of relying on a random `python3` on PATH.",
            "That interpreter belongs to the Synapse engine install and stays separate from the subject repo's own app/test environment.",
            "",
            f"Subject: {subject}",
            "",
            "Contents:",
            f"- `{LOCAL_CODEX_MANIFEST}`: local integration manifest and asset receipt",
            f"- `{LOCAL_CODEX_CONFIG}`: repo-local Codex config enabling hooks and the Synapse MCP server",
            f"- `{LOCAL_CODEX_HOOKS_CONFIG}`: Codex lifecycle hook registration for raw capture and close-turn validation",
            f"- `{LOCAL_CODEX_HOOK_DIR}/`: wrapper scripts for UserPromptSubmit, PreToolUse, PostToolUse, and Stop",
            f"- `{LOCAL_CODEX_MCP}`: legacy MCP config hint kept only for backwards compatibility",
            "",
            "Current Codex clients load repo-local lifecycle hooks from `hooks.json` and project-scoped settings from `config.toml`.",
            "If the local client does not load these assets, Synapse must run in degraded posture rather than pretending hooks are active.",
            "",
        ]
    )


def install_local_codex_integration(
    *,
    subject: str,
    repo_root: Path,
    data_root: Path,
    synapse_root: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    data_root = data_root.resolve()
    synapse_root = (synapse_root or resolve_synapse_root()).resolve()
    runtime_env = ensure_synapse_runtime_environment(synapse_root)
    synapse_python = _absolute_path(Path(str(runtime_env["engine_python_path"])))
    codex_dir = local_codex_dir(repo_root)
    hook_dir = local_codex_hook_dir(repo_root)
    manifest_path = local_codex_manifest_path(repo_root)
    config_path = local_codex_config_path(repo_root)
    hooks_config_path = local_codex_hooks_config_path(repo_root)
    mcp_path = local_codex_mcp_config_path(repo_root)
    readme_path = codex_dir / LOCAL_CODEX_README

    codex_dir.mkdir(parents=True, exist_ok=True)
    hook_dir.mkdir(parents=True, exist_ok=True)

    manifest_status = _write_text_if_changed(
        manifest_path,
        json.dumps(
            _local_codex_manifest(subject, data_root, synapse_root=synapse_root, synapse_python=synapse_python),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    config_status = _write_text_if_changed(
        config_path,
        _local_codex_config(repo_root=repo_root, synapse_root=synapse_root, synapse_python=synapse_python),
    )
    hooks_config_status = _write_text_if_changed(
        hooks_config_path,
        json.dumps(_local_codex_hooks_config(repo_root=repo_root), indent=2, sort_keys=True) + "\n",
    )
    mcp_status = _write_text_if_changed(
        mcp_path,
        json.dumps(
            {
                "mcpServers": {
                    "synapse": {
                        "command": str(_absolute_path(synapse_python)),
                        "args": [str((synapse_root.resolve() / "runtime" / "synapse_mcp" / "server.py").resolve())],
                        "cwd": "${REPO_ROOT:-.}",
                        "env": {
                            "SYNAPSE_ROOT": str(synapse_root.resolve()),
                            "SYNAPSE_PYTHON": str(_absolute_path(synapse_python)),
                        },
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
    )
    readme_status = _write_text_if_changed(readme_path, _local_codex_readme(subject))
    hook_statuses: dict[str, str] = {}
    for hook_name, filename in LOCAL_CODEX_HOOKS.items():
        hook_path = hook_dir / filename
        source_name = filename.replace(".sh", "")
        hook_statuses[hook_name] = _write_text_if_changed(
            hook_path,
            _hook_wrapper_source(source_name, synapse_root=synapse_root, synapse_python=synapse_python),
            executable=True,
        )

    exclude_status = _ensure_git_exclude_entries(repo_root, entries=[f"/{LOCAL_CODEX_DIRNAME}"])
    inspection = inspect_local_codex_integration(repo_root, synapse_root=synapse_root)
    overall = LocalIntegrationHealth.NOOP.value
    if any(
        status != "noop"
        for status in [manifest_status, config_status, hooks_config_status, mcp_status, readme_status, *hook_statuses.values()]
    ):
        overall = LocalIntegrationHealth.INSTALLED.value if inspection["integration_health"] == LocalIntegrationHealth.INSTALLED.value else LocalIntegrationHealth.UPDATED.value
    inspection.update(
        {
            **runtime_env,
            "integration_status": overall,
            "manifest_write_status": manifest_status,
            "config_write_status": config_status,
            "hooks_config_write_status": hooks_config_status,
            "mcp_config_write_status": mcp_status,
            "readme_write_status": readme_status,
            "hook_write_statuses": hook_statuses,
            "exclude_status": exclude_status,
        }
    )
    return inspection


def inspect_local_codex_integration(repo_root: Path, *, synapse_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    synapse_root = (synapse_root or resolve_synapse_root()).resolve()
    codex_dir = local_codex_dir(repo_root)
    manifest_path = local_codex_manifest_path(repo_root)
    config_path = local_codex_config_path(repo_root)
    hooks_config_path = local_codex_hooks_config_path(repo_root)
    mcp_path = local_codex_mcp_config_path(repo_root)
    readme_path = codex_dir / LOCAL_CODEX_README
    hook_dir = local_codex_hook_dir(repo_root)
    runtime_env = inspect_synapse_runtime_environment(synapse_root)

    missing: list[str] = []
    hook_paths: dict[str, str] = {}
    for hook_name, filename in LOCAL_CODEX_HOOKS.items():
        path = hook_dir / filename
        hook_paths[hook_name] = str(path.resolve())
        if not path.exists():
            missing.append(f"hooks/{filename}")
    if not manifest_path.exists():
        missing.append(LOCAL_CODEX_MANIFEST)
    if not config_path.exists():
        missing.append(LOCAL_CODEX_CONFIG)
    if not hooks_config_path.exists():
        missing.append(LOCAL_CODEX_HOOKS_CONFIG)
    if not mcp_path.exists():
        pass
    if not readme_path.exists():
        missing.append(LOCAL_CODEX_README)

    integration_health = LocalIntegrationHealth.MISSING.value
    if not missing:
        integration_health = LocalIntegrationHealth.INSTALLED.value
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if int(manifest.get("schema_version") or 0) != LOCAL_CODEX_INTEGRATION_VERSION:
                integration_health = LocalIntegrationHealth.STALE.value
                missing.append("schema_version")
        except Exception:
            integration_health = LocalIntegrationHealth.STALE.value
            missing.append("manifest_parse")
    elif len(missing) < (len(LOCAL_CODEX_HOOKS) + 4):
        integration_health = LocalIntegrationHealth.PARTIAL.value
    if not runtime_env["engine_runtime_ready"]:
        if integration_health == LocalIntegrationHealth.INSTALLED.value:
            integration_health = LocalIntegrationHealth.STALE.value
        missing.append("engine_runtime")
        if runtime_env["engine_runtime_missing_modules"]:
            missing.append("engine_runtime_modules:" + ",".join(runtime_env["engine_runtime_missing_modules"]))
        elif runtime_env.get("engine_runtime_probe_error"):
            missing.append("engine_runtime_probe")

    posture = (
        LocalIntegrationPosture.HOOKED.value
        if integration_health == LocalIntegrationHealth.INSTALLED.value
        else LocalIntegrationPosture.DEGRADED.value
    )
    return {
        "integration_posture": posture,
        "integration_health": integration_health,
        "integration_dir": str(codex_dir.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "config_path": str(config_path.resolve()),
        "hooks_config_path": str(hooks_config_path.resolve()),
        "mcp_config_path": str(mcp_path.resolve()),
        "readme_path": str(readme_path.resolve()),
        "hook_paths": hook_paths,
        "missing_assets": missing,
        "legacy_mcp_config_present": mcp_path.exists(),
        "synapse_root": str(synapse_root),
        **runtime_env,
    }


def ensure_subject_repo_bridge(
    *,
    subject: str,
    repo_root: Path,
    data_root: Path,
    shim_filename: str = "AGENTS.md",
    synapse_root: Path | None = None,
) -> dict[str, str]:
    synapse_root = (synapse_root or resolve_synapse_root()).resolve()
    repo_root = repo_root.resolve()
    data_root = data_root.resolve()
    bridge_path = repo_root / shim_filename
    block = _managed_bridge_block(
        subject=subject,
        data_root=data_root,
        synapse_root=synapse_root,
        shim_filename=shim_filename,
    )
    existing = bridge_path.read_text(encoding="utf-8") if bridge_path.exists() else ""
    merged, bridge_status = _merge_bridge(existing, block)

    if bridge_path.exists() and existing == merged:
        bridge_status = "noop"
    else:
        bridge_path.write_text(merged, encoding="utf-8")

    exclude_status = ensure_subject_bridge_git_exclude(repo_root, shim_filename=shim_filename)
    return {
        "shim_filename": shim_filename,
        "bridge_path": str(bridge_path.resolve()),
        "bridge_status": bridge_status,
        "exclude_status": exclude_status,
        "synapse_root": str(synapse_root),
    }


def ensure_subject_repo_bridges(
    *,
    subject: str,
    repo_root: Path,
    data_root: Path,
    synapse_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    bridges: dict[str, dict[str, str]] = {}
    for shim_filename in SHIM_FILENAMES:
        bridges[shim_filename] = ensure_subject_repo_bridge(
            subject=subject,
            repo_root=repo_root,
            data_root=data_root,
            shim_filename=shim_filename,
            synapse_root=synapse_root,
        )
    return bridges


def ensure_subject_bridge_git_exclude(repo_root: Path, *, shim_filename: str) -> str:
    return _ensure_git_exclude_entries(repo_root.resolve(), entries=[f"/{shim_filename}"])

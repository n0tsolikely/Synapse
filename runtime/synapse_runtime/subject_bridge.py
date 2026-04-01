"""Repo-local bridge files and optional local integration assets."""

from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

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
LOCAL_CODEX_MCP = "mcp.json"
LOCAL_CODEX_HOOK_DIR = "hooks"
LOCAL_CODEX_HOOKS = {
    "UserPromptSubmit": "user_prompt_submit.sh",
    "PreToolUse": "pre_tool.sh",
    "PostToolUse": "post_tool.sh",
    "Stop": "stop.sh",
}
LOCAL_CODEX_README = "README.md"


def _managed_bridge_block(*, subject: str, data_root: Path, synapse_root: Path, shim_filename: str) -> str:
    executor_path = (synapse_root / "EXECUTOR.md").resolve()
    runtime_path = (synapse_root / "runtime" / "synapse.py").resolve()
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
        f"- `python3 {runtime_path} engage --adopt-current-repo --shell`",
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


def local_codex_hook_dir(repo_root: Path) -> Path:
    return local_codex_dir(repo_root) / LOCAL_CODEX_HOOK_DIR


def _hook_wrapper_source(hook_name: str) -> str:
    runtime_hook = f"synapse_hook_{hook_name}.py"
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"',
            'export SYNAPSE_ROOT="${SYNAPSE_ROOT:-$HOME/Synapse}"',
            'exec python3 "$SYNAPSE_ROOT/runtime/tools/%s" --repo-root "$REPO_ROOT" "$@"' % runtime_hook,
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


def _local_codex_manifest(subject: str, data_root: Path) -> dict[str, Any]:
    hook_entries = {
        name: {
            "script": f"{LOCAL_CODEX_DIRNAME}/{LOCAL_CODEX_HOOK_DIR}/{filename}",
            "runtime_entrypoint": f"${{SYNAPSE_ROOT:-$HOME/Synapse}}/runtime/tools/synapse_hook_{filename.replace('.sh', '.py')}",
        }
        for name, filename in LOCAL_CODEX_HOOKS.items()
    }
    return {
        "schema_version": LOCAL_CODEX_INTEGRATION_VERSION,
        "integration": "synapse-phase0-local-codex",
        "subject": subject,
        "data_root": str(data_root.resolve()),
        "synapse_root_env": "SYNAPSE_ROOT",
        "default_synapse_root": "$HOME/Synapse",
        "mcp": {
            "command": "python3",
            "args": ["${SYNAPSE_ROOT:-$HOME/Synapse}/runtime/synapse_mcp/server.py"],
            "cwd": "${REPO_ROOT:-.}",
            "env": {"SYNAPSE_ROOT": "${SYNAPSE_ROOT:-$HOME/Synapse}"},
        },
        "hooks": hook_entries,
    }


def _local_codex_readme(subject: str) -> str:
    return "\n".join(
        [
            "# Synapse Local Codex Integration",
            "",
            "This directory contains optional local integration assets for repo-level Synapse engagement.",
            "It is intentionally excluded from git because it may rely on local runtime paths and client support.",
            "",
            f"Subject: {subject}",
            "",
            "Contents:",
            f"- `{LOCAL_CODEX_MANIFEST}`: local MCP + hook manifest with env-based path resolution",
            f"- `{LOCAL_CODEX_MCP}`: thin MCP config hint for Synapse runtime transport",
            f"- `{LOCAL_CODEX_HOOK_DIR}/`: wrapper scripts for UserPromptSubmit, PreToolUse, PostToolUse, and Stop",
            "",
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
    codex_dir = local_codex_dir(repo_root)
    hook_dir = local_codex_hook_dir(repo_root)
    manifest_path = local_codex_manifest_path(repo_root)
    mcp_path = local_codex_mcp_config_path(repo_root)
    readme_path = codex_dir / LOCAL_CODEX_README

    codex_dir.mkdir(parents=True, exist_ok=True)
    hook_dir.mkdir(parents=True, exist_ok=True)

    manifest_status = _write_text_if_changed(
        manifest_path,
        json.dumps(_local_codex_manifest(subject, data_root), indent=2, sort_keys=True) + "\n",
    )
    mcp_status = _write_text_if_changed(
        mcp_path,
        json.dumps(
            {
                "mcpServers": {
                    "synapse": {
                        "command": "python3",
                        "args": ["${SYNAPSE_ROOT:-$HOME/Synapse}/runtime/synapse_mcp/server.py"],
                        "cwd": "${REPO_ROOT:-.}",
                        "env": {"SYNAPSE_ROOT": "${SYNAPSE_ROOT:-$HOME/Synapse}"},
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
            _hook_wrapper_source(source_name),
            executable=True,
        )

    exclude_status = _ensure_git_exclude_entries(repo_root, entries=[f"/{LOCAL_CODEX_DIRNAME}"])
    inspection = inspect_local_codex_integration(repo_root, synapse_root=synapse_root)
    overall = LocalIntegrationHealth.NOOP.value
    if any(status != "noop" for status in [manifest_status, mcp_status, readme_status, *hook_statuses.values()]):
        overall = LocalIntegrationHealth.INSTALLED.value if inspection["integration_health"] == LocalIntegrationHealth.INSTALLED.value else LocalIntegrationHealth.UPDATED.value
    inspection.update(
        {
            "integration_status": overall,
            "manifest_write_status": manifest_status,
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
    mcp_path = local_codex_mcp_config_path(repo_root)
    readme_path = codex_dir / LOCAL_CODEX_README
    hook_dir = local_codex_hook_dir(repo_root)

    missing: list[str] = []
    hook_paths: dict[str, str] = {}
    for hook_name, filename in LOCAL_CODEX_HOOKS.items():
        path = hook_dir / filename
        hook_paths[hook_name] = str(path.resolve())
        if not path.exists():
            missing.append(f"hooks/{filename}")
    if not manifest_path.exists():
        missing.append(LOCAL_CODEX_MANIFEST)
    if not mcp_path.exists():
        missing.append(LOCAL_CODEX_MCP)
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
    elif len(missing) < (len(LOCAL_CODEX_HOOKS) + 3):
        integration_health = LocalIntegrationHealth.PARTIAL.value

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
        "mcp_config_path": str(mcp_path.resolve()),
        "readme_path": str(readme_path.resolve()),
        "hook_paths": hook_paths,
        "missing_assets": missing,
        "synapse_root": str(synapse_root),
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

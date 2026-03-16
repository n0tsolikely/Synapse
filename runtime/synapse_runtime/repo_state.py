"""Repo-scoped state and elastic governance drift gating."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.governance_pack import resolve_synapse_root

VALID_MODES = {"INCUBATION", "PLAN", "EXECUTE"}
DEFAULT_MODE = "EXECUTE"
GOVERNANCE_PATHS = [
    "AGENTS.md",
    "governance",
    "runtime/synapse.py",
    "runtime/synapse_runtime",
]


def state_path(synapse_root: Path | None = None) -> Path:
    root = synapse_root or resolve_synapse_root()
    return root / ".synapse" / "STATE.json"


def _legacy_state_path(cwt: Path | None = None) -> Path:
    workspace_root = cwt or detect_canonical_working_tree()
    return workspace_root / ".synapse" / "STATE.json"


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )


def _head_commit(repo_root: Path) -> str:
    out = _run_git(repo_root, ["rev-parse", "HEAD"])
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def _governance_changes(repo_root: Path, from_commit: str) -> tuple[bool, list[str], str]:
    if not from_commit.strip():
        return True, [], "last_ack_commit is not set"

    diff = _run_git(
        repo_root,
        ["diff", "--name-only", f"{from_commit}..HEAD", "--", *GOVERNANCE_PATHS],
    )
    if diff.returncode != 0:
        return True, [], "unable to diff from last_ack_commit"

    changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    return bool(changed), changed, ""


def _session_id(env: dict[str, str] | None = None) -> str:
    env_map = env or os.environ
    val = str(env_map.get("SYNAPSE_SESSION_ID") or "").strip()
    if val:
        return val
    return f"ppid:{os.getppid()}"


def _risk_level(risk: str) -> int | None:
    match = re.match(r"^R(\d+)", str(risk or "").strip().upper())
    if not match:
        return None
    return int(match.group(1))


def load_state(*, synapse_root: Path | None = None, cwt: Path | None = None) -> dict[str, Any]:
    root = synapse_root or resolve_synapse_root()
    install_path = state_path(root)
    legacy_path = _legacy_state_path(cwt)

    state: dict[str, Any] = {
        "mode": DEFAULT_MODE,
        "last_ack_commit": "",
        "drift_warned_sessions": {},
    }

    source_path = install_path if install_path.exists() else legacy_path if legacy_path.exists() else None
    if source_path is not None:
        try:
            raw = json.loads(source_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state.update(raw)
        except Exception:
            pass

    mode = str(state.get("mode") or "").upper()
    if mode not in VALID_MODES:
        state["mode"] = DEFAULT_MODE
    else:
        state["mode"] = mode

    if not isinstance(state.get("drift_warned_sessions"), dict):
        state["drift_warned_sessions"] = {}

    state["last_ack_commit"] = str(state.get("last_ack_commit") or "").strip()
    return state


def save_state(state: dict[str, Any], *, synapse_root: Path | None = None) -> Path:
    root = synapse_root or resolve_synapse_root()
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def set_mode(mode: str, *, synapse_root: Path | None = None, cwt: Path | None = None) -> dict[str, Any]:
    normalized = str(mode or "").upper()
    if normalized not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}. Expected one of: {', '.join(sorted(VALID_MODES))}")
    root = synapse_root or resolve_synapse_root()
    state = load_state(synapse_root=root, cwt=cwt)
    state["mode"] = normalized
    save_state(state, synapse_root=root)
    return state


def acknowledge_head(*, synapse_root: Path | None = None, cwt: Path | None = None) -> dict[str, Any]:
    root = synapse_root or resolve_synapse_root()
    head = _head_commit(root)
    state = load_state(synapse_root=root, cwt=cwt)
    state["last_ack_commit"] = head
    save_state(state, synapse_root=root)
    return state


def drift_status(*, synapse_root: Path | None = None, cwt: Path | None = None) -> dict[str, Any]:
    root = synapse_root or resolve_synapse_root()
    state = load_state(synapse_root=root, cwt=cwt)
    head = _head_commit(root)
    ack = str(state.get("last_ack_commit") or "").strip()

    if not head:
        return {
            "head_commit": "",
            "last_ack_commit": ack,
            "governance_changed": False,
            "changed_files": [],
            "reason": "unable to resolve git HEAD",
            "mode": state.get("mode", DEFAULT_MODE),
            "state_path": str(state_path(root).resolve()),
        }

    changed, files, reason = _governance_changes(root, ack)
    return {
        "head_commit": head,
        "last_ack_commit": ack,
        "governance_changed": changed,
        "changed_files": files,
        "reason": reason,
        "mode": state.get("mode", DEFAULT_MODE),
        "state_path": str(state_path(root).resolve()),
    }


def drift_commands(status: dict[str, Any], *, synapse_root: Path | None = None) -> list[str]:
    root = (synapse_root or resolve_synapse_root()).resolve()
    prefix = f"git -C {shlex.quote(str(root))}"
    ack = str(status.get("last_ack_commit") or "").strip()
    if ack:
        return [
            f"{prefix} diff --name-status {ack}..HEAD -- {' '.join(GOVERNANCE_PATHS)}",
            f"{prefix} diff {ack}..HEAD -- {' '.join(GOVERNANCE_PATHS)}",
        ]
    return [
        f"{prefix} show --name-status -- {' '.join(GOVERNANCE_PATHS)}",
        f"{prefix} log --oneline -- {' '.join(GOVERNANCE_PATHS)}",
    ]


def enforce_execution_gate(
    *,
    risk: str,
    tool: str,
    action: str,
    synapse_root: Path | None = None,
    cwt: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, message). Message can be warning or block reason."""

    root = synapse_root or resolve_synapse_root()
    state = load_state(synapse_root=root, cwt=cwt)
    mode = str(state.get("mode") or DEFAULT_MODE)
    risk_norm = str(risk or "R1").upper()
    risk_level = _risk_level(risk_norm)
    high_risk = risk_level is not None and risk_level >= 2

    if mode != "EXECUTE":
        return (
            False,
            f"BLOCKED: mode={mode}. {tool}:{action} requires EXECUTE mode. "
            "Switch with `python3 runtime/synapse.py mode --set EXECUTE`.",
        )

    status = drift_status(synapse_root=root, cwt=cwt)
    if not status.get("governance_changed"):
        return True, None

    if high_risk:
        cmds = drift_commands(status, synapse_root=root)
        return (
            False,
            "BLOCKED: governance drift is unacknowledged for R2+ action.\n"
            f"tool={tool} action={action} risk={risk_norm}\n"
            f"head_commit={status.get('head_commit')}\n"
            f"last_ack_commit={status.get('last_ack_commit') or '(unset)'}\n"
            f"Inspect:\n- {cmds[0]}\n- {cmds[1]}\n"
            "Then acknowledge: python3 runtime/synapse.py acknowledge",
        )

    sid = _session_id(env)
    warned = state.get("drift_warned_sessions", {})
    head = str(status.get("head_commit") or "")
    if warned.get(sid) == head:
        return True, None

    warned[sid] = head
    if len(warned) > 32:
        keys = sorted(warned.keys())
        for key in keys[:-32]:
            warned.pop(key, None)
    state["drift_warned_sessions"] = warned
    save_state(state, synapse_root=root)

    cmds = drift_commands(status, synapse_root=root)
    return (
        True,
        "WARNING: governance drift is unacknowledged (R0/R1 continues under elastic policy).\n"
        f"head_commit={status.get('head_commit')}\n"
        f"last_ack_commit={status.get('last_ack_commit') or '(unset)'}\n"
        f"Inspect:\n- {cmds[0]}\n- {cmds[1]}\n"
        "Acknowledge: python3 runtime/synapse.py acknowledge",
    )

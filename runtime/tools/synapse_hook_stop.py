#!/usr/bin/env python3
"""Thin hook entrypoint for stop-bound raw capture."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse_hook_stop")
    parser.add_argument("--repo-root", help="Subject repo root where the hook fired")
    parser.add_argument("--payload", help="Literal payload")
    parser.add_argument("--payload-json", help="Inline JSON payload")
    parser.add_argument("--payload-file", help="Path to payload file")
    parser.add_argument(
        "--codex-hook-json-stdin",
        action="store_true",
        help="Read the current Codex hook payload JSON from stdin.",
    )
    parser.add_argument("--metadata-json", help="Optional JSON metadata object")
    parser.add_argument("--run-id", help="Optional run id")
    parser.add_argument("--session-id", help="Optional session id")
    parser.add_argument("--status", default="stop")
    parser.add_argument("--source-surface", default="codex_hook_stop")
    parser.add_argument("--phase", default="stop")
    parser.add_argument("--no-close-turn", action="store_true", help="Skip close-turn validation after raw capture")
    parser.add_argument("--warn-only", action="store_true", help="Do not fail closed when close-turn detects blocker obligations")
    return parser


def _emit_hook_output(payload: dict[str, object]) -> int:
    print(json.dumps(payload))
    return 0


def _resolve_repo_root(raw_repo_root: str | None, payload: dict[str, object] | None) -> str:
    candidate = raw_repo_root or str((payload or {}).get("cwd") or os.getcwd())
    return str(Path(candidate).expanduser().resolve())


def _hook_metadata(payload: dict[str, object]) -> str:
    metadata = {
        key: payload.get(key)
        for key in (
            "session_id",
            "turn_id",
            "transcript_path",
            "cwd",
            "hook_event_name",
            "model",
            "stop_hook_active",
        )
        if payload.get(key) is not None
    }
    return json.dumps(metadata, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hook_payload: dict[str, object] | None = None
    if args.codex_hook_json_stdin:
        try:
            hook_payload = json.load(sys.stdin)
        except json.JSONDecodeError:
            return _emit_hook_output(
                {
                    "continue": True,
                    "systemMessage": "Synapse stop hook could not parse the Codex hook payload JSON. Continuity is degraded for this turn.",
                }
            )

    repo_root = _resolve_repo_root(args.repo_root, hook_payload)
    synapse_root = Path(os.environ.get("SYNAPSE_ROOT") or (Path.home() / "Synapse")).expanduser().resolve()
    command = [
        sys.executable,
        str(synapse_root / "runtime" / "synapse.py"),
        "record-raw-execution",
        "--family",
        "execution",
        "--source-surface",
        args.source_surface,
        "--phase",
        args.phase,
        "--status",
        args.status,
    ]
    if args.payload:
        command.extend(["--payload", args.payload])
    elif args.payload_json:
        command.extend(["--payload-json", args.payload_json])
    elif hook_payload is not None:
        command.extend(["--payload-json", json.dumps(hook_payload, sort_keys=True)])
    if args.payload_file:
        command.extend(["--payload-file", args.payload_file])
    if args.metadata_json:
        command.extend(["--metadata-json", args.metadata_json])
    elif hook_payload is not None:
        command.extend(["--metadata-json", _hook_metadata(hook_payload)])
    if args.run_id:
        command.extend(["--run-id", args.run_id])
    session_id = args.session_id or str((hook_payload or {}).get("session_id") or "").strip() or None
    if session_id:
        command.extend(["--session-id", session_id])
    result = subprocess.run(command + ["--json"], cwd=repo_root, text=True, capture_output=True, check=False)
    if result.returncode != 0 or args.no_close_turn:
        if hook_payload is not None:
            if result.returncode != 0:
                return _emit_hook_output(
                    {
                        "continue": True,
                        "systemMessage": "Synapse stop hook raw capture failed; continuity is degraded for this turn.",
                    }
                )
            return _emit_hook_output({"continue": True})
        return result.returncode
    close_command = [
        sys.executable,
        str(synapse_root / "runtime" / "synapse.py"),
        "close-turn",
        "--boundary",
        "stop",
        "--json",
    ]
    if not args.warn_only:
        close_command.append("--strict")
    if session_id:
        close_command.extend(["--session-id", session_id])
    close_result = subprocess.run(close_command, cwd=repo_root, text=True, capture_output=True, check=False)
    if hook_payload is None:
        return close_result.returncode

    close_payload: dict[str, object] | None = None
    if close_result.stdout.strip():
        try:
            close_payload = json.loads(close_result.stdout)
        except json.JSONDecodeError:
            close_payload = None

    validation_status = str((close_payload or {}).get("validation_status") or "").strip().lower()
    blocker_count = int((close_payload or {}).get("blocker_continuity_obligation_count") or 0)
    if close_result.returncode == 0:
        return _emit_hook_output({"continue": True})
    if validation_status == "blocked" or blocker_count > 0:
        return _emit_hook_output(
            {
                "decision": "block",
                "reason": "Synapse close-turn validation found blocker continuity obligations. Resolve the continuity blockers before stopping.",
            }
        )
    return _emit_hook_output(
        {
            "continue": True,
            "systemMessage": "Synapse close-turn validation failed unexpectedly; continuity is degraded for this turn.",
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())

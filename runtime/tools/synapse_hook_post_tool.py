#!/usr/bin/env python3
"""Thin hook entrypoint for post-tool raw capture."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse_hook_post_tool")
    parser.add_argument("--repo-root", help="Subject repo root where the hook fired")
    parser.add_argument("--tool-name", help="Tool name if available")
    parser.add_argument("--command-text", help="Command summary if available")
    parser.add_argument("--payload", help="Literal payload")
    parser.add_argument("--payload-json", help="Inline JSON payload")
    parser.add_argument("--payload-file", help="Path to payload file")
    parser.add_argument(
        "--codex-hook-json-stdin",
        action="store_true",
        help="Read the current Codex hook payload JSON from stdin.",
    )
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file (repeatable)")
    parser.add_argument("--metadata-json", help="Optional JSON metadata object")
    parser.add_argument("--run-id", help="Optional run id")
    parser.add_argument("--session-id", help="Optional session id")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--source-surface", default="codex_hook_post_tool")
    parser.add_argument("--phase", default="post_tool_use")
    parser.add_argument("--close-turn", action="store_true", help="Run close-turn validation after raw capture")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if close-turn validation blocks")
    return parser


def _emit_hook_warning(message: str) -> int:
    print(json.dumps({"systemMessage": message}))
    return 0


def _resolve_repo_root(raw_repo_root: str | None, payload: dict[str, object] | None) -> str:
    candidate = raw_repo_root or str((payload or {}).get("cwd") or os.getcwd())
    return str(Path(candidate).expanduser().resolve())


def _hook_metadata(payload: dict[str, object]) -> str:
    metadata = {
        key: payload.get(key)
        for key in ("session_id", "turn_id", "tool_use_id", "transcript_path", "cwd", "hook_event_name", "model")
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
            return _emit_hook_warning("Synapse post-tool capture failed because the Codex hook payload was not valid JSON.")

    repo_root = _resolve_repo_root(args.repo_root, hook_payload)
    synapse_root = Path(os.environ.get("SYNAPSE_ROOT") or (Path.home() / "Synapse")).expanduser().resolve()
    command = [
        sys.executable,
        str(synapse_root / "runtime" / "synapse.py"),
        "record-raw-execution",
        "--family",
        "tool",
        "--source-surface",
        args.source_surface,
        "--phase",
        args.phase,
        "--status",
        args.status,
    ]
    tool_name = args.tool_name or str((hook_payload or {}).get("tool_name") or "").strip() or None
    command_text = args.command_text
    if hook_payload is not None and not command_text:
        tool_input = hook_payload.get("tool_input")
        if isinstance(tool_input, dict):
            command_text = str(tool_input.get("command") or "").strip() or None
    if tool_name:
        command.extend(["--tool-name", tool_name])
    if command_text:
        command.extend(["--command-text", command_text])
    if args.payload:
        command.extend(["--payload", args.payload])
    elif args.payload_json:
        command.extend(["--payload-json", args.payload_json])
    elif hook_payload is not None:
        command.extend(["--payload-json", json.dumps(hook_payload, sort_keys=True)])
    if args.payload_file:
        command.extend(["--payload-file", args.payload_file])
    for changed_file in args.changed_file:
        command.extend(["--changed-file", changed_file])
    if args.metadata_json:
        command.extend(["--metadata-json", args.metadata_json])
    elif hook_payload is not None:
        command.extend(["--metadata-json", _hook_metadata(hook_payload)])
    if args.run_id:
        command.extend(["--run-id", args.run_id])
    session_id = args.session_id or str((hook_payload or {}).get("session_id") or "").strip() or None
    if session_id:
        command.extend(["--session-id", session_id])
    result = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    if result.returncode != 0 or not args.close_turn:
        if result.returncode != 0 and hook_payload is not None:
            return _emit_hook_warning("Synapse post-tool capture failed; continuity is degraded for this command.")
        return result.returncode
    close_command = [
        sys.executable,
        str(synapse_root / "runtime" / "synapse.py"),
        "close-turn",
        "--boundary",
        "post_tool_use",
    ]
    if args.strict:
        close_command.append("--strict")
    if session_id:
        close_command.extend(["--session-id", session_id])
    close_result = subprocess.run(close_command, cwd=repo_root, text=True, capture_output=True, check=False)
    if close_result.returncode != 0 and hook_payload is not None:
        return _emit_hook_warning("Synapse close-turn validation failed after post-tool capture; continuity is degraded for this command.")
    return close_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

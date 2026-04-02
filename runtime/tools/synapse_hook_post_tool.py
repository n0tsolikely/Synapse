#!/usr/bin/env python3
"""Thin hook entrypoint for post-tool raw capture."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse_hook_post_tool")
    parser.add_argument("--repo-root", required=True, help="Subject repo root where the hook fired")
    parser.add_argument("--tool-name", help="Tool name if available")
    parser.add_argument("--command-text", help="Command summary if available")
    parser.add_argument("--payload", help="Literal payload")
    parser.add_argument("--payload-json", help="Inline JSON payload")
    parser.add_argument("--payload-file", help="Path to payload file")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    if args.tool_name:
        command.extend(["--tool-name", args.tool_name])
    if args.command_text:
        command.extend(["--command-text", args.command_text])
    if args.payload:
        command.extend(["--payload", args.payload])
    if args.payload_json:
        command.extend(["--payload-json", args.payload_json])
    if args.payload_file:
        command.extend(["--payload-file", args.payload_file])
    for changed_file in args.changed_file:
        command.extend(["--changed-file", changed_file])
    if args.metadata_json:
        command.extend(["--metadata-json", args.metadata_json])
    if args.run_id:
        command.extend(["--run-id", args.run_id])
    if args.session_id:
        command.extend(["--session-id", args.session_id])
    result = subprocess.run(command, cwd=args.repo_root, text=True, check=False)
    if result.returncode != 0 or not args.close_turn:
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
    if args.session_id:
        close_command.extend(["--session-id", args.session_id])
    close_result = subprocess.run(close_command, cwd=args.repo_root, text=True, check=False)
    return close_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

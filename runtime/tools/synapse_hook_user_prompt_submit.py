#!/usr/bin/env python3
"""Thin hook entrypoint for raw user-turn capture."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse_hook_user_prompt_submit")
    parser.add_argument("--repo-root", required=True, help="Subject repo root where the hook fired")
    parser.add_argument("--text", help="Literal prompt text")
    parser.add_argument("--text-file", help="Path to prompt text file")
    parser.add_argument("--stdin", action="store_true", help="Read prompt text from stdin")
    parser.add_argument("--source-surface", default="codex_hook_user_prompt_submit")
    parser.add_argument("--metadata-json", help="Optional JSON metadata object")
    parser.add_argument("--run-id", help="Optional run id")
    parser.add_argument("--session-id", help="Optional session id")
    parser.add_argument("--close-turn", action="store_true", help="Run close-turn validation after raw capture")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if close-turn validation blocks")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    synapse_root = Path(os.environ.get("SYNAPSE_ROOT") or (Path.home() / "Synapse")).expanduser().resolve()
    command = [
        sys.executable,
        str(synapse_root / "runtime" / "synapse.py"),
        "record-raw-turn",
        "--role",
        "user",
        "--source-surface",
        args.source_surface,
    ]
    if args.text:
        command.extend(["--text", args.text])
    if args.text_file:
        command.extend(["--text-file", args.text_file])
    if args.stdin or (not args.text and not args.text_file and not sys.stdin.isatty()):
        command.append("--stdin")
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
        "user_prompt_submit",
    ]
    if args.strict:
        close_command.append("--strict")
    if args.session_id:
        close_command.extend(["--session-id", args.session_id])
    close_result = subprocess.run(close_command, cwd=args.repo_root, text=True, check=False)
    return close_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

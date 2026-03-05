#!/usr/bin/env python3
"""Synapse runtime CLI."""

import argparse
import sys

from synapse_runtime.doctor import run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Run deterministic governance checks")
    doctor_parser.add_argument(
        "--governance-root",
        required=True,
        help="Path to governance root (relative to canonical working tree or absolute path)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args.governance_root)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

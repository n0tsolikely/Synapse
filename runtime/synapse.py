#!/usr/bin/env python3
"""Synapse runtime CLI."""

import argparse
import json
import sys
from pathlib import Path

from synapse_runtime.doctor import run_doctor
from synapse_runtime.subject_resolver import (
    SubjectResolutionError,
    detect_subject_candidates,
    resolve_subject,
    write_focus_lock,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Run deterministic governance checks")
    doctor_parser.add_argument(
        "--governance-root",
        required=True,
        help="Path to governance root (relative to canonical working tree or absolute path)",
    )
    doctor_parser.add_argument("--subject", help="Explicit subject key override (must match active lock unless switching via focus)")
    doctor_parser.add_argument("--no-subject", action="store_true", help="Skip subject resolution gates (governance-only checks)")

    focus_parser = subparsers.add_parser("focus", help="Select and persist active subject focus lock")
    focus_parser.add_argument("--subject", help="Subject key to set directly (non-interactive)")
    focus_parser.add_argument("--data-root", help="Override data root path")
    focus_parser.add_argument("--engine-root", help="Override engine root path")
    focus_parser.add_argument("--selected-by", default="Hands", help="Who made the selection (default: Hands)")
    focus_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")

    res_parser = subparsers.add_parser("resolve-subject", help=argparse.SUPPRESS)
    res_parser.add_argument("--subject", help="Explicit subject key")
    res_parser.add_argument("--data-root", help="Explicit data root")
    res_parser.add_argument("--engine-root", help="Explicit engine root")
    res_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    res_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    res_parser.add_argument("--shell", action="store_true", help="Print shell assignments")

    return parser


def _print_subject_receipt(receipt: dict) -> None:
    print("=== RESOLVED SUBJECT RECEIPT ===")
    print(f"subject: {receipt.get('subject')}")
    print(f"data_root: {receipt.get('data_root')}")
    print(f"engine_root: {receipt.get('engine_root')}")
    print(f"selected_at: {receipt.get('selected_at')}")
    print(f"selected_by: {receipt.get('selected_by')}")
    print(f"selection_method: {receipt.get('selection_method')}")
    print(f"source_detail: {receipt.get('source_detail')}")


def _prompt_focus_choice(current: dict | None, candidates: list[dict]) -> tuple[str, dict]:
    if current:
        current_sub = current["subject"]
        print("Focus menu:")
        print(f"[Enter] continue with {current_sub}")
        print("2) switch subject")
        print("3) create new subject scaffold")
        choice = input("> ").strip()
        if choice == "":
            return "continue", current
        if choice == "2":
            return "switch", {}
        if choice == "3":
            return "create", {}
        raise SubjectResolutionError("Invalid focus selection.")
    return "switch", {}


def _choose_subject_from_candidates(candidates: list[dict]) -> dict:
    if not candidates:
        raise SubjectResolutionError("No *_Data subjects found in $HOME. Use option 3 to scaffold a new subject.")
    print("Detected subjects:")
    for idx, c in enumerate(candidates, start=1):
        print(f"{idx}) {c['subject']}  [{c['data_root']}]")
    raw = input("Select subject number: ").strip()
    try:
        pos = int(raw)
    except Exception as exc:
        raise SubjectResolutionError("Invalid selection.") from exc
    if pos < 1 or pos > len(candidates):
        raise SubjectResolutionError("Selection out of range.")
    return candidates[pos - 1]


def _create_subject_scaffold(home: Path) -> dict:
    subject = input("New subject key (e.g. ProductX): ").strip()
    if not subject:
        raise SubjectResolutionError("Subject key cannot be empty.")
    data_root = (home / f"{subject}_Data").resolve()
    engine_root = (home / f"{subject}_Engine").resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    engine_root.mkdir(parents=True, exist_ok=True)
    return {"subject": subject, "data_root": str(data_root), "engine_root": str(engine_root)}


def cmd_focus(args: argparse.Namespace) -> int:
    home = Path.home().resolve()
    if args.subject:
        subject = args.subject.strip()
        data_root = str(Path(args.data_root).expanduser().resolve()) if args.data_root else str((home / f"{subject}_Data").resolve())
        engine_root = str(Path(args.engine_root).expanduser().resolve()) if args.engine_root else str((home / f"{subject}_Engine").resolve())
        receipt = write_focus_lock(
            subject=subject,
            data_root=data_root,
            engine_root=engine_root,
            selected_by=args.selected_by,
            selection_method="flag",
            write_home_lock=not args.no_home_lock,
        )
        _print_subject_receipt(receipt)
        return 0

    current = None
    try:
        current = resolve_subject(allow_switch=False)
    except SubjectResolutionError:
        current = None

    candidates = detect_subject_candidates(home)
    action, payload = _prompt_focus_choice(current, candidates)

    if action == "continue":
        selected = payload
        method = "lockfile"
    elif action == "switch":
        selected = _choose_subject_from_candidates(candidates)
        method = "interactive"
    else:
        selected = _create_subject_scaffold(home)
        method = "interactive"

    receipt = write_focus_lock(
        subject=selected["subject"],
        data_root=selected["data_root"],
        engine_root=selected["engine_root"],
        selected_by=args.selected_by,
        selection_method=method,
        write_home_lock=not args.no_home_lock,
    )
    _print_subject_receipt(receipt)
    return 0


def cmd_resolve_subject(args: argparse.Namespace) -> int:
    try:
        receipt = resolve_subject(
            subject_flag=args.subject,
            data_root_flag=args.data_root,
            engine_root_flag=args.engine_root,
            allow_switch=args.allow_switch,
        )
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.shell:
        print(f"SUBJECT={receipt['subject']}")
        print(f"DATA_ROOT={receipt['data_root']}")
        print(f"ENGINE_ROOT={receipt['engine_root']}")
        print(f"SELECTION_METHOD={receipt['selection_method']}")
        print(f"SOURCE_DETAIL={receipt['source_detail']}")
        return 0
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    _print_subject_receipt(receipt)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        if args.no_subject:
            return run_doctor(args.governance_root, None)
        try:
            receipt = resolve_subject(subject_flag=args.subject, allow_switch=False)
        except SubjectResolutionError as exc:
            print(f"FAIL: {exc}")
            print("Hint: run `python3 runtime/synapse.py focus` first.")
            return 2
        return run_doctor(args.governance_root, receipt)
    if args.command == "focus":
        return cmd_focus(args)
    if args.command == "resolve-subject":
        return cmd_resolve_subject(args)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

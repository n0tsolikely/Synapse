#!/usr/bin/env python3
"""Synapse runtime CLI."""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from synapse_runtime.doctor import run_doctor
from synapse_runtime.repo_state import (
    acknowledge_head,
    drift_commands,
    drift_status,
    enforce_execution_gate,
    load_state,
    set_mode,
    state_path,
)
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
    focus_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    focus_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")

    res_parser = subparsers.add_parser("resolve-subject", help=argparse.SUPPRESS)
    res_parser.add_argument("--subject", help="Explicit subject key")
    res_parser.add_argument("--data-root", help="Explicit data root")
    res_parser.add_argument("--engine-root", help="Explicit engine root")
    res_parser.add_argument("--allow-switch", action="store_true", help="Allow switching away from active lock")
    res_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    res_parser.add_argument("--shell", action="store_true", help="Print shell assignments")

    mode_parser = subparsers.add_parser("mode", help="Get/set elastic governance mode")
    mode_parser.add_argument("--set", dest="set_mode", choices=["INCUBATION", "PLAN", "EXECUTE"], help="Set active mode")

    drift_parser = subparsers.add_parser("drift", help="Show governance drift status and diff commands")
    drift_parser.add_argument("--json", action="store_true", help="Print JSON output")

    subparsers.add_parser("acknowledge", help="Acknowledge current governance HEAD commit")

    gate_parser = subparsers.add_parser("enforce", help=argparse.SUPPRESS)
    gate_parser.add_argument("--risk", default="R1", help="Risk class (R0/R1/R2/...)")
    gate_parser.add_argument("--tool", default="synapse", help="Tool name for receipt context")
    gate_parser.add_argument("--action", default="operation", help="Action name for receipt context")

    scaffold_parser = subparsers.add_parser(
        "scaffold-subject",
        help="Create incubation + codex scaffolding in active subject data root",
    )
    scaffold_parser.add_argument("--subject", help="Optional subject override")
    scaffold_parser.add_argument("--incubation-only", action="store_true", help="Only scaffold Incubation artifacts")
    scaffold_parser.add_argument("--codex-only", action="store_true", help="Only scaffold Codex artifacts")
    scaffold_parser.add_argument("--force", action="store_true", help="Overwrite existing template files")

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


def _print_mode_receipt(mode: str) -> None:
    print("=== MODE RECEIPT ===")
    print(f"mode: {mode}")
    print(f"state_path: {state_path().resolve()}")


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


def cmd_mode(args: argparse.Namespace) -> int:
    if args.set_mode:
        state = set_mode(args.set_mode)
        _print_mode_receipt(str(state["mode"]))
        return 0

    state = load_state()
    _print_mode_receipt(str(state["mode"]))
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    status = drift_status()
    cmds = drift_commands(status)

    if args.json:
        payload = dict(status)
        payload["commands"] = cmds
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("=== DRIFT STATUS ===")
    print(f"mode: {status.get('mode')}")
    print(f"head_commit: {status.get('head_commit') or '(unknown)'}")
    print(f"last_ack_commit: {status.get('last_ack_commit') or '(unset)'}")
    print(f"governance_changed: {'YES' if status.get('governance_changed') else 'NO'}")
    reason = str(status.get("reason") or "").strip()
    if reason:
        print(f"reason: {reason}")
    files = status.get("changed_files") or []
    if files:
        print("changed_files:")
        for item in files:
            print(f"- {item}")
    print("inspect_commands:")
    print(f"- {cmds[0]}")
    print(f"- {cmds[1]}")
    print("acknowledge_command:")
    print("- python3 runtime/synapse.py acknowledge")
    return 0


def cmd_acknowledge(_args: argparse.Namespace) -> int:
    status_before = drift_status()
    state = acknowledge_head()
    status_after = drift_status()
    print("=== ACK RECEIPT ===")
    print(f"last_ack_commit_before: {status_before.get('last_ack_commit') or '(unset)'}")
    print(f"last_ack_commit_after: {state.get('last_ack_commit') or '(unset)'}")
    print(f"governance_changed_after_ack: {'YES' if status_after.get('governance_changed') else 'NO'}")
    print(f"state_path: {state_path().resolve()}")
    return 0


def cmd_enforce(args: argparse.Namespace) -> int:
    allowed, msg = enforce_execution_gate(
        risk=args.risk,
        tool=args.tool,
        action=args.action,
    )
    if msg:
        stream = sys.stderr if msg.startswith("BLOCKED:") else sys.stdout
        print(msg, file=stream)
    return 0 if allowed else 2


def _write_file(path: Path, text: str, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return "SKIP"
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return "WRITE"


def cmd_scaffold_subject(args: argparse.Namespace) -> int:
    try:
        ctx = resolve_subject(subject_flag=args.subject, allow_switch=False)
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        print("Hint: run `python3 runtime/synapse.py focus` first.")
        return 2

    data_root = Path(str(ctx["data_root"])).expanduser().resolve()
    now_day = dt.datetime.now().astimezone().date().isoformat()

    do_incubation = not args.codex_only
    do_codex = not args.incubation_only
    if not do_incubation and not do_codex:
        do_incubation = True
        do_codex = True

    receipts: list[tuple[str, str]] = []

    if do_incubation:
        receipts.append((_write_file(data_root / "Incubation" / "SessionLogs" / ".gitkeep", "", args.force), "Incubation/SessionLogs/.gitkeep"))
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "DISCOVERIES.md",
                    """# DISCOVERIES (FINAL ONLY)

Only FINAL decisions live here.

## ACTIVE DECISIONS
- D-001 | Status: ACTIVE | Decision: <fill>
  - Rationale: <fill>
  - Constraints: <fill>
  - Effective: <YYYY-MM-DD>

## SUPERSEDED DECISIONS
- D-000 | Status: SUPERSEDED | SUPERSEDED_BY: D-001
  - Former Decision: <fill>
  - Why Superseded: <fill>

## RULES
- Do not store brainstorming chatter here.
- Store explorations in SessionLogs or Draftshots.
""",
                    args.force,
                ),
                "Incubation/DISCOVERIES.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "OPEN_QUESTIONS.md",
                    """# OPEN QUESTIONS

Only unresolved design/execution questions belong here.

## BLOCKING (INTERRUPTS USER)
- Q-001 | Status: BLOCKING | Question: <fill>
  - Why Blocking: <fill>
  - Needed Decision By: <phase>

## NONBLOCKING (DEFERRED)
- Q-002 | Status: NONBLOCKING | Question: <fill>
  - Deferred Until: <milestone>
  - Owner: <fill>

## TRIAGE RULE
- BLOCKING items interrupt.
- NONBLOCKING items are recorded and deferred.
""",
                    args.force,
                ),
                "Incubation/OPEN_QUESTIONS.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Incubation" / "DRAFTSHOT__INCUBATION__TEMPLATE.md",
                    f"""# DRAFTSHOT — INCUBATION

- Date: {now_day}
- Status: ACTIVE
- Scope: Incubation
- Subject: {ctx.get("subject")}

## Capture Rules
- Keep only decisions, constraints, definitions, non-goals, risks, dependencies, interfaces.
- Exclude chatter and non-project banter.

## Session Notes
- <fill>

## Candidate Decisions
- <fill>
""",
                    args.force,
                ),
                "Incubation/DRAFTSHOT__INCUBATION__TEMPLATE.md",
            )
        )

    if do_codex:
        receipts.append((_write_file(data_root / "Codex" / "Sections" / ".gitkeep", "", args.force), "Codex/Sections/.gitkeep"))
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "TOC_DRAFT.md",
                    """# TOC_DRAFT

Status: DRAFT

## Sections
1. <Section Name>
2. <Section Name>

## Notes
- Section PART files are allowed for large sections.
- Stitch PART files into final section file under `Codex/Sections/`.
""",
                    args.force,
                ),
                "Codex/TOC_DRAFT.md",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "ANCHOR_INDEX.yaml",
                    """schema_version: 1
updated_at: null
terms: []
invariants: []
contracts: []
section_receipts: []
""",
                    args.force,
                ),
                "Codex/ANCHOR_INDEX.yaml",
            )
        )
        receipts.append(
            (
                _write_file(
                    data_root / "Codex" / "CODEX_BUILD_STATE.yaml",
                    """schema_version: 1
overall_status: NOT_STARTED
spec_completeness_gate:
  status: NEEDS_DECISIONS
  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]
consistency_gate:
  status: NEEDS_DECISIONS
  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]
sections: []
notes:
  - "Only BLOCKING questions should interrupt."
  - "NONBLOCKING questions are deferred in Incubation/OPEN_QUESTIONS.md."
""",
                    args.force,
                ),
                "Codex/CODEX_BUILD_STATE.yaml",
            )
        )

    print("=== SUBJECT SCAFFOLD RECEIPT ===")
    _print_subject_receipt(ctx)
    print("artifacts:")
    for action, rel in receipts:
        print(f"- {action}: {data_root / rel}")
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
    if args.command == "mode":
        return cmd_mode(args)
    if args.command == "drift":
        return cmd_drift(args)
    if args.command == "acknowledge":
        return cmd_acknowledge(args)
    if args.command == "enforce":
        return cmd_enforce(args)
    if args.command == "scaffold-subject":
        return cmd_scaffold_subject(args)

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

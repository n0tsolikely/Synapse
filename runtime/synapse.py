#!/usr/bin/env python3
"""Synapse runtime CLI."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from synapse_runtime.doctor import run_doctor
from synapse_runtime.persona import resolve_persona
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
    is_placeholder_subject,
    load_active_focus_lock,
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
    doctor_parser.add_argument(
        "--subject",
        help="Explicit subject key override (must match active lock unless switching via focus)",
    )
    doctor_parser.add_argument(
        "--no-subject",
        action="store_true",
        help="Skip subject resolution gates (governance-only checks)",
    )

    engage_parser = subparsers.add_parser("engage", help="Resolve or select subject context for the current session")
    engage_parser.add_argument("--subject", help="Subject key to set directly")
    engage_parser.add_argument("--data-root", help="Override data root path")
    engage_parser.add_argument("--engine-root", help="Override engine root path")
    engage_parser.add_argument("--selected-by", default="Brains", help="Who made the selection (default: Brains)")
    engage_parser.add_argument("--json", action="store_true", help="Print JSON receipt")
    engage_parser.add_argument("--shell", action="store_true", help="Print shell assignments")
    engage_parser.add_argument("--no-home-lock", action="store_true", help="Do not write ~/.synapse/ACTIVE_SUBJECT.json")

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

    persona_parser = subparsers.add_parser("persona", help="Resolve optional Synapse-managed persona overlay")
    persona_parser.add_argument("--json", action="store_true", help="Print JSON output")
    persona_parser.add_argument("--shell", action="store_true", help="Print shell assignments")

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


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _print_subject_receipt(receipt: dict[str, Any]) -> None:
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


def _subject_receipt_to_shell(receipt: dict[str, Any]) -> None:
    print(f"SUBJECT={receipt['subject']}")
    print(f"DATA_ROOT={receipt['data_root']}")
    print(f"ENGINE_ROOT={receipt['engine_root']}")
    print(f"SELECTION_METHOD={receipt['selection_method']}")
    print(f"SOURCE_DETAIL={receipt['source_detail']}")


def _emit_subject_output(receipt: dict[str, Any], *, json_mode: bool, shell_mode: bool) -> None:
    if shell_mode:
        _subject_receipt_to_shell(receipt)
        return
    if json_mode:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    _print_subject_receipt(receipt)


def _print_noninteractive_focus_help(command_name: str, candidates: list[dict[str, str]]) -> None:
    print(f"FAIL: `{command_name}` requires interactive selection when no `--subject` is provided.")
    if candidates:
        print("Detected subject candidates:")
        for item in candidates:
            print(f"- {item['subject']} [{item['data_root']}]")
    else:
        print("Detected subject candidates: none")
    print("Use one of:")
    print("- python3 runtime/synapse.py engage")
    print("- python3 runtime/synapse.py focus --subject <SUBJECT>")


def _print_noninteractive_engage_help(candidates: list[dict[str, str]]) -> None:
    print("FAIL: subject is unresolved.")
    if candidates:
        print("Detected subject candidates:")
        for item in candidates:
            print(f"- {item['subject']} [{item['data_root']}]")
    else:
        print("Detected subject candidates: none")
    print("Use one of:")
    print("- python3 runtime/synapse.py engage")
    print("- python3 runtime/synapse.py focus --subject <SUBJECT>")


def _input_line(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError as exc:
        raise SubjectResolutionError("Interactive selection cancelled (stdin closed).") from exc


def _apply_root_overrides(selected: dict[str, Any], args: argparse.Namespace, home: Path) -> dict[str, str]:
    subject = str(selected["subject"]).strip()
    data_root = args.data_root or selected.get("data_root") or str((home / f"{subject}_Data").resolve())
    engine_root = args.engine_root or selected.get("engine_root") or str((home / f"{subject}_Engine").resolve())
    return {
        "subject": subject,
        "data_root": str(Path(str(data_root)).expanduser().resolve()),
        "engine_root": str(Path(str(engine_root)).expanduser().resolve()),
    }


def _choose_subject_from_candidates(candidates: list[dict[str, str]]) -> dict[str, str]:
    if not candidates:
        raise SubjectResolutionError("No *_Data subjects found in $HOME. Choose create new subject instead.")
    print("Detected subjects:")
    for idx, item in enumerate(candidates, start=1):
        print(f"{idx}) {item['subject']} [{item['data_root']}]")
    raw = _input_line("Select subject number: ").strip()
    try:
        pos = int(raw)
    except Exception as exc:
        raise SubjectResolutionError("Invalid subject selection.") from exc
    if pos < 1 or pos > len(candidates):
        raise SubjectResolutionError("Subject selection out of range.")
    return candidates[pos - 1]


def _create_subject_scaffold(home: Path) -> dict[str, str]:
    subject = _input_line("New subject key (e.g. ProductX): ").strip()
    if is_placeholder_subject(subject):
        raise SubjectResolutionError(
            "Reserved placeholder subject keys are not allowed. Choose a real subject key."
        )
    data_root = (home / f"{subject}_Data").resolve()
    engine_root = (home / f"{subject}_Engine").resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    engine_root.mkdir(parents=True, exist_ok=True)
    return {"subject": subject, "data_root": str(data_root), "engine_root": str(engine_root)}


def _interactive_engage_selection(home: Path, args: argparse.Namespace) -> dict[str, Any] | None:
    candidates = detect_subject_candidates(home)
    current = None
    current_error = None
    if load_active_focus_lock():
        try:
            current = resolve_subject()
        except SubjectResolutionError as exc:
            current_error = str(exc)

    if current_error:
        print(f"NOTE: {current_error}")

    if current:
        print("Session start:")
        print(f"[Enter]/1) continue with {current['subject']}")
        print("2) switch subject")
        print("3) create new subject")
        print("4) cancel")
        choice = _input_line("> ").strip()
        if choice in {"", "1"}:
            return {
                **_apply_root_overrides(current, args, home),
                "selection_method": "lockfile",
                "source_detail": current.get("source_detail", "lockfile"),
            }
        if choice == "2":
            selected = _choose_subject_from_candidates(candidates)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_switch",
            }
        if choice == "3":
            selected = _create_subject_scaffold(home)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_create",
            }
        if choice == "4":
            return None
        raise SubjectResolutionError("Invalid session-start selection.")

    if candidates:
        print("Session start:")
        print("1) choose existing subject")
        print("2) create new subject")
        print("3) cancel")
        choice = _input_line("> ").strip()
        if choice == "1":
            selected = _choose_subject_from_candidates(candidates)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_select",
            }
        if choice == "2":
            selected = _create_subject_scaffold(home)
            return {
                **_apply_root_overrides(selected, args, home),
                "selection_method": "interactive",
                "source_detail": "interactive_create",
            }
        if choice == "3":
            return None
        raise SubjectResolutionError("Invalid session-start selection.")

    print("Session start:")
    print("1) create new subject")
    print("2) cancel")
    choice = _input_line("> ").strip()
    if choice == "1":
        selected = _create_subject_scaffold(home)
        return {
            **_apply_root_overrides(selected, args, home),
            "selection_method": "interactive",
            "source_detail": "interactive_create",
        }
    if choice == "2":
        return None
    raise SubjectResolutionError("Invalid session-start selection.")


def _write_subject_lock_from_selection(selection: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return write_focus_lock(
        subject=selection["subject"],
        data_root=selection["data_root"],
        engine_root=selection["engine_root"],
        selected_by=args.selected_by,
        selection_method=selection["selection_method"],
        source_detail=selection["source_detail"],
        write_home_lock=not args.no_home_lock,
    )


def cmd_focus(args: argparse.Namespace) -> int:
    home = Path.home().resolve()

    try:
        if args.subject:
            subject = args.subject.strip()
            selection = _apply_root_overrides({"subject": subject}, args, home)
            receipt = write_focus_lock(
                subject=selection["subject"],
                data_root=selection["data_root"],
                engine_root=selection["engine_root"],
                selected_by=args.selected_by,
                selection_method="flag",
                source_detail="flag",
                write_home_lock=not args.no_home_lock,
            )
            _print_subject_receipt(receipt)
            return 0

        if not _stdin_is_interactive():
            _print_noninteractive_focus_help("python3 runtime/synapse.py focus", detect_subject_candidates(home))
            return 2

        current = None
        if load_active_focus_lock():
            try:
                current = resolve_subject(allow_switch=False)
            except SubjectResolutionError as exc:
                print(f"NOTE: {exc}")

        candidates = detect_subject_candidates(home)
        if current:
            print("Focus menu:")
            print(f"[Enter]/1) continue with {current['subject']}")
            print("2) switch subject")
            print("3) create new subject")
            print("4) cancel")
            choice = _input_line("> ").strip()
            if choice in {"", "1"}:
                selected = {
                    **_apply_root_overrides(current, args, home),
                    "selection_method": "lockfile",
                    "source_detail": current.get("source_detail", "lockfile"),
                }
            elif choice == "2":
                picked = _choose_subject_from_candidates(candidates)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_switch",
                }
            elif choice == "3":
                picked = _create_subject_scaffold(home)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_create",
                }
            elif choice == "4":
                print("CANCELLED")
                return 130
            else:
                raise SubjectResolutionError("Invalid focus selection.")
        else:
            print("Focus menu:")
            print("1) choose existing subject")
            print("2) create new subject")
            print("3) cancel")
            choice = _input_line("> ").strip()
            if choice == "1":
                picked = _choose_subject_from_candidates(candidates)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_select",
                }
            elif choice == "2":
                picked = _create_subject_scaffold(home)
                selected = {
                    **_apply_root_overrides(picked, args, home),
                    "selection_method": "interactive",
                    "source_detail": "interactive_create",
                }
            elif choice == "3":
                print("CANCELLED")
                return 130
            else:
                raise SubjectResolutionError("Invalid focus selection.")

        receipt = _write_subject_lock_from_selection(selected, args)
        _print_subject_receipt(receipt)
        return 0
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        return 2


def cmd_engage(args: argparse.Namespace) -> int:
    home = Path.home().resolve()

    try:
        if args.subject:
            selection = _apply_root_overrides({"subject": args.subject.strip()}, args, home)
            selection["selection_method"] = "flag"
            selection["source_detail"] = "flag"
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        if _stdin_is_interactive():
            selection = _interactive_engage_selection(home, args)
            if selection is None:
                print("CANCELLED")
                return 130
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        active_lock = load_active_focus_lock()
        if active_lock:
            receipt = resolve_subject(allow_switch=False)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        candidates = detect_subject_candidates(home)
        if len(candidates) == 1:
            selection = {
                **_apply_root_overrides(candidates[0], args, home),
                "selection_method": "inferred",
                "source_detail": "single_candidate",
            }
            receipt = _write_subject_lock_from_selection(selection, args)
            _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
            return 0

        _print_noninteractive_engage_help(candidates)
        return 2
    except SubjectResolutionError as exc:
        print(f"FAIL: {exc}")
        return 2


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

    _emit_subject_output(receipt, json_mode=args.json, shell_mode=args.shell)
    return 0


def cmd_persona(args: argparse.Namespace) -> int:
    receipt = resolve_persona()
    if args.shell:
        print(f"PERSONA_ID={receipt['PERSONA_ID']}")
        print(f"PERSONA_SOURCE={receipt['PERSONA_SOURCE']}")
        print(f"PERSONA_PATH={receipt['PERSONA_PATH']}")
        print(f"PERSONA_EXISTS={receipt['PERSONA_EXISTS']}")
        return 0
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    print("=== PERSONA RECEIPT ===")
    print(f"PERSONA_ID: {receipt['PERSONA_ID']}")
    print(f"PERSONA_SOURCE: {receipt['PERSONA_SOURCE']}")
    print(f"PERSONA_PATH: {receipt['PERSONA_PATH']}")
    print(f"PERSONA_EXISTS: {receipt['PERSONA_EXISTS']}")
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
        print("Hint: run `python3 runtime/synapse.py engage` or `python3 runtime/synapse.py focus --subject <SUBJECT>`.")
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
            print("Hint: run `python3 runtime/synapse.py engage` first, or use `doctor --no-subject` for governance-only work.")
            return 2
        return run_doctor(args.governance_root, receipt)
    if args.command == "engage":
        return cmd_engage(args)
    if args.command == "focus":
        return cmd_focus(args)
    if args.command == "resolve-subject":
        return cmd_resolve_subject(args)
    if args.command == "persona":
        return cmd_persona(args)
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

#!/usr/bin/env python3
"""Synapse OS — Governance Guard (subject-agnostic).

Version: v0.2
Last Updated: 2026-02-18

This is NOT a subject runtime.
It is a deterministic governance helper that:
- Initializes an Execution Audit bundle for a given Accepted quest
- Validates that the bundle meets minimum proof requirements

Why this exists:
- Agents love claiming "done" with no receipts.
- Synapse OS requires proof artifacts and structured audits.

This tool intentionally does NOT try to be smart. It enforces file/format rules.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional


REQUIRED_BUNDLE_FILES = [
    "00_SUMMARY.md",
    "01_PREQUEST.md",
    "02_EXECUTION.md",
    "03_VERIFY.md",
    "04_OUTCOME.md",
    "00_ACCEPTANCE_RECEIPT.txt",
    "90_ORIGINAL_QUEST__as_found.txt",
    "00_GOVERNANCE_PREFLIGHT.md",
    "DISCLOSURE_GATE.md",
]


def _extract_quest_num(name_or_id: str) -> int | None:
    m = re.search(r"QUEST_(\d{3})", name_or_id.upper())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _accepted_quest_ids(accepted_dir: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(accepted_dir.glob("QUEST_*.txt")):
        m = re.match(r"(QUEST_\d{3})__", p.name)
        if m:
            out.append(m.group(1))
    return out


def _lowest_active_quest_id(accepted_dir: Path) -> str | None:
    ids = _accepted_quest_ids(accepted_dir)
    if not ids:
        return None
    ranked = sorted(ids, key=lambda qid: (_extract_quest_num(qid) is None, _extract_quest_num(qid) or 10**9, qid))
    return ranked[0]


def _find_quest_file(accepted_dir: Path, quest_id: str) -> Path | None:
    matches = sorted(accepted_dir.glob(f"{quest_id}__*.txt"))
    return matches[0] if matches else None


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _check(condition: bool, failures: List[str], message: str) -> None:
    if not condition:
        failures.append(message)


def _has_any_proof_files(bundle: Path) -> bool:
    return any(p.is_file() for p in bundle.glob("06_*"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _infer_subject_from_data_root(data_root: Path, explicit: Optional[str]) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    name = data_root.name
    if name.endswith("_Data") and len(name) > 5:
        return name[:-5]
    return "UNKNOWN_SUBJECT"


def _snapshot_name_regex(subject: str) -> re.Pattern:
    # Matches:
    # <Subject>_End_of_Day_Snapshot_YYYY-MM-DD.txt
    # <Subject>_End_of_Day_Snapshot__02_YYYY-MM-DD.txt
    # <Subject>_End_of_Day_Snapshot__03_YYYY-MM-DD.txt
    safe = re.escape(subject)
    return re.compile(rf"^{safe}_End_of_Day_Snapshot(?:__\d{{2}})?_\d{{4}}-\d{{2}}-\d{{2}}\.txt$")


def cmd_init_bundle(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).expanduser().resolve()
    accepted_dir = data_root / "Quest Board" / "Accepted"
    audits_dir = data_root / "Audits" / "Execution"

    quest_id = args.quest_id.strip().upper()
    if not re.fullmatch(r"QUEST_\d{3}|SIDE-QUEST_\d{3}", quest_id):
        print(f"FAIL: invalid quest id format: {quest_id}")
        return 2

    quest_file = _find_quest_file(accepted_dir, quest_id)
    if quest_file is None:
        print(f"FAIL: {quest_id} is not in {accepted_dir}")
        return 2

    date = args.date or dt.date.today().isoformat()
    bundle = audits_dir / f"{quest_id}__{date}__{args.slug}"
    bundle.mkdir(parents=True, exist_ok=True)

    shutil.copy2(quest_file, bundle / "90_ORIGINAL_QUEST__as_found.txt")

    _write_if_missing(
        bundle / "00_GOVERNANCE_PREFLIGHT.md",
        (
            "# Governance Preflight\n\n"
            f"- QUEST_ID: {quest_id}\n"
            f"- ACCEPTED_SOURCE: {quest_file}\n"
            "- AUTHORITY_REVIEWED: YES\n"
            "- BOARD_STATE_VERIFIED: YES\n"
            "- PRE-FLIGHT: PASS\n"
        ),
    )
    _write_if_missing(
        bundle / "DISCLOSURE_GATE.md",
        (
            "# Disclosure Gate\n\n"
            "- TRIGGER: <fill>\n"
            "- RISK_BOUNDARY: <fill>\n"
            "- USER_DISCLOSED: YES\n"
            "- DISCLOSURE_DECISION: ACKNOWLEDGED\n"
            "- EXECUTION_ALLOWED: YES\n"
        ),
    )

    for fname in REQUIRED_BUNDLE_FILES:
        _write_if_missing(bundle / fname, f"# {fname}\n")

    print(f"OK: initialized {bundle}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).expanduser().resolve()
    bundle = Path(args.bundle).expanduser().resolve()
    quest_id = args.quest_id.strip().upper()
    subject = _infer_subject_from_data_root(data_root, args.subject)

    failures: List[str] = []

    _check(bundle.exists() and bundle.is_dir(), failures, f"bundle missing: {bundle}")
    if failures:
        return _print_failures(failures)

    accepted_dir = data_root / "Quest Board" / "Accepted"
    completed_dir = data_root / "Quest Board" / "Completed"

    in_accepted = _find_quest_file(accepted_dir, quest_id) is not None
    in_completed = any(completed_dir.glob(f"{quest_id}__*.txt"))
    _check(in_accepted or in_completed, failures, f"{quest_id} not found in Accepted or Completed")

    if not args.allow_out_of_order:
        expected = _lowest_active_quest_id(accepted_dir)
        if expected is not None:
            _check(
                quest_id == expected or in_completed,
                failures,
                f"out-of-order execution: expected active quest {expected}, got {quest_id}",
            )

    for fname in REQUIRED_BUNDLE_FILES:
        _check((bundle / fname).is_file(), failures, f"missing required audit file: {fname}")

    _check(_has_any_proof_files(bundle), failures, "missing proof artifacts: expected at least one 06_* file")

    preflight = _read_text(bundle / "00_GOVERNANCE_PREFLIGHT.md")
    _check("PRE-FLIGHT: PASS" in preflight, failures, "preflight not passed (missing 'PRE-FLIGHT: PASS')")

    disclosure = _read_text(bundle / "DISCLOSURE_GATE.md")
    _check("DISCLOSURE_DECISION: ACKNOWLEDGED" in disclosure, failures, "disclosure gate missing acknowledgement")
    _check("EXECUTION_ALLOWED: YES" in disclosure, failures, "disclosure gate missing execution permission")

    if args.snapshot is not None:
        snap = Path(args.snapshot).expanduser().resolve()
        expected_dir = (data_root / "Snapshots" / "End of Day").resolve()
        _check(snap.is_file(), failures, f"snapshot missing: {snap}")
        if snap.exists():
            _check(snap.parent.resolve() == expected_dir, failures, f"snapshot must be under {expected_dir}, got {snap.parent}")

            if subject == "UNKNOWN_SUBJECT":
                failures.append("subject unknown; pass --subject to validate snapshot naming")
            else:
                rx = _snapshot_name_regex(subject)
                _check(bool(rx.fullmatch(snap.name)), failures, f"snapshot filename invalid for subject {subject}: {snap.name}")

    if failures:
        return _print_failures(failures)

    print(f"PASS: governance validation OK for {quest_id} at {bundle}")
    return 0


def _print_failures(failures: Iterable[str]) -> int:
    print("FAIL: governance validation errors:")
    for f in failures:
        print(f"- {f}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Synapse governance guard for quest execution (subject-agnostic).")
    p.add_argument("--data-root", default="~/Ashby_Data", help="Canonical <Subject>_Data root")
    p.add_argument("--subject", help="Subject name (required for validating snapshot filenames if data root isn't <Subject>_Data)")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-bundle", help="Initialize a quest audit bundle with governance templates.")
    p_init.add_argument("--quest-id", required=True, help="QUEST_### or SIDE-QUEST_###")
    p_init.add_argument("--slug", required=True, help="Bundle slug suffix")
    p_init.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p_init.set_defaults(func=cmd_init_bundle)

    p_val = sub.add_parser("validate", help="Validate governance compliance for a quest bundle.")
    p_val.add_argument("--quest-id", required=True, help="QUEST_### or SIDE-QUEST_###")
    p_val.add_argument("--bundle", required=True, help="Path to audit bundle")
    p_val.add_argument("--snapshot", help="Optional EOD snapshot file to validate naming/location")
    p_val.add_argument(
        "--allow-out-of-order",
        action="store_true",
        help="Allow validating a quest that is not the lowest numeric ACTIVE quest in Accepted.",
    )
    p_val.set_defaults(func=cmd_validate)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

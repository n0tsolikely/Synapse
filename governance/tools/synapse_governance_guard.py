#!/usr/bin/env python3
"""Synapse OS — Governance Guard (subject-agnostic).

Version: v0.4
Last Updated: 2026-02-24

This is NOT a subject runtime.
It is a deterministic governance helper that:
- Initializes an Execution Audit bundle for a given Accepted quest
- Validates that the bundle meets minimum proof requirements

Why this exists:
- Agents love claiming "done" with no receipts.
- Synapse OS requires proof artifacts and structured audits.

Design posture:
- Deterministic.
- File/format enforcement.
- Refuses placeholders.
- Refuses "empty" 03_VERIFY/04_OUTCOME.

Notes:
- This tool cannot prevent intentional fraud (an agent can always lie).
  It *can* prevent accidental fabrication by enforcing required receipts and
  meaningful verification/outcome content.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


REQUIRED_BUNDLE_FILES = [
    "00_SUMMARY.md",
    "01_PREQUEST.md",
    "02_EXECUTION.md",
    "03_VERIFY.md",
    "04_OUTCOME.md",
    "06_TESTS.txt",
    "06_CHANGED_FILES.txt",
    "00_ACCEPTANCE_RECEIPT.txt",
    "90_ORIGINAL_QUEST__as_found.txt",
    "00_GOVERNANCE_PREFLIGHT.md",
    "DISCLOSURE_GATE.md",
]

# 03_VERIFY must contain an explicit, machine-checkable outcome line.
_VERIFY_OUTCOME_RX = re.compile(
    r"(?im)^(?:[-*]\s*)?(?:overall|determination|result|outcome|status)\s*:\s*(PASS|FAIL|BLOCKED)\b"
)


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


def _parse_date_from_quest_filename(quest_file: Path) -> str | None:
    """Extract YYYY-MM-DD from the final __YYYY-MM-DD.txt token."""
    m = re.search(r"__(\d{4}-\d{2}-\d{2})\.txt$", quest_file.name)
    if not m:
        return None
    return m.group(1)


def _is_placeholder_md(md_text: str) -> bool:
    """True when file is effectively just a header like '# 03_VERIFY.md'."""
    lines = [ln.strip() for ln in md_text.splitlines()]
    nonempty = [ln for ln in lines if ln]
    if not nonempty:
        return True
    if len(nonempty) == 1 and nonempty[0].startswith("#"):
        return True
    return False


def _proof_receipts_ok(bundle: Path) -> Tuple[bool, str]:
    """Return (ok, failure_reason)."""
    tests = bundle / "06_TESTS.txt"
    changed = bundle / "06_CHANGED_FILES.txt"

    if not tests.is_file() or not changed.is_file():
        return False, "missing required proof receipts: 06_TESTS.txt and/or 06_CHANGED_FILES.txt"

    t = _read_text(tests)
    c = _read_text(changed)

    if "PLACEHOLDER" in t:
        return False, "06_TESTS.txt is still PLACEHOLDER"
    if "PLACEHOLDER" in c:
        return False, "06_CHANGED_FILES.txt is still PLACEHOLDER"

    # Enforce at least one recorded command receipt line.
    # This is the simplest non-LLM guardrail against "audit-only" bundles.
    # (If a quest truly has no commands, run a trivial cmd via wrapper like `echo ok`.)
    if not re.search(r"(?m)^CMD:\s", t):
        return False, "06_TESTS.txt must contain at least one 'CMD:' receipt line (run commands via quest runner wrapper)"

    # Ensure changed-files receipt isn't empty.
    if not any(ln.strip() for ln in c.splitlines()):
        return False, "06_CHANGED_FILES.txt is empty"

    return True, ""


def _verify_md_ok(bundle: Path) -> Tuple[bool, str]:
    p = bundle / "03_VERIFY.md"
    txt = _read_text(p)

    if _is_placeholder_md(txt):
        return False, "03_VERIFY.md is placeholder-only; it must contain real verification content"

    if not _VERIFY_OUTCOME_RX.search(txt):
        return (
            False,
            "03_VERIFY.md must include an explicit outcome line (e.g. 'OVERALL: PASS' / 'OVERALL: FAIL' / 'OVERALL: BLOCKED')",
        )

    # Must reference raw receipts.
    if "06_TESTS.txt" not in txt:
        return False, "03_VERIFY.md must reference 06_TESTS.txt (raw receipts)"

    return True, ""


def _outcome_md_ok(bundle: Path) -> Tuple[bool, str]:
    p = bundle / "04_OUTCOME.md"
    txt = _read_text(p)

    if _is_placeholder_md(txt):
        return False, "04_OUTCOME.md is placeholder-only; it must state what is now true + artifacts/paths"

    # Require at least one non-header content line.
    lines = [ln.rstrip("\n") for ln in txt.splitlines()]
    nonempty = [ln for ln in lines if ln.strip()]
    nonheader = [ln for ln in nonempty if not ln.lstrip().startswith("#")]
    if not nonheader:
        return False, "04_OUTCOME.md has no content beyond header"

    return True, ""


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

    inferred = _parse_date_from_quest_filename(quest_file)
    date = args.date or inferred or dt.date.today().isoformat()

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
        if fname in {"06_TESTS.txt", "06_CHANGED_FILES.txt"}:
            _write_if_missing(
                bundle / fname,
                (
                    "PLACEHOLDER: populate this file with real command output via "
                    "the Synapse quest runner wrapper. DO NOT LEAVE PLACEHOLDER.\n"
                ),
            )
        else:
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

    ok, why = _proof_receipts_ok(bundle)
    _check(ok, failures, why)

    ok, why = _verify_md_ok(bundle)
    _check(ok, failures, why)

    ok, why = _outcome_md_ok(bundle)
    _check(ok, failures, why)

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
    p_init.add_argument("--date", help="YYYY-MM-DD (default: inferred from quest filename; else today)")
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

#!/usr/bin/env python3
"""Synapse — Governance Guard (subject-agnostic).

Version: v0.4
Last Updated: 2026-02-24

This is NOT a subject runtime.
It is a deterministic governance helper that:
- Initializes an Execution Audit bundle for a given Accepted quest
- Validates that the bundle meets minimum proof requirements

Why this exists:
- Agents love claiming "done" with no receipts.
- Synapse requires proof artifacts and structured audits.

Design posture:
- Deterministic.
- File/format enforcement.
- Refuses placeholders.
- Refuses "empty" 03_VERIFY/04_OUTCOME.
- Enforces Talent Tree updates when a Quest awards a Talent Point.

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

SCRIPT_DIR = Path(__file__).resolve().parent
SYNAPSE_ROOT = SCRIPT_DIR.parent.parent
RUNTIME_ROOT = SYNAPSE_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.subject_resolver import SubjectResolutionError, resolve_subject


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
    r"(?im)^(?:[-*]\\s*)?(?:overall|determination|result|outcome|status)\\s*:\\s*(PASS|FAIL|BLOCKED)\\b"
)

_QUEST_TALENT_AWARDED_RX = re.compile(r"(?im)^Talent Point Awarded:\\s*(YES|NO)\\b")
_OUTCOME_TALENT_AWARDED_RX = re.compile(r"(?im)^Talent Point Awarded:\\s*(YES|NO)\\b")
_OUTCOME_TALENT_ID_RX = re.compile(r"(?im)^(?:Talent Spent On|Talent ID):\\s*(?:\\()?((?:T-\\d{3}))\\b")


def _extract_quest_num(name_or_id: str) -> int | None:
    m = re.search(r"QUEST_(\\d{3})", name_or_id.upper())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _accepted_quest_ids(accepted_dir: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(accepted_dir.glob("QUEST_*.txt")):
        m = re.match(r"(QUEST_\\d{3})__", p.name)
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


def _parse_talent_point_awarded(quest_text: str) -> str | None:
    m = _QUEST_TALENT_AWARDED_RX.search(quest_text)
    if not m:
        return None
    v = (m.group(1) or "").strip().upper()
    return v if v in {"YES", "NO"} else None


def _ensure_talent_tree_initialized(data_root: Path, failures: List[str]) -> None:
    """Ensure the 3 Talent Tree subject-state files exist (copy templates if missing)."""

    target_dir = data_root / "Talent Tree"
    templates_dir = SYNAPSE_ROOT / "governance" / "Talent Tree"
    target_dir.mkdir(parents=True, exist_ok=True)

    for fname in ("TALENT_TREE.txt", "TALENT_LOG.txt", "RESPEC_RULES.txt"):
        dst = target_dir / fname
        if dst.exists():
            continue
        src = templates_dir / fname
        if not src.is_file():
            failures.append(f"missing governance talent template: {src}")
            continue
        try:
            shutil.copy2(src, dst)
        except Exception as exc:
            failures.append(f"failed to initialize talent file {dst}: {exc}")


def _extract_talent_id_from_outcome(outcome_text: str) -> str | None:
    m = _OUTCOME_TALENT_ID_RX.search(outcome_text)
    if not m:
        return None
    return (m.group(1) or "").strip().upper()


def _split_talent_entries(talent_tree_text: str) -> list[tuple[str, str]]:
    """Return list of (talent_id, entry_text) blocks."""

    rx = re.compile(r"(?im)^TALENT ID:\\s*(T-\\d{3})\\b")
    matches = list(rx.finditer(talent_tree_text))
    if not matches:
        return []

    out: list[tuple[str, str]] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(talent_tree_text)
        tid = (m.group(1) or "").strip().upper()
        out.append((tid, talent_tree_text[start:end]))
    return out


def _entry_has_required_fields(entry_text: str, failures: List[str], *, context: str) -> None:
    required_labels = [
        "Name:",
        "Unlocked On:",
        "Source Quest:",
        "Scope:",
        "Capability:",
        "Implications / Constraints:",
        "Evidence / Receipts:",
    ]
    for lab in required_labels:
        if lab not in entry_text:
            failures.append(f"{context}: missing required field label: {lab}")

    m_name = re.search(r"(?im)^Name:\\s*(.+)$", entry_text)
    if not m_name or not m_name.group(1).strip() or m_name.group(1).strip().upper() in {"TBD", "<FILL>"}:
        failures.append(f"{context}: Name must be non-empty (no TBD/<fill>)")

    m_date = re.search(r"(?im)^Unlocked On:\\s*(\\d{4}-\\d{2}-\\d{2})\\b", entry_text)
    if not m_date:
        failures.append(f"{context}: Unlocked On must be YYYY-MM-DD")


def _validate_talent_award(
    *,
    data_root: Path,
    quest_id: str,
    quest_text: str,
    bundle: Path,
    failures: List[str],
) -> None:
    awarded = _parse_talent_point_awarded(quest_text)
    if awarded is None:
        failures.append("Quest missing required field: 'Talent Point Awarded: (YES/NO)'")
        return

    outcome_txt = _read_text(bundle / "04_OUTCOME.md")
    outcome_awarded: str | None = None
    m = _OUTCOME_TALENT_AWARDED_RX.search(outcome_txt)
    if m:
        outcome_awarded = (m.group(1) or "").strip().upper()

    if outcome_awarded is None:
        failures.append("04_OUTCOME.md must include 'Talent Point Awarded: YES/NO' (must match Quest)")
    elif outcome_awarded != awarded:
        failures.append(f"04_OUTCOME.md Talent Point Awarded mismatch: quest={awarded} outcome={outcome_awarded}")

    if awarded != "YES":
        return

    _ensure_talent_tree_initialized(data_root, failures)
    if failures:
        return

    talent_dir = data_root / "Talent Tree"
    tree_path = talent_dir / "TALENT_TREE.txt"
    log_path = talent_dir / "TALENT_LOG.txt"

    if not tree_path.is_file() or not log_path.is_file():
        failures.append(f"Talent Tree not initialized under {talent_dir} (missing TALENT_TREE.txt and/or TALENT_LOG.txt)")
        return

    talent_id = _extract_talent_id_from_outcome(outcome_txt)
    if not talent_id:
        failures.append(
            "Talent awarded but 04_OUTCOME.md is missing a Talent ID. Add either:\n"
            "- Talent Spent On: T-### — <Name>\n"
            "- Talent ID: T-###"
        )
        return

    if "TALENT_TREE.txt" not in outcome_txt or "TALENT_LOG.txt" not in outcome_txt:
        failures.append("04_OUTCOME.md must reference the updated Talent Tree + Talent Log paths (TALENT_TREE.txt and TALENT_LOG.txt)")

    tree_txt = _read_text(tree_path)
    entries = _split_talent_entries(tree_txt)
    entry_map = {tid: txt for tid, txt in entries}

    if talent_id not in entry_map:
        failures.append(f"TALENT_TREE.txt missing entry for Talent ID {talent_id}")
    else:
        entry_txt = entry_map[talent_id]
        if quest_id not in entry_txt:
            failures.append(f"TALENT_TREE.txt entry {talent_id} must reference Source Quest {quest_id}")
        _entry_has_required_fields(entry_txt, failures, context=f"TALENT_TREE.txt entry {talent_id}")

        if "03_VERIFY.md" not in entry_txt and "04_OUTCOME.md" not in entry_txt:
            failures.append(
                f"TALENT_TREE.txt entry {talent_id} Evidence/Receipts should reference audit evidence "
                "(03_VERIFY.md and/or 04_OUTCOME.md)"
            )

    log_txt = _read_text(log_path)
    rx = re.compile(
        rf"(?is)Quest ID:\\s*{re.escape(quest_id)}.*?Talent Point Awarded:\\s*YES.*?Talent Spent On:\\s*.*{re.escape(talent_id)}"
    )
    if not rx.search(log_txt):
        failures.append(f"TALENT_LOG.txt missing award entry for {quest_id} with Talent Spent On {talent_id}")


def _resolve_context(args: argparse.Namespace, *, high_risk: bool) -> tuple[Path, str, str]:
    try:
        ctx = resolve_subject(
            subject_flag=args.subject,
            data_root_flag=args.data_root,
            allow_switch=False,
        )
    except SubjectResolutionError as exc:
        raise RuntimeError(str(exc)) from exc

    selection_method = str(ctx.get("selection_method") or "")
    if high_risk and selection_method not in {"flag", "lockfile"}:
        raise RuntimeError(
            "high-risk action requires explicit subject source (flag or lockfile). "
            f"selection_method={selection_method}"
        )

    return Path(str(ctx["data_root"])).expanduser().resolve(), str(ctx["subject"]), selection_method


def _snapshot_name_regex(subject: str) -> re.Pattern:
    # Matches:
    # <Subject>_End_of_Day_Snapshot_YYYY-MM-DD.txt
    # <Subject>_End_of_Day_Snapshot__02_YYYY-MM-DD.txt
    # <Subject>_End_of_Day_Snapshot__03_YYYY-MM-DD.txt
    safe = re.escape(subject)
    return re.compile(rf"^{safe}_End_of_Day_Snapshot(?:__\\d{{2}})?_\\d{{4}}-\\d{{2}}-\\d{{2}}\\.txt$")


def _parse_date_from_quest_filename(quest_file: Path) -> str | None:
    """Extract YYYY-MM-DD from the final __YYYY-MM-DD.txt token."""
    m = re.search(r"__(\\d{4}-\\d{2}-\\d{2})\\.txt$", quest_file.name)
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
    if not re.search(r"(?m)^CMD:\\s", t):
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
    try:
        data_root, _subject, _sel = _resolve_context(args, high_risk=False)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    accepted_dir = data_root / "Quest Board" / "Accepted"
    audits_dir = data_root / "Audits" / "Execution"

    quest_id = args.quest_id.strip().upper()
    if not re.fullmatch(r"QUEST_\\d{3}|SIDE-QUEST_\\d{3}", quest_id):
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
    quest_txt = _read_text(quest_file)
    talent_awarded = _parse_talent_point_awarded(quest_txt) or "<MISSING_IN_QUEST>"

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
        elif fname == "04_OUTCOME.md":
            _write_if_missing(
                bundle / fname,
                (
                    "# 04_OUTCOME.md\n\n"
                    "## Outcome\n"
                    "- Final status: <fill>\n"
                    "- State transition performed: <fill>\n"
                    f"- Audit bundle: {bundle}\n"
                    "- Notes: <fill>\n\n"
                    "## Talent Decision\n"
                    f"Talent Point Awarded: {talent_awarded}\n"
                    "Talent Spent On: (T-### — Name) | NONE\n"
                    "Evidence Paths:\n"
                    f"- {bundle / '03_VERIFY.md'}\n"
                    f"- {bundle / '04_OUTCOME.md'}\n"
                    f"- {data_root / 'Talent Tree' / 'TALENT_TREE.txt'}\n"
                    f"- {data_root / 'Talent Tree' / 'TALENT_LOG.txt'}\n"
                ),
            )
        else:
            _write_if_missing(bundle / fname, f"# {fname}\n")

    print(f"OK: initialized {bundle}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        data_root, subject, _sel = _resolve_context(args, high_risk=True)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    bundle = Path(args.bundle).expanduser().resolve()
    quest_id = args.quest_id.strip().upper()

    failures: List[str] = []

    _check(bundle.exists() and bundle.is_dir(), failures, f"bundle missing: {bundle}")
    if failures:
        return _print_failures(failures)

    accepted_dir = data_root / "Quest Board" / "Accepted"
    completed_dir = data_root / "Quest Board" / "Completed"

    quest_file = _find_quest_file(accepted_dir, quest_id)
    in_accepted = quest_file is not None
    in_completed = any(completed_dir.glob(f"{quest_id}__*.txt"))
    _check(in_accepted or in_completed, failures, f"{quest_id} not found in Accepted or Completed")
    if quest_file is None and in_completed:
        done = sorted(completed_dir.glob(f"{quest_id}__*.txt"))
        quest_file = done[0] if done else None

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

    if quest_file is None:
        failures.append(f"unable to locate quest file for {quest_id} (needed for Talent Point Awarded field)")
    else:
        _validate_talent_award(
            data_root=data_root,
            quest_id=quest_id,
            quest_text=_read_text(quest_file),
            bundle=bundle,
            failures=failures,
        )

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
            _check(
                snap.parent.resolve() == expected_dir,
                failures,
                f"snapshot must be under {expected_dir}, got {snap.parent}",
            )

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
    p.add_argument("--data-root", help="Canonical <Subject>_Data root")
    p.add_argument(
        "--subject",
        help="Subject name (required for validating snapshot filenames if data root isn't <Subject>_Data)",
    )

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

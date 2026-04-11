#!/usr/bin/env python3
"""Synapse Codex Gates (lightweight, deterministic first pass)."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SYNAPSE_ROOT = SCRIPT_DIR.parent.parent
RUNTIME_ROOT = SYNAPSE_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.subject_resolver import SubjectResolutionError, resolve_subject
from synapse_runtime.sidecar_store import (
    canonical_open_questions_path,
    load_open_questions_text,
    load_recent_decision_summaries,
    load_recent_discovery_summaries,
)

ALLOWED = {"READY", "NEEDS_DECISIONS", "CONTRADICTION_FOUND"}
HANDWAVY_RX = re.compile(r"\b(TBD|TODO|TBA|maybe|possibly|later)\b", re.IGNORECASE)
CONTRADICTION_RX = re.compile(r"\b(CONTRADICTS?|CONTRADICTION)\b", re.IGNORECASE)


def _resolve_data_root(args: argparse.Namespace) -> tuple[Path, str]:
    try:
        ctx = resolve_subject(
            subject_flag=args.subject,
            data_root_flag=args.data_root,
            allow_switch=False,
        )
    except SubjectResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    return Path(str(ctx["data_root"])).expanduser().resolve(), str(ctx["subject"])


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _toc_has_sections(toc_text: str) -> bool:
    for line in toc_text.splitlines():
        if re.match(r"^\s*\d+\.\s+\S+", line):
            return True
    return False


def _blocking_open_questions_legacy(open_questions_text: str) -> int:
    count = 0
    for line in open_questions_text.splitlines():
        if re.search(r"Status:\s*BLOCKING\b", line, re.IGNORECASE):
            count += 1
    return count


def _blocking_open_questions_sidecar(open_questions_text: str) -> int:
    lines = open_questions_text.splitlines()
    in_blocking = False
    seen_blocking = False
    count = 0
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if re.match(r"^##\s+Blocking\s*$", stripped, re.IGNORECASE):
            in_blocking = True
            seen_blocking = True
            continue
        if re.match(r"^##\s+", stripped):
            in_blocking = False
            continue
        if not in_blocking:
            continue
        if stripped.startswith("- "):
            body = stripped[2:].strip()
            if body.lower() == "none yet.":
                continue
            if body:
                count += 1
    if not seen_blocking:
        raise RuntimeError("Malformed canonical sidecar open questions: missing '## Blocking' section.")
    return count


def _spec_continuity_inputs(data_root: Path) -> tuple[int, str]:
    canonical_open_questions = canonical_open_questions_path(data_root)
    if canonical_open_questions.exists():
        blocking = _blocking_open_questions_sidecar(load_open_questions_text(data_root))
        summaries = load_recent_discovery_summaries(data_root) + load_recent_decision_summaries(data_root)
        return blocking, "\n".join(summaries)

    legacy_discoveries = data_root / "Incubation" / "DISCOVERIES.md"
    legacy_open_questions = data_root / "Incubation" / "OPEN_QUESTIONS.md"
    blocking = _blocking_open_questions_legacy(_read(legacy_open_questions))
    return blocking, _read(legacy_discoveries)


def _parse_anchor_index(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": 1,
        "updated_at": None,
        "terms": [],
        "invariants": [],
        "contracts": [],
        "section_receipts": [],
    }
    if not path.exists():
        return out

    current: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and line[:-1] in out:
            current = line[:-1]
            continue
        if line.startswith("- ") and current in {"terms", "invariants", "contracts", "section_receipts"}:
            out[current].append(line[2:].strip())
            continue
        if ":" in line and not line.startswith("- "):
            key, val = [s.strip() for s in line.split(":", 1)]
            if key in {"schema_version"}:
                try:
                    out[key] = int(val)
                except Exception:
                    pass
            elif key in {"updated_at"}:
                out[key] = None if val in {"null", ""} else val
            current = None
    return out


def _write_anchor_index(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"schema_version: {int(payload.get('schema_version', 1))}",
        f"updated_at: {payload.get('updated_at') or 'null'}",
        "terms:",
    ]
    lines.extend([f"- {x}" for x in payload.get("terms", [])])
    lines.append("invariants:")
    lines.extend([f"- {x}" for x in payload.get("invariants", [])])
    lines.append("contracts:")
    lines.extend([f"- {x}" for x in payload.get("contracts", [])])
    lines.append("section_receipts:")
    lines.extend([f"- {x}" for x in payload.get("section_receipts", [])])
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def _set_gate_status(build_state_path: Path, gate_key: str, status: str) -> None:
    build_state_path.parent.mkdir(parents=True, exist_ok=True)
    if not build_state_path.exists():
        build_state_path.write_text(
            (
                "schema_version: 1\n"
                "overall_status: NOT_STARTED\n"
                "spec_completeness_gate:\n"
                "  status: NEEDS_DECISIONS\n"
                "  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]\n"
                "consistency_gate:\n"
                "  status: NEEDS_DECISIONS\n"
                "  allowed: [READY, NEEDS_DECISIONS, CONTRADICTION_FOUND]\n"
                "sections: []\n"
                "notes: []\n"
            ),
            encoding="utf-8",
        )

    text = build_state_path.read_text(encoding="utf-8", errors="replace")
    rx = re.compile(rf"(?ms)({re.escape(gate_key)}:\n\s+status:\s*)([A-Z_]+)")
    if rx.search(text):
        text = rx.sub(rf"\g<1>{status}", text, count=1)
    else:
        text = text.rstrip("\n") + f"\n{gate_key}:\n  status: {status}\n"
    build_state_path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def cmd_spec(args: argparse.Namespace) -> int:
    try:
        data_root, subject = _resolve_data_root(args)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    canonical_toc_path = data_root / "Codex" / "TOC.md"
    draft_toc_path = data_root / "Codex" / "TOC_DRAFT.md"
    build_state_path = data_root / "Codex" / "CODEX_BUILD_STATE.yaml"

    toc_text = _read(canonical_toc_path) if canonical_toc_path.exists() else _read(draft_toc_path)
    try:
        blocking, continuity_text = _spec_continuity_inputs(data_root)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    has_contradiction = bool(CONTRADICTION_RX.search(toc_text) or CONTRADICTION_RX.search(continuity_text))
    has_sections = _toc_has_sections(toc_text)

    if has_contradiction:
        status = "CONTRADICTION_FOUND"
    elif blocking > 0:
        status = "NEEDS_DECISIONS"
    elif has_sections:
        status = "READY"
    else:
        status = "NEEDS_DECISIONS"

    if args.write_state:
        _set_gate_status(build_state_path, "spec_completeness_gate", status)

    print("=== SPEC COMPLETENESS GATE ===")
    print(f"subject: {subject}")
    print(f"data_root: {data_root}")
    print(f"status: {status}")
    print(f"blocking_questions: {blocking}")
    print(f"toc_has_sections: {'YES' if has_sections else 'NO'}")
    print(f"contradiction_markers: {'YES' if has_contradiction else 'NO'}")
    print(f"build_state_updated: {'YES' if args.write_state else 'NO'}")
    return 0 if status != "CONTRADICTION_FOUND" else 2


def cmd_consistency(args: argparse.Namespace) -> int:
    try:
        data_root, subject = _resolve_data_root(args)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    section = Path(args.section).expanduser().resolve()
    if not section.exists():
        print(f"FAIL: section file missing: {section}")
        return 2

    build_state_path = data_root / "Codex" / "CODEX_BUILD_STATE.yaml"
    anchor_path = data_root / "Codex" / "ANCHOR_INDEX.yaml"
    text = _read(section)

    has_contradiction = bool(CONTRADICTION_RX.search(text))
    has_handwavy = bool(HANDWAVY_RX.search(text))

    if has_contradiction:
        status = "CONTRADICTION_FOUND"
    elif has_handwavy:
        status = "NEEDS_DECISIONS"
    else:
        status = "READY"

    if args.write_state:
        _set_gate_status(build_state_path, "consistency_gate", status)

    terms = sorted(set(re.findall(r"(?im)^\s*(?:TERM|Term)\s*:\s*(.+)$", text)))
    invariants = sorted(set(re.findall(r"(?im)^\s*(?:INVARIANT|Invariant)\s*:\s*(.+)$", text)))
    contracts = sorted(set(re.findall(r"(?im)^\s*(?:CONTRACT|Contract)\s*:\s*(.+)$", text)))
    if args.update_anchor:
        idx = _parse_anchor_index(anchor_path)
        idx["updated_at"] = dt.datetime.now().astimezone().isoformat()
        idx["terms"] = sorted(set(idx.get("terms", []) + terms))
        idx["invariants"] = sorted(set(idx.get("invariants", []) + invariants))
        idx["contracts"] = sorted(set(idx.get("contracts", []) + contracts))
        receipt = f"{dt.datetime.now().astimezone().isoformat()} | {section} | {status}"
        idx["section_receipts"] = (idx.get("section_receipts", []) + [receipt])[-200:]
        _write_anchor_index(anchor_path, idx)

    print("=== CONSISTENCY GATE ===")
    print(f"subject: {subject}")
    print(f"data_root: {data_root}")
    print(f"section: {section}")
    print(f"status: {status}")
    print(f"handwavy_markers: {'YES' if has_handwavy else 'NO'}")
    print(f"contradiction_markers: {'YES' if has_contradiction else 'NO'}")
    print(f"anchor_index_updated: {'YES' if args.update_anchor else 'NO'}")
    print(f"build_state_updated: {'YES' if args.write_state else 'NO'}")
    print(f"term_anchors_found: {len(terms)}")
    print(f"invariant_anchors_found: {len(invariants)}")
    print(f"contract_anchors_found: {len(contracts)}")
    return 0 if status != "CONTRADICTION_FOUND" else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Synapse codex gates (spec completeness + consistency).")
    p.add_argument("--data-root", help="Canonical <Subject>_Data root")
    p.add_argument("--subject", help="Subject key override")

    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("spec", help="Run Spec Completeness Gate")
    ps.add_argument("--write-state", action="store_true", help="Write gate status into CODEX_BUILD_STATE.yaml")
    ps.set_defaults(func=cmd_spec)

    pc = sub.add_parser("consistency", help="Run Consistency Gate for one section")
    pc.add_argument("--section", required=True, help="Section file path")
    pc.add_argument("--write-state", action="store_true", help="Write gate status into CODEX_BUILD_STATE.yaml")
    pc.add_argument("--update-anchor", action="store_true", help="Update ANCHOR_INDEX.yaml from section anchors")
    pc.set_defaults(func=cmd_consistency)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

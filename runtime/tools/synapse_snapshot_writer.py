#!/usr/bin/env python3
"""Synapse — Snapshot Writer (subject-agnostic).

Version: v0.3
Last Updated: 2026-02-18

This tool is NOT an LLM runtime.
It is a deterministic artifact writer that produces Snapshot files aligned to:
- governance/Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt

AI11 support:
- If a Draftshot is ACTIVE for the session being Snapshotted, the Snapshot MUST
  reference the Draftshot (path + REV) and the Draftshot is marked CONSUMED.
  (See: Processes/SYNAPSE_GUILD__DRAFTSHOTS.txt and Terms/Formalization.md)

Why this exists:
- Agents drift when they hand-write snapshots.
- Templates define minimum required structure.
- This tool emits the skeleton exactly, then optionally splices in operator/agent
  content blocks from plain text files.

Design constraints:
- Subject-agnostic (<SUBJECT>, etc.)
- No suffix-after-date in filenames.
- Same-day duplicates use __02 / __03 counters BEFORE the date token.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SYNAPSE_ROOT = SCRIPT_DIR.parent.parent
RUNTIME_ROOT = SYNAPSE_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.subject_resolver import SubjectResolutionError, resolve_subject
from synapse_runtime.draftshots import DraftshotError, consume_draftshot_for_snapshot, resolve_snapshot_draftshot
from synapse_runtime.snapshot_candidates import snapshot_candidate_summary
from synapse_runtime.snapshot_checkpoint_policy import (
    CONTROL_SYNC_KIND,
    EOD_KIND,
    GENERAL_KIND,
    evaluate_snapshot_checkpoint,
)


# -------------------------
# helpers
# -------------------------

def _now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_text(path: Optional[Path]) -> str:
    if not path:
        return ""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _runtime_state_path(data_root: Path) -> Path:
    # NOTE: this is just a tiny receipt for open/close Control Sync state.
    return data_root / ".governance_runtime" / "control_sync_state.json"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, state: dict) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_context(args: argparse.Namespace, *, high_risk: bool) -> tuple[Path, str, str]:
    try:
        ctx = resolve_subject(
            subject_flag=args.subject,
            data_root_flag=args.data_root,
            allow_switch=bool(getattr(args, "allow_switch", False)),
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


def _codex_freeze_status(data_root: Path) -> tuple[str, str]:
    """Return (world_state, codex_freeze_line)."""
    freeze = data_root / "Codex" / "CODEX_FREEZE.md"
    if freeze.exists():
        return ("Fog Lifted", f"Codex Freeze status: PRESENT ({freeze})")
    return (
        "Fog of War",
        "Codex Freeze status: MISSING (Fog of War ⇒ execution forbidden)",
    )


def _snapshot_path(base_dir: Path, filename_prefix: str, stamp_date: str) -> Path:
    """Return a non-colliding snapshot path following Synapse naming law.

    Primary:
      <prefix>_<YYYY-MM-DD>.txt

    Duplicates:
      <prefix>__02_<YYYY-MM-DD>.txt
      <prefix>__03_<YYYY-MM-DD>.txt
      ...
    """
    primary = base_dir / f"{filename_prefix}_{stamp_date}.txt"
    if not primary.exists():
        return primary

    for i in range(2, 100):
        cand = base_dir / f"{filename_prefix}__{i:02d}_{stamp_date}.txt"
        if not cand.exists():
            return cand

    # If someone wrote 99 snapshots in one day, they deserve pain.
    raise RuntimeError(f"Too many same-day snapshots for {filename_prefix}_{stamp_date}")


def _data_root_from_snapshot_path(snap: Path) -> Path:
    # .../<DataRoot>/Snapshots/<Type>/file
    return snap.parents[2]


def _rel_to_data_root(data_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except Exception:
        return str(path)


def _explicit_canonical_checkpoint_receipt(
    *,
    data_root: Path,
    boundary: str,
    snapshot_kind: str,
    target_day: str,
    draftshot_meta: Optional["DraftshotMeta"],
) -> dict[str, Any]:
    draftshot_payload = {"refreshed_at": f"{target_day}T00:00:00-04:00"} if draftshot_meta is not None else None
    decision = evaluate_snapshot_checkpoint(
        boundary=boundary,
        requested_candidate_kinds=[],
        target_day_hint=target_day,
        current_summary=snapshot_candidate_summary(data_root),
        draftshot=draftshot_payload,
        session_anchor_present=True,
        decision_mode="explicit_canonical",
        requested_snapshot_kind=snapshot_kind,
    )
    payload = decision.to_dict()
    if payload.get("blocked_reason"):
        raise RuntimeError(f"snapshot checkpoint blocked: {payload['blocked_reason']}")
    return payload


# -------------------------
# Draftshots (AI11)
# -------------------------

@dataclass(frozen=True)
class DraftshotMeta:
    path: Path
    rel_path: str
    revision: str
    status: str


def _draftshot_dir(data_root: Path) -> Path:
    return data_root / "Snapshots" / "Draft Shots"


def _parse_draftshot_meta(data_root: Path, path: Path) -> DraftshotMeta:
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:80])

    # Status: ACTIVE / CONSUMED / ABANDONED
    m_status = re.search(r"(?im)^(?:-\s*)?Status:\s*([A-Z_]+)\s*$", head)
    status = (m_status.group(1).strip().upper() if m_status else "UNKNOWN")

    # Revision: REV#
    m_rev = re.search(r"(?im)^(?:-\s*)?Revision:\s*(REV\d+)\s*$", head)
    if m_rev:
        revision = m_rev.group(1).strip().upper()
    else:
        m_rev2 = re.search(r"(?i)__?(REV\d+)\b", path.name)
        revision = (m_rev2.group(1).upper() if m_rev2 else "REV?")

    rel = _rel_to_data_root(data_root, path)
    return DraftshotMeta(path=path, rel_path=rel, revision=revision, status=status)


def _resolve_active_draftshot(data_root: Path, explicit: Optional[str]) -> Optional[DraftshotMeta]:
    """Return the resolved Draftshot meta, or None, via the runtime owner."""
    try:
        payload = resolve_snapshot_draftshot(data_root=data_root, explicit=explicit)
    except DraftshotError as exc:
        raise RuntimeError(str(exc)) from exc
    if payload is None:
        return None

    path = Path(str(payload.get("body_path") or "")).resolve()
    revision_number = payload.get("revision_number")
    revision = (
        f"REV{int(revision_number)}"
        if isinstance(revision_number, int) or str(revision_number or "").isdigit()
        else str(payload.get("revision_label") or "REV?")
    )
    return DraftshotMeta(
        path=path,
        rel_path=_rel_to_data_root(data_root, path),
        revision=revision,
        status=str(payload.get("status") or "UNKNOWN").strip().upper(),
    )


def _draftshot_header_block(meta: DraftshotMeta, *, consume: bool) -> list[str]:
    state_line = "ACTIVE → CONSUMED" if consume else meta.status
    return [
        "- Source Draftshot:",
        f"  - Path: {meta.rel_path}",
        f"  - Revision: {meta.revision}",
        f"  - State at snapshot time: {state_line}",
    ]


# -------------------------
# writers
# -------------------------

def _write_control_sync_snapshot(
    *,
    snap: Path,
    subject: str,
    day: str,
    topic: str,
    started_at: str,
    closed_at: str,
    participants: str,
    reason: str,
    next_action: str,
    draftshot_meta: Optional[DraftshotMeta],
    consume_draftshot: bool,
    rehydration_review_block: str,
    reality_block: str,
    decisions_block: str,
    deferred_block: str,
    scope_block: str,
    artifacts_block: str,
    notes_block: str,
    exit_block: str,
) -> None:
    data_root = _data_root_from_snapshot_path(snap)
    world_state, freeze_line = _codex_freeze_status(data_root)

    header_lines = [
        "================================================================================",
        "CONTROL SYNC SNAPSHOT",
        "================================================================================",
        "A) Header (required)",
        f"- Subject: {subject}",
        f"- Date: {day}",
        f"- Topic: {topic or '(none)'}",
        "- Snapshot Type: Control_Sync",
        f"- World State: {world_state}",
        f"- {freeze_line}",
    ]
    if draftshot_meta is not None:
        header_lines.extend(_draftshot_header_block(draftshot_meta, consume=consume_draftshot))

    body = header_lines + [
        "",
        "B) Rehydration Review (required when resuming)",
        rehydration_review_block
        or "- Latest Control Sync Snapshot reviewed: (fill)\n- Latest End-of-Day Snapshot reviewed: (fill)\n- Relevant General Snapshots reviewed: (fill)",
        "",
        "C) Current Reality (State Surface)",
        reality_block
        or "- Active Guild Orders / Raids: (fill)\n- Paused Guild Orders / Raids: (fill)\n- Quest Board summary: (fill)\n- Blockers: (fill)\n- Known risks / unknowns: (fill)",
        "",
        "D) Binding Decisions (required when binding decisions exist)",
        decisions_block or "- (none recorded)",
        "",
        "Deferred / Not decided:",
        deferred_block or "- (none recorded)",
        "",
        "Decision changes (if any):",
        "- prior decision → new decision (with reference)",
        "",
        "E) Scope Commitment (required)",
        scope_block
        or "- Quests to accept now (by ID): (fill)\n- Deferred work (and why): (fill)\n- Expected side-work (bugs/refactors): (fill)",
        "",
        "F) Artifacts Touched / Created (required)",
        artifacts_block
        or "- Codex/TOC updates: (paths)\n- Guild Orders/Raids updates: (paths)\n- Dungeon/Quest artifacts: (paths)\n- Other data artifacts: (paths)",
        "",
        "G) NOTES",
        notes_block or "- (none)",
        "",
        "H) Exit Condition + Closure Statement (required)",
        "- Closure statement: This Control Sync is CLOSED only when this Snapshot exists as a file.",
        f"- Started At: {started_at}",
        f"- Closed At: {closed_at}",
        f"- Participants: {participants or '(unknown)'}",
        f"- Reason: {reason or '(unknown)'}",
        f"- Next immediate action: {next_action or '(not specified)'}",
        "",
        exit_block
        or "- If execution will begin: state the first Quest to accept/execute.\n- If no execution committed: state why.",
        "",
        "END OF SNAPSHOT",
        "",
    ]

    _ensure_parent(snap)
    snap.write_text("\n".join(body), encoding="utf-8")


def _write_eod_snapshot(
    *,
    snap: Path,
    subject: str,
    day: str,
    topic: str,
    draftshot_meta: Optional[DraftshotMeta],
    consume_draftshot: bool,
    work_block: str,
    completed_block: str,
    incomplete_block: str,
    verification_block: str,
    bugs_block: str,
    raid_block: str,
    talent_block: str,
    resume_block: str,
) -> None:
    data_root = _data_root_from_snapshot_path(snap)
    world_state, freeze_line = _codex_freeze_status(data_root)

    header_lines = [
        "================================================================================",
        "END OF DAY SNAPSHOT",
        "================================================================================",
        "A) Header (required)",
        f"- Subject: {subject}",
        f"- Date: {day}",
        f"- Topic: {topic or '(none)'}",
        "- Snapshot Type: End_of_Day",
        f"- World State: {world_state}",
        f"- {freeze_line}",
    ]
    if draftshot_meta is not None:
        header_lines.extend(_draftshot_header_block(draftshot_meta, consume=consume_draftshot))

    body = header_lines + [
        "",
        "B) Work Performed (Quest-by-Quest) (required)",
        work_block or "- (none recorded)",
        "",
        "C) Completed Work Summary (required when anything completed)",
        completed_block or "- (none)",
        "",
        "D) Incomplete / Failed / Blocked Work (required when relevant)",
        incomplete_block or "- (none)",
        "",
        "E) System Verification Performed (required when applicable)",
        verification_block or "- (none)",
        "",
        "F) Bugs / Weirdness / Discoveries",
        bugs_block or "- (none)",
        "",
        "G) Raid / Guild Orders status changes",
        raid_block or "- (none)",
        "",
        "H) Talent Tree updates (mandatory when relevant)",
        talent_block or "- (none)",
        "",
        "I) Resume Instructions (required)",
        resume_block
        or "- Tomorrow's Control Sync must start by reviewing: (fill)\n- Known blockers: (fill)\n- Next recommended Quests: (fill)\n- Rehydration notes: (fill)",
        "",
        "END OF SNAPSHOT",
        "",
    ]

    _ensure_parent(snap)
    snap.write_text("\n".join(body), encoding="utf-8")


def _write_general_snapshot(
    *,
    snap: Path,
    subject: str,
    day: str,
    topic: str,
    draftshot_meta: Optional[DraftshotMeta],
    consume_draftshot: bool,
    purpose: str,
    content: str,
    binding: bool,
    notes: str,
) -> None:
    header_lines = [
        "================================================================================",
        "GENERAL SNAPSHOT",
        "================================================================================",
        "A) Header (required)",
        f"- Subject: {subject}",
        f"- Date: {day}",
        f"- Topic: {topic or '(none)'}",
        "- Snapshot Type: General",
    ]
    if draftshot_meta is not None:
        header_lines.extend(_draftshot_header_block(draftshot_meta, consume=consume_draftshot))

    body = header_lines + [
        "",
        "B) Purpose",
        purpose or "- (fill)",
        "",
        "C) Content (facts / notes)",
        content or "- (fill)",
        "",
        "D) Binding marker (conditional)",
        "- BINDING" if binding else "- (none)",
        "",
        "E) NOTES",
        notes or "- (none)",
        "",
        "END OF SNAPSHOT",
        "",
    ]

    _ensure_parent(snap)
    snap.write_text("\n".join(body), encoding="utf-8")


# -------------------------
# commands
# -------------------------

def cmd_control_open(args: argparse.Namespace) -> int:
    try:
        data_root, subject, _sel = _resolve_context(args, high_risk=False)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    state_path = _runtime_state_path(data_root)
    now = _now_local()

    state = _load_state(state_path)
    if state.get("active"):
        print("FAIL: Control Sync already active.")
        print(f"- started_at: {state.get('started_at')}")
        print(f"- subject: {state.get('subject')}")
        return 2

    new_state = {
        "active": True,
        "subject": subject,
        "participants": args.participants,
        "reason": args.reason,
        "topic": args.topic,
        "started_at": now.isoformat(),
        "timezone": str(now.tzinfo),
    }
    _save_state(state_path, new_state)

    print("OK: Control Sync opened.")
    print(f"- state: {state_path}")
    print(f"- subject: {subject}")
    return 0


def cmd_control_close(args: argparse.Namespace) -> int:
    try:
        data_root, subject, _sel = _resolve_context(args, high_risk=True)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    state_path = _runtime_state_path(data_root)
    state = _load_state(state_path)

    if not state.get("active"):
        print("FAIL: Control Sync is not active.")
        return 2

    now = _now_local()
    day = now.date().isoformat()

    out_dir = data_root / "Snapshots" / "Control Sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = _snapshot_path(out_dir, f"{subject}_Control_Sync_Snapshot", day)

    # Draftshot (AI11)
    draftshot_meta: Optional[DraftshotMeta] = None
    try:
        draftshot_meta = _resolve_active_draftshot(data_root, args.draftshot)
    except RuntimeError as e:
        print(str(e))
        return 2

    consume_draftshot = bool(draftshot_meta) and (not args.no_consume_draftshot)
    try:
        checkpoint_receipt = _explicit_canonical_checkpoint_receipt(
            data_root=data_root,
            boundary="control-close",
            snapshot_kind=CONTROL_SYNC_KIND,
            target_day=day,
            draftshot_meta=draftshot_meta,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    # blocks
    decisions_block = _read_text(Path(args.decisions_file).expanduser().resolve() if args.decisions_file else None)
    deferred_block = _read_text(Path(args.deferred_file).expanduser().resolve() if args.deferred_file else None)
    rehydration_review_block = _read_text(Path(args.rehydration_review_file).expanduser().resolve() if args.rehydration_review_file else None)
    reality_block = _read_text(Path(args.reality_file).expanduser().resolve() if args.reality_file else None)
    scope_block = _read_text(Path(args.scope_file).expanduser().resolve() if args.scope_file else None)
    artifacts_block = _read_text(Path(args.artifacts_file).expanduser().resolve() if args.artifacts_file else None)
    notes_block = _read_text(Path(args.notes_file).expanduser().resolve() if args.notes_file else None)
    exit_block = _read_text(Path(args.exit_file).expanduser().resolve() if args.exit_file else None)

    _write_control_sync_snapshot(
        snap=snap,
        subject=subject,
        day=day,
        topic=args.topic or state.get("topic") or "",
        started_at=state.get("started_at", ""),
        closed_at=now.isoformat(),
        participants=state.get("participants", ""),
        reason=state.get("reason", ""),
        next_action=args.next_action,
        draftshot_meta=draftshot_meta,
        consume_draftshot=consume_draftshot,
        rehydration_review_block=rehydration_review_block,
        reality_block=reality_block,
        decisions_block=decisions_block,
        deferred_block=deferred_block,
        scope_block=scope_block,
        artifacts_block=artifacts_block,
        notes_block=notes_block,
        exit_block=exit_block,
    )

    if draftshot_meta is not None and consume_draftshot:
        try:
            consume_draftshot_for_snapshot(
                data_root=data_root,
                explicit=str(draftshot_meta.path),
                snapshot_path=str(snap),
                consumed_at_iso=now.isoformat(),
            )
        except DraftshotError as exc:
            print(f"FAIL: {exc}")
            return 2

    _save_state(state_path, {"active": False, "last_closed_snapshot": str(snap), "closed_at": now.isoformat(), "subject": subject})

    print("OK: Control Sync closed.")
    print(f"- snapshot: {snap}")
    if draftshot_meta is not None:
        print(f"- draftshot: {draftshot_meta.rel_path} ({draftshot_meta.revision})")
        print(f"- draftshot_consumed: {'YES' if consume_draftshot else 'NO'}")
    print(
        f"- checkpoint_policy: {checkpoint_receipt['snapshot_kind']} "
        f"target_day={checkpoint_receipt['target_day']} writer_command={checkpoint_receipt['writer_command']}"
    )
    return 0


def cmd_eod(args: argparse.Namespace) -> int:
    try:
        data_root, subject, _sel = _resolve_context(args, high_risk=True)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    now = _now_local()
    day = now.date().isoformat()

    out_dir = data_root / "Snapshots" / "End of Day"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = _snapshot_path(out_dir, f"{subject}_End_of_Day_Snapshot", day)

    # Draftshot (AI11)
    draftshot_meta: Optional[DraftshotMeta] = None
    try:
        draftshot_meta = _resolve_active_draftshot(data_root, args.draftshot)
    except RuntimeError as e:
        print(str(e))
        return 2

    consume_draftshot = bool(draftshot_meta) and (not args.no_consume_draftshot)
    try:
        checkpoint_receipt = _explicit_canonical_checkpoint_receipt(
            data_root=data_root,
            boundary="eod",
            snapshot_kind=EOD_KIND,
            target_day=day,
            draftshot_meta=draftshot_meta,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    work_block = _read_text(Path(args.work_file).expanduser().resolve() if args.work_file else None)
    completed_block = _read_text(Path(args.completed_file).expanduser().resolve() if args.completed_file else None)
    incomplete_block = _read_text(Path(args.incomplete_file).expanduser().resolve() if args.incomplete_file else None)
    verification_block = _read_text(Path(args.verification_file).expanduser().resolve() if args.verification_file else None)
    bugs_block = _read_text(Path(args.bugs_file).expanduser().resolve() if args.bugs_file else None)
    raid_block = _read_text(Path(args.raid_file).expanduser().resolve() if args.raid_file else None)
    talent_block = _read_text(Path(args.talent_file).expanduser().resolve() if args.talent_file else None)
    resume_block = _read_text(Path(args.resume_file).expanduser().resolve() if args.resume_file else None)

    _write_eod_snapshot(
        snap=snap,
        subject=subject,
        day=day,
        topic=args.topic,
        draftshot_meta=draftshot_meta,
        consume_draftshot=consume_draftshot,
        work_block=work_block,
        completed_block=completed_block,
        incomplete_block=incomplete_block,
        verification_block=verification_block,
        bugs_block=bugs_block,
        raid_block=raid_block,
        talent_block=talent_block,
        resume_block=resume_block,
    )

    if draftshot_meta is not None and consume_draftshot:
        try:
            consume_draftshot_for_snapshot(
                data_root=data_root,
                explicit=str(draftshot_meta.path),
                snapshot_path=str(snap),
                consumed_at_iso=now.isoformat(),
            )
        except DraftshotError as exc:
            print(f"FAIL: {exc}")
            return 2

    print("OK: EOD snapshot written.")
    print(f"- snapshot: {snap}")
    if draftshot_meta is not None:
        print(f"- draftshot: {draftshot_meta.rel_path} ({draftshot_meta.revision})")
        print(f"- draftshot_consumed: {'YES' if consume_draftshot else 'NO'}")
    print(
        f"- checkpoint_policy: {checkpoint_receipt['snapshot_kind']} "
        f"target_day={checkpoint_receipt['target_day']} writer_command={checkpoint_receipt['writer_command']}"
    )
    return 0


def cmd_general(args: argparse.Namespace) -> int:
    try:
        data_root, subject, _sel = _resolve_context(args, high_risk=True)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    now = _now_local()
    day = now.date().isoformat()

    out_dir = data_root / "Snapshots" / "General"
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = _snapshot_path(out_dir, f"{subject}_General_Snapshot", day)

    # Draftshot (AI11)
    draftshot_meta: Optional[DraftshotMeta] = None
    try:
        draftshot_meta = _resolve_active_draftshot(data_root, args.draftshot)
    except RuntimeError as e:
        print(str(e))
        return 2

    consume_draftshot = bool(draftshot_meta) and (not args.no_consume_draftshot)
    try:
        checkpoint_receipt = _explicit_canonical_checkpoint_receipt(
            data_root=data_root,
            boundary="general",
            snapshot_kind=GENERAL_KIND,
            target_day=day,
            draftshot_meta=draftshot_meta,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2

    purpose = _read_text(Path(args.purpose_file).expanduser().resolve() if args.purpose_file else None)
    content = _read_text(Path(args.content_file).expanduser().resolve() if args.content_file else None)
    notes = _read_text(Path(args.notes_file).expanduser().resolve() if args.notes_file else None)

    _write_general_snapshot(
        snap=snap,
        subject=subject,
        day=day,
        topic=args.topic,
        draftshot_meta=draftshot_meta,
        consume_draftshot=consume_draftshot,
        purpose=purpose,
        content=content,
        binding=args.binding,
        notes=notes,
    )

    if draftshot_meta is not None and consume_draftshot:
        try:
            consume_draftshot_for_snapshot(
                data_root=data_root,
                explicit=str(draftshot_meta.path),
                snapshot_path=str(snap),
                consumed_at_iso=now.isoformat(),
            )
        except DraftshotError as exc:
            print(f"FAIL: {exc}")
            return 2

    print("OK: General snapshot written.")
    print(f"- snapshot: {snap}")
    if draftshot_meta is not None:
        print(f"- draftshot: {draftshot_meta.rel_path} ({draftshot_meta.revision})")
        print(f"- draftshot_consumed: {'YES' if consume_draftshot else 'NO'}")
    print(
        f"- checkpoint_policy: {checkpoint_receipt['snapshot_kind']} "
        f"target_day={checkpoint_receipt['target_day']} writer_command={checkpoint_receipt['writer_command']}"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        data_root, _subject, _sel = _resolve_context(args, high_risk=False)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 2
    state_path = _runtime_state_path(data_root)
    state = _load_state(state_path)
    if not state:
        print("STATUS: no control sync state recorded")
        return 0
    print("STATUS:")
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


# -------------------------
# parser
# -------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Synapse snapshot writer (deterministic, subject-agnostic).")

    p.add_argument("--data-root", help="Canonical <Subject>_Data root (optional; resolved from focus lock if omitted)")
    p.add_argument("--subject", help="Subject name override")
    p.add_argument(
        "--allow-switch",
        action="store_true",
        help="Allow explicit subject/data-root overrides to differ from the active focus lock",
    )
    p.add_argument(
        "--draftshot",
        help="Optional Draftshot file path. If omitted, auto-detects single ACTIVE Draftshot under Snapshots/Draft Shots.",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("control-open", help="Open Control Sync mode.")
    p_open.add_argument("--participants", default="Brains, Hands")
    p_open.add_argument("--reason", default="alignment + decisions")
    p_open.add_argument("--topic", default="")
    p_open.set_defaults(func=cmd_control_open)

    p_close = sub.add_parser("control-close", help="Close Control Sync and write Control Sync snapshot.")
    p_close.add_argument("--decisions-file", help="Path to text file containing binding decisions")
    p_close.add_argument("--deferred-file", help="Path to text file containing deferred items")
    p_close.add_argument("--rehydration-review-file", help="Optional: prewritten Rehydration Review block")
    p_close.add_argument("--reality-file", help="Optional: prewritten Current Reality block")
    p_close.add_argument("--scope-file", help="Optional: prewritten Scope Commitment block")
    p_close.add_argument("--artifacts-file", help="Optional: prewritten Artifacts Touched block")
    p_close.add_argument("--notes-file", help="Optional: prewritten Notes block")
    p_close.add_argument("--exit-file", help="Optional: prewritten Exit block")
    p_close.add_argument("--next-action", default="")
    p_close.add_argument("--topic", default="")
    p_close.add_argument(
        "--no-consume-draftshot",
        action="store_true",
        help="Do NOT mark an ACTIVE Draftshot as CONSUMED after writing the Snapshot (not governance-compliant).",
    )
    p_close.set_defaults(func=cmd_control_close)

    p_eod = sub.add_parser("eod", help="Write End-of-Day snapshot.")
    p_eod.add_argument("--topic", default="")
    p_eod.add_argument("--work-file", help="Block file for section B (work performed)")
    p_eod.add_argument("--completed-file", help="Block file for section C (completed work summary)")
    p_eod.add_argument("--incomplete-file", help="Block file for section D (incomplete/blocked)")
    p_eod.add_argument("--verification-file", help="Block file for section E (verification)")
    p_eod.add_argument("--bugs-file", help="Block file for section F (bugs/weirdness)")
    p_eod.add_argument("--raid-file", help="Block file for section G (raid status)")
    p_eod.add_argument("--talent-file", help="Block file for section H (talent updates)")
    p_eod.add_argument("--resume-file", help="Block file for section I (resume instructions)")
    p_eod.add_argument(
        "--no-consume-draftshot",
        action="store_true",
        help="Do NOT mark an ACTIVE Draftshot as CONSUMED after writing the Snapshot (not governance-compliant).",
    )
    p_eod.set_defaults(func=cmd_eod)

    p_gen = sub.add_parser("general", help="Write General snapshot.")
    p_gen.add_argument("--topic", default="")
    p_gen.add_argument("--purpose-file", help="Block file for Purpose")
    p_gen.add_argument("--content-file", help="Block file for Content")
    p_gen.add_argument("--binding", action="store_true", help="Mark snapshot as containing BINDING statements")
    p_gen.add_argument("--notes-file", help="Block file for Notes")
    p_gen.add_argument(
        "--no-consume-draftshot",
        action="store_true",
        help="Do NOT mark an ACTIVE Draftshot as CONSUMED after writing the Snapshot (not governance-compliant).",
    )
    p_gen.set_defaults(func=cmd_general)

    p_stat = sub.add_parser("status", help="Show Control Sync state receipt")
    p_stat.set_defaults(func=cmd_status)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

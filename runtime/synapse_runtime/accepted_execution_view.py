"""Accepted/completed quest and audit-bundle read/projection helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from synapse_runtime.quest_acceptance import parse_quest_document
from synapse_runtime.quest_completion import COMPLETION_AUDIT_FILENAME, completion_audit_is_clean_pass, parse_completion_audit


_QUEST_NUMBER_RX = re.compile(r"(?i)(?:SIDE-QUEST|QUEST)_(\d{3})")


def _quest_number(value: str) -> int | None:
    match = _QUEST_NUMBER_RX.search(str(value or ""))
    if not match:
        return None
    return int(match.group(1))


def _quest_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    number = _quest_number(item.get("quest_id") or item.get("path") or "")
    number_key = number if number is not None else -1
    return (number_key, str(item.get("path") or ""))


def find_quest_file(data_root: Path, quest_id: str) -> Path | None:
    board_root = data_root / "Quest Board"
    for directory in (
        board_root / "Accepted",
        board_root / "Completed",
        board_root / "Abandoned",
        board_root,
    ):
        if not directory.exists():
            continue
        matches = sorted(directory.glob(f"{quest_id}__*.txt"))
        if matches:
            return matches[0]
    return None


def parse_audit_bundle_path(subject: str, data_root: Path, quest_text: str) -> Path | None:
    match = re.search(
        r"(?ims)^Audit Bundle Folder Path \(required once ACCEPTED\):\s*$\n(?P<body>.*?)(?:^\s*=+\s*$|\Z)",
        quest_text,
    )
    if not match:
        return None
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        if line.startswith("Audits/"):
            return (data_root / line).resolve()
        if line.startswith(f"{subject}_Data/"):
            return (data_root.parent / line).resolve()
        return (data_root / line).resolve()
    return None


def load_accepted_quest_details(subject: str, data_root: Path) -> list[dict[str, Any]]:
    accepted_dir = data_root / "Quest Board" / "Accepted"
    details: list[dict[str, Any]] = []
    if not accepted_dir.exists():
        return details
    for path in sorted(accepted_dir.glob("*.txt")):
        try:
            doc = parse_quest_document(subject=subject, data_root=data_root, path=path)
        except Exception:
            continue
        bundle_path = doc.audit_bundle_path
        execution_ready = bool(bundle_path and bundle_path.exists())
        latest_completion = bundle_path / COMPLETION_AUDIT_FILENAME if bundle_path else None
        completion = parse_completion_audit(latest_completion) if latest_completion and latest_completion.exists() else None
        details.append(
            {
                "quest_id": doc.quest_id or path.stem,
                "title": doc.title or path.stem,
                "path": str(path.resolve()),
                "state": "accepted",
                "audit_bundle_path": str(bundle_path.resolve()) if bundle_path else None,
                "execution_ready": execution_ready,
                "audit_state": doc.audit_state,
                "completion_verdict": completion.overall_verdict if completion else None,
            }
        )
    return details


def select_current_accepted_quest(details: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not details:
        return None
    return sorted(details, key=_quest_sort_key, reverse=True)[0]


def load_completed_quest_details(subject: str, data_root: Path) -> list[dict[str, Any]]:
    completed_dir = data_root / "Quest Board" / "Completed"
    details: list[dict[str, Any]] = []
    if not completed_dir.exists():
        return details
    for path in sorted(completed_dir.glob("*.txt")):
        try:
            doc = parse_quest_document(subject=subject, data_root=data_root, path=path)
            audit_bundle_path = doc.audit_bundle_path
        except Exception:
            quest_text = path.read_text(encoding="utf-8", errors="replace")
            quest_id = _QUEST_NUMBER_RX.search(path.name)
            audit_bundle_path = parse_audit_bundle_path(subject, data_root, quest_text)
            doc = None
        details.append(
            {
                "quest_id": (doc.quest_id if doc else None) or path.name.split("__", 1)[0],
                "title": (doc.title if doc else None) or path.stem,
                "path": str(path.resolve()),
                "state": "completed",
                "audit_bundle_path": str(audit_bundle_path.resolve()) if audit_bundle_path else None,
                "completion_verdict": (
                    parse_completion_audit(audit_bundle_path / COMPLETION_AUDIT_FILENAME).overall_verdict
                    if audit_bundle_path and (audit_bundle_path / COMPLETION_AUDIT_FILENAME).exists()
                    else ("PASS" if audit_bundle_path and completion_audit_is_clean_pass(audit_bundle_path / COMPLETION_AUDIT_FILENAME) else None)
                ),
            }
        )
    return sorted(details, key=_quest_sort_key, reverse=True)


def select_latest_completed_quest(details: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not details:
        return None
    return sorted(details, key=_quest_sort_key, reverse=True)[0]


def _disclosure_phase_path(bundle: Path, trigger: str, status_labels: list[str]) -> Path:
    latest = bundle / COMPLETION_AUDIT_FILENAME
    if latest.exists():
        return latest
    legacy_verify = bundle / "03_VERIFY.md"
    if legacy_verify.exists():
        return legacy_verify
    return bundle / "00_SUMMARY.md"


def _append_markdown_section(path: Path, heading: str, body: str, token: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if token in text:
        return False
    append = f"\n\n{heading}\n{body.strip()}\n"
    path.write_text(text.rstrip() + append, encoding="utf-8")
    return True


def record_disclosure_in_quest_audits(
    *,
    subject: str,
    data_root: Path,
    related_quests: list[str],
    disclosure_id: str,
    disclosure_block: str,
    trigger: str,
    status_labels: list[str],
) -> list[str]:
    touched: list[str] = []
    for quest_id in related_quests:
        quest_key = str(quest_id).strip()
        if not quest_key:
            continue
        quest_file = find_quest_file(data_root, quest_key)
        if quest_file is None:
            continue
        bundle = parse_audit_bundle_path(
            subject,
            data_root,
            quest_file.read_text(encoding="utf-8", errors="replace"),
        )
        if bundle is None or not bundle.exists():
            continue

        summary_body = (
            f"Disclosure ID: {disclosure_id}\n\n"
            f"Trigger: {trigger}\n"
            f"Status Labels: {', '.join(status_labels) or 'UNSPECIFIED'}"
        )
        if _append_markdown_section(bundle / "00_SUMMARY.md", "## Disclosure Gate Event", summary_body, disclosure_id):
            touched.append(str((bundle / "00_SUMMARY.md").resolve()))

        phase_path = _disclosure_phase_path(bundle, trigger, status_labels)
        phase_body = f"Disclosure ID: {disclosure_id}\n\n```\n{disclosure_block.strip()}\n```"
        if _append_markdown_section(phase_path, "## Disclosure Gate Event", phase_body, disclosure_id):
            touched.append(str(phase_path.resolve()))

        disclosure_path = bundle / "05_DISCLOSURE.md"
        if not disclosure_path.exists():
            disclosure_path.write_text(
                f"# 05_DISCLOSURE.md\n\n```\n{disclosure_block.strip()}\n```\n",
                encoding="utf-8",
            )
        else:
            _append_markdown_section(
                disclosure_path,
                "## Disclosure Gate Event",
                f"```\n{disclosure_block.strip()}\n```",
                disclosure_id,
            )
        touched.append(str(disclosure_path.resolve()))
    return touched


# Compatibility wrappers for callers not yet migrated to public names.
_find_quest_file = find_quest_file
_parse_audit_bundle_path = parse_audit_bundle_path
_load_accepted_quest_details = load_accepted_quest_details
_select_current_accepted_quest = select_current_accepted_quest
_record_disclosure_in_quest_audits = record_disclosure_in_quest_audits

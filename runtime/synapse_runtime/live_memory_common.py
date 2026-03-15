"""Shared live-memory utility helpers and error types."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


class LiveMemoryError(RuntimeError):
    """Raised when live-memory operations fail."""


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "run"


def _normalize_relpaths(data_root: Path, paths: Iterable[str]) -> list[str]:
    results: list[str] = []
    for value in paths:
        raw = str(value).strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            try:
                raw = candidate.resolve().relative_to(data_root.resolve()).as_posix()
            except Exception:
                raw = str(candidate.resolve())
        results.append(raw)
    return results


def _unique_strings(values: Iterable[str]) -> list[str]:
    results: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in results:
            results.append(text)
    return results


def _tokenize_text(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 3}


def _tokens_overlap(left: str, right: str) -> bool:
    return len(_tokenize_text(left) & _tokenize_text(right)) >= 2


def _next_item_id(items: list[dict[str, object]]) -> str:
    ids = [item.get("id", "") for item in items if isinstance(item, dict)]
    numbers = []
    for item_id in ids:
        match = re.search(r"(\d+)$", str(item_id))
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers or [0]) + 1
    return f"ITEM-{next_num:03d}"


def _normalize_items(items: Iterable[str], existing: list[dict[str, object]] | None = None) -> list[dict[str, str]]:
    existing_items = existing or []
    results: list[dict[str, str]] = []
    for text in items:
        item_text = str(text).strip()
        if not item_text:
            continue
        item_id = _next_item_id(existing_items + results)
        results.append({"id": item_id, "text": item_text, "status": "TODO"})
    return results


def _parse_status_updates(entries: Iterable[str]) -> list[tuple[str, str]]:
    updates: list[tuple[str, str]] = []
    for entry in entries:
        raw = str(entry).strip()
        if not raw:
            continue
        if ":" in raw:
            key, status = raw.split(":", 1)
        elif "=" in raw:
            key, status = raw.split("=", 1)
        else:
            raise LiveMemoryError(
                f"Invalid status update '{raw}'. Use ITEM-001:DONE or ITEM-001=DONE."
            )
        key = key.strip()
        status = status.strip().upper()
        if not key or not status:
            raise LiveMemoryError(
                f"Invalid status update '{raw}'. Use ITEM-001:DONE or ITEM-001=DONE."
            )
        updates.append((key, status))
    return updates


def _is_terminal_status(value: str | None) -> bool:
    text = str(value or "").strip().upper()
    return text in {"DONE", "COMPLETED", "BLOCKED", "CANCELLED", "CANCELED", "ABANDONED"}


def _extract_run_id(filename: str) -> str:
    return filename.split("__", 1)[0]


def _extract_decision_id(filename: str) -> str:
    return filename.split(".", 1)[0]

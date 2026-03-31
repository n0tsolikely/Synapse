"""Persisted execution-plan artifacts for outcome-based quests."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.live_memory_common import _slugify, _unique_strings


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
PLAN_SCHEMA_VERSION = 1
VALID_DUNGEON_COVERAGE = {"FULL_DUNGEON", "PARTIAL_DUNGEON", "N/A"}
_PLAN_FILENAME_STEM = re.compile(r"^PLAN__(?P<plan_id>PLAN-[A-Z0-9T]+)__REVISION-(?P<rev>\d{3})__", re.IGNORECASE)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _timestamp_token() -> str:
    return _now().strftime("%Y%m%dT%H%M%S%f%z")


def plans_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "PLANS"


def _plan_id() -> str:
    return f"PLAN-{_timestamp_token()}"


def _plan_filename(*, plan_id: str, revision_number: int, title: str) -> str:
    slug = _slugify(title)[:64] or "plan"
    return f"PLAN__{plan_id}__REVISION-{revision_number:03d}__{slug}.yaml"


def _existing_revisions(root: Path, plan_id: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob(f"PLAN__{plan_id}__REVISION-*.yaml"))


def _revision_number(path: Path) -> int | None:
    match = _PLAN_FILENAME_STEM.match(path.name)
    if not match:
        return None
    return int(match.group("rev"))


def _milestone_id(index: int) -> str:
    return f"MILESTONE-{index:03d}"


def normalize_milestones(items: Iterable[str] | Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    milestones: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(items, start=1):
        if isinstance(raw, dict):
            milestone_id = str(raw.get("id") or _milestone_id(index)).strip() or _milestone_id(index)
            text = str(raw.get("text") or "").strip()
            status = str(raw.get("status") or "PENDING").strip().upper() or "PENDING"
        else:
            milestone_id = _milestone_id(index)
            text = str(raw or "").strip()
            status = "PENDING"
        if not text:
            continue
        if milestone_id in seen_ids:
            milestone_id = _milestone_id(index)
        seen_ids.add(milestone_id)
        milestones.append({"id": milestone_id, "text": text, "status": status})
    return milestones


def _normalize_text_list(values: Iterable[str]) -> list[str]:
    return [value for value in _unique_strings(str(item).strip() for item in values) if value]


def persist_execution_plan(
    *,
    subject: str,
    data_root: Path,
    title: str,
    summary: str,
    origin: str,
    objective: str,
    coherent_outcome: str,
    closure_statement: str,
    out_of_scope: str,
    dependencies: Iterable[str],
    risk: str,
    verification_plan: str,
    milestones: Iterable[str] | Iterable[dict[str, Any]],
    split_triggers: Iterable[str],
    guild_orders_ref: str | None = None,
    dungeon_ref: str | None = None,
    dungeon_coverage: str = "N/A",
    links: Iterable[str] = (),
    quest_refs: Iterable[str] = (),
    related_run_ids: Iterable[str] = (),
    source: str = "plan-quests",
    plan_id: str | None = None,
) -> dict[str, Any]:
    root = plans_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    effective_plan_id = str(plan_id or _plan_id()).strip()
    if not effective_plan_id:
        raise ValueError("plan_id must not be empty")

    coverage = str(dungeon_coverage or "N/A").strip().upper()
    if coverage not in VALID_DUNGEON_COVERAGE:
        raise ValueError(f"Invalid dungeon coverage: {dungeon_coverage}")

    prior_revisions = _existing_revisions(root, effective_plan_id)
    revision_number = max((_revision_number(path) or 0 for path in prior_revisions), default=0) + 1
    revision_id = f"{effective_plan_id}::REVISION-{revision_number:03d}"
    path = root / _plan_filename(plan_id=effective_plan_id, revision_number=revision_number, title=title)
    previous_path = prior_revisions[-1] if prior_revisions else None
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": effective_plan_id,
        "revision_id": revision_id,
        "revision_number": revision_number,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "subject": subject,
        "source": source,
        "origin": origin,
        "title": title,
        "summary": summary,
        "objective": objective,
        "coherent_outcome": coherent_outcome,
        "closure_statement": closure_statement,
        "out_of_scope": out_of_scope,
        "dependencies": _normalize_text_list(dependencies),
        "risk": str(risk or "R0").strip().upper() or "R0",
        "verification_plan": verification_plan,
        "milestones": normalize_milestones(milestones),
        "split_triggers": _normalize_text_list(split_triggers),
        "guild_orders_ref": str(guild_orders_ref or "").strip() or None,
        "dungeon_ref": str(dungeon_ref or "").strip() or None,
        "dungeon_coverage": coverage,
        "links": _normalize_text_list(links),
        "related_run_ids": _normalize_text_list(related_run_ids),
        "quest_refs": _normalize_text_list(quest_refs),
        "previous_revision_path": str(previous_path.resolve()) if previous_path else None,
        "revision_history_paths": [str(item.resolve()) for item in prior_revisions] + [str(path.resolve())],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {
        **payload,
        "path": str(path.resolve()),
    }


def load_execution_plan(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid plan artifact: {path}")
    payload["path"] = str(Path(path).resolve())
    return payload


def parse_plan_artifact_refs(raw: str) -> list[str]:
    refs: list[str] = []
    for line in str(raw or "").splitlines():
        text = re.sub(r"^[-*]\s*", "", line.strip())
        if text:
            refs.append(text)
    return refs

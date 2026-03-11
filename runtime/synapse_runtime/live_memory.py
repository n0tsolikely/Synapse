"""Live subject-memory sidecar helpers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.governance_model import (
    AmbientSignal,
    ArtifactType,
    DraftshotState,
    ProposalKind,
    ProposalState,
    current_session_id,
    derive_world_state,
    evaluate_promotion,
    infer_interaction_mode,
    required_sidecar_paths,
)
from synapse_runtime.quest_acceptance import parse_quest_document, prequest_has_execution_readiness

LIVE_DIRNAME = ".synapse"
DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


class LiveMemoryError(RuntimeError):
    """Raised when live-memory operations fail."""


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "run"


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def live_root(data_root: Path) -> Path:
    return data_root / LIVE_DIRNAME


def _default_state(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "status": "idle",
        "world_state": "fog_of_war",
        "active_phase": "idle",
        "active_modes": ["ambient"],
        "current_capabilities": [],
        "active_constraints": [],
        "current_priorities": [],
        "recent_changes": [],
        "open_threads": [],
        "active_run_id": None,
        "last_run_id": None,
        "last_decision_id": None,
        "governed_execution_ready": False,
        "current_accepted_quest_id": None,
        "current_accepted_audit_bundle_path": None,
        "last_rehydrate_at": None,
    }


def _default_manifold(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "world_state": "fog_of_war",
        "active_phase": "idle",
        "active_modes": ["ambient"],
        "active_session_ids": [],
        "active_run_ids": [],
        "active_order_candidates": [],
        "active_quest_candidates": [],
        "pending_formalizations": [],
        "current_build_manual_candidate_backlog": [],
        "current_codex_shard_backlog": [],
        "current_disclosure_candidate_backlog": [],
        "current_talent_candidate_backlog": [],
        "current_decision_ledger_path": None,
        "current_discovery_ledger_path": None,
        "current_disclosure_ledger_path": None,
        "current_build_manual_candidate_path": None,
        "current_disclosure_candidate_path": None,
        "current_snapshot_candidate_path": None,
        "current_verification_status": None,
        "latest_verification_entries": [],
        "accepted_quest_ids": [],
        "accepted_quest_details": [],
        "current_accepted_quest_id": None,
        "current_accepted_quest_path": None,
        "current_accepted_audit_bundle_path": None,
        "governed_execution_ready": False,
        "last_updated_at": _now_iso(),
    }


def _default_active_run(subject: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active": False,
        "run_id": None,
        "subject": subject,
        "session_id": None,
        "title": None,
        "goal": None,
        "started_at": None,
        "updated_at": _now_iso(),
        "status": "idle",
        "interaction_mode": "maintenance",
        "plan": {"items": []},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "related_quests": [],
        "pending_questions": [],
        "result_summary": None,
    }


def _default_daily_ledger(subject: str, day: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": subject,
        "date": day,
        "entries": [],
    }


def ensure_live_scaffold(subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    decisions_dir = live / "DECISIONS"
    discoveries_dir = live / "DISCOVERIES"
    disclosures_dir = live / "DISCLOSURES"
    runs_dir = live / "RUNS"
    threads_dir = live / "THREADS"
    proposals_dir = live / "PROPOSALS"
    proposal_kinds = {
        "quests": proposals_dir / "quests",
        "side_quests": proposals_dir / "side_quests",
        "snapshots": proposals_dir / "snapshots",
        "control_sync": proposals_dir / "control_sync",
        "guild_orders": proposals_dir / "guild_orders",
        "codex": proposals_dir / "codex",
        "build_manual": proposals_dir / "build_manual",
        "talent": proposals_dir / "talent",
        "disclosures": proposals_dir / "disclosures",
    }

    decisions_dir.mkdir(parents=True, exist_ok=True)
    discoveries_dir.mkdir(parents=True, exist_ok=True)
    disclosures_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    threads_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir.mkdir(parents=True, exist_ok=True)
    for directory in proposal_kinds.values():
        directory.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    existing: list[str] = []

    vision_path = live / "VISION.md"
    vision_template = """# Vision (Live)

This is the concise, living identity for the subject.
Keep it short, truthful, and current.

## Project
- Name:
- One-line summary:

## Purpose
- Why this exists:

## Core experience / feel
- What it should feel like to use or operate:

## What exists now
- Known capabilities:

## What does not exist yet
- Explicit gaps:

## Non-negotiables
- Principles that must not be violated:

## Recent important shifts
- Changes in direction or scope:
"""
    if _write_if_missing(vision_path, vision_template):
        created.append(str(vision_path))
    else:
        existing.append(str(vision_path))

    state_path = live / "STATE.yaml"
    if not state_path.exists():
        _write_yaml(state_path, _default_state(subject))
        created.append(str(state_path))
    else:
        existing.append(str(state_path))

    manifold_path = live / "MANIFOLD.yaml"
    if not manifold_path.exists():
        _write_yaml(manifold_path, _default_manifold(subject))
        created.append(str(manifold_path))
    else:
        existing.append(str(manifold_path))

    rehydrate_path = live / "REHYDRATE.md"
    rehydrate_template = """# Rehydrate

Run `python3 runtime/synapse.py render-rehydrate` to refresh this file.
"""
    if _write_if_missing(rehydrate_path, rehydrate_template):
        created.append(str(rehydrate_path))
    else:
        existing.append(str(rehydrate_path))

    active_run_path = live / "ACTIVE_RUN.yaml"
    if not active_run_path.exists():
        _write_yaml(active_run_path, _default_active_run(subject))
        created.append(str(active_run_path))
    else:
        existing.append(str(active_run_path))

    today = _now().date().isoformat()
    decision_ledger_path = decisions_dir / f"{today}.yaml"
    if not decision_ledger_path.exists():
        _write_yaml(decision_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(decision_ledger_path))
    else:
        existing.append(str(decision_ledger_path))

    discovery_ledger_path = discoveries_dir / f"{today}.yaml"
    if not discovery_ledger_path.exists():
        _write_yaml(discovery_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(discovery_ledger_path))
    else:
        existing.append(str(discovery_ledger_path))

    disclosure_ledger_path = disclosures_dir / f"{today}.yaml"
    if not disclosure_ledger_path.exists():
        _write_yaml(disclosure_ledger_path, _default_daily_ledger(subject, today))
        created.append(str(disclosure_ledger_path))
    else:
        existing.append(str(disclosure_ledger_path))

    open_questions_path = threads_dir / "open_questions.md"
    open_questions_template = """# Open Questions

## Blocking
- None yet.

## Nonblocking
- None yet.
"""
    if _write_if_missing(open_questions_path, open_questions_template):
        created.append(str(open_questions_path))
    else:
        existing.append(str(open_questions_path))

    return {
        "live_root": str(live),
        "created": created,
        "existing": existing,
        "required_paths": {kind.value: str(path) for kind, path in required_sidecar_paths(data_root).items()},
    }


def _append_recent_change(state: dict[str, Any], note: str) -> None:
    entries = state.get("recent_changes")
    if not isinstance(entries, list):
        entries = []
    entries.append(f"{_now_iso()} - {note}")
    state["recent_changes"] = entries[-10:]


def _load_state(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_state(subject)
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    defaults = _default_state(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def _load_active_run(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_active_run(subject)
    defaults = _default_active_run(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    if data.get("subject") in (None, ""):
        data["subject"] = subject
    if "plan" not in data or not isinstance(data["plan"], dict):
        data["plan"] = {"items": []}
    if "items" not in data["plan"] or not isinstance(data["plan"]["items"], list):
        data["plan"]["items"] = []
    return data


def _load_manifold(path: Path, subject: str) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return _default_manifold(subject)
    defaults = _default_manifold(subject)
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def _daily_ledger_path(data_root: Path, ledger_name: str, stamp: str | None = None) -> Path:
    day = stamp or _now().date().isoformat()
    return live_root(data_root) / ledger_name / f"{day}.yaml"


def _append_ledger_entry(path: Path, *, subject: str, entry: dict[str, Any]) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        data = _default_daily_ledger(subject, path.stem)
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    data["entries"].append(entry)
    _write_yaml(path, data)
    return data


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


def _find_quest_file(data_root: Path, quest_id: str) -> Path | None:
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


def _parse_audit_bundle_path(subject: str, data_root: Path, quest_text: str) -> Path | None:
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


def _load_accepted_quest_details(subject: str, data_root: Path) -> list[dict[str, Any]]:
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
        execution_ready = False
        if bundle_path and bundle_path.exists():
            prequest = bundle_path / "01_PREQUEST.md"
            if prequest.exists():
                execution_ready = prequest_has_execution_readiness(prequest.read_text(encoding="utf-8", errors="replace"))
        details.append(
            {
                "quest_id": doc.quest_id or path.stem,
                "title": doc.title or path.stem,
                "path": str(path.resolve()),
                "audit_bundle_path": str(bundle_path.resolve()) if bundle_path else None,
                "execution_ready": execution_ready,
            }
        )
    return details


def _select_current_accepted_quest(details: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not details:
        return None
    for item in details:
        if item.get("execution_ready"):
            return item
    return details[0]


def _disclosure_phase_path(bundle: Path, trigger: str, status_labels: list[str]) -> Path:
    text = f"{trigger} {' '.join(status_labels)}".lower()
    if any(marker in text for marker in ("verify", "verification", "test", "unverified")):
        return bundle / "03_VERIFY.md"
    if any(marker in text for marker in ("anchor", "codex", "canonical", "orientation", "placement", "prequest")):
        return bundle / "01_PREQUEST.md"
    if any(marker in text for marker in ("outcome", "resume", "closeout")):
        return bundle / "04_OUTCOME.md"
    return bundle / "02_EXECUTION.md"


def _append_markdown_section(path: Path, heading: str, body: str, token: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if token in text:
        return False
    append = f"\n\n{heading}\n{body.strip()}\n"
    path.write_text(text.rstrip() + append, encoding="utf-8")
    return True


def _record_disclosure_in_quest_audits(
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
        quest_file = _find_quest_file(data_root, quest_key)
        if quest_file is None:
            continue
        bundle = _parse_audit_bundle_path(subject, data_root, quest_file.read_text(encoding="utf-8", errors="replace"))
        if bundle is None or not bundle.exists():
            continue

        summary_body = (
            f"- Related Quest: {quest_key}\n"
            f"- Disclosure ID: {disclosure_id}\n"
            f"- Trigger: {trigger}\n"
            f"- See: 05_DISCLOSURE.md"
        )
        if _append_markdown_section(bundle / "00_SUMMARY.md", "## Disclosure Gate Event", summary_body, disclosure_id):
            touched.append(str((bundle / "00_SUMMARY.md").resolve()))

        phase_path = _disclosure_phase_path(bundle, trigger, status_labels)
        phase_body = f"Disclosure ID: {disclosure_id}\n\n```\n{disclosure_block.strip()}\n```"
        if _append_markdown_section(phase_path, "## Disclosure Gate Event", phase_body, disclosure_id):
            touched.append(str(phase_path.resolve()))

        disclosure_path = bundle / "05_DISCLOSURE.md"
        if not disclosure_path.exists():
            disclosure_path.write_text(f"# 05_DISCLOSURE.md\n\n```\n{disclosure_block.strip()}\n```\n", encoding="utf-8")
        else:
            _append_markdown_section(disclosure_path, "## Disclosure Gate Event", f"```\n{disclosure_block.strip()}\n```", disclosure_id)
        touched.append(str(disclosure_path.resolve()))
    return touched


def _proposal_dir(live: Path, kind: ProposalKind) -> Path:
    mapping = {
        ProposalKind.QUEST: live / "PROPOSALS" / "quests",
        ProposalKind.SIDE_QUEST: live / "PROPOSALS" / "side_quests",
        ProposalKind.SNAPSHOT: live / "PROPOSALS" / "snapshots",
        ProposalKind.CONTROL_SYNC: live / "PROPOSALS" / "control_sync",
        ProposalKind.GUILD_ORDERS: live / "PROPOSALS" / "guild_orders",
        ProposalKind.CODEX: live / "PROPOSALS" / "codex",
        ProposalKind.BUILD_MANUAL: live / "PROPOSALS" / "build_manual",
        ProposalKind.TALENT: live / "PROPOSALS" / "talent",
        ProposalKind.DISCLOSURE: live / "PROPOSALS" / "disclosures",
    }
    return mapping[kind]


def _proposal_id(kind: ProposalKind, source_id: str, title: str) -> str:
    return f"{kind.value.upper()}__{source_id}__{_slugify(title,)}".upper().replace("-", "_")


def _entry_id(prefix: str) -> str:
    return f"{prefix}-{_now().strftime('%Y%m%d-%H%M%S-%f')}"


def _run_ledger_path(live: Path, run_data: dict[str, Any]) -> Path:
    existing = str(run_data.get("ledger_path") or "").strip()
    if existing:
        return Path(existing)
    run_id = str(run_data.get("run_id") or "").strip()
    if not run_id:
        raise LiveMemoryError("Cannot derive run ledger path without run_id.")
    slug = _slugify(str(run_data.get("title") or run_id))
    return live / "RUNS" / f"{run_id}__{slug}.yaml"


def _sync_run_ledger(live: Path, run_data: dict[str, Any]) -> str | None:
    run_id = str(run_data.get("run_id") or "").strip()
    if not run_id:
        return None
    ledger_path = _run_ledger_path(live, run_data)
    run_data["ledger_path"] = str(ledger_path)
    _write_yaml(ledger_path, run_data)
    return str(ledger_path)


def _read_ledger_entries(path: Path) -> list[dict[str, Any]]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return []
    entries = data.get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _classify_verification_status(entries: Iterable[str]) -> str | None:
    status: str | None = None
    for raw in entries:
        text = str(raw).strip().lower()
        if not text:
            continue
        if any(token in text for token in ("blocked", "unable", "unverified")):
            status = "BLOCKED"
        if any(token in text for token in ("fail", "failed", "error")):
            return "FAIL"
        if any(token in text for token in ("pass", "passed", "ok", "success")) and status is None:
            status = "PASS"
    return status


def _load_recent_daily_entries(data_root: Path, ledger_name: str, limit: int) -> list[dict[str, Any]]:
    ledger_dir = live_root(data_root) / ledger_name
    paths = sorted(ledger_dir.glob("*.yaml"))
    entries: list[dict[str, Any]] = []
    for path in reversed(paths):
        entries.extend(reversed(_read_ledger_entries(path)))
        if len(entries) >= limit:
            break
    return list(reversed(entries[-limit:]))


def _load_proposal_records(live: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    proposals_root = live / "PROPOSALS"
    if not proposals_root.exists():
        return records
    for path in sorted(proposals_root.rglob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        data["path"] = str(path)
        records.append(data)
    return records


def _write_proposals(
    *,
    live: Path,
    subject: str,
    source_id: str,
    interaction_mode: str,
    promotions: list[dict[str, Any]],
) -> list[str]:
    written: list[str] = []
    for proposal in promotions:
        kind = ProposalKind(str(proposal["kind"]))
        proposal_path = _proposal_dir(live, kind) / f"{proposal['proposal_id']}.yaml"
        payload = {
            "schema_version": 1,
            "proposal_id": proposal["proposal_id"],
            "subject": subject,
            "kind": kind.value,
            "state": proposal["state"],
            "interaction_mode": interaction_mode,
            "source_id": source_id,
            "created_at": proposal.get("created_at") or _now_iso(),
            "updated_at": _now_iso(),
            "title": proposal["title"],
            "summary": proposal["summary"],
            "reason": proposal["reason"],
            "blockers": proposal.get("blockers", []),
            "evidence": proposal.get("evidence", []),
            "codex_implications": proposal.get("codex_implications", []),
        }
        _write_yaml(proposal_path, payload)
        written.append(str(proposal_path))
    return written


def _sync_sidecar(
    *,
    subject: str,
    data_root: Path,
    active_run: dict[str, Any],
    signal: AmbientSignal | None = None,
    decisions_path: Path | None = None,
    discoveries_path: Path | None = None,
    disclosures_path: Path | None = None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    world_state = derive_world_state(data_root)
    inferred_mode = infer_interaction_mode(signal) if signal is not None else active_run.get("interaction_mode") or "maintenance"
    interaction_mode = str(getattr(inferred_mode, "value", inferred_mode) or "maintenance")
    session_id = active_run.get("session_id") or current_session_id()
    run_id = active_run.get("run_id")
    accepted_details = _load_accepted_quest_details(subject, data_root)
    current_accepted = _select_current_accepted_quest(accepted_details)
    governed_execution_ready = bool(
        current_accepted
        and current_accepted.get("execution_ready")
        and world_state.value == "fog_lifted"
    )

    state["world_state"] = world_state.value
    state["active_phase"] = "execute" if run_id else ("incubation" if world_state.value == "fog_of_war" else "idle")
    state["active_modes"] = ["ambient", interaction_mode]
    state["active_run_id"] = run_id
    state["status"] = "active" if active_run.get("active") else "idle"
    state["governed_execution_ready"] = governed_execution_ready
    state["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    state["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    if decisions_path is not None:
        state["last_decision_id"] = decisions_path.stem
    _write_yaml(state_path, state)

    manifold["world_state"] = world_state.value
    manifold["active_phase"] = state["active_phase"]
    manifold["active_modes"] = state["active_modes"]
    manifold["active_run_ids"] = [run_id] if run_id else []
    manifold["accepted_quest_ids"] = [str(item.get("quest_id")) for item in accepted_details if item.get("quest_id")]
    manifold["accepted_quest_details"] = accepted_details
    manifold["current_accepted_quest_id"] = current_accepted.get("quest_id") if current_accepted else None
    manifold["current_accepted_quest_path"] = current_accepted.get("path") if current_accepted else None
    manifold["current_accepted_audit_bundle_path"] = (
        current_accepted.get("audit_bundle_path") if current_accepted else None
    )
    manifold["governed_execution_ready"] = governed_execution_ready
    if session_id:
        manifold["active_session_ids"] = [session_id]
    if decisions_path is not None:
        manifold["current_decision_ledger_path"] = str(decisions_path)
    if discoveries_path is not None:
        manifold["current_discovery_ledger_path"] = str(discoveries_path)
    if disclosures_path is not None:
        manifold["current_disclosure_ledger_path"] = str(disclosures_path)

    proposal_paths: list[str] = []
    pending = list(manifold.get("pending_formalizations") or [])
    build_manual_candidates = list(manifold.get("current_build_manual_candidate_backlog") or [])
    quest_candidates = list(manifold.get("active_quest_candidates") or [])
    talent_candidates = list(manifold.get("current_talent_candidate_backlog") or [])
    codex_candidates = list(manifold.get("current_codex_shard_backlog") or [])
    disclosure_candidates = list(manifold.get("current_disclosure_candidate_backlog") or [])
    order_candidates = list(manifold.get("active_order_candidates") or [])
    build_manual_candidate_path = manifold.get("current_build_manual_candidate_path")
    disclosure_candidate_path = manifold.get("current_disclosure_candidate_path")
    snapshot_candidate_path = manifold.get("current_snapshot_candidate_path")
    verification_entries = list(manifold.get("latest_verification_entries") or [])
    verification_status = manifold.get("current_verification_status")
    if signal is not None:
        if signal.verification:
            verification_entries.extend(str(item) for item in signal.verification if str(item).strip())
            verification_entries = verification_entries[-10:]
            verification_status = _classify_verification_status(verification_entries) or verification_status
        promotions = evaluate_promotion(signal, data_root)
        promotion_payloads: list[dict[str, Any]] = []
        for promotion in promotions:
            source_id = run_id or "NO_RUN"
            proposal_id = _proposal_id(promotion.kind, source_id, promotion.title)
            promotion_payloads.append(
                {
                    "proposal_id": proposal_id,
                    "kind": promotion.kind.value,
                    "state": promotion.state.value,
                    "title": promotion.title,
                    "summary": promotion.summary,
                    "reason": promotion.reason,
                    "blockers": list(promotion.blockers),
                    "evidence": list(promotion.evidence),
                    "codex_implications": list(promotion.codex_implications),
                    "created_at": _now_iso(),
                }
            )
            if promotion.state in {ProposalState.PROPOSED, ProposalState.READY, ProposalState.BLOCKED, ProposalState.ESCALATED}:
                if proposal_id not in pending:
                    pending.append(proposal_id)
            if promotion.kind in {ProposalKind.QUEST, ProposalKind.SIDE_QUEST}:
                if proposal_id not in quest_candidates:
                    quest_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.GUILD_ORDERS:
                if proposal_id not in order_candidates:
                    order_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.TALENT:
                if proposal_id not in talent_candidates:
                    talent_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.CODEX:
                if proposal_id not in codex_candidates:
                    codex_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.BUILD_MANUAL:
                if proposal_id not in build_manual_candidates:
                    build_manual_candidates.append(proposal_id)
            if promotion.kind == ProposalKind.DISCLOSURE:
                if proposal_id not in disclosure_candidates:
                    disclosure_candidates.append(proposal_id)
        proposal_paths = _write_proposals(
            live=live,
            subject=subject,
            source_id=run_id or "NO_RUN",
            interaction_mode=interaction_mode,
            promotions=promotion_payloads,
        )

    manifold["active_order_candidates"] = order_candidates
    manifold["active_quest_candidates"] = quest_candidates
    manifold["current_build_manual_candidate_backlog"] = build_manual_candidates
    manifold["current_talent_candidate_backlog"] = talent_candidates
    manifold["current_codex_shard_backlog"] = codex_candidates
    manifold["current_disclosure_candidate_backlog"] = disclosure_candidates
    manifold["pending_formalizations"] = pending
    if signal is not None:
        build_manual_candidate_path = next(
            (path for path in proposal_paths if "/build_manual/" in path),
            build_manual_candidate_path,
        )
        disclosure_candidate_path = next(
            (path for path in proposal_paths if "/disclosures/" in path),
            disclosure_candidate_path,
        )
        snapshot_candidate_path = next((path for path in proposal_paths if "/snapshots/" in path), snapshot_candidate_path)
    manifold["current_build_manual_candidate_path"] = build_manual_candidate_path
    manifold["current_disclosure_candidate_path"] = disclosure_candidate_path
    manifold["current_snapshot_candidate_path"] = snapshot_candidate_path
    manifold["current_verification_status"] = verification_status
    manifold["latest_verification_entries"] = verification_entries
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(manifold_path, manifold)

    return {
        "state_path": str(state_path),
        "manifold_path": str(manifold_path),
        "proposal_paths": proposal_paths,
        "interaction_mode": interaction_mode,
        "world_state": world_state.value,
    }


def _next_item_id(items: list[dict[str, Any]]) -> str:
    ids = [item.get("id", "") for item in items if isinstance(item, dict)]
    numbers = []
    for item_id in ids:
        match = re.search(r"(\d+)$", str(item_id))
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers or [0]) + 1
    return f"ITEM-{next_num:03d}"


def _normalize_items(items: Iterable[str], existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    existing_items = existing or []
    results: list[dict[str, Any]] = []
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
            raise LiveMemoryError(f"Invalid status format '{raw}'. Use ITEM-###:STATUS")
        updates.append((key.strip(), status.strip().upper()))
    return updates


def _is_terminal_status(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().upper() in {"DONE", "COMPLETED", "SKIPPED", "CANCELED", "ABANDONED"}


def _extract_run_id(filename: str) -> str:
    return filename.split("__", 1)[0]


def _extract_decision_id(filename: str) -> str:
    return filename.split(".", 1)[0]


def load_active_run_record(*, subject: str, data_root: Path) -> dict[str, Any]:
    ensure_live_scaffold(subject, data_root)
    return _load_active_run(live_root(data_root) / "ACTIVE_RUN.yaml", subject)


def list_proposals(
    *,
    data_root: Path,
    kind: ProposalKind | None = None,
    state: ProposalState | None = None,
) -> list[dict[str, Any]]:
    live = live_root(data_root)
    records = _load_proposal_records(live)
    results: list[dict[str, Any]] = []
    for record in records:
        if kind is not None and str(record.get("kind") or "") != kind.value:
            continue
        if state is not None and str(record.get("state") or "") != state.value:
            continue
        results.append(record)
    return results


def mark_proposal_state(
    *,
    data_root: Path,
    proposal_id: str,
    state: ProposalState,
    artifact_path: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    live = live_root(data_root)
    proposals = _load_proposal_records(live)
    for proposal in proposals:
        if str(proposal.get("proposal_id") or "") != proposal_id:
            continue
        path = Path(str(proposal["path"]))
        proposal["state"] = state.value
        proposal["updated_at"] = _now_iso()
        if artifact_path:
            proposal["formalized_artifact_path"] = artifact_path
        if note:
            notes = proposal.get("notes")
            if not isinstance(notes, list):
                notes = []
            notes.append(note)
            proposal["notes"] = notes[-10:]
        proposal.pop("path", None)
        _write_yaml(path, proposal)
        return dict(proposal, path=str(path))
    raise LiveMemoryError(f"Proposal not found: {proposal_id}")


def run_start(
    *,
    subject: str,
    data_root: Path,
    title: str,
    goal: str | None,
    items: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    scaffold = ensure_live_scaffold(subject, data_root)

    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"

    state = _load_state(state_path, subject)
    existing_run = _load_active_run(run_path, subject)

    run_id = f"RUN-{_now().strftime('%Y%m%d-%H%M%S')}"
    plan_items = _normalize_items(items, existing_run.get("plan", {}).get("items", []))
    session_id = current_session_id()
    signal = AmbientSignal(
        source="run-start",
        subject=subject,
        title=title,
        summary=goal,
        notes=tuple(items),
        status="active",
    )

    run_data = {
        "schema_version": 1,
        "active": True,
        "run_id": run_id,
        "subject": subject,
        "session_id": session_id,
        "title": title,
        "goal": goal,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "active",
        "interaction_mode": infer_interaction_mode(signal).value,
        "plan": {"items": plan_items},
        "commands": [],
        "files_touched": [],
        "notes": [],
        "verification": [],
        "related_sidequests": [],
        "related_quests": [],
        "pending_questions": [],
        "result_summary": None,
    }

    _write_yaml(run_path, run_data)
    ledger_path = _sync_run_ledger(live, run_data)
    _write_yaml(run_path, run_data)

    state["active_run_id"] = run_id
    state["last_run_id"] = run_id
    state["status"] = "active"
    _append_recent_change(state, f"Run started: {title}")
    _write_yaml(state_path, state)
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, signal=signal)

    return {
        "run_path": str(run_path),
        "run_id": run_id,
        "title": title,
        "goal": goal,
        "items": plan_items,
        "ledger_path": ledger_path,
        "scaffold": scaffold,
        "sidecar": sidecar,
    }


def run_update(
    *,
    subject: str,
    data_root: Path,
    add_items: list[str],
    status_updates: list[str],
    commands: list[str],
    files_touched: list[str],
    notes: list[str],
    verification: list[str],
    related_sidequests: list[str],
    related_quests: list[str],
    status: str | None,
    summary: str | None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    discoveries_path = _daily_ledger_path(data_root, "DISCOVERIES")

    run_data = _load_active_run(run_path, subject)
    if not run_data.get("run_id"):
        raise LiveMemoryError("No ACTIVE_RUN found. Run `python3 runtime/synapse.py run-start` first.")

    plan_items = run_data.get("plan", {}).get("items", [])
    if not isinstance(plan_items, list):
        plan_items = []

    new_items = _normalize_items(add_items, plan_items)
    plan_items.extend(new_items)

    updates = _parse_status_updates(status_updates)
    for item_id, status_value in updates:
        matched = False
        for item in plan_items:
            if str(item.get("id")) == item_id:
                item["status"] = status_value
                matched = True
        if not matched:
            raise LiveMemoryError(f"No plan item with id '{item_id}'.")

    run_data["plan"] = {"items": plan_items}

    if commands:
        run_data.setdefault("commands", [])
        run_data["commands"].extend(commands)
    if files_touched:
        run_data.setdefault("files_touched", [])
        run_data["files_touched"].extend(_normalize_relpaths(data_root, files_touched))
    if notes:
        run_data.setdefault("notes", [])
        run_data["notes"].extend(notes)
    if verification:
        run_data.setdefault("verification", [])
        run_data["verification"].extend(verification)
    if related_sidequests:
        run_data.setdefault("related_sidequests", [])
        run_data["related_sidequests"].extend(related_sidequests)
    if related_quests:
        run_data.setdefault("related_quests", [])
        run_data["related_quests"].extend(related_quests)
    if status:
        run_data["status"] = status
    if summary:
        run_data["result_summary"] = summary

    signal = AmbientSignal(
        source="run-update",
        subject=subject,
        title=str(run_data.get("title") or ""),
        summary=summary or run_data.get("result_summary"),
        notes=tuple(notes),
        commands=tuple(commands),
        files_touched=tuple(run_data.get("files_touched", [])),
        verification=tuple(verification),
        related_sidequests=tuple(related_sidequests),
        related_quests=tuple(related_quests),
        status=status or str(run_data.get("status") or ""),
    )
    run_data["interaction_mode"] = infer_interaction_mode(signal).value
    run_data["updated_at"] = _now_iso()

    _write_yaml(run_path, run_data)
    ledger_path = _sync_run_ledger(live, run_data)
    _write_yaml(run_path, run_data)

    state = _load_state(state_path, subject)
    state["active_run_id"] = run_data.get("run_id")
    state["status"] = "active"
    change_note = "Run updated"
    if summary:
        change_note = f"Run updated: {summary}"
    _append_recent_change(state, change_note)
    _write_yaml(state_path, state)

    discovery_entries: list[dict[str, Any]] = []
    for note in list(notes) + ([summary] if summary else []):
        if not note:
            continue
        discovery_entries.append(
            {
                "discovery_id": _entry_id("DISCOVERY"),
                "logged_at": _now_iso(),
                "kind": run_data["interaction_mode"],
                "summary": note,
                "evidence": {
                    "run_id": run_data.get("run_id"),
                    "files_touched": run_data.get("files_touched", []),
                    "commands": commands,
                    "verification": verification,
                },
            }
        )
    for entry in discovery_entries:
        _append_ledger_entry(discoveries_path, subject=subject, entry=entry)

    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        discoveries_path=discoveries_path,
    )

    return {
        "run_path": str(run_path),
        "run_id": run_data.get("run_id"),
        "added_items": new_items,
        "status_updates": updates,
        "ledger_path": ledger_path,
        "discoveries_path": str(discoveries_path),
        "sidecar": sidecar,
    }


def run_finalize(
    *,
    subject: str,
    data_root: Path,
    status: str,
    summary: str | None,
) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"

    run_data = _load_active_run(run_path, subject)
    run_id = run_data.get("run_id")
    if not run_id:
        raise LiveMemoryError("No ACTIVE_RUN found to finalize.")

    if status.strip().lower() == "completed":
        plan_items = run_data.get("plan", {}).get("items", [])
        open_items = [
            item
            for item in plan_items
            if not _is_terminal_status(str(item.get("status") or ""))
        ]
        if open_items:
            details = ", ".join(f"{item.get('id')}={item.get('status')}" for item in open_items)
            raise LiveMemoryError(f"Cannot finalize as completed with open plan items: {details}")

    run_data["active"] = False
    run_data["status"] = status
    run_data["result_summary"] = summary or run_data.get("result_summary")
    run_data["updated_at"] = _now_iso()
    run_data["finalized_at"] = _now_iso()

    runs_dir = live / "RUNS"
    runs_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(run_data.get("title") or run_id)
    archive_name = f"{run_id}__{slug}.yaml"
    archive_path = runs_dir / archive_name
    existing_ledger = str(run_data.get("ledger_path") or "").strip()
    same_ledger = existing_ledger and Path(existing_ledger).resolve() == archive_path.resolve()
    if archive_path.exists() and not same_ledger:
        raise LiveMemoryError(f"Archived run already exists: {archive_path}")

    run_data["ledger_path"] = str(archive_path)
    _write_yaml(archive_path, run_data)
    signal = AmbientSignal(
        source="run-finalize",
        subject=subject,
        title=str(run_data.get("title") or ""),
        summary=run_data.get("result_summary"),
        notes=tuple([summary] if summary else []),
        commands=tuple(run_data.get("commands", [])),
        files_touched=tuple(run_data.get("files_touched", [])),
        verification=tuple(run_data.get("verification", [])),
        related_sidequests=tuple(run_data.get("related_sidequests", [])),
        related_quests=tuple(run_data.get("related_quests", [])),
        status=status,
    )
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, signal=signal)

    _write_yaml(run_path, _default_active_run(subject))

    state = _load_state(state_path, subject)
    state["active_run_id"] = None
    state["last_run_id"] = run_id
    state["status"] = "idle"
    _append_recent_change(state, f"Run finalized: {run_data.get('title')}")
    _write_yaml(state_path, state)
    _sync_sidecar(subject=subject, data_root=data_root, active_run=_default_active_run(subject))

    return {
        "archive_path": str(archive_path),
        "run_id": run_id,
        "sidecar": sidecar,
    }


def log_decision(
    *,
    subject: str,
    data_root: Path,
    title: str,
    summary: str,
    why: str | None,
    constraints: list[str],
    tradeoffs: list[str],
    related_runs: list[str],
    related_quests: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    decisions_dir = live / "DECISIONS"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = _daily_ledger_path(data_root, "DECISIONS")
    run_data = _load_active_run(live / "ACTIVE_RUN.yaml", subject)

    timestamp = _now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(title)
    filename = f"DECISION__{timestamp}__{slug}.md"
    path = decisions_dir / filename
    if path.exists():
        raise LiveMemoryError(f"Decision already exists: {path}")

    lines = [
        f"# {title}",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {_now_iso()}",
        "",
        "## Summary",
        summary.strip(),
        "",
    ]

    if why:
        lines.extend(["## Rationale", why.strip(), ""])

    if constraints:
        lines.append("## Constraints")
        lines.extend([f"- {c}" for c in constraints])
        lines.append("")

    if tradeoffs:
        lines.append("## Tradeoffs")
        lines.extend([f"- {t}" for t in tradeoffs])
        lines.append("")

    if related_runs or related_quests:
        lines.append("## Related")
        for run in related_runs:
            lines.append(f"- Run: {run}")
        for quest in related_quests:
            lines.append(f"- Quest: {quest}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    ledger_entry = {
        "decision_id": _extract_decision_id(path.name),
        "logged_at": _now_iso(),
        "title": title,
        "summary": summary,
        "why": why,
        "constraints": constraints,
        "tradeoffs": tradeoffs,
        "related_runs": related_runs,
        "related_quests": related_quests,
        "artifact_path": str(path),
        "binding": True,
    }
    _append_ledger_entry(decisions_path, subject=subject, entry=ledger_entry)

    state_path = live / "STATE.yaml"
    state = _load_state(state_path, subject)
    state["last_decision_id"] = _extract_decision_id(path.name)
    _append_recent_change(state, f"Decision logged: {title}")
    _write_yaml(state_path, state)
    signal = AmbientSignal(
        source="log-decision",
        subject=subject,
        title=title,
        summary=summary,
        notes=tuple((why,) if why else ()),
        files_touched=tuple(_normalize_relpaths(data_root, [str(path)])),
        related_quests=tuple(related_quests),
        related_sidequests=(),
        status="binding",
    )
    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        decisions_path=decisions_path,
    )

    return {
        "decision_path": str(path),
        "decisions_ledger_path": str(decisions_path),
        "sidecar": sidecar,
    }


def log_disclosure(
    *,
    subject: str,
    data_root: Path,
    trigger: str,
    expected: str,
    provable: str,
    status_labels: list[str],
    impact: str,
    safe_options: list[str],
    decision_needed: str,
    related_runs: list[str],
    related_quests: list[str],
) -> dict[str, Any]:
    live = live_root(data_root)
    disclosures_dir = live / "DISCLOSURES"
    disclosures_dir.mkdir(parents=True, exist_ok=True)
    disclosures_path = _daily_ledger_path(data_root, "DISCLOSURES")
    run_data = _load_active_run(live / "ACTIVE_RUN.yaml", subject)

    timestamp = _now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(trigger)
    filename = f"DISCLOSURE__{timestamp}__{slug}.md"
    path = disclosures_dir / filename
    if path.exists():
        raise LiveMemoryError(f"Disclosure already exists: {path}")

    labels = [label.strip().upper() for label in status_labels if str(label).strip()]
    options = [option.strip() for option in safe_options if str(option).strip()]
    if not options:
        options = ["HALT until Brains chooses the next legal action."]
    disclosure_id = _extract_decision_id(path.name)
    disclosure_block = "\n".join(
        [
            "DISCLOSURE GATE -- EVENT",
            "",
            "Trigger:",
            trigger.strip(),
            "Expected:",
            expected.strip(),
            "Provable:",
            provable.strip(),
            "Status Labels:",
            *[f"- {label}" for label in labels],
            "Impact:",
            impact.strip(),
            "Safe Options:",
            *[f"- {option}" for option in options],
            "Decision Needed From Brains:",
            decision_needed.strip(),
        ]
    )

    lines = [
        "DISCLOSURE GATE -- EVENT",
        "",
        f"- Subject: {subject}",
        f"- Logged at: {_now_iso()}",
        "",
        "Trigger:",
        trigger.strip(),
        "",
        "Expected:",
        expected.strip(),
        "",
        "Provable:",
        provable.strip(),
        "",
        "Status Labels:",
        *(f"- {label}" for label in labels),
        "",
        "Impact:",
        impact.strip(),
        "",
        "Safe Options:",
        *(f"- {option}" for option in options),
        "",
        "Decision Needed From Brains:",
        decision_needed.strip(),
        "",
    ]
    if related_runs or related_quests:
        lines.extend(["Related:", *(f"- Run: {run}" for run in related_runs), *(f"- Quest: {quest}" for quest in related_quests), ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    audit_touches = _record_disclosure_in_quest_audits(
        subject=subject,
        data_root=data_root,
        related_quests=related_quests,
        disclosure_id=disclosure_id,
        disclosure_block=disclosure_block,
        trigger=trigger,
        status_labels=labels,
    )

    ledger_entry = {
        "disclosure_id": disclosure_id,
        "logged_at": _now_iso(),
        "trigger": trigger,
        "expected": expected,
        "provable": provable,
        "status_labels": labels,
        "impact": impact,
        "safe_options": options,
        "decision_needed": decision_needed,
        "related_runs": related_runs,
        "related_quests": related_quests,
        "artifact_path": str(path),
        "audit_paths": audit_touches,
    }
    _append_ledger_entry(disclosures_path, subject=subject, entry=ledger_entry)

    state_path = live / "STATE.yaml"
    state = _load_state(state_path, subject)
    _append_recent_change(state, f"Disclosure logged: {trigger}")
    _write_yaml(state_path, state)
    signal = AmbientSignal(
        source="log-disclosure",
        subject=subject,
        title=trigger,
        summary=impact,
        notes=tuple([expected, provable, decision_needed, *options]),
        files_touched=tuple(_normalize_relpaths(data_root, [str(path), *audit_touches])),
        related_quests=tuple(related_quests),
        related_sidequests=(),
        status="blocked" if any(label in {"BLOCKED", "UNVERIFIED", "UNKNOWN"} for label in labels) else "unknown",
    )
    sidecar = _sync_sidecar(
        subject=subject,
        data_root=data_root,
        active_run=run_data,
        signal=signal,
        disclosures_path=disclosures_path,
    )

    return {
        "disclosure_path": str(path),
        "disclosures_ledger_path": str(disclosures_path),
        "sidecar": sidecar,
    }


def record_quest_acceptance(
    *,
    subject: str,
    data_root: Path,
    quest_id: str,
    quest_title: str,
    accepted_path: Path,
    audit_bundle_path: Path,
    control_sync_state_path: Path,
) -> dict[str, Any]:
    live = live_root(data_root)
    ensure_live_scaffold(subject, data_root)
    state_path = live / "STATE.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    discoveries_path = _daily_ledger_path(data_root, "DISCOVERIES")
    run_data = _load_active_run(run_path, subject)

    if run_data.get("run_id"):
        related = list(run_data.get("related_quests") or [])
        if quest_id not in related:
            related.append(quest_id)
            run_data["related_quests"] = related
            run_data["updated_at"] = _now_iso()
            _write_yaml(run_path, run_data)
            _sync_run_ledger(live, run_data)
            _write_yaml(run_path, run_data)

    discovery_entry = {
        "discovery_id": _entry_id("DISCOVERY"),
        "logged_at": _now_iso(),
        "kind": "governed_execution_readiness",
        "summary": f"Quest accepted for governed execution: {quest_id} - {quest_title}",
        "evidence": {
            "accepted_path": str(accepted_path.resolve()),
            "audit_bundle_path": str(audit_bundle_path.resolve()),
            "control_sync_state_path": str(control_sync_state_path.resolve()),
        },
    }
    _append_ledger_entry(discoveries_path, subject=subject, entry=discovery_entry)

    state = _load_state(state_path, subject)
    _append_recent_change(state, f"Quest accepted: {quest_id}")
    _write_yaml(state_path, state)
    sidecar = _sync_sidecar(subject=subject, data_root=data_root, active_run=run_data, discoveries_path=discoveries_path)
    return {
        "discoveries_path": str(discoveries_path),
        "sidecar": sidecar,
    }


def render_rehydrate(*, subject: str, data_root: Path) -> dict[str, Any]:
    live = live_root(data_root)
    state_path = live / "STATE.yaml"
    manifold_path = live / "MANIFOLD.yaml"
    run_path = live / "ACTIVE_RUN.yaml"
    rehydrate_path = live / "REHYDRATE.md"

    state = _load_state(state_path, subject)
    manifold = _load_manifold(manifold_path, subject)
    active_run = _load_active_run(run_path, subject)

    decisions_dir = live / "DECISIONS"
    discoveries_dir = live / "DISCOVERIES"
    disclosures_dir = live / "DISCLOSURES"
    runs_dir = live / "RUNS"
    threads_path = live / "THREADS" / "open_questions.md"
    build_manual_path = data_root / "Build_Manual" / "BUILD_MANUAL.md"
    proposals = _load_proposal_records(live)

    recent_decisions = sorted(decisions_dir.glob("DECISION__*.md"))[-5:]
    recent_runs = sorted(runs_dir.glob("RUN-*.yaml"))[-3:]
    recent_decision_entries = _load_recent_daily_entries(data_root, "DECISIONS", 5)
    recent_discovery_entries = _load_recent_daily_entries(data_root, "DISCOVERIES", 5)
    recent_disclosure_entries = _load_recent_daily_entries(data_root, "DISCLOSURES", 5)
    pending_proposals = [
        proposal
        for proposal in proposals
        if str(proposal.get("state") or "") in {
            ProposalState.PROPOSED.value,
            ProposalState.READY.value,
            ProposalState.BLOCKED.value,
            ProposalState.ESCALATED.value,
        }
    ][-8:]

    active_run_id = active_run.get("run_id")
    state["active_run_id"] = active_run_id
    state["status"] = "active" if active_run_id else "idle"
    if not state.get("last_run_id") and recent_runs:
        state["last_run_id"] = _extract_run_id(recent_runs[-1].name)
    if not state.get("last_decision_id") and recent_decisions:
        state["last_decision_id"] = _extract_decision_id(recent_decisions[-1].name)

    lines = [
        "# Rehydrate",
        "",
        f"Subject: {subject}",
        f"Last updated: {_now_iso()}",
        "",
        "## What this project is",
        "See VISION.md for the current concise identity.",
        "",
        "## Current state",
        f"- Status: {state.get('status')}",
        f"- World state: {state.get('world_state')}",
        f"- Active phase: {state.get('active_phase')}",
        f"- Active modes: {', '.join(state.get('active_modes') or []) or 'none'}",
        f"- Governed execution ready: {'YES' if manifold.get('governed_execution_ready') else 'NO'}",
    ]
    if manifold.get("current_verification_status"):
        lines.append(f"- Verification status: {manifold.get('current_verification_status')}")
    if manifold.get("accepted_quest_ids"):
        lines.append(f"- Accepted quests: {', '.join(manifold.get('accepted_quest_ids') or [])}")

    if active_run_id:
        lines.append(f"- Active run: {active_run_id}")
    else:
        lines.append("- Active run: none")

    if state.get("last_run_id"):
        lines.append(f"- Last run: {state.get('last_run_id')}")

    if state.get("last_decision_id"):
        lines.append(f"- Last decision: {state.get('last_decision_id')}")

    lines.append("")

    if active_run_id:
        lines.append("## Active run")
        lines.append(f"- Run: {active_run_id} — {active_run.get('title')}")
        if active_run.get("goal"):
            lines.append(f"- Goal: {active_run.get('goal')}")
        items = active_run.get("plan", {}).get("items", [])
        if items:
            lines.append("- Plan items:")
            for item in items:
                lines.append(f"  - [{item.get('status')}] {item.get('id')}: {item.get('text')}")
        lines.append("")

    if pending_proposals:
        lines.append("## Pending formalizations")
        for proposal in pending_proposals:
            lines.append(
                f"- [{proposal.get('state')}] {proposal.get('kind')}: {proposal.get('proposal_id')} - {proposal.get('title')}"
            )
        lines.append("")

    if manifold.get("current_accepted_quest_id"):
        lines.append("## Governed execution")
        lines.append(
            f"- Current accepted quest: {manifold.get('current_accepted_quest_id')}"
            f" - {next((item.get('title') for item in manifold.get('accepted_quest_details', []) if item.get('quest_id') == manifold.get('current_accepted_quest_id')), '')}"
        )
        if manifold.get("current_accepted_quest_path"):
            lines.append(f"- Accepted quest path: {manifold.get('current_accepted_quest_path')}")
        if manifold.get("current_accepted_audit_bundle_path"):
            lines.append(f"- Audit bundle: {manifold.get('current_accepted_audit_bundle_path')}")
        lines.append(
            f"- Ready to execute: {'YES' if manifold.get('governed_execution_ready') else 'NO'}"
        )
        extra = [
            item.get("quest_id")
            for item in manifold.get("accepted_quest_details", [])
            if item.get("quest_id") != manifold.get("current_accepted_quest_id")
        ]
        if extra:
            lines.append(f"- Additional accepted quests: {', '.join(str(item) for item in extra)}")
        lines.append("")

    if recent_decision_entries:
        lines.append("## Recent binding decisions")
        for entry in recent_decision_entries:
            lines.append(f"- {entry.get('decision_id')}: {entry.get('title')} - {entry.get('summary')}")
        lines.append("")

    if recent_discovery_entries:
        lines.append("## Recent discoveries")
        for entry in recent_discovery_entries:
            lines.append(f"- {entry.get('discovery_id')}: {entry.get('summary')}")
        lines.append("")

    if manifold.get("latest_verification_entries"):
        lines.append("## Recent verification")
        for entry in list(manifold.get("latest_verification_entries") or [])[-5:]:
            lines.append(f"- {entry}")
        lines.append("")

    if recent_disclosure_entries:
        lines.append("## Recent disclosures")
        for entry in recent_disclosure_entries:
            labels = ", ".join(entry.get("status_labels") or []) or "UNSPECIFIED"
            lines.append(f"- {entry.get('disclosure_id')}: [{labels}] {entry.get('trigger')} -> {entry.get('decision_needed')}")
        lines.append("")

    if state.get("recent_changes"):
        lines.append("## Recent changes")
        for entry in state.get("recent_changes", [])[-5:]:
            lines.append(f"- {entry}")
        lines.append("")

    if recent_decisions:
        lines.append("## Recent decisions")
        for decision in recent_decisions:
            lines.append(f"- {decision.name}")
        lines.append("")

    if recent_runs:
        lines.append("## Recent runs")
        for run in recent_runs:
            lines.append(f"- {run.name}")
        lines.append("")

    if threads_path.exists():
        lines.append("## Open questions")
        lines.append(threads_path.read_text(encoding="utf-8").strip())
        lines.append("")

    lines.append("## Files")
    lines.append(f"- {live / 'VISION.md'}")
    lines.append(f"- {state_path}")
    lines.append(f"- {manifold_path}")
    lines.append(f"- {run_path}")
    lines.append(f"- {decisions_dir}")
    lines.append(f"- {discoveries_dir}")
    lines.append(f"- {disclosures_dir}")
    lines.append(f"- {runs_dir}")
    if build_manual_path.exists():
        lines.append(f"- {build_manual_path}")

    rehydrate_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    state["last_rehydrate_at"] = _now_iso()
    manifold["current_decision_ledger_path"] = str(_daily_ledger_path(data_root, "DECISIONS"))
    manifold["current_discovery_ledger_path"] = str(_daily_ledger_path(data_root, "DISCOVERIES"))
    manifold["current_disclosure_ledger_path"] = str(_daily_ledger_path(data_root, "DISCLOSURES"))
    manifold["last_updated_at"] = _now_iso()
    _write_yaml(state_path, state)
    _write_yaml(manifold_path, manifold)

    return {
        "rehydrate_path": str(rehydrate_path),
        "pending_formalization_count": len(pending_proposals),
        "recent_decision_count": len(recent_decision_entries),
        "recent_discovery_count": len(recent_discovery_entries),
        "recent_disclosure_count": len(recent_disclosure_entries),
    }

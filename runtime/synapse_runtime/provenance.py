"""Runtime-owned provenance model, raw-store helpers, and trust derivation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from synapse_runtime.accepted_execution_view import load_accepted_quest_details, select_current_accepted_quest
from synapse_runtime.git_hooks import HOOK_TEMPLATE_VERSION, inspect_git_hooks, load_hooks_receipt
from synapse_runtime.sidecar_store import _load_active_run, authoritative_coordination_paths
from synapse_runtime.wrapper_proof import current_wrapper_proof_receipt


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
HONESTY_NOTE = (
    "Clear means no current warnings or blockers under Phase 5 checks. "
    "It does not prove universal mediation or perfect provenance."
)


class ProvenanceStatus(str, Enum):
    CLEAR = "clear"
    CAUTION = "caution"
    BLOCKED = "blocked"


class WrapperProofStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    INVALID = "invalid"
    VALID = "valid"


class GitHooksStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    INSTALLED = "installed"
    OUTDATED = "outdated"


class ProvenanceSeverity(str, Enum):
    WARNING = "warning"
    BLOCKER = "blocker"


class ProvenanceAnomalyKind(str, Enum):
    ACCEPTED_QUEST_BUNDLE_MISSING = "accepted_quest_bundle_missing"
    WRAPPER_PROOF_MISSING = "wrapper_proof_missing"
    WRAPPER_PROOF_INVALID = "wrapper_proof_invalid"
    ENGINE_MUTATION_WITHOUT_WRAPPER_RECEIPT = "engine_mutation_without_wrapper_receipt"
    COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS = "coordination_state_changed_without_event_progress"
    GIT_HOOKS_MISSING = "git_hooks_missing"
    GIT_HOOKS_OUTDATED = "git_hooks_outdated"


SEVERITY_BY_KIND = {
    ProvenanceAnomalyKind.ACCEPTED_QUEST_BUNDLE_MISSING: ProvenanceSeverity.BLOCKER,
    ProvenanceAnomalyKind.WRAPPER_PROOF_MISSING: ProvenanceSeverity.BLOCKER,
    ProvenanceAnomalyKind.WRAPPER_PROOF_INVALID: ProvenanceSeverity.BLOCKER,
    ProvenanceAnomalyKind.ENGINE_MUTATION_WITHOUT_WRAPPER_RECEIPT: ProvenanceSeverity.BLOCKER,
    ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS: ProvenanceSeverity.WARNING,
    ProvenanceAnomalyKind.GIT_HOOKS_MISSING: ProvenanceSeverity.WARNING,
    ProvenanceAnomalyKind.GIT_HOOKS_OUTDATED: ProvenanceSeverity.WARNING,
}


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def provenance_root(data_root: Path) -> Path:
    return data_root / ".synapse" / "PROVENANCE"


def baseline_path(data_root: Path) -> Path:
    return provenance_root(data_root) / "WATCH_BASELINE.yaml"


def hooks_receipt_path(data_root: Path) -> Path:
    return provenance_root(data_root) / "HOOKS.yaml"


def anomalies_dir(data_root: Path) -> Path:
    return provenance_root(data_root) / "ANOMALIES"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _subject_state_engine_root(data_root: Path) -> Path | None:
    subject_state = data_root / "SUBJECT_STATE.yaml"
    if not subject_state.exists():
        return None
    try:
        payload = yaml.safe_load(subject_state.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    roots = payload.get("roots")
    if not isinstance(roots, dict):
        return None
    engine_root = roots.get("engine_root")
    if not engine_root:
        return None
    return Path(str(engine_root)).expanduser().resolve()


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _engine_git_snapshot(engine_root: Path) -> dict[str, Any]:
    if not (engine_root / ".git").is_dir():
        return {
            "engine_is_git_repo": False,
            "engine_git_head": None,
            "engine_dirty_files": [],
            "engine_dirty_fingerprint": None,
        }
    head = _git(["rev-parse", "HEAD"], cwd=engine_root)
    status_text = _git(["status", "--porcelain"], cwd=engine_root) or ""
    dirty_files = [line.rstrip() for line in status_text.splitlines() if line.strip()]
    dirty_fingerprint = _sha256_text("\n".join(dirty_files)) if dirty_files else None
    return {
        "engine_is_git_repo": True,
        "engine_git_head": head,
        "engine_dirty_files": dirty_files,
        "engine_dirty_fingerprint": dirty_fingerprint,
    }


def _event_progress(data_root: Path) -> dict[str, Any]:
    events_root = data_root / ".synapse" / "EVENTS"
    files = sorted(events_root.glob("*.jsonl")) if events_root.exists() else []
    if not files:
        return {
            "latest_event_file_path": None,
            "latest_event_file_fingerprint": None,
            "latest_event_count": 0,
        }
    latest = files[-1]
    text = latest.read_text(encoding="utf-8", errors="replace")
    count = len([line for line in text.splitlines() if line.strip()])
    return {
        "latest_event_file_path": str(latest.resolve()),
        "latest_event_file_fingerprint": _sha256_bytes(text.encode("utf-8")),
        "latest_event_count": count,
    }


def _coordination_fingerprints(data_root: Path) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for path in authoritative_coordination_paths(data_root):
        key = str(path.resolve())
        if not path.exists():
            values[key] = None
            continue
        values[key] = _sha256_bytes(path.read_bytes())
    return values


def _current_accepted_execution_view(subject: str, data_root: Path) -> dict[str, Any]:
    details = load_accepted_quest_details(subject, data_root)
    current = select_current_accepted_quest(details)
    return {
        "accepted_details": details,
        "current_accepted": current,
    }


def build_provenance_snapshot(subject, data_root, engine_root, active_run, accepted_execution_view) -> dict:
    data_root = Path(data_root).expanduser().resolve()
    engine_root = Path(engine_root).expanduser().resolve()
    current_accepted = accepted_execution_view.get("current_accepted") if isinstance(accepted_execution_view, dict) else None
    bundle_path = str(current_accepted.get("audit_bundle_path") or "").strip() if current_accepted else ""
    wrapper = current_wrapper_proof_receipt(subject, data_root)
    hooks = inspect_git_hooks(engine_root=engine_root, synapse_root=Path(__file__).resolve().parents[2])
    git_view = _engine_git_snapshot(engine_root)
    baseline_id = f"BASELINE-{_now().strftime('%Y%m%dT%H%M%S%f%z')}"
    return {
        "baseline_id": baseline_id,
        "captured_at": _now_iso(),
        "subject": subject,
        "run_id": active_run.get("run_id") if isinstance(active_run, dict) else None,
        "session_id": active_run.get("session_id") if isinstance(active_run, dict) else None,
        "event_progress": _event_progress(data_root),
        "coordination_fingerprints": _coordination_fingerprints(data_root),
        **git_view,
        "accepted_quest_id": current_accepted.get("quest_id") if current_accepted else None,
        "accepted_audit_bundle_path": bundle_path or None,
        "wrapper_proof_status": wrapper.get("wrapper_proof_status"),
        "wrapper_proof_path": wrapper.get("wrapper_proof_path"),
        "wrapper_proof_fingerprint": wrapper.get("wrapper_proof_fingerprint"),
        "git_hooks_status": hooks.get("hooks_status"),
        "git_hooks_fingerprint": hooks.get("git_hooks_fingerprint"),
    }


def load_provenance_baseline(data_root) -> dict | None:
    path = baseline_path(Path(data_root))
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def save_provenance_baseline(data_root, snapshot) -> Path:
    path = baseline_path(Path(data_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
    return path


def _anomaly_fingerprint(kind: ProvenanceAnomalyKind, severity: ProvenanceSeverity, subject: str, accepted_quest_id: str | None, message: str, evidence: dict[str, Any]) -> str:
    base = {
        "kind": kind.value,
        "severity": severity.value,
        "subject": subject,
        "accepted_quest_id": accepted_quest_id,
        "message": message,
        "evidence": evidence,
    }
    return _sha256_text(json.dumps(base, sort_keys=True, separators=(",", ":")))


def _build_anomaly(*, kind: ProvenanceAnomalyKind, severity: ProvenanceSeverity, subject: str, run_id: str | None, session_id: str | None, accepted_quest_id: str | None, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _anomaly_fingerprint(kind, severity, subject, accepted_quest_id, message, evidence)
    return {
        "anomaly_id": f"ANOM-{_now().strftime('%Y%m%dT%H%M%S%f%z')}",
        "fingerprint": fingerprint,
        "detected_at": _now_iso(),
        "kind": kind.value,
        "severity": severity.value,
        "subject": subject,
        "run_id": run_id,
        "session_id": session_id,
        "accepted_quest_id": accepted_quest_id,
        "message": message,
        "evidence": evidence,
    }


def classify_absolute_provenance_anomalies(snapshot) -> list[dict]:
    anomalies: list[dict[str, Any]] = []
    subject = str(snapshot.get("subject") or "")
    run_id = snapshot.get("run_id")
    session_id = snapshot.get("session_id")
    accepted_quest_id = snapshot.get("accepted_quest_id")
    bundle_path = snapshot.get("accepted_audit_bundle_path")
    wrapper_status = str(snapshot.get("wrapper_proof_status") or WrapperProofStatus.NOT_APPLICABLE.value)
    if accepted_quest_id and (not bundle_path or not Path(str(bundle_path)).exists()):
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.ACCEPTED_QUEST_BUNDLE_MISSING,
            severity=ProvenanceSeverity.BLOCKER,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Accepted quest is active but its audit bundle path is missing or unreadable.",
            evidence={"accepted_audit_bundle_path": bundle_path},
        ))
    if accepted_quest_id and bundle_path and Path(str(bundle_path)).exists() and wrapper_status == WrapperProofStatus.MISSING.value:
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.WRAPPER_PROOF_MISSING,
            severity=ProvenanceSeverity.BLOCKER,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Accepted quest audit bundle is present but wrapper proof is missing.",
            evidence={"accepted_audit_bundle_path": bundle_path, "wrapper_proof_path": snapshot.get("wrapper_proof_path")},
        ))
    if snapshot.get("wrapper_proof_path") and wrapper_status == WrapperProofStatus.INVALID.value:
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.WRAPPER_PROOF_INVALID,
            severity=ProvenanceSeverity.BLOCKER,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Wrapper proof exists but failed shared validation.",
            evidence={"wrapper_proof_path": snapshot.get("wrapper_proof_path")},
        ))
    if snapshot.get("engine_is_git_repo") and str(snapshot.get("git_hooks_status") or "") == GitHooksStatus.MISSING.value:
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.GIT_HOOKS_MISSING,
            severity=ProvenanceSeverity.WARNING,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Managed git hooks are missing from the engine repo.",
            evidence={"engine_git_head": snapshot.get("engine_git_head")},
        ))
    if snapshot.get("engine_is_git_repo") and str(snapshot.get("git_hooks_status") or "") == GitHooksStatus.OUTDATED.value:
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.GIT_HOOKS_OUTDATED,
            severity=ProvenanceSeverity.WARNING,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Managed git hooks are present but outdated relative to the current template.",
            evidence={"engine_git_head": snapshot.get("engine_git_head")},
        ))
    return anomalies


def classify_delta_provenance_anomalies(previous_snapshot, current_snapshot) -> list[dict]:
    if not previous_snapshot:
        return []
    anomalies: list[dict[str, Any]] = []
    subject = str(current_snapshot.get("subject") or "")
    run_id = current_snapshot.get("run_id")
    session_id = current_snapshot.get("session_id")
    accepted_quest_id = current_snapshot.get("accepted_quest_id")
    engine_changed = (
        previous_snapshot.get("engine_git_head") != current_snapshot.get("engine_git_head")
        or previous_snapshot.get("engine_dirty_fingerprint") != current_snapshot.get("engine_dirty_fingerprint")
    )
    if (
        accepted_quest_id
        and current_snapshot.get("engine_is_git_repo")
        and engine_changed
        and previous_snapshot.get("wrapper_proof_fingerprint") == current_snapshot.get("wrapper_proof_fingerprint")
    ):
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.ENGINE_MUTATION_WITHOUT_WRAPPER_RECEIPT,
            severity=ProvenanceSeverity.BLOCKER,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Engine mutation changed under accepted execution without wrapper-proof advancement.",
            evidence={
                "previous_engine_git_head": previous_snapshot.get("engine_git_head"),
                "current_engine_git_head": current_snapshot.get("engine_git_head"),
                "previous_engine_dirty_fingerprint": previous_snapshot.get("engine_dirty_fingerprint"),
                "current_engine_dirty_fingerprint": current_snapshot.get("engine_dirty_fingerprint"),
                "wrapper_proof_fingerprint": current_snapshot.get("wrapper_proof_fingerprint"),
            },
        ))
    if previous_snapshot.get("coordination_fingerprints") != current_snapshot.get("coordination_fingerprints") and previous_snapshot.get("event_progress") == current_snapshot.get("event_progress"):
        severity = ProvenanceSeverity.BLOCKER if current_snapshot.get("run_id") else ProvenanceSeverity.WARNING
        anomalies.append(_build_anomaly(
            kind=ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS,
            severity=severity,
            subject=subject,
            run_id=run_id,
            session_id=session_id,
            accepted_quest_id=accepted_quest_id,
            message="Authoritative coordination state changed without event progress.",
            evidence={
                "previous_coordination_fingerprints": previous_snapshot.get("coordination_fingerprints"),
                "current_coordination_fingerprints": current_snapshot.get("coordination_fingerprints"),
                "event_progress": current_snapshot.get("event_progress"),
            },
        ))
    return anomalies


def _anomaly_ledger_path(data_root: Path, *, day: str | None = None) -> Path:
    target_day = day or _now().date().isoformat()
    return anomalies_dir(data_root) / f"{target_day}.yaml"


def append_provenance_anomalies(data_root, anomalies) -> Path | None:
    anomalies = list(anomalies or [])
    if not anomalies:
        return None
    data_root = Path(data_root).expanduser().resolve()
    path = _anomaly_ledger_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
    else:
        payload = None
    if not isinstance(payload, dict):
        subject = data_root.name[:-5] if data_root.name.endswith("_Data") else data_root.name
        payload = {"schema_version": 1, "subject": subject, "date": _now().date().isoformat(), "entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        entries = []
    existing = {str(item.get("fingerprint")) for item in entries if isinstance(item, dict)}
    appended = False
    for anomaly in anomalies:
        fingerprint = str(anomaly.get("fingerprint") or "").strip()
        if not fingerprint or fingerprint in existing:
            continue
        entries.append(anomaly)
        existing.add(fingerprint)
        appended = True
    if not appended:
        return None
    payload["entries"] = entries
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _recent_anomalies(data_root: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    ledger_dir = anomalies_dir(data_root)
    if not ledger_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(ledger_dir.glob("*.yaml"), reverse=True):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        batch = payload.get("entries")
        if not isinstance(batch, list):
            continue
        for entry in reversed(batch):
            if isinstance(entry, dict):
                entries.append(entry)
                if len(entries) >= limit:
                    return entries
    return entries


def _unresolved_historical_delta_anomalies(snapshot: dict[str, Any], recent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unresolved: list[dict[str, Any]] = []
    for anomaly in recent:
        kind = str(anomaly.get("kind") or "")
        evidence = anomaly.get("evidence")
        if not isinstance(evidence, dict):
            continue
        if kind == ProvenanceAnomalyKind.ENGINE_MUTATION_WITHOUT_WRAPPER_RECEIPT.value:
            if (
                snapshot.get("accepted_quest_id")
                and snapshot.get("engine_is_git_repo")
                and snapshot.get("wrapper_proof_fingerprint") == evidence.get("wrapper_proof_fingerprint")
            ):
                unresolved.append(anomaly)
        elif kind == ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS.value:
            if (
                snapshot.get("event_progress") == evidence.get("event_progress")
                and snapshot.get("coordination_fingerprints") == evidence.get("current_coordination_fingerprints")
            ):
                unresolved.append(anomaly)
    return unresolved


def _trust_from_current(anomalies: list[dict[str, Any]]) -> tuple[ProvenanceStatus, list[dict[str, Any]], list[dict[str, Any]]]:
    blockers = [item for item in anomalies if str(item.get("severity") or "") == ProvenanceSeverity.BLOCKER.value]
    warnings = [item for item in anomalies if str(item.get("severity") or "") == ProvenanceSeverity.WARNING.value]
    if blockers:
        return ProvenanceStatus.BLOCKED, blockers, warnings
    if warnings:
        return ProvenanceStatus.CAUTION, blockers, warnings
    return ProvenanceStatus.CLEAR, blockers, warnings


def compute_current_provenance_summary(subject, data_root, engine_root=None, *, write_projection: bool = False) -> dict:
    data_root = Path(data_root).expanduser().resolve()
    if engine_root is None:
        engine_root = _subject_state_engine_root(data_root)
    if engine_root is None:
        raise RuntimeError(f"Unable to resolve engine_root for provenance summary from {data_root / 'SUBJECT_STATE.yaml'}")
    engine_root = Path(engine_root).expanduser().resolve()
    active_run = _load_active_run(data_root / ".synapse" / "ACTIVE_RUN.yaml", subject)
    accepted_view = _current_accepted_execution_view(subject, data_root)
    snapshot = build_provenance_snapshot(subject, data_root, engine_root, active_run, accepted_view)
    baseline = load_provenance_baseline(data_root)
    absolute = classify_absolute_provenance_anomalies(snapshot)
    hooks_receipt = load_hooks_receipt(data_root) or {}
    recent = _recent_anomalies(data_root, limit=10)
    current_anomalies = absolute + _unresolved_historical_delta_anomalies(snapshot, recent)
    status, blockers, warnings = _trust_from_current(current_anomalies)
    summary = {
        "observed_at": snapshot.get("captured_at"),
        "subject": subject,
        "provenance_status": status.value,
        "honesty_note": HONESTY_NOTE,
        "blockers": blockers,
        "warnings": warnings,
        "recent_provenance_anomalies": recent,
        "recent_anomaly_count": len(recent),
        "current_wrapper_proof_status": snapshot.get("wrapper_proof_status") or WrapperProofStatus.NOT_APPLICABLE.value,
        "current_wrapper_proof_path": snapshot.get("wrapper_proof_path"),
        "current_wrapper_proof_fingerprint": snapshot.get("wrapper_proof_fingerprint"),
        "git_hooks_status": snapshot.get("git_hooks_status") or GitHooksStatus.NOT_APPLICABLE.value,
        "git_hooks_template_version": HOOK_TEMPLATE_VERSION,
        "git_hooks_last_verified_at": hooks_receipt.get("last_verified_at"),
        "baseline_path": str(baseline_path(data_root).resolve()) if baseline_path(data_root).exists() else None,
        "last_watch_at": baseline.get("captured_at") if isinstance(baseline, dict) else None,
        "accepted_quest_id": snapshot.get("accepted_quest_id"),
        "accepted_audit_bundle_path": snapshot.get("accepted_audit_bundle_path"),
        "snapshot": snapshot,
    }
    if write_projection:
        from synapse_runtime.sidecar_projection import refresh_provenance_projection
        refresh_provenance_projection(subject=subject, data_root=data_root, engine_root=engine_root, summary=summary)
    return summary


def projectable_provenance_summary(summary) -> dict:
    return {
        "provenance_status": summary.get("provenance_status"),
        "provenance_last_observed_at": summary.get("observed_at"),
        "provenance_last_watch_at": summary.get("last_watch_at"),
        "provenance_blockers": list(summary.get("blockers") or []),
        "provenance_warnings": list(summary.get("warnings") or []),
        "recent_provenance_anomalies": list(summary.get("recent_provenance_anomalies") or []),
        "current_wrapper_proof_status": summary.get("current_wrapper_proof_status"),
        "current_wrapper_proof_path": summary.get("current_wrapper_proof_path"),
        "current_wrapper_proof_fingerprint": summary.get("current_wrapper_proof_fingerprint"),
        "git_hooks_status": summary.get("git_hooks_status"),
        "git_hooks_template_version": summary.get("git_hooks_template_version"),
        "git_hooks_last_verified_at": summary.get("git_hooks_last_verified_at"),
        "provenance_baseline_path": summary.get("baseline_path"),
    }


def run_provenance_watch_cycle(*, subject: str, data_root: Path, engine_root: Path | None = None) -> dict[str, Any]:
    data_root = Path(data_root).expanduser().resolve()
    if engine_root is None:
        engine_root = _subject_state_engine_root(data_root)
    if engine_root is None:
        raise RuntimeError(f"Unable to resolve engine_root for provenance watch from {data_root / 'SUBJECT_STATE.yaml'}")
    engine_root = Path(engine_root).expanduser().resolve()
    active_run = _load_active_run(data_root / ".synapse" / "ACTIVE_RUN.yaml", subject)
    accepted_view = _current_accepted_execution_view(subject, data_root)
    previous = load_provenance_baseline(data_root)
    state_path = data_root / ".synapse" / "STATE.yaml"
    previous_projected_state: dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            previous_projected_state = loaded
    snapshot = build_provenance_snapshot(subject, data_root, engine_root, active_run, accepted_view)
    absolute = classify_absolute_provenance_anomalies(snapshot)
    delta = classify_delta_provenance_anomalies(previous, snapshot) if previous else []
    new_anomalies = absolute + delta
    anomaly_ledger_path = append_provenance_anomalies(data_root, new_anomalies)
    baseline_written = save_provenance_baseline(data_root, snapshot)
    summary = compute_current_provenance_summary(subject, data_root, engine_root)
    previous_status = previous_projected_state.get("provenance_status")
    previous_wrapper = previous_projected_state.get("current_wrapper_proof_status")
    previous_hooks = previous_projected_state.get("git_hooks_status")
    provenance_changed = (
        previous is None
        or bool(anomaly_ledger_path)
        or previous_status != summary.get("provenance_status")
        or previous_wrapper != summary.get("current_wrapper_proof_status")
        or previous_hooks != summary.get("git_hooks_status")
    )
    return {
        "summary": summary,
        "snapshot": snapshot,
        "baseline_path": str(baseline_written.resolve()),
        "anomaly_ledger_path": str(anomaly_ledger_path.resolve()) if anomaly_ledger_path else None,
        "new_anomalies": new_anomalies,
        "new_anomaly_ids": [item.get("anomaly_id") for item in new_anomalies if item.get("anomaly_id")],
        "provenance_changed": provenance_changed,
        "baseline_initialized": previous is None,
    }

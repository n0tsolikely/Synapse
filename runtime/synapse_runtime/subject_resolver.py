"""Subject resolution and focus-lock persistence for Synapse."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from synapse_runtime.cwt import detect_canonical_working_tree


class SubjectResolutionError(RuntimeError):
    """Raised when subject cannot be resolved deterministically."""


def _now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _subject_from_data_dir(path: Path) -> str | None:
    name = path.name
    if name.endswith("_Data") and len(name) > 5:
        return name[:-5]
    return None


def _load_lock(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    needed = {"subject", "data_root", "engine_root", "selected_at", "selected_by", "selection_method"}
    if not needed.issubset(set(data.keys())):
        return None
    return data


def repo_focus_lock_path(cwt: Path | None = None) -> Path:
    cwt = cwt or detect_canonical_working_tree()
    return cwt / ".synapse" / "ACTIVE_SUBJECT.json"


def home_focus_lock_path(home: Path | None = None) -> Path:
    home = home or Path.home()
    return home / ".synapse" / "ACTIVE_SUBJECT.json"


def detect_subject_candidates(home: Path | None = None) -> list[dict[str, str]]:
    home = (home or Path.home()).resolve()
    candidates: list[dict[str, str]] = []
    for data_dir in sorted(home.glob("*_Data")):
        if not data_dir.is_dir():
            continue
        subject = _subject_from_data_dir(data_dir)
        if not subject:
            continue
        engine_dir = home / f"{subject}_Engine"
        candidates.append(
            {
                "subject": subject,
                "data_root": str(data_dir.resolve()),
                "engine_root": str(engine_dir.resolve()),
            }
        )
    return candidates


def write_focus_lock(
    *,
    subject: str,
    data_root: str | Path,
    engine_root: str | Path,
    cwt: Path | None = None,
    home: Path | None = None,
    selected_by: str = "Brains",
    selection_method: str = "interactive",
    write_home_lock: bool = True,
) -> dict[str, Any]:
    cwt = cwt or detect_canonical_working_tree()
    home = (home or Path.home()).resolve()

    receipt: dict[str, Any] = {
        "subject": str(subject),
        "data_root": str(Path(data_root).expanduser().resolve()),
        "engine_root": str(Path(engine_root).expanduser().resolve()),
        "selected_at": _now_iso(),
        "selected_by": selected_by,
        "selection_method": selection_method,
        "source_detail": "focus_lock_write",
    }

    repo_lock = repo_focus_lock_path(cwt)
    repo_lock.parent.mkdir(parents=True, exist_ok=True)
    repo_lock.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["repo_lockfile"] = str(repo_lock.resolve())

    if write_home_lock:
        home_lock = home_focus_lock_path(home)
        home_lock.parent.mkdir(parents=True, exist_ok=True)
        home_lock.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt["home_lockfile"] = str(home_lock.resolve())

    return receipt


def resolve_subject(
    *,
    subject_flag: str | None = None,
    data_root_flag: str | None = None,
    engine_root_flag: str | None = None,
    env: dict[str, str] | None = None,
    cwt: Path | None = None,
    home: Path | None = None,
    allow_prompt: bool = False,
    allow_switch: bool = False,
) -> dict[str, Any]:
    """Resolve subject context deterministically with lockfile-aware precedence."""

    cwt = cwt or detect_canonical_working_tree()
    home = (home or Path.home()).resolve()
    env_map = env or os.environ

    repo_lock = _load_lock(repo_focus_lock_path(cwt))
    home_lock = _load_lock(home_focus_lock_path(home))
    active_lock = repo_lock or home_lock

    requested_subject = (subject_flag or "").strip()
    if active_lock and requested_subject and requested_subject != active_lock.get("subject") and not allow_switch:
        raise SubjectResolutionError(
            f"Active subject lock is '{active_lock.get('subject')}'. "
            "Use `python3 runtime/synapse.py focus` to switch subject explicitly."
        )

    env_subject = (env_map.get("SUBJECT") or "").strip()

    source = ""
    base: dict[str, Any] | None = None

    if requested_subject:
        source = "flag"
        base = {"subject": requested_subject}
    elif repo_lock:
        source = "lockfile_repo"
        base = repo_lock
    elif home_lock:
        source = "lockfile_home"
        base = home_lock
    elif env_subject:
        source = "env"
        base = {"subject": env_subject}
    else:
        candidates = detect_subject_candidates(home)
        if len(candidates) == 1:
            source = "inferred"
            base = candidates[0]
        elif allow_prompt:
            raise SubjectResolutionError("Prompt-based resolution is handled by `synapse.py focus`.")
        else:
            raise SubjectResolutionError(
                "Subject is not resolved. Run `python3 runtime/synapse.py focus` "
                "or pass `--subject <SUBJECT>`."
            )

    subject = str(base.get("subject") or "").strip()
    if not subject:
        raise SubjectResolutionError("Resolved subject is empty.")

    if source in {"lockfile_repo", "lockfile_home"}:
        data_root = str(base.get("data_root") or "")
        engine_root = str(base.get("engine_root") or "")
    else:
        data_root = str(data_root_flag or base.get("data_root") or (home / f"{subject}_Data"))
        engine_root = str(engine_root_flag or base.get("engine_root") or (home / f"{subject}_Engine"))

    selection_method = "lockfile" if source.startswith("lockfile") else source

    receipt: dict[str, Any] = {
        "subject": subject,
        "data_root": str(Path(data_root).expanduser().resolve()),
        "engine_root": str(Path(engine_root).expanduser().resolve()),
        "selected_at": str(base.get("selected_at") or _now_iso()),
        "selected_by": str(base.get("selected_by") or "Brains"),
        "selection_method": selection_method,
        "source_detail": source,
        "repo_lockfile": str(repo_focus_lock_path(cwt).resolve()),
        "home_lockfile": str(home_focus_lock_path(home).resolve()),
    }
    return receipt

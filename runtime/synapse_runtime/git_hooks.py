"""Managed git-hook rendering, install, inspection, and receipt helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
HOOK_TEMPLATE_VERSION = 1
HOOK_NAMES = ("pre-commit", "pre-push")
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "tools" / "git_hooks"
MANAGED_MARKER = "SYNAPSE_MANAGED_HOOK: YES"
VERSION_MARKER = "SYNAPSE_HOOK_TEMPLATE_VERSION:"
HASH_MARKER = "SYNAPSE_HOOK_TEMPLATE_HASH:"


class GitHooksError(RuntimeError):
    """Raised when managed hook installation or inspection fails."""


def _now_iso() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_git_repo(engine_root: Path) -> bool:
    return (engine_root / ".git").is_dir()


def _hooks_dir(engine_root: Path) -> Path:
    return engine_root / ".git" / "hooks"


def _template_path(hook_name: str) -> Path:
    return TEMPLATE_DIR / f"{hook_name}.template"


def _template_source(hook_name: str) -> str:
    path = _template_path(hook_name)
    return path.read_text(encoding="utf-8")


def render_hook_template(*, hook_name: str, synapse_root: Path) -> dict[str, Any]:
    raw = _template_source(hook_name)
    seeded = raw.replace("__HOOK_NAME__", hook_name)
    seeded = seeded.replace("__TEMPLATE_VERSION__", str(HOOK_TEMPLATE_VERSION))
    seeded = seeded.replace("__SYNAPSE_ROOT__", str(synapse_root.resolve()))
    template_hash = _sha256_text(seeded.replace("__TEMPLATE_HASH__", ""))
    rendered = seeded.replace("__TEMPLATE_HASH__", template_hash)
    return {
        "hook_name": hook_name,
        "template_version": HOOK_TEMPLATE_VERSION,
        "template_hash": template_hash,
        "rendered": rendered,
    }


def _hook_path(engine_root: Path, hook_name: str) -> Path:
    return _hooks_dir(engine_root) / hook_name


def _inspect_single_hook(*, engine_root: Path, hook_name: str, synapse_root: Path) -> dict[str, Any]:
    path = _hook_path(engine_root, hook_name)
    expected = render_hook_template(hook_name=hook_name, synapse_root=synapse_root)
    if not path.exists():
        return {
            "hook_name": hook_name,
            "path": str(path.resolve()),
            "status": "missing",
            "managed": False,
            "template_version": expected["template_version"],
            "template_hash": expected["template_hash"],
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    managed = MANAGED_MARKER in text
    if text == expected["rendered"]:
        status = "installed"
    elif managed:
        status = "outdated"
    else:
        status = "outdated"
    live_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "hook_name": hook_name,
        "path": str(path.resolve()),
        "status": status,
        "managed": managed,
        "template_version": expected["template_version"],
        "template_hash": expected["template_hash"],
        "live_hash": live_hash,
    }


def inspect_git_hooks(*, engine_root: Path, synapse_root: Path) -> dict[str, Any]:
    engine_root = engine_root.expanduser().resolve()
    synapse_root = synapse_root.expanduser().resolve()
    if not _is_git_repo(engine_root):
        return {
            "hooks_status": "not_applicable",
            "engine_root": str(engine_root),
            "engine_is_git_repo": False,
            "template_version": HOOK_TEMPLATE_VERSION,
            "template_hash": None,
            "pre_commit_status": "not_applicable",
            "pre_push_status": "not_applicable",
            "last_verified_at": None,
            "git_hooks_fingerprint": None,
            "hook_details": [],
        }
    details = [_inspect_single_hook(engine_root=engine_root, hook_name=name, synapse_root=synapse_root) for name in HOOK_NAMES]
    statuses = [detail["status"] for detail in details]
    if any(status == "outdated" for status in statuses):
        hooks_status = "outdated"
    elif any(status == "missing" for status in statuses):
        hooks_status = "missing"
    else:
        hooks_status = "installed"
    fingerprint_input = "|".join(
        f"{detail['hook_name']}:{detail['status']}:{detail.get('live_hash') or detail['template_hash']}" for detail in details
    )
    return {
        "hooks_status": hooks_status,
        "engine_root": str(engine_root),
        "engine_is_git_repo": True,
        "template_version": HOOK_TEMPLATE_VERSION,
        "template_hash": details[0]["template_hash"] if details else None,
        "pre_commit_status": next((detail["status"] for detail in details if detail["hook_name"] == "pre-commit"), "missing"),
        "pre_push_status": next((detail["status"] for detail in details if detail["hook_name"] == "pre-push"), "missing"),
        "last_verified_at": None,
        "git_hooks_fingerprint": _sha256_text(fingerprint_input),
        "hook_details": details,
    }


def write_hooks_receipt(*, data_root: Path, receipt: dict[str, Any]) -> Path:
    path = data_root / ".synapse" / "PROVENANCE" / "HOOKS.yaml"
    payload = {
        "hooks_status": receipt.get("hooks_status"),
        "engine_root": receipt.get("engine_root"),
        "engine_is_git_repo": bool(receipt.get("engine_is_git_repo")),
        "template_version": receipt.get("template_version"),
        "template_hash": receipt.get("template_hash"),
        "pre_commit_status": receipt.get("pre_commit_status"),
        "pre_push_status": receipt.get("pre_push_status"),
        "installed_at": receipt.get("installed_at"),
        "last_verified_at": receipt.get("last_verified_at"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def load_hooks_receipt(data_root: Path) -> dict[str, Any] | None:
    path = data_root / ".synapse" / "PROVENANCE" / "HOOKS.yaml"
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def install_managed_hooks(*, engine_root: Path, synapse_root: Path, force: bool = False) -> dict[str, Any]:
    engine_root = engine_root.expanduser().resolve()
    synapse_root = synapse_root.expanduser().resolve()
    inspection_before = inspect_git_hooks(engine_root=engine_root, synapse_root=synapse_root)
    if not inspection_before.get("engine_is_git_repo"):
        return {
            **inspection_before,
            "mutated": False,
            "backups": [],
            "installed_at": None,
            "last_verified_at": None,
        }
    hooks_dir = _hooks_dir(engine_root)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    backups: list[str] = []
    mutated = False
    for name in HOOK_NAMES:
        path = _hook_path(engine_root, name)
        expected = render_hook_template(hook_name=name, synapse_root=synapse_root)
        existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
        if existing is None:
            path.write_text(expected["rendered"], encoding="utf-8")
            os.chmod(path, 0o755)
            mutated = True
            continue
        if existing == expected["rendered"]:
            continue
        managed = MANAGED_MARKER in existing
        if not managed and not force:
            raise GitHooksError(
                f"Refusing to overwrite unmanaged existing git hook without --force: {path}"
            )
        if not managed and force:
            backup = hooks_dir / f"{name}.{dt.datetime.now(tz=DEFAULT_TIMEZONE).strftime('%Y%m%dT%H%M%S%f%z')}.synapse.bak"
            shutil.copy2(path, backup)
            backups.append(str(backup.resolve()))
        path.write_text(expected["rendered"], encoding="utf-8")
        os.chmod(path, 0o755)
        mutated = True
    verified = inspect_git_hooks(engine_root=engine_root, synapse_root=synapse_root)
    now = _now_iso()
    verified["mutated"] = mutated
    verified["backups"] = backups
    verified["installed_at"] = now if mutated else None
    verified["last_verified_at"] = now
    return verified

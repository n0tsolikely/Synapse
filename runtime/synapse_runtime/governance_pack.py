"""Governance pack path resolution and file checks."""

from __future__ import annotations

import os
from pathlib import Path


REQUIRED_GOVERNANCE_FILES = [
    "README.txt",
    "INDEX.txt",
    "SYNAPSE_STATE.yaml",
    "CANAON_VERSION.txt",
    "Schemas/SYNAPSE_STATE.schema.json",
]


def resolve_synapse_root() -> Path:
    root_env = str(os.environ.get("SYNAPSE_ROOT") or "").strip()
    candidate = Path(root_env).expanduser() if root_env else Path(__file__).resolve().parents[2]
    root = candidate.resolve()
    missing = [name for name in ("runtime", "governance") if not (root / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Invalid SYNAPSE_ROOT {root}: missing required path(s): {', '.join(missing)}"
        )
    return root


def resolve_governance_root(governance_root: str | Path | None = None) -> Path:
    raw_root = governance_root or os.environ.get("SYNAPSE_GOVERNANCE_ROOT") or "governance"
    root_path = Path(raw_root).expanduser()
    if not root_path.is_absolute():
        root_path = resolve_synapse_root() / root_path
    resolved = root_path.resolve()
    missing = [path for path, ok in required_file_checks(resolved).items() if not ok]
    if missing:
        raise FileNotFoundError(
            f"Invalid governance root {resolved}: missing required file(s): {', '.join(missing)}"
        )
    return resolved


def resolve_governance_asset(*parts: str, governance_root: str | Path | None = None) -> Path:
    return resolve_governance_root(governance_root).joinpath(*parts)


def required_file_checks(governance_root: Path) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for rel_path in REQUIRED_GOVERNANCE_FILES:
        checks[rel_path] = (governance_root / rel_path).exists()
    return checks

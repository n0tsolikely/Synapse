"""Governance pack path resolution and file checks."""

from __future__ import annotations

from pathlib import Path


REQUIRED_GOVERNANCE_FILES = [
    "README.txt",
    "INDEX.txt",
    "SYNAPSE_STATE.yaml",
    "CANAON_VERSION.txt",
    "Schemas/SYNAPSE_STATE.schema.json",
]


def resolve_governance_root(cwt: Path, governance_root: str) -> Path:
    root_path = Path(governance_root)
    if not root_path.is_absolute():
        root_path = cwt / root_path
    return root_path.resolve()


def required_file_checks(governance_root: Path) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for rel_path in REQUIRED_GOVERNANCE_FILES:
        checks[rel_path] = (governance_root / rel_path).exists()
    return checks


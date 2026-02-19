"""Canonical Working Tree detection."""

from __future__ import annotations

import subprocess
from pathlib import Path


def detect_canonical_working_tree() -> Path:
    """Return git toplevel when available, otherwise current working directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        git_root = result.stdout.strip()
        if git_root:
            return Path(git_root).resolve()
    return Path.cwd().resolve()


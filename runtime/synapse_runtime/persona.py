"""Optional Synapse-managed persona overlay resolution."""

from __future__ import annotations

import os
from pathlib import Path

from synapse_runtime.cwt import detect_canonical_working_tree


def _repo_persona_file(cwt: Path | None = None) -> Path:
    cwt = cwt or detect_canonical_working_tree()
    return cwt / ".synapse" / "PERSONA_ACTIVE.txt"


def _home_persona_file(home: Path | None = None) -> Path:
    home = (home or Path.home()).resolve()
    return home / ".synapse" / "PERSONA_ACTIVE.txt"


def _resolve_persona_path(value: str, cwt: Path) -> tuple[str, str]:
    cleaned = value.strip()
    if not cleaned or cleaned.upper() == "NONE":
        return "NONE", ""
    if cleaned.upper() == "DEFAULT":
        return "DEFAULT", str((cwt / "docs" / "personas" / "PERSONA__DEFAULT.md").resolve())
    if cleaned.upper() == "ASH":
        return "ASH", str((cwt / "docs" / "personas" / "PERSONA__ASH.md").resolve())
    if cleaned.upper().startswith("PATH:"):
        raw_path = cleaned[5:].strip()
        path = Path(raw_path)
        if not path.is_absolute():
            path = (cwt / path).resolve()
        else:
            path = path.resolve()
        return f"PATH:{raw_path}", str(path)
    return cleaned, ""


def resolve_persona(
    *,
    env: dict[str, str] | None = None,
    cwt: Path | None = None,
    home: Path | None = None,
) -> dict[str, str]:
    cwt = cwt or detect_canonical_working_tree()
    home = (home or Path.home()).resolve()
    env_map = env or os.environ

    source = "default"
    raw_value = "NONE"

    env_value = (env_map.get("SYNAPSE_PERSONA") or "").strip()
    if env_value:
        raw_value = env_value
        source = "env"
    else:
        home_file = _home_persona_file(home)
        if home_file.exists():
            raw_value = home_file.read_text(encoding="utf-8").strip() or "NONE"
            source = str(home_file.resolve())
        else:
            repo_file = _repo_persona_file(cwt)
            if repo_file.exists():
                raw_value = repo_file.read_text(encoding="utf-8").strip() or "NONE"
                source = str(repo_file.resolve())

    persona_id, persona_path = _resolve_persona_path(raw_value, cwt)
    persona_exists = "YES" if persona_path and Path(persona_path).exists() else "NO"
    if persona_id == "NONE":
        persona_exists = "NO"

    return {
        "PERSONA_ID": persona_id,
        "PERSONA_SOURCE": source,
        "PERSONA_PATH": persona_path,
        "PERSONA_EXISTS": persona_exists,
    }

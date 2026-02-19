"""SYNAPSE_STATE schema validation helpers."""

from __future__ import annotations

from pathlib import Path

import yaml
from jsonschema import ValidationError, validate


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at {path}, got {type(data).__name__}")
    return data


def load_json(path: Path) -> dict:
    import json

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object at {path}, got {type(data).__name__}")
    return data


def validate_state_schema(state: dict, schema: dict) -> tuple[bool, str | None]:
    try:
        validate(instance=state, schema=schema)
    except ValidationError as exc:
        return False, exc.message
    return True, None


"""Deterministic governance doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.governance_pack import required_file_checks, resolve_governance_root
from synapse_runtime.schema_validation import load_json, load_yaml, validate_state_schema


@dataclass(frozen=True)
class ReadOrderCheck:
    path: str
    kind: str
    status: str
    ok: bool


FILE_SUFFIXES = (".txt", ".md", ".yaml", ".yml", ".json")


def _extract_required_read_paths(state: dict) -> list[str]:
    entries = state.get("required_read_order", [])
    if not isinstance(entries, list):
        return []

    paths: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and len(entry) == 1:
            value = next(iter(entry.values()))
            if isinstance(value, str):
                paths.append(value)
            else:
                paths.append(str(value))
        else:
            paths.append(str(entry))
    return paths


def _classify_required_item(path: str) -> str:
    if "/" in path or path.endswith(FILE_SUFFIXES):
        return "FILE"
    return "POINTER"


def _check_required_read_order(governance_root: Path, state: dict, paths: list[str]) -> list[ReadOrderCheck]:
    results: list[ReadOrderCheck] = []
    for item_path in paths:
        item_kind = _classify_required_item(item_path)
        if item_kind == "FILE":
            resolved = (governance_root / item_path).resolve()
            exists = resolved.exists()
            results.append(
                ReadOrderCheck(
                    path=item_path,
                    kind=item_kind,
                    status="EXISTS" if exists else "MISSING",
                    ok=exists,
                )
            )
            continue

        results.append(
            ReadOrderCheck(
                path=item_path,
                kind=item_kind,
                status="INFO (pointer)",
                ok=True,
            )
        )
    return results


def run_doctor(governance_root_arg: str, subject_receipt: dict | None = None) -> int:
    cwt = detect_canonical_working_tree()
    governance_root = resolve_governance_root(cwt, governance_root_arg)

    governance_root_exists = governance_root.exists() and governance_root.is_dir()
    schema_valid = False
    read_order_checks: list[ReadOrderCheck] = []

    if governance_root_exists:
        required_files = required_file_checks(governance_root)

        state_path = governance_root / "SYNAPSE_STATE.yaml"
        schema_path = governance_root / "Schemas/SYNAPSE_STATE.schema.json"

        if all(required_files.values()) and state_path.exists() and schema_path.exists():
            try:
                state = load_yaml(state_path)
                schema = load_json(schema_path)
                schema_valid, _ = validate_state_schema(state, schema)
                if schema_valid:
                    read_order_paths = _extract_required_read_paths(state)
                    read_order_checks = _check_required_read_order(governance_root, state, read_order_paths)
            except Exception:
                schema_valid = False

    file_items_ok = all(item.ok for item in read_order_checks if item.kind == "FILE")
    overall_pass = governance_root_exists and schema_valid and file_items_ok

    if subject_receipt is not None:
        print("=== RESOLVED SUBJECT RECEIPT ===")
        print(f"subject: {subject_receipt.get('subject')}")
        print(f"data_root: {subject_receipt.get('data_root')}")
        print(f"engine_root: {subject_receipt.get('engine_root')}")
        print(f"selected_at: {subject_receipt.get('selected_at')}")
        print(f"selected_by: {subject_receipt.get('selected_by')}")
        print(f"selection_method: {subject_receipt.get('selection_method')}")
        print(f"source_detail: {subject_receipt.get('source_detail')}")
    print("=== SYNAPSE DOCTOR REPORT ===")
    print(f"CWT: {cwt}")
    print(f"Governance root: {governance_root}")
    print(f"Schema validation: {'PASS' if schema_valid else 'FAIL'}")
    print("Required Read Order:")
    for item in read_order_checks:
        print(f"  - {item.path}: {item.status}")
    print(f"Overall Status: {'PASS' if overall_pass else 'FAIL'}")

    return 0 if overall_pass else 1

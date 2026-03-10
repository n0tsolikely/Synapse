"""Deterministic governance doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.governance_model import derive_world_state, required_sidecar_paths
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


def _check_subject_state(governance_root: Path, subject_receipt: dict) -> list[ReadOrderCheck]:
    checks: list[ReadOrderCheck] = []
    subject = str(subject_receipt.get("subject") or "").strip()
    data_root = Path(str(subject_receipt.get("data_root") or "")).expanduser().resolve()
    buff_prefix = subject.upper()

    def add(path: str, ok: bool, status: str) -> None:
        checks.append(ReadOrderCheck(path=path, kind="SUBJECT", status=status, ok=ok))

    add(str(data_root), data_root.exists() and data_root.is_dir(), "EXISTS" if data_root.exists() else "MISSING")

    subject_state_path = data_root / "SUBJECT_STATE.yaml"
    add(str(subject_state_path), subject_state_path.exists(), "EXISTS" if subject_state_path.exists() else "MISSING")
    if subject_state_path.exists():
        subject_schema_path = governance_root / "Schemas/SUBJECT_STATE.schema.json"
        if not subject_schema_path.exists():
            add(str(subject_schema_path), False, "MISSING")
        else:
            try:
                subject_state = load_yaml(subject_state_path)
                subject_schema = load_json(subject_schema_path)
                ok, _ = validate_state_schema(subject_state, subject_schema)
                add(str(subject_schema_path), ok, "PASS" if ok else "FAIL")
            except Exception:
                add(str(subject_schema_path), False, "FAIL")

    buffs_dir = data_root / "Buffs"
    add(str(buffs_dir), buffs_dir.exists() and buffs_dir.is_dir(), "EXISTS" if buffs_dir.exists() else "MISSING")
    for name in (
        f"{buff_prefix}_EXECUTION_PROTOCOL.txt",
        f"{buff_prefix}_DATA_DIRECTORY_MAP.txt",
        f"{buff_prefix}_SESSION_START_CHECK.txt",
    ):
        path = buffs_dir / name
        add(str(path), path.exists(), "EXISTS" if path.exists() else "MISSING")

    rehydration_dir = data_root / "Latest Rehydration Pack"
    add(
        str(rehydration_dir),
        rehydration_dir.exists() and rehydration_dir.is_dir(),
        "EXISTS" if rehydration_dir.exists() else "MISSING",
    )
    bootstrap_files: list[Path] = []
    continuity_files: list[Path] = []
    if rehydration_dir.exists() and rehydration_dir.is_dir():
        for path in sorted(rehydration_dir.iterdir()):
            if not path.is_file():
                continue
            if "BOOTSTRAP_PROMPT" in path.name:
                bootstrap_files.append(path)
            if "CONTINUITY_LOCK" in path.name:
                continuity_files.append(path)
    add(
        f"{rehydration_dir}/*BOOTSTRAP_PROMPT*",
        len(bootstrap_files) == 1,
        "SINGLE_FOUND" if len(bootstrap_files) == 1 else f"INVALID_COUNT:{len(bootstrap_files)}",
    )
    add(
        f"{rehydration_dir}/*CONTINUITY_LOCK*",
        len(continuity_files) == 1,
        "SINGLE_FOUND" if len(continuity_files) == 1 else f"INVALID_COUNT:{len(continuity_files)}",
    )

    live_root = data_root / ".synapse"
    if not live_root.exists():
        add(str(live_root), True, "MISSING (UPGRADEABLE AMBIENT SIDECAR)")
    else:
        add(str(live_root), live_root.is_dir(), "EXISTS" if live_root.is_dir() else "INVALID")
        for artifact_type, path in required_sidecar_paths(data_root).items():
            exists = path.exists()
            if not exists:
                add(str(path), True, f"MISSING (UPGRADEABLE {artifact_type.value})")
                continue
            if path.suffix in {".yaml", ".yml"}:
                try:
                    parsed = load_yaml(path)
                    ok = isinstance(parsed, dict)
                    add(str(path), ok, "PASS" if ok else "FAIL")
                except Exception:
                    add(str(path), False, "FAIL")
                continue
            add(str(path), True, "EXISTS")

    return checks


def _subject_mode(subject_receipt: dict) -> str:
    data_root = Path(str(subject_receipt.get("data_root") or "")).expanduser().resolve()
    world_state = derive_world_state(data_root).value
    live_root = data_root / ".synapse"
    has_live = live_root.exists()
    has_subject_state = (data_root / "SUBJECT_STATE.yaml").exists()
    has_active_orders = any((data_root / "Guild Orders" / "ACTIVE").glob("*")) if (data_root / "Guild Orders" / "ACTIVE").exists() else False
    has_accepted_quests = any((data_root / "Quest Board" / "Accepted").glob("*")) if (data_root / "Quest Board" / "Accepted").exists() else False

    if not has_subject_state:
        return "invalid_subject_state"
    if world_state == "fog_of_war":
        if has_live:
            return "ambient_attached_subject"
        return "legacy_manual_subject"
    if has_active_orders or has_accepted_quests:
        return "fully_governed_execution_ready"
    return "ambient_attached_subject"


def run_doctor(governance_root_arg: str, subject_receipt: dict | None = None) -> int:
    cwt = detect_canonical_working_tree()
    governance_root = resolve_governance_root(cwt, governance_root_arg)

    governance_root_exists = governance_root.exists() and governance_root.is_dir()
    schema_valid = False
    read_order_checks: list[ReadOrderCheck] = []
    subject_checks: list[ReadOrderCheck] = []

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
    if subject_receipt is not None:
        subject_checks = _check_subject_state(governance_root, subject_receipt)
    subject_items_ok = all(item.ok for item in subject_checks)
    overall_pass = governance_root_exists and schema_valid and file_items_ok and subject_items_ok

    if subject_receipt is not None:
        subject_mode = _subject_mode(subject_receipt)
        print("=== RESOLVED SUBJECT RECEIPT ===")
        print(f"subject: {subject_receipt.get('subject')}")
        print(f"data_root: {subject_receipt.get('data_root')}")
        print(f"engine_root: {subject_receipt.get('engine_root')}")
        print(f"selected_at: {subject_receipt.get('selected_at')}")
        print(f"selected_by: {subject_receipt.get('selected_by')}")
        print(f"selection_method: {subject_receipt.get('selection_method')}")
        print(f"source_detail: {subject_receipt.get('source_detail')}")
        print(f"subject_mode: {subject_mode}")
    print("=== SYNAPSE DOCTOR REPORT ===")
    print(f"CWT: {cwt}")
    print(f"Governance root: {governance_root}")
    print(f"Schema validation: {'PASS' if schema_valid else 'FAIL'}")
    print("Required Read Order:")
    for item in read_order_checks:
        print(f"  - {item.path}: {item.status}")
    if subject_checks:
        print("Subject State Checks:")
        for item in subject_checks:
            print(f"  - {item.path}: {item.status}")
    print(f"Overall Status: {'PASS' if overall_pass else 'FAIL'}")

    return 0 if overall_pass else 1

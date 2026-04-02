"""Deterministic governance doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from synapse_runtime.automation_orchestrator import automation_policy_for_context
from synapse_runtime.current_state_publication import PUBLICATION_FILENAMES, read_publication_metadata
from synapse_runtime.cwt import detect_canonical_working_tree
from synapse_runtime.event_log import validate_event_stream
from synapse_runtime.governance_model import derive_world_state, required_sidecar_paths
from synapse_runtime.governance_pack import required_file_checks, resolve_governance_root, resolve_synapse_root
from synapse_runtime.repo_state import inspect_engaged_kernel_posture
from synapse_runtime.schema_validation import load_json, load_yaml, validate_state_schema
from synapse_runtime.truth_compiler import canonical_truth_publication_paths, load_compiler_report


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
    subject_state: dict | None = None

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
    execution_pack_dir = rehydration_dir / "Execution Pack"
    add(
        str(execution_pack_dir),
        True,
        "EXISTS" if execution_pack_dir.exists() and execution_pack_dir.is_dir() else "MISSING (OPTIONAL)",
    )
    execution_pack_pointers = []
    if execution_pack_dir.exists() and execution_pack_dir.is_dir():
        execution_pack_pointers = sorted(
            path
            for path in execution_pack_dir.glob("ACTIVE_EXECUTION_PACK*.yaml")
            if path.is_file()
        )
    add(
        f"{execution_pack_dir}/ACTIVE_EXECUTION_PACK*.yaml",
        len(execution_pack_pointers) <= 1,
        "OPTIONAL_NONE"
        if len(execution_pack_pointers) == 0
        else "SINGLE_FOUND"
        if len(execution_pack_pointers) == 1
        else f"INVALID_COUNT:{len(execution_pack_pointers)}",
    )
    latest_pack = {}
    if isinstance(subject_state, dict):
        latest_pack = subject_state.get("pointers", {}).get("latest_rehydration_pack", {})
    if isinstance(latest_pack, dict):
        execution_pack_entry = latest_pack.get("execution_pack", {})
        if isinstance(execution_pack_entry, dict):
            pointer_rel = str(execution_pack_entry.get("path") or "").strip()
            if pointer_rel:
                pointer_path = (data_root / pointer_rel).resolve()
                add(str(pointer_path), pointer_path.exists(), "EXISTS" if pointer_path.exists() else "MISSING")
            source_rel = str(execution_pack_entry.get("source_path") or "").strip()
            if source_rel:
                source_path = (data_root / source_rel).resolve()
                add(str(source_path), source_path.exists(), "EXISTS" if source_path.exists() else "MISSING")

    world_state = derive_world_state(data_root).value
    active_orders_dir = data_root / "Guild Orders" / "ACTIVE"
    accepted_dir = data_root / "Quest Board" / "Accepted"
    active_orders_count = len([path for path in active_orders_dir.glob("*") if path.is_file()]) if active_orders_dir.exists() else 0
    accepted_count = len([path for path in accepted_dir.glob("*.txt") if path.is_file()]) if accepted_dir.exists() else 0
    if world_state == "fog_of_war":
        add(
            f"{accepted_dir} (fog_of_war acceptance gate)",
            accepted_count == 0,
            "PASS" if accepted_count == 0 else f"FAIL_ACCEPTED_QUESTS_PRESENT:{accepted_count}",
        )
        add(
            f"{active_orders_dir} (fog_of_war active-orders gate)",
            active_orders_count == 0,
            "PASS" if active_orders_count == 0 else f"FAIL_ACTIVE_ORDERS_PRESENT:{active_orders_count}",
        )

    live_root = data_root / ".synapse"
    if not live_root.exists():
        add(str(live_root), True, "MISSING (UPGRADEABLE AMBIENT SIDECAR)")
    else:
        add(str(live_root), live_root.is_dir(), "EXISTS" if live_root.is_dir() else "INVALID")
        events_root = live_root / "EVENTS"
        if not events_root.exists():
            add(str(events_root), True, "MISSING (UPGRADEABLE EVENT SPINE)")
        else:
            add(str(events_root), events_root.is_dir(), "EXISTS" if events_root.is_dir() else "INVALID")
            if events_root.is_dir():
                event_problems = validate_event_stream(data_root)
                add(
                    f"{events_root}/*.jsonl",
                    not event_problems,
                    "PASS" if not event_problems else f"FAIL_INVALID_EVENTS:{len(event_problems)}",
                )
        for artifact_type, path in required_sidecar_paths(data_root).items():
            if artifact_type.value == "event_spine":
                continue
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

    engine_root = Path(str(subject_receipt.get("engine_root") or "")).expanduser().resolve()
    if engine_root.exists() and engine_root.is_dir():
        kernel_posture = inspect_engaged_kernel_posture(repo_root=engine_root, data_root=data_root)
        raw_scaffold = kernel_posture.get("raw_scaffold") or {}
        raw_root = str(raw_scaffold.get("raw_root") or (data_root / ".synapse" / "RAW"))
        raw_status = str(raw_scaffold.get("scaffold_status") or "missing").strip().lower()
        raw_missing = list(raw_scaffold.get("missing_families") or [])
        if raw_status == "healthy":
            add(raw_root, True, "RAW_HEALTHY")
        elif raw_status == "partial":
            add(raw_root, True, f"RAW_PARTIAL:{','.join(raw_missing) or 'unknown'}")
        else:
            add(raw_root, True, "RAW_MISSING (UPGRADEABLE RAW SCAFFOLD)")

        integration = kernel_posture.get("local_integration") or {}
        posture = str(kernel_posture.get("posture") or "degraded").strip().upper()
        integration_dir = str(integration.get("integration_dir") or (engine_root / ".codex"))
        health = str(integration.get("integration_health") or "missing").strip().lower()
        missing_assets = ",".join(str(item) for item in integration.get("missing_assets") or [])
        if health in {"installed", "missing"}:
            add(integration_dir, True, f"LOCAL_INTEGRATION:{posture}:{health.upper()}")
        else:
            suffix = missing_assets or "unknown"
            add(integration_dir, False, f"LOCAL_INTEGRATION:{posture}:{health.upper()}:{suffix}")

        obligations_root = str((data_root / ".synapse" / "CONTINUITY_OBLIGATIONS").resolve())
        blocker_count = int(kernel_posture.get("blocker_continuity_obligation_count") or 0)
        open_count = int(kernel_posture.get("open_continuity_obligation_count") or 0)
        if blocker_count:
            add(obligations_root, False, f"BLOCKER_CONTINUITY_OBLIGATIONS:{blocker_count}")
        elif open_count:
            add(obligations_root, True, f"OPEN_CONTINUITY_OBLIGATIONS:{open_count}")
        else:
            add(obligations_root, True, "NO_OPEN_CONTINUITY_OBLIGATIONS")

    try:
        automation_policy = automation_policy_for_context(data_root=data_root)
    except Exception:
        automation_policy = None
    if automation_policy is not None and automation_policy.onboarding_required:
        missing = set(automation_policy.missing_publication_fields)
        add(
            "continuity_readiness_gate",
            False,
            f"FAIL_ONBOARDING_CONFIRMATION_REQUIRED:{automation_policy.onboarding_requirement_reason}",
        )
        add(
            "latest_confirmed_onboarding_id",
            "latest_confirmed_onboarding_id" not in missing,
            "EXISTS" if "latest_confirmed_onboarding_id" not in missing else "MISSING",
        )
        add(
            "published_project_model_path",
            "published_project_model_path" not in missing,
            "EXISTS" if "published_project_model_path" not in missing else "MISSING",
        )
        add(
            "published_project_story_path",
            "published_project_story_path" not in missing,
            "EXISTS" if "published_project_story_path" not in missing else "MISSING",
        )
        add(
            "published_vision_path",
            "published_vision_path" not in missing,
            "EXISTS" if "published_vision_path" not in missing else "MISSING",
        )

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
            return "incubation_mode"
        return "legacy_manual_subject"
    if has_active_orders or has_accepted_quests:
        return "fully_governed_execution_ready"
    return "ambient_attached_subject"


def _check_truth_compile(subject_receipt: dict) -> list[ReadOrderCheck]:
    checks: list[ReadOrderCheck] = []
    data_root = Path(str(subject_receipt.get("data_root") or "")).expanduser().resolve()
    live_root = data_root / ".synapse"
    state_path = live_root / "STATE.yaml"
    if not state_path.exists():
        return checks
    try:
        state = load_yaml(state_path)
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}

    cycle_id = str(state.get("last_truth_compile_cycle_id") or "").strip()
    if not cycle_id:
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH"),
                kind="TRUTH",
                status="WARN_NO_TRUTH_COMPILE",
                ok=True,
            )
        )
        return checks

    report = load_compiler_report(data_root)
    if not isinstance(report, dict):
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH" / "COMPILER_REPORT.yaml"),
                kind="TRUTH",
                status="FAIL_TRUTH_REPORT_MISSING",
                ok=False,
            )
        )
        return checks

    report_cycle_id = str(report.get("compile_cycle_id") or "").strip()
    if report_cycle_id != cycle_id:
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH" / "COMPILER_REPORT.yaml"),
                kind="TRUTH",
                status="FAIL_PUBLICATION_REPORT_CYCLE_MISMATCH",
                ok=False,
            )
        )
        return checks

    if int(report.get("material_contradiction_count") or 0) > 0:
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH" / "COMPILER_REPORT.yaml"),
                kind="TRUTH",
                status=f"FAIL_MATERIAL_TRUTH_CONTRADICTION:{report.get('material_contradiction_count')}",
                ok=False,
            )
        )

    stale_active_run_detected = bool(
        state.get("truth_stale_active_run_detected") or report.get("stale_active_run_detected")
    )
    if stale_active_run_detected:
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "ACTIVE_RUN.yaml"),
                kind="TRUTH",
                status="FAIL_STALE_ACTIVE_RUN_DETECTED",
                ok=False,
            )
        )

    publication_paths = dict(report.get("truth_publication_paths") or canonical_truth_publication_paths(data_root))
    for filename in PUBLICATION_FILENAMES.values():
        publication_path = Path(str(publication_paths.get(filename) or (live_root / "TRUTH" / "PUBLICATIONS" / filename)))
        if not publication_path.exists():
            checks.append(
                ReadOrderCheck(
                    path=str(publication_path),
                    kind="TRUTH",
                    status="FAIL_PUBLICATION_PACK_MISSING",
                    ok=False,
                )
            )
            continue
        try:
            metadata = read_publication_metadata(publication_path)
        except Exception:
            checks.append(
                ReadOrderCheck(
                    path=str(publication_path),
                    kind="TRUTH",
                    status="FAIL_PUBLICATION_REPORT_CYCLE_MISMATCH",
                    ok=False,
                )
            )
            continue
        if str(metadata.get("compile_cycle_id") or "").strip() != cycle_id:
            checks.append(
                ReadOrderCheck(
                    path=str(publication_path),
                    kind="TRUTH",
                    status="FAIL_PUBLICATION_REPORT_CYCLE_MISMATCH",
                    ok=False,
                )
            )

    if bool(state.get("truth_compile_stale")):
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH"),
                kind="TRUTH",
                status="WARN_TRUTH_COMPILE_STALE",
                ok=True,
            )
        )

    warning_count = int(report.get("external_source_warning_count") or 0)
    if warning_count > 0:
        checks.append(
            ReadOrderCheck(
                path=str(live_root / "TRUTH" / "COMPILER_REPORT.yaml"),
                kind="TRUTH",
                status=f"WARN_EXTERNAL_SOURCE_PARSE_WARNINGS:{warning_count}",
                ok=True,
            )
        )
    return checks


def run_doctor(governance_root_arg: str | None, subject_receipt: dict | None = None) -> int:
    cwt = detect_canonical_working_tree()
    try:
        governance_root = resolve_governance_root(governance_root_arg)
        governance_error = None
    except Exception as exc:
        raw_root = governance_root_arg or os.environ.get("SYNAPSE_GOVERNANCE_ROOT") or "governance"
        governance_root = Path(raw_root).expanduser()
        if not governance_root.is_absolute():
            governance_root = (resolve_synapse_root() / governance_root).resolve()
        governance_error = str(exc)

    governance_root_exists = governance_error is None and governance_root.exists() and governance_root.is_dir()
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
        subject_checks.extend(_check_truth_compile(subject_receipt))
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
    if governance_error:
        print(f"Governance resolution: FAIL ({governance_error})")
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

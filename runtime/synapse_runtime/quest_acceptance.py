"""Quest acceptance helpers for BOARD -> ACCEPTED governed execution."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from synapse_runtime.governance_model import derive_world_state, quest_state_from_path


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")
VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_CHANGE_CLASSES = {"TRIVIAL", "FEATURE", "STRUCTURAL"}
VALID_VISION_DELTAS = {"ALIGNED", "VARIATION", "SHIFT"}
VALID_TALENT_FLAGS = {"YES", "NO"}
VALID_RISK_LEVELS = {"R0", "R1", "R2"}
PLACEHOLDER_TOKENS = ("<fill>", "tbd", "placeholder", "unknown")
REQUIRED_AUDIT_FILES = (
    "00_SUMMARY.md",
    "01_PREQUEST.md",
    "02_EXECUTION.md",
    "03_VERIFY.md",
    "04_OUTCOME.md",
    "06_CHANGED_FILES.txt",
    "06_TESTS.txt",
    "06_WRAPPER_PROOF.json",
    "00_ACCEPTANCE_RECEIPT.txt",
    "90_ORIGINAL_QUEST__as_found.txt",
    "00_GOVERNANCE_PREFLIGHT.md",
    "DISCLOSURE_GATE.md",
)


class QuestAcceptanceError(RuntimeError):
    """Raised when a quest cannot be accepted lawfully."""


@dataclass(frozen=True)
class QuestDocument:
    path: Path
    raw_text: str
    quest_id: str
    title: str
    subject: str
    origin: str
    priority: str
    codex_anchors_raw: str
    codex_constraints_raw: str
    change_class: str
    vision_delta: str
    system_context: str
    anti_duplication_plan: str
    placement_intent: str
    atomicity_statement: str
    risk: str
    r2_confirmation_artifact: str
    description: str
    objective: str
    out_of_scope: str
    dependencies: str
    door_impact: str
    testing_level: str
    verification_plan: str
    talent_point_awarded: str
    audit_bundle_field: str
    audit_bundle_path: Path | None
    variation_mapping: str
    codification_sidequest: str


def _now() -> dt.datetime:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE)


def _now_iso() -> str:
    return _now().isoformat()


def _today() -> str:
    return _now().date().isoformat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _looks_like_label(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return bool(re.match(r"^[A-Za-z0-9_ /().-]+:\s*(?:.*)?$", stripped))


def _extract_labeled_block(text: str, label: str) -> str:
    needle = f"{label}:"
    lines = text.splitlines()
    for idx, raw in enumerate(lines):
        if raw.strip().startswith(needle):
            remainder = raw.split(":", 1)[1].strip()
            values: list[str] = []
            if remainder:
                values.append(remainder)
            j = idx + 1
            while j < len(lines):
                candidate = lines[j]
                stripped = candidate.strip()
                if not stripped:
                    if values:
                        break
                    j += 1
                    continue
                if stripped.startswith("#"):
                    j += 1
                    continue
                if stripped.startswith("==="):
                    break
                if _looks_like_label(stripped):
                    break
                values.append(stripped)
                j += 1
            return "\n".join(values).strip()
    return ""


def _placeholder_like(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if any(token in lowered for token in PLACEHOLDER_TOKENS):
        return True
    return False


def _normalize_inline_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "quest"


def _resolve_data_relative_path(subject: str, data_root: Path, raw: str) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if value.startswith("Audits/") or value.startswith("confirmations/"):
        return (data_root / value).resolve()
    if value.startswith(f"{subject}_Data/"):
        return (data_root.parent / value).resolve()
    return (data_root / value).resolve()


def _anchor_tokens(raw: str) -> list[str]:
    if not raw.strip():
        return []
    tokens: list[str] = []
    for chunk in re.split(r"[,\n]", raw):
        item = chunk.strip()
        item = re.sub(r"^[-*]\s*", "", item)
        if item:
            tokens.append(item)
    return tokens


def _extract_filename_quest_id(path: Path) -> str:
    match = re.match(r"((?:SIDE-QUEST|QUEST)_\d{3})__", path.name.upper())
    return match.group(1) if match else ""


def _extract_variation_mapping(text: str) -> str:
    for pattern in (
        r"(?im)^Variation Mapping:\s*(.+)$",
        r"(?im)^Codex intent class it maps to:\s*(.+)$",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_codification_sidequest(text: str) -> str:
    for pattern in (
        r"(?im)^Codification Side-Quest:\s*(SIDE-QUEST_\d{3})\b",
        r"(?im)^Codification path:\s*(SIDE-QUEST_\d{3})\b",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().upper()
    return ""


def parse_quest_document(*, subject: str, data_root: Path, path: Path) -> QuestDocument:
    raw_text = _read_text(path)
    audit_field = _extract_labeled_block(raw_text, "Audit Bundle Folder Path (required once ACCEPTED)")
    return QuestDocument(
        path=path.resolve(),
        raw_text=raw_text,
        quest_id=_normalize_inline_value(_extract_labeled_block(raw_text, "Quest ID")) or _extract_filename_quest_id(path),
        title=_normalize_inline_value(_extract_labeled_block(raw_text, "Title")),
        subject=_normalize_inline_value(_extract_labeled_block(raw_text, "Subject")),
        origin=_normalize_inline_value(_extract_labeled_block(raw_text, "Origin")),
        priority=_normalize_inline_value(_extract_labeled_block(raw_text, "Priority")).upper(),
        codex_anchors_raw=_extract_labeled_block(raw_text, "Codex Anchors (DRAFT)"),
        codex_constraints_raw=_extract_labeled_block(raw_text, "Codex Constraint Summary (DRAFT)"),
        change_class=_normalize_inline_value(_extract_labeled_block(raw_text, "Change Class")).upper(),
        vision_delta=_normalize_inline_value(_extract_labeled_block(raw_text, "Vision Delta")).upper(),
        system_context=_extract_labeled_block(raw_text, "System Context Statement"),
        anti_duplication_plan=_extract_labeled_block(raw_text, "Anti-Duplication Plan"),
        placement_intent=_extract_labeled_block(raw_text, "Placement Intent"),
        atomicity_statement=_extract_labeled_block(raw_text, "Atomicity Statement"),
        risk=_normalize_inline_value(_extract_labeled_block(raw_text, "Risk")).upper() or "R0",
        r2_confirmation_artifact=_normalize_inline_value(_extract_labeled_block(raw_text, "R2 Confirmation Artifact (REQUIRED if Risk = R2)")),
        description=_extract_labeled_block(raw_text, "Description"),
        objective=_extract_labeled_block(raw_text, "Scope / Objective"),
        out_of_scope=_extract_labeled_block(raw_text, "Out of Scope"),
        dependencies=_extract_labeled_block(raw_text, "Dependencies"),
        door_impact=_normalize_inline_value(_extract_labeled_block(raw_text, "Door Impact")).upper(),
        testing_level=_normalize_inline_value(_extract_labeled_block(raw_text, "Testing Level (TL)")).upper(),
        verification_plan=_extract_labeled_block(raw_text, "Verification Plan"),
        talent_point_awarded=_normalize_inline_value(_extract_labeled_block(raw_text, "Talent Point Awarded")).upper(),
        audit_bundle_field=audit_field,
        audit_bundle_path=_resolve_data_relative_path(subject, data_root, audit_field),
        variation_mapping=_extract_variation_mapping(raw_text),
        codification_sidequest=_extract_codification_sidequest(raw_text),
    )


def prequest_has_execution_readiness(text: str) -> bool:
    body = text.strip()
    if not body:
        return False
    lowered = body.lower()
    if "deferred to 01_prequest.md" in lowered:
        return False
    if any(token in lowered for token in PLACEHOLDER_TOKENS):
        return False
    if re.search(r"(?im)^Execution Readiness:\s*READY\b", body):
        return True
    if re.search(r"(?im)^##\s*Verification Plan\b", body) or re.search(r"(?im)^Verification Plan:\s*", body):
        return True
    if re.search(r"(?im)^Verification Commands", body):
        return True
    return False


def _canonical_bundle_field(subject: str, data_root: Path, bundle_path: Path) -> str:
    return f"{subject}_Data/Audits/Execution/{bundle_path.name}"


def _replace_labeled_value(text: str, label: str, value: str) -> str:
    lines = text.splitlines()
    needle = f"{label}:"
    for idx, raw in enumerate(lines):
        if raw.strip().startswith(needle):
            prefix = raw.split(":", 1)[0] + ":"
            lines[idx] = f"{prefix} {value}".rstrip()
            j = idx + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if not stripped:
                    break
                if stripped.startswith("#"):
                    j += 1
                    continue
                if stripped.startswith("===") or _looks_like_label(stripped):
                    break
                del lines[j]
            return "\n".join(lines).rstrip() + "\n"
    return text.rstrip() + f"\n{label}: {value}\n"


def resolve_board_quest(data_root: Path, quest_ref: str) -> Path:
    board_root = data_root / "Quest Board"
    raw = str(quest_ref or "").strip()
    if not raw:
        raise QuestAcceptanceError("Quest reference is required.")
    probe = Path(raw).expanduser()
    if probe.exists():
        path = probe.resolve()
    else:
        matches = sorted(board_root.glob(f"{raw.upper()}__*.txt"))
        if not matches:
            raise QuestAcceptanceError(f"Quest not found on BOARD: {raw}")
        if len(matches) > 1:
            joined = ", ".join(str(item) for item in matches)
            raise QuestAcceptanceError(f"Quest reference is ambiguous on BOARD: {joined}")
        path = matches[0].resolve()

    state = quest_state_from_path(path, data_root)
    if state is None:
        raise QuestAcceptanceError(f"Quest path is outside the canonical Quest Board: {path}")
    if str(getattr(state, "value", state)) != "board":
        raise QuestAcceptanceError(f"Quest must be on BOARD before acceptance: {path}")
    if not path.is_file():
        raise QuestAcceptanceError(f"Quest file does not exist: {path}")
    return path


def _load_control_sync_state(data_root: Path) -> tuple[dict, Path]:
    path = data_root / ".governance_runtime" / "control_sync_state.json"
    if not path.exists():
        return {}, path
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except Exception:
        return {}, path


def _find_sidequest_anywhere(data_root: Path, quest_id: str) -> Path | None:
    board_root = data_root / "Quest Board"
    for directory in (
        board_root,
        board_root / "Accepted",
        board_root / "Completed",
        board_root / "Abandoned",
    ):
        if not directory.exists():
            continue
        matches = sorted(directory.glob(f"{quest_id}__*.txt"))
        if matches:
            return matches[0]
    return None


def _validate_confirmation_artifact(data_root: Path, doc: QuestDocument, failures: list[str]) -> Path | None:
    if doc.risk != "R2":
        return None
    if not doc.r2_confirmation_artifact:
        failures.append("Risk = R2 but R2 Confirmation Artifact is missing.")
        return None
    confirmation_path = _resolve_data_relative_path(doc.subject or data_root.name.removesuffix("_Data"), data_root, doc.r2_confirmation_artifact)
    if confirmation_path is None or not confirmation_path.is_file():
        failures.append("Risk = R2 but the confirmation artifact file does not exist.")
        return None
    content = _read_text(confirmation_path)
    if "CONFIRM: YES" not in content:
        failures.append("Risk = R2 but the confirmation artifact does not contain 'CONFIRM: YES'.")
        return None
    return confirmation_path


def _validate_bundle_path(data_root: Path, doc: QuestDocument, failures: list[str]) -> Path | None:
    if doc.audit_bundle_path is None:
        failures.append("Audit Bundle Folder Path is required before acceptance.")
        return None
    bundle_path = doc.audit_bundle_path
    audits_root = (data_root / "Audits" / "Execution").resolve()
    if bundle_path.parent != audits_root:
        failures.append(f"Audit bundle must live directly under {audits_root}, got {bundle_path}.")
    if not re.fullmatch(rf"{re.escape(doc.quest_id)}__\d{{4}}-\d{{2}}-\d{{2}}__[-a-z0-9._]+", bundle_path.name):
        failures.append(f"Audit bundle folder name is invalid for {doc.quest_id}: {bundle_path.name}")
    return bundle_path


def _resolve_verification_plan(doc: QuestDocument, bundle_path: Path | None, failures: list[str]) -> tuple[str | None, str | None]:
    quest_plan = doc.verification_plan.strip()
    if quest_plan and "DEFERRED TO 01_PREQUEST.MD" not in quest_plan.upper() and not _placeholder_like(quest_plan):
        return quest_plan, "quest_file"
    if bundle_path is not None:
        prequest = bundle_path / "01_PREQUEST.md"
        if prequest.exists():
            text = _read_text(prequest)
            if prequest_has_execution_readiness(text):
                return text, "audit_bundle"
    failures.append("Verification Plan must be concrete before acceptance; a deferred/empty plan is not execution-ready.")
    return None, None


def _build_summary(doc: QuestDocument, accepted_path: Path, bundle_path: Path) -> str:
    lines = [
        "# 00_SUMMARY.md",
        "",
        f"- Quest ID: {doc.quest_id}",
        f"- Title: {doc.title}",
        f"- Accepted At: {_now_iso()}",
        f"- Accepted Quest Path: {accepted_path}",
        f"- Audit Bundle: {bundle_path}",
        "- State: ACCEPTED",
        "- Governed Execution Ready: YES",
        "",
        "## Scope Summary",
        doc.objective or doc.description,
        "",
        "## Immediate Next Step",
        "- Execute the quest through runtime/tools/synapse_quest_run.sh using this audit bundle.",
        "",
    ]
    return "\n".join(lines)


def _build_prequest(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    doc: QuestDocument,
    accepted_path: Path,
    bundle_path: Path,
    verification_plan: str,
    verification_plan_source: str,
    confirmation_path: Path | None,
) -> str:
    anchors = _anchor_tokens(doc.codex_anchors_raw)
    constraints = [item.strip() for item in doc.codex_constraints_raw.splitlines() if item.strip()]
    lines = [
        "# 01_PREQUEST.md",
        "",
        "## Acceptance Readiness",
        "Execution Readiness: READY",
        f"- Accepted At: {_now_iso()}",
        f"- Verification Plan Source: {verification_plan_source}",
        "",
        "## Quest Identity",
        f"- Quest ID: {doc.quest_id}",
        f"- Title: {doc.title}",
        f"- Subject: {subject}",
        f"- Accepted Quest Path: {accepted_path}",
        f"- Audit Bundle Path: {bundle_path}",
        "",
        "## Orientation Receipt",
        f"- ENGINE_ROOT: {engine_root}",
        f"- DATA_ROOT: {data_root}",
        f"- GOVERNANCE_ROOT: {engine_root / 'governance'}",
        f"- Working Tree Root: {engine_root}",
        f"- System Context Statement: {doc.system_context}",
        "",
        "## Repo Orientation Receipt",
        f"- Anti-Duplication Plan: {doc.anti_duplication_plan}",
        f"- Placement Intent: {doc.placement_intent}",
        "",
        "## Quest Structure",
        f"- Change Class: {doc.change_class}",
        f"- Vision Delta: {doc.vision_delta}",
        f"- Atomicity Statement: {doc.atomicity_statement}",
        f"- Dependencies: {doc.dependencies}",
        "",
        "## Codex Anchors",
    ]
    lines.extend(f"- {anchor}" for anchor in anchors)
    lines.extend(["", "## Codex Constraint Summary"])
    if constraints:
        lines.extend(f"- {item}" for item in constraints)
    else:
        lines.append(f"- {doc.codex_constraints_raw}")
    lines.extend(
        [
            "",
            "## Success Definition",
            f"- Objective: {doc.objective}",
            f"- Out of Scope: {doc.out_of_scope}",
            "",
            "## Verification Plan",
            verification_plan.strip(),
            "",
            "## Verification Metadata",
            f"- Door Impact: {doc.door_impact}",
            f"- Testing Level: {doc.testing_level}",
            "",
            "## Risk / Consent",
            f"- Risk: {doc.risk}",
            f"- Confirmation Artifact: {confirmation_path if confirmation_path else 'NOT REQUIRED'}",
            "",
            "## World State",
            f"- World State: {derive_world_state(data_root).value}",
            f"- Codex Freeze Marker: {data_root / 'Codex' / 'CODEX_FREEZE.md'}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_acceptance_receipt(
    *,
    doc: QuestDocument,
    board_path: Path,
    accepted_path: Path,
    bundle_path: Path,
    control_sync_path: Path,
    verification_plan_source: str,
    confirmation_path: Path | None,
) -> str:
    lines = [
        "ACCEPTANCE RECEIPT",
        f"ACCEPTANCE_STATUS: PASS",
        f"ACCEPTED_AT: {_now_iso()}",
        f"QUEST_ID: {doc.quest_id}",
        f"QUEST_TITLE: {doc.title}",
        f"BOARD_SOURCE: {board_path}",
        f"ACCEPTED_TARGET: {accepted_path}",
        f"AUDIT_BUNDLE: {bundle_path}",
        f"CONTROL_SYNC_STATE: {control_sync_path}",
        f"CONTROL_SYNC_ACTIVE: YES",
        f"WORLD_STATE: {derive_world_state(bundle_path.parents[2]).value}",
        f"VERIFICATION_PLAN_SOURCE: {verification_plan_source}",
        f"RISK: {doc.risk}",
        f"R2_CONFIRMATION: {confirmation_path if confirmation_path else 'NOT REQUIRED'}",
        "GOVERNED_EXECUTION_READY: YES",
    ]
    return "\n".join(lines)


def _build_preflight(
    *,
    doc: QuestDocument,
    board_path: Path,
    accepted_path: Path,
    bundle_path: Path,
    control_sync_path: Path,
) -> str:
    lines = [
        "# Governance Preflight",
        "",
        f"- QUEST_ID: {doc.quest_id}",
        f"- BOARD_SOURCE: {board_path}",
        f"- ACCEPTED_TARGET: {accepted_path}",
        f"- AUDIT_BUNDLE: {bundle_path}",
        f"- CONTROL_SYNC_STATE: {control_sync_path}",
        "- CONTROL_SYNC_ACTIVE: YES",
        f"- WORLD_STATE: {derive_world_state(bundle_path.parents[2]).value}",
        f"- CHANGE_CLASS: {doc.change_class}",
        f"- VISION_DELTA: {doc.vision_delta}",
        "- PRE-FLIGHT: PASS",
        "",
    ]
    return "\n".join(lines)


def _build_disclosure_gate(doc: QuestDocument) -> str:
    lines = [
        "# Disclosure Gate",
        "",
        "- TRIGGER: none",
        f"- RISK_BOUNDARY: {doc.risk}",
        "- USER_DISCLOSED: YES",
        "- DISCLOSURE_DECISION: ACKNOWLEDGED",
        "- EXECUTION_ALLOWED: YES",
        "- NOTES: Acceptance gate passed; continue under audit truth requirements.",
        "",
    ]
    return "\n".join(lines)


def _build_execution_placeholder(name: str, bundle_path: Path) -> str:
    if name == "02_EXECUTION.md":
        return "\n".join(
            [
                "# 02_EXECUTION.md",
                "",
                "## Execution",
                "- No commands executed yet. Use synapse_quest_run.sh to populate real receipts during execution.",
                f"- Audit bundle: {bundle_path}",
                "",
            ]
        )
    if name == "03_VERIFY.md":
        return "\n".join(
            [
                "# 03_VERIFY.md",
                "",
                "## Verification",
                "- No verification executed yet.",
                "- Use 06_TESTS.txt for raw receipts captured during execution.",
                "",
            ]
        )
    if name == "04_OUTCOME.md":
        return "\n".join(
            [
                "# 04_OUTCOME.md",
                "",
                "## Outcome",
                "- Final status: ACCEPTED (execution not started yet)",
                f"- Audit bundle: {bundle_path}",
                "- Notes: Governed execution readiness established at acceptance.",
                "",
            ]
        )
    if name == "06_TESTS.txt":
        return "PLACEHOLDER: no commands executed yet. Populate with real wrapper receipts during execution.\n"
    if name == "06_CHANGED_FILES.txt":
        return "PLACEHOLDER: no governed execution changes recorded yet.\n"
    if name == "06_WRAPPER_PROOF.json":
        return '{\n  "schema_version": 1,\n  "status": "NOT_RUN_YET"\n}\n'
    return f"# {name}\n"


def _ensure_bundle(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    doc: QuestDocument,
    board_path: Path,
    accepted_path: Path,
    bundle_path: Path,
    verification_plan: str,
    verification_plan_source: str,
    control_sync_path: Path,
    confirmation_path: Path | None,
) -> dict[str, list[str]]:
    created: list[str] = []
    existing: list[str] = []
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    if bundle_path.exists() and not bundle_path.is_dir():
        raise QuestAcceptanceError(f"Audit bundle path exists but is not a directory: {bundle_path}")
    bundle_path.mkdir(parents=True, exist_ok=True)

    file_specs = {
        "90_ORIGINAL_QUEST__as_found.txt": doc.raw_text,
        "00_SUMMARY.md": _build_summary(doc, accepted_path, bundle_path),
        "01_PREQUEST.md": _build_prequest(
            subject=subject,
            data_root=data_root,
            engine_root=engine_root,
            doc=doc,
            accepted_path=accepted_path,
            bundle_path=bundle_path,
            verification_plan=verification_plan,
            verification_plan_source=verification_plan_source,
            confirmation_path=confirmation_path,
        ),
        "00_ACCEPTANCE_RECEIPT.txt": _build_acceptance_receipt(
            doc=doc,
            board_path=board_path,
            accepted_path=accepted_path,
            bundle_path=bundle_path,
            control_sync_path=control_sync_path,
            verification_plan_source=verification_plan_source,
            confirmation_path=confirmation_path,
        ),
        "00_GOVERNANCE_PREFLIGHT.md": _build_preflight(
            doc=doc,
            board_path=board_path,
            accepted_path=accepted_path,
            bundle_path=bundle_path,
            control_sync_path=control_sync_path,
        ),
        "DISCLOSURE_GATE.md": _build_disclosure_gate(doc),
    }
    for name in REQUIRED_AUDIT_FILES:
        if name not in file_specs:
            file_specs[name] = _build_execution_placeholder(name, bundle_path)

    for name, content in file_specs.items():
        path = bundle_path / name
        if path.exists():
            existing.append(str(path.resolve()))
            if name == "01_PREQUEST.md" and not prequest_has_execution_readiness(_read_text(path)):
                raise QuestAcceptanceError(
                    f"Existing audit bundle is not execution-ready: {path} is missing a concrete verification plan."
                )
            if name == "00_ACCEPTANCE_RECEIPT.txt":
                receipt = _read_text(path)
                if "ACCEPTANCE_STATUS: PASS" not in receipt or f"QUEST_ID: {doc.quest_id}" not in receipt:
                    raise QuestAcceptanceError(
                        f"Existing acceptance receipt in {path} conflicts with the current quest and cannot be overwritten."
                    )
            if name == "00_GOVERNANCE_PREFLIGHT.md":
                preflight = _read_text(path)
                if "PRE-FLIGHT: PASS" not in preflight:
                    raise QuestAcceptanceError(f"Existing governance preflight in {path} is not PASS.")
            if name == "DISCLOSURE_GATE.md":
                disclosure = _read_text(path)
                if "EXECUTION_ALLOWED: YES" not in disclosure:
                    raise QuestAcceptanceError(f"Existing disclosure gate in {path} does not allow execution.")
            continue
        _write_text(path, content)
        created.append(str(path.resolve()))
    return {"created": created, "existing": existing}


def accept_quest(
    *,
    subject: str,
    data_root: Path,
    engine_root: Path,
    quest_ref: str,
) -> dict[str, object]:
    board_path = resolve_board_quest(data_root, quest_ref)
    doc = parse_quest_document(subject=subject, data_root=data_root, path=board_path)
    accepted_dir = data_root / "Quest Board" / "Accepted"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = accepted_dir / board_path.name
    if accepted_path.exists():
        raise QuestAcceptanceError(f"Accepted quest already exists: {accepted_path}")

    control_sync_state, control_sync_path = _load_control_sync_state(data_root)
    failures: list[str] = []
    if not control_sync_state.get("active"):
        failures.append("Acceptance requires an OPEN Control Sync, but no active control sync state was found.")
    elif str(control_sync_state.get("subject") or "") not in {"", subject}:
        failures.append(
            f"Acceptance requires the active Control Sync to match subject {subject}, got {control_sync_state.get('subject')}."
        )

    world_state = derive_world_state(data_root).value
    if world_state != "fog_lifted":
        failures.append("Fog of War is active; BOARD -> ACCEPTED is illegal until Codex Freeze is present and valid.")

    if not re.fullmatch(r"(?:SIDE-QUEST|QUEST)_\d{3}", doc.quest_id):
        failures.append(f"Quest ID is missing or invalid: {doc.quest_id or '<missing>'}")
    if doc.quest_id and _extract_filename_quest_id(board_path) and doc.quest_id != _extract_filename_quest_id(board_path):
        failures.append(f"Quest ID in file does not match filename prefix: {doc.quest_id} vs {board_path.name}")
    if doc.subject != subject:
        failures.append(f"Quest Subject must match active subject {subject}, got {doc.subject or '<missing>'}.")
    if _placeholder_like(doc.title):
        failures.append("Title is required before acceptance.")
    if _placeholder_like(doc.origin):
        failures.append("Origin is required before acceptance.")
    if doc.priority not in VALID_PRIORITIES:
        failures.append(f"Priority must be one of {sorted(VALID_PRIORITIES)}, got {doc.priority or '<missing>'}.")
    if _placeholder_like(doc.description):
        failures.append("Description is required before acceptance.")
    if _placeholder_like(doc.objective):
        failures.append("Scope / Objective is required before acceptance.")
    if _placeholder_like(doc.out_of_scope):
        failures.append("Out of Scope is required before acceptance.")
    if _placeholder_like(doc.dependencies):
        failures.append("Dependencies must be stated explicitly (or 'None') before acceptance.")
    if doc.change_class not in VALID_CHANGE_CLASSES:
        failures.append(
            f"Change Class must be one of {sorted(VALID_CHANGE_CLASSES)}, got {doc.change_class or '<missing>'}."
        )
    if doc.vision_delta not in VALID_VISION_DELTAS:
        failures.append(
            f"Vision Delta must be one of {sorted(VALID_VISION_DELTAS)}, got {doc.vision_delta or '<missing>'}."
        )
    if doc.vision_delta == "SHIFT":
        failures.append("Vision Delta = SHIFT is blocked; Control Sync + Codex update are required before acceptance.")
    if _placeholder_like(doc.system_context):
        failures.append("System Context Statement is required before acceptance.")
    if doc.change_class in {"FEATURE", "STRUCTURAL"}:
        if _placeholder_like(doc.anti_duplication_plan) or "REPO_ORIENTATION_REQUIRED" in doc.anti_duplication_plan.upper():
            failures.append("Anti-Duplication Plan is unresolved; FEATURE/STRUCTURAL quests cannot be accepted yet.")
        if _placeholder_like(doc.placement_intent) or "REPO_ORIENTATION_REQUIRED" in doc.placement_intent.upper():
            failures.append("Placement Intent is unresolved; FEATURE/STRUCTURAL quests cannot be accepted yet.")
    if _placeholder_like(doc.atomicity_statement):
        failures.append("Atomicity Statement is required before acceptance.")
    if doc.risk not in VALID_RISK_LEVELS:
        failures.append(f"Risk must be one of {sorted(VALID_RISK_LEVELS)}, got {doc.risk or '<missing>'}.")
    if _placeholder_like(doc.door_impact):
        failures.append("Door Impact must be set before acceptance.")
    if _placeholder_like(doc.testing_level):
        failures.append("Testing Level must be set before acceptance.")
    if doc.talent_point_awarded not in VALID_TALENT_FLAGS:
        failures.append("Talent Point Awarded must be explicitly YES or NO before acceptance.")

    anchors = _anchor_tokens(doc.codex_anchors_raw)
    if not anchors or "CODEX_ANCHORS_MISSING" in doc.codex_anchors_raw.upper():
        failures.append("Codex Anchors are unresolved; the quest may remain on BOARD but cannot move to ACCEPTED.")
    elif not 2 <= len(anchors) <= 7:
        failures.append(f"Codex Anchors must contain 2-7 references, got {len(anchors)}.")
    if _placeholder_like(doc.codex_constraints_raw):
        failures.append("Codex Constraint Summary is required before acceptance.")

    if doc.vision_delta == "VARIATION":
        if _placeholder_like(doc.variation_mapping):
            failures.append("Vision Delta = VARIATION requires Variation Mapping.")
        if not doc.codification_sidequest:
            failures.append("Vision Delta = VARIATION requires a Codification Side-Quest declaration.")
        elif _find_sidequest_anywhere(data_root, doc.codification_sidequest) is None:
            failures.append(f"Codification Side-Quest does not exist on the Quest Board: {doc.codification_sidequest}")

    bundle_path = _validate_bundle_path(data_root, doc, failures)
    verification_plan, verification_plan_source = _resolve_verification_plan(doc, bundle_path, failures)
    confirmation_path = _validate_confirmation_artifact(data_root, doc, failures)

    if failures:
        raise QuestAcceptanceError("\n".join(f"- {item}" for item in failures))

    if bundle_path is None or verification_plan is None or verification_plan_source is None:
        raise QuestAcceptanceError("Quest acceptance prerequisites were not satisfied.")

    bundle_info = _ensure_bundle(
        subject=subject,
        data_root=data_root,
        engine_root=engine_root,
        doc=doc,
        board_path=board_path,
        accepted_path=accepted_path,
        bundle_path=bundle_path,
        verification_plan=verification_plan,
        verification_plan_source=verification_plan_source,
        control_sync_path=control_sync_path,
        confirmation_path=confirmation_path,
    )

    normalized_text = _replace_labeled_value(
        doc.raw_text,
        "Audit Bundle Folder Path (required once ACCEPTED)",
        _canonical_bundle_field(subject, data_root, bundle_path),
    )
    accepted_path.write_text(normalized_text, encoding="utf-8")
    try:
        board_path.unlink()
    except Exception as exc:
        accepted_path.unlink(missing_ok=True)
        raise QuestAcceptanceError(f"Failed to remove BOARD quest after writing Accepted copy: {exc}") from exc

    return {
        "quest_id": doc.quest_id,
        "quest_title": doc.title,
        "board_path": str(board_path.resolve()),
        "accepted_path": str(accepted_path.resolve()),
        "audit_bundle_path": str(bundle_path.resolve()),
        "control_sync_state_path": str(control_sync_path.resolve()),
        "world_state": world_state,
        "risk": doc.risk,
        "verification_plan_source": verification_plan_source,
        "confirmation_artifact_path": str(confirmation_path.resolve()) if confirmation_path else None,
        "created_bundle_files": bundle_info["created"],
        "existing_bundle_files": bundle_info["existing"],
        "governed_execution_ready": True,
    }

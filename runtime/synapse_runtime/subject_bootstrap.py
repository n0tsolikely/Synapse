"""Subject bootstrap helpers for attach/init flows."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from synapse_runtime.live_memory import ensure_live_scaffold


DEFAULT_TIMEZONE = ZoneInfo("America/Toronto")


def today_toronto() -> str:
    return dt.datetime.now(tz=DEFAULT_TIMEZONE).date().isoformat()


def write_file(path: Path, text: str, *, force: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return "SKIP"
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return "WRITE"


def repo_subject_defaults(cwt: Path) -> dict[str, str]:
    repo_name = cwt.name.strip()
    if not repo_name:
        raise RuntimeError("Cannot derive subject from current repository root (empty name).")
    return {
        "subject": repo_name,
        "data_root": str((cwt.parent / f"{repo_name}_Data").resolve()),
        "engine_root": str(cwt.resolve()),
    }


def initialize_subject_state(subject: str, data_root: Path, engine_root: Path, *, force: bool = False) -> dict[str, list[str]]:
    """Initialize minimum canonical Subject_Data state for current repo adoption."""
    created: list[str] = []
    existing: list[str] = []

    required_dirs = [
        "confirmations",
        "Snapshots/General",
        "Snapshots/Control Sync",
        "Snapshots/End of Day",
        "Snapshots/Draft Shots",
        "Guild Orders/ACTIVE",
        "Guild Orders/PAUSED",
        "Guild Orders/COMPLETED",
        "Quest Board/Accepted",
        "Quest Board/Completed",
        "Quest Board/Abandoned",
        "Audits/Execution",
        "Codex/Sections",
        "Docs",
        "Docs/Execution Packs/Active",
        "Docs/Execution Packs/Archived",
        "Buffs",
        "To Do",
        "Talent Tree",
        "Latest Rehydration Pack",
        "Latest Rehydration Pack/Execution Pack",
        "Incubation",
        "Archive",
    ]

    for rel in required_dirs:
        path = data_root / rel
        if path.exists():
            existing.append(str(path))
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))

    today = today_toronto()
    buff_prefix = subject.upper()

    subject_state = data_root / "SUBJECT_STATE.yaml"
    subject_state_text = (
        "schema_version: 1\n"
        "subject:\n"
        f"  name: \"{subject}\"\n"
        f"  key: \"{subject}\"\n"
        "roots:\n"
        f"  data_root: \"{data_root}\"\n"
        f"  engine_root: \"{engine_root}\"\n"
        "pointers:\n"
        "  latest_rehydration_pack:\n"
        "    dir: \"Latest Rehydration Pack\"\n"
        "    bootstrap_prompt:\n"
        "      filename_contains_any:\n"
        "        - \"BOOTSTRAP_PROMPT\"\n"
        "      pick: \"single_required\"\n"
        "    continuity_lock:\n"
        "      filename_contains_any:\n"
        "        - \"CONTINUITY_LOCK\"\n"
        "      pick: \"single_required\"\n"
        "    execution_pack:\n"
        "      dir: \"Execution Pack\"\n"
        "      pick: \"optional_single\"\n"
        "  buffs:\n"
        "    dir: \"Buffs\"\n"
        f"    buff_prefix: \"{buff_prefix}\"\n"
        "    required_files:\n"
        f"      - \"{buff_prefix}_EXECUTION_PROTOCOL.txt\"\n"
        f"      - \"{buff_prefix}_DATA_DIRECTORY_MAP.txt\"\n"
        f"      - \"{buff_prefix}_SESSION_START_CHECK.txt\"\n"
    )

    buff_execution = data_root / "Buffs" / f"{buff_prefix}_EXECUTION_PROTOCOL.txt"
    buff_map = data_root / "Buffs" / f"{buff_prefix}_DATA_DIRECTORY_MAP.txt"
    buff_start = data_root / "Buffs" / f"{buff_prefix}_SESSION_START_CHECK.txt"
    bootstrap = data_root / "Latest Rehydration Pack" / f"{subject}_BOOTSTRAP_PROMPT__{today}.txt"
    continuity = data_root / "Latest Rehydration Pack" / f"{subject}_CONTINUITY_LOCK__{today}.txt"
    file_specs: list[tuple[Path, str]] = [
        (subject_state, subject_state_text),
        (
            buff_execution,
            (
                f"{subject} - EXECUTION PROTOCOL (BUFF)\n"
                "Version: v1.1\n"
                f"Last Updated: {today}\n"
                "Status: Canonical startup posture for adopted subject initialization.\n"
                "\n"
                "AUTHORITY ORDER:\n"
                "1) Locks and governance law\n"
                "2) Canonical on-disk artifacts under DATA_ROOT\n"
                "3) Conversation as intent only (never state authority)\n"
                "\n"
                "CANONICAL ROOTS:\n"
                f"- SUBJECT: {subject}\n"
                f"- ENGINE_ROOT: {engine_root}\n"
                f"- DATA_ROOT: {data_root}\n"
                "\n"
                "EXECUTION LAW:\n"
                "- Governed quest execution uses runtime/tools/synapse_quest_run.sh.\n"
                "- Completion claims require receipts in execution bundles.\n"
                "- No silent subject switching; use focus/engage explicitly.\n"
                "- Ambient sidecar truth lives in DATA_ROOT/.synapse.\n"
                "\n"
                "FIRST-SESSION POSTURE:\n"
                "- Treat this subject as newly initialized continuity.\n"
                "- Open Control Sync before creating governed execution scope.\n"
            ),
        ),
        (
            buff_map,
            (
                f"{subject} - DATA DIRECTORY MAP (BUFF)\n"
                "Version: v1.1\n"
                f"Last Updated: {today}\n"
                "Status: Canonical continuity map for adopted subject initialization.\n"
                "\n"
                "CANONICAL ROOTS:\n"
                f"- ENGINE_ROOT: {engine_root}\n"
                f"- DATA_ROOT: {data_root}\n"
                "\n"
                "CANONICAL PATHS:\n"
                f"- Buffs: {data_root / 'Buffs'}\n"
                f"- Latest Rehydration Pack: {data_root / 'Latest Rehydration Pack'}\n"
                f"- Quest Board: {data_root / 'Quest Board'}\n"
                f"- Guild Orders: {data_root / 'Guild Orders'}\n"
                f"- Audits/Execution: {data_root / 'Audits' / 'Execution'}\n"
                f"- Snapshots: {data_root / 'Snapshots'}\n"
                f"- Codex: {data_root / 'Codex'}\n"
                f"- Live sidecar: {data_root / '.synapse'}\n"
                "\n"
                "AUTHORITY SPLIT:\n"
                "- Canonical continuity/state lives in DATA_ROOT and DATA_ROOT/.synapse.\n"
                "- External .synapse lockfiles are runtime/session cursors only.\n"
                "\n"
                "EDIT RULES:\n"
                "- Update canonical artifacts in DATA_ROOT first.\n"
                "- Treat Latest Rehydration Pack artifacts as active startup anchors.\n"
            ),
        ),
        (
            buff_start,
            (
                f"{subject} - SESSION START CHECK (BUFF)\n"
                "Version: v1.1\n"
                f"Last Updated: {today}\n"
                "Status: Deterministic startup checklist for code/software subject execution.\n"
                "\n"
                "REQUIRED VERIFY FIELDS\n"
                "VERIFY_SMOKE_CMD:\n"
                "  NONE YET\n"
                "\n"
                "VERIFY_FULL_CMD:\n"
                "  NONE YET\n"
                "\n"
                "VERIFY_E2E_CMD:\n"
                "  NONE YET\n"
                "\n"
                "NETWORK_POLICY:\n"
                "  NO_EGRESS\n"
                "\n"
                "EXECUTION_SURFACE:\n"
                "  LOCAL_RUNTIME\n"
                "\n"
                "MINIMUM VERIFICATION BASELINE (until real tests exist):\n"
                "- Run import/lint/static sanity checks available in ENGINE_ROOT.\n"
                "- If no test harness exists yet, record command receipts for baseline checks.\n"
                "\n"
                "SESSION START CHECKLIST:\n"
                "- [ ] Resolve subject context via engage/focus/resolve-subject.\n"
                "- [ ] Run doctor for governance + subject state.\n"
                "- [ ] Read all three canonical Buffs in DATA_ROOT/Buffs.\n"
                "- [ ] Read active Continuity Lock in Latest Rehydration Pack.\n"
                "- [ ] Read active Bootstrap Prompt in Latest Rehydration Pack.\n"
                "- [ ] Open Control Sync before binding scope or quest execution.\n"
            ),
        ),
        (
            bootstrap,
            (
                f"{subject} - BOOTSTRAP PROMPT\n"
                "Version: v1.1\n"
                f"Last Updated: {today}\n"
                f"DATE (local): {today} (America/Toronto)\n"
                "\n"
                "ROLE / STANCE:\n"
                f"- You are Hands operating under Synapse governance for subject {subject}.\n"
                "- Conversation is input; files on disk are authority.\n"
                "- Operate deterministically and prefer receipts over claims.\n"
                "\n"
                "AUTHORITY ORDER:\n"
                "1) Locks + governance law\n"
                "2) Canonical subject artifacts in DATA_ROOT\n"
                "3) Runtime/session lockfiles as cursor hints\n"
                "4) Conversation intent (non-authoritative)\n"
                "\n"
                "BINDING STATE (DO NOT RE-LITIGATE):\n"
                "- Continuity Lock defines what is true and what is binding.\n"
                "- Do not redesign settled decisions without explicit Control Sync.\n"
                "\n"
                "ALLOWED NOW:\n"
                "- Rehydrate from Buffs + Continuity Lock + Bootstrap Prompt.\n"
                "- Inspect ENGINE_ROOT and DATA_ROOT to establish truthful baseline.\n"
                "- Run doctor and prepare Control Sync inputs.\n"
                "\n"
                "FORBIDDEN NOW:\n"
                "- Do not treat chat text as canonical state.\n"
                "- Do not silently change subject roots.\n"
                "- Do not claim completion without execution receipts.\n"
                "\n"
                "READ PRIORITY:\n"
                "1) DATA_ROOT/Buffs/*\n"
                "2) DATA_ROOT/Latest Rehydration Pack/*CONTINUITY_LOCK*\n"
                "3) DATA_ROOT/Latest Rehydration Pack/*BOOTSTRAP_PROMPT*\n"
                "4) DATA_ROOT/Codex and active governance routing docs\n"
                "\n"
                "FIRST ACTION:\n"
                "- Run doctor, then open Control Sync and define the first governed next step.\n"
                "\n"
                "CANONICAL ROOTS:\n"
                f"- SUBJECT: {subject}\n"
                f"- DATA_ROOT: {data_root}\n"
                f"- ENGINE_ROOT: {engine_root}\n"
            ),
        ),
        (
            continuity,
            (
                "CONTINUITY LOCK\n"
                "Version: v1.1\n"
                f"Last Updated: {today}\n"
                "\n"
                f"SUBJECT: {subject}\n"
                f"DATE: {today}\n"
                "WORLD STATE: FOG OF WAR (initial subject continuity scaffold; no codex freeze marker yet)\n"
                "CURRENT PHASE: Subject initialization via attach-or-init / engage --adopt-current-repo\n"
                "\n"
                "BINDING DECISIONS (LAW):\n"
                f"- ENGINE_ROOT is fixed to: {engine_root}\n"
                f"- DATA_ROOT is fixed to: {data_root}\n"
                "- Canonical continuity artifacts live under DATA_ROOT.\n"
                "- Canonical ambient sidecar state lives under DATA_ROOT/.synapse.\n"
                "- External session locks are convenience cursors only.\n"
                "- Governed quest execution waits for Control Sync + accepted quest scope.\n"
                "\n"
                "DEFERRED / REJECTED:\n"
                "- DEFERRED: Codex freeze and execution-phase guild orders.\n"
                "- REJECTED: Phantom *_Engine defaults that diverge from the adopted repo.\n"
                "\n"
                "ACTIVE SCOPE / COMMITMENTS:\n"
                "- ACTIVE: Establish deterministic startup continuity and read order.\n"
                "- PAUSED: Governed execution until Control Sync defines first scoped quest.\n"
                "- COMPLETE: Subject continuity scaffold initialization.\n"
                "\n"
                "REQUIRED READ FIRST:\n"
                f"- {data_root / 'Buffs' / f'{buff_prefix}_EXECUTION_PROTOCOL.txt'}\n"
                f"- {data_root / 'Buffs' / f'{buff_prefix}_DATA_DIRECTORY_MAP.txt'}\n"
                f"- {data_root / 'Buffs' / f'{buff_prefix}_SESSION_START_CHECK.txt'}\n"
                f"- {continuity}\n"
                f"- {bootstrap}\n"
                "\n"
                "RESUME POINT:\n"
                "- Open Control Sync and define the first governed quest or incubation objective.\n"
            ),
        ),
    ]

    for path, text in file_specs:
        result = write_file(path, text, force=force)
        if result == "WRITE":
            created.append(str(path))
        else:
            existing.append(str(path))

    live = ensure_live_scaffold(subject, data_root)
    created.extend([str(Path(p)) for p in live.get("created", [])])
    existing.extend([str(Path(p)) for p in live.get("existing", [])])
    return {"created": created, "existing": existing}

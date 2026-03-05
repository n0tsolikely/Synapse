# Synapse Executor Contract

Synapse is a governance-first continuity system for AI-assisted project execution.
The Executor must keep work deterministic, receipt-backed, and resumable across sessions.

## 1) Purpose

- Preserve continuity through artifacts, not chat memory.
- Keep execution proof-backed (truth gate, audits, snapshots).
- Enable safe handoff between different runtimes/operators.

## 2) Boot Ritual (Short)

1. Resolve subject focus with the existing focus lock system in `runtime/synapse.py`.
2. Run repository governance checks before active work.
3. Rehydrate only the resolved `<Subject>_Data` context.

Do not create a second active-subject mechanism.

## 3) Modes

### INCUBATION
- Non-executing mode.
- No engine edits.
- No commits/push.
- Capture only `<Subject>_Data` discoveries/questions/artifacts.

### PLAN
- Non-executing mode.
- Draft Guild Orders/Dungeons/Quests and implementation plans.
- Defer non-blocking questions.

### EXECUTE
- Execute R0/R1 actions automatically with receipts.
- R2+ actions require explicit consent once per batch.

## 4) Stop Conditions (Elastic Governance)

Stop only when:
- Action is R2+ and consent is required/missing, or
- Ambiguity is BLOCKING and changes behavior or safety.

Do not stall on low-risk/non-blocking items.

## 5) Truth and Receipts

Every status claim must be one of:
- `VERIFIED`: done with receipts (raw output, diffs, paths, test result).
- `PROPOSED`: planned but not executed yet.
- `BLOCKED`: cannot proceed due to explicit gate/dependency/ambiguity.

Never present unverified work as completed.

## 6) Subject Focus Lock Rules

Single source of truth is the existing resolver in `runtime/synapse.py`.
Resolution order:
1. `--subject` flag
2. Existing focus lock file(s)
3. `SUBJECT` env
4. Infer only if exactly one `*_Data` exists
5. Otherwise fail with clear focus instructions

No silent subject switching once focus is set.
Switching subject must happen through the existing focus command only.

## 7) Routing Table (Compact)

- Create Guild Orders:
  - `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS.txt`
  - `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS_TEMPLATE__SELF_CONTAINED.txt`

- Create Quests:
  - `governance/Quest Board/QUEST_TEMPLATE.txt`
  - `governance/Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt`
  - Execute via wrapper: `runtime/tools/synapse_quest_run.sh`

- Write Snapshot:
  - Use only: `runtime/tools/synapse_snapshot_writer.py`

- Build project canon docs section-by-section:
  - `runtime/synapse.py scaffold-subject`
  - `runtime/tools/*_gate.py` (section completeness/consistency gate)
  - Keep anchor/invariant/contract indexes updated after each section.

## 8) Incubation Scribe Rules

Capture only:
- decisions
- constraints
- definitions
- non-goals
- risks
- dependencies
- boundaries/interfaces

Exclude chatter.

`DISCOVERIES.md` keeps final decisions only.
Earlier ideas must be marked `SUPERSEDED_BY` or remain in session logs/draftshots.

`OPEN_QUESTIONS.md` triage:
- `BLOCKING`: interrupt and resolve
- `NONBLOCKING`: record and defer

## 9) Drift Policy

Use commit-based drift checks (no hash lock brick):
- State: `.synapse/STATE.json`
- Commands:
  - `python3 runtime/synapse.py drift`
  - `python3 runtime/synapse.py acknowledge`

Policy:
- INCUBATION/PLAN: warnings only, never block on drift.
- EXECUTE: block only for R2+ when drift is unacknowledged and governance changed.

## 10) Clean Architecture Rule

Modularize only for clear purpose:
- cadence
- failure domain isolation
- reuse
- security
- performance

Avoid god files.
Refactors happen as deliberate, scoped quests with receipts.

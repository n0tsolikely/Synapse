# AGENTS.md — Synapse Elastic Governance Router

Scope:
- Applies to this repository tree.
- Purpose is routing and enforcement, not encyclopedic restatement.

================================================================================
0) Canonical Roots
================================================================================

- `SYNAPSE_ROOT=${SYNAPSE_ROOT:-$HOME/Synapse}`
- `GOVERNANCE_ROOT=${GOVERNANCE_ROOT:-$SYNAPSE_ROOT/governance}`
- Subject is resolved ONLY via existing Subject Focus Lock system in `runtime/synapse.py`.

================================================================================
1) Start Ritual (Mandatory)
================================================================================

1. Run focus first:
   - `python3 "$SYNAPSE_ROOT/runtime/synapse.py" focus`
2. Run doctor:
   - `python3 "$SYNAPSE_ROOT/runtime/synapse.py" doctor --governance-root "$GOVERNANCE_ROOT"`
3. Rehydrate only the resolved subject.

Rule:
- Do not read/write subject artifacts before focus is resolved.

================================================================================
2) Subject Focus Lock (Single Source of Truth)
================================================================================

Use the existing implementation only. Do not build a second focus system.

Resolution order:
1. `--subject` flag
2. existing focus lock file(s)
3. `SUBJECT` env
4. infer if exactly one `*_Data` exists
5. else fail with instruction to run `synapse focus`

No silent switching:
- If active focus lock exists, subject change is forbidden unless user runs:
  - `python3 "$SYNAPSE_ROOT/runtime/synapse.py" focus`

================================================================================
3) Elastic Modes
================================================================================

Modes:
- `INCUBATION`
- `PLAN`
- `EXECUTE`

Commands:
- Show mode: `python3 runtime/synapse.py mode`
- Set mode: `python3 runtime/synapse.py mode --set INCUBATION|PLAN|EXECUTE`

Friction budget:
- Stop only on:
  - R2+ actions (side effects/state transitions), or
  - BLOCKING ambiguity.

Mode law:
- INCUBATION:
  - No execution.
  - No engine edits.
  - No commits/push.
  - Only `<Subject>_Data` artifacts.
  - If user asks to execute: reply `Switch to EXECUTE mode.`
- PLAN:
  - Planning/specification only.
  - Keep non-blocking questions deferred.
- EXECUTE:
  - R0/R1 auto.
  - R2+ requires explicit consent (once per batch, not per step).

================================================================================
4) Drift Policy (Git Commit IDs, No Hash Brick)
================================================================================

State file:
- `.synapse/STATE.json`

Fields include:
- `mode`
- `last_ack_commit`
- `drift_warned_sessions`

Commands:
- `python3 runtime/synapse.py drift`
- `python3 runtime/synapse.py acknowledge`

Policy:
- INCUBATION/PLAN: never block due to drift.
- EXECUTE:
  - R0/R1: warn once per session.
  - R2+: block only if drift is unacknowledged AND governance changed.

================================================================================
5) Tool Routing (Authoritative Path)
================================================================================

Always route through canonical governance docs first, then tool/validator.

- Guild Orders:
  - Docs: `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS.txt`
  - Template: `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS_TEMPLATE__SELF_CONTAINED.txt`

- Quests / execution receipts:
  - Tool: `governance/tools/synapse_quest_run.sh`
  - Validator: `governance/tools/synapse_governance_guard.py`

- Consent:
  - Tool: `governance/tools/synapse_consent.sh`

- Snapshots:
  - Tool: `governance/tools/synapse_snapshot_writer.py`

- Incubation/Codex scaffolding:
  - Tool: `python3 runtime/synapse.py scaffold-subject`

- Codex gates:
  - Tool: `governance/tools/synapse_codex_gate.py`

================================================================================
6) Incubation Scribe Rules
================================================================================

Capture only:
- decisions, constraints, definitions, non-goals, risks, dependencies, boundaries, interfaces.

Do not capture chatter.

Artifacts:
- `Incubation/SessionLogs/`
- `Incubation/DISCOVERIES.md`
- `Incubation/OPEN_QUESTIONS.md`
- `Incubation/DRAFTSHOT__INCUBATION__TEMPLATE.md`

Ledger rules:
- `DISCOVERIES.md` contains FINAL decisions only.
- superseded ideas must be marked `SUPERSEDED_BY` or kept in SessionLogs/Draftshots.
- `OPEN_QUESTIONS.md` must be triaged:
  - BLOCKING: interrupt
  - NONBLOCKING: defer

================================================================================
7) Truth + Receipts (Non-Negotiable)
================================================================================

No claims without receipts:
- raw command output
- diffs/patches
- concrete file paths
- test results where applicable


# Synapse Governance Skill

Use this skill when the current workspace contains:

- `EXECUTOR.md`
- `governance/SYNAPSE_STATE.yaml`

## Purpose

Apply Synapse governance without replacing the runtime's existing persona or identity files.

## Rules

- Preserve the agent's existing `SOUL`, `USER`, `IDENTITY`, and runtime-native tool behavior.
- Read repo `AGENTS.md`, then repo `EXECUTOR.md`.
- Resolve subject via:
  - `python3 runtime/synapse.py engage --shell`
  - or `python3 runtime/synapse.py resolve-subject --shell`
- Run doctor.

Use Synapse tools for governed operations:

- snapshots
- consent
- quest execution
- audit validation
- codex gate

If subject is unresolved:

- stop cleanly
- tell the human to continue, switch, or create a subject

Do not silently default to placeholder subjects.

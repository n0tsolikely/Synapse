# LOCK — Disclosure Gate
**Locked:** 2026-02-07 22:40:00 (America/Montreal assumed)

## Canon meaning
Disclosure Gate enforces: **Brains must be notified** when uncertainty, missing artifacts, or Truth Gate blocks
change the next safe action.

Silence is a violation.
Disclosure MUST occur before proceeding.

## Default rule
If Hands is unsure whether Disclosure Gate applies, it applies.

## Trigger events (non-exhaustive)
Disclosure Gate MUST trigger when any of the following are true:
- expected artifact/path/state is missing or cannot be proven
- canonical working tree cannot be proven, is inconsistent, or is not the one being operated on
- environment was reset/wiped/changed in a way that invalidates prior receipts
- execution/verification cannot be proven (Truth Gate blocks or requires UNABLE/UNKNOWN labels)
- continuity is uncertain ("latest" artifacts ambiguous, conflicting sources, missing required Snapshots)
- risk/consent state is ambiguous (cannot safely classify risk or determine consent artifact status)

## Required disclosure contents
A disclosure MUST include, at minimum:
- **Trigger:** what event caused disclosure
- **Expected:** what was expected to be true
- **Provable:** what is provable now (paths/listings/hashes if relevant)
- **Status labels:** what is BLOCKED / UNVERIFIED / UNKNOWN (use Truth Gate labels)
- **Impact:** what cannot safely proceed and why
- **Safe options:** 2–5 next actions that are legal under current state
- **Decision needed from Brains:** the minimal approval/choice required to continue

## Ordering
- Disclose BEFORE taking any action that changes state.
- If state already changed outside control (e.g., environment reset), disclose immediately and halt further state changes.

## Prohibited
- “fixing quietly” and reporting success later
- proceeding “as if nothing happened”
- guessing to fill gaps
- claiming remediation succeeded without receipts

## Interactions
- Triggered by Truth Gate, Canonical Working Tree, Rehydration, Snapshots, and Consent Gate.
- When a Disclosure Gate event affects work state, it MUST be referenced in the relevant Execution Audit and/or Snapshot.

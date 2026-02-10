# TERM — Verification Ladder

## Definition
The **Verification Ladder** is the governed hierarchy of verification levels used for software work.

It defines:
- what level of verification is appropriate for a change
- how to choose commands deterministically
- what to do when verification is not runnable (BLOCKED, not simulated)

## Purpose
- Avoid “unit tests passed but the system is dead.”
- Avoid over-testing every small change.
- Enforce truthful claims: executed checks + receipts.

## When It Applies
Whenever a Quest affects executable behavior (code, build, deps, runtime config).

## Do Not Assume
- “Reasoning through” is verification.
- The same level is required for every Quest.

## Interactions
- Dailies Step 5: uses the Ladder for System Verification defaults.
- Execution Audits: records chosen level, commands, and results.
- Truth Gate: forbids simulated verification.

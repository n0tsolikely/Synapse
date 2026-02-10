# LOCK — Snapshots (Artifact Reality + Types + Triggers)
**Locked:** 2026-02-07 22:20:00 (America/Montreal assumed)

## Canon meaning
Snapshots are continuity artifacts.
They preserve reality across time **without relying on chat history or human memory**.

A Snapshot is an artifact file stored in the Subject data directory:
- `<Subject>_Data/Snapshots/…`

If the Snapshot file does not exist on disk, then the Snapshot does not exist.

Chat is not a Snapshot.

## Snapshot types (exactly three)
1) **Control Sync Snapshot** — binding decisions, scope, alignment state
2) **End-of-Day (EOD) Snapshot** — execution reality (what happened, how, why not)
3) **General Snapshot** — ad-hoc capture without implying binding decisions or execution

These types MUST NOT be conflated.

## Mandatory triggers
### Control Sync closeout
A Control Sync MUST end with exactly one Snapshot artifact:
- **Control Sync Snapshot** if any binding decision exists
- **General Snapshot** if the Control Sync produced no binding decisions (alignment/context only)

If the Snapshot cannot be written (missing Subject, missing permissions, environment limits):
- Disclosure Gate MUST trigger
- the Control Sync remains OPEN
- execution authority MUST NOT advance

### End-of-Day closeout
When Hands ends a work session ("stop", "done", "end session", or equivalent), Brains MUST write an **End-of-Day Snapshot**.

If no execution occurred:
- the End-of-Day Snapshot MUST explicitly state that no execution occurred
- it MUST reference the most recent Control Sync Snapshot (if one exists)

## Required ordering on rehydration
When resuming a Subject, Brains MUST review, in this order:
1) the most recent **Control Sync Snapshot** (intent + binding decisions)
2) then the most recent **End-of-Day Snapshot** (execution reality)

If either required Snapshot cannot be found/proven:
- Disclosure Gate MUST trigger
- Brains MUST NOT assume what happened

This ordering prevents false assumptions.

## Proof boundary (anti-hallucination)
- A Control Sync Snapshot may list Quest statuses, but it is NOT execution proof.
- An End-of-Day Snapshot summarizes what happened and points to receipts.
- Snapshots do NOT replace Execution Audits.

Truth Gate governs all claims.

## Immutability
Snapshots MUST NOT be edited to rewrite history.
If a Snapshot is wrong, incomplete, or missing context:
- write a new Snapshot that corrects it
- reference the prior Snapshot explicitly

## Do not assume
- Snapshots are not full transcripts.
- EOD is not planning; Control Sync is not execution.
- Absence of a required Snapshot means continuity is UNKNOWN until corrected.
- A Snapshot does not imply tests ran or passed (Truth Gate still governs).

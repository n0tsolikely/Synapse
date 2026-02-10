# TERM — Snapshot

## Definition
A Snapshot is a **Subject_Data continuity artifact** (a file on disk) that
captures a bounded state of alignment or execution at a point in time.

## Artifact Law
- If the Snapshot file does not exist on disk in `<Subject>_Data/Snapshots/`, the
  Snapshot does not exist.
- Chat summaries are not Snapshots.

## Types
- Control Sync Snapshot
- End‑of‑Day Snapshot
- General Snapshot

## Trigger Rules (hard anchor; no interpretation)
- Every Control Sync MUST end with exactly one Snapshot file:
  - Control Sync Snapshot if binding decisions exist
  - General Snapshot if no binding decisions exist
- Every execution session/day MUST end with an End‑of‑Day Snapshot file.

## Purpose
- Prevent context loss across sessions/days/operators
- Preserve “intent vs reality” (decisions vs executed outcomes)
- Make rehydration deterministic (no guessing)

## Do Not Assume
- A Snapshot is not a full transcript.
- A Snapshot is not a substitute for per‑quest audit bundles.
- A Snapshot is not optional when required by law.

## Interactions
- Rehydration reviews Snapshots in locked order:
  1) latest Control Sync Snapshot (intent/decisions)
  2) latest End‑of‑Day Snapshot (execution reality/outcomes/blockers)
  3) relevant General Snapshots
- Snapshots are referenced by the Continuity Lock and Bootstrap Prompt.

## Authority
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt`
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt`

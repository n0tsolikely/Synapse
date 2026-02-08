# TERM — Snapshot

## Definition
A Snapshot is a recorded state of alignment or execution at a point in time, captured as an artifact to preserve continuity.

## Purpose
Snapshots prevent context loss across sessions and ensure future operators (human or AI) can resume without guessing.

## When It Applies
- At the end of a Control Sync
- At the end of execution periods (End-of-Day)
- When continuity risk is high (General)

## What It Enables
- Deterministic rehydration
- Evidence of what was decided vs what was executed
- Reduced rework and repeated failure

## Do Not Assume
- A Snapshot is not a full transcript
- A Snapshot is not always execution-related
- A Snapshot is not a replacement for Audits (receipts) or Talents (capability index)

## Interactions
- Control Sync Snapshot is reviewed before the corresponding End-of-Day Snapshot (intent → reality)
- End-of-Day Snapshot provides execution receipts and failure reasons

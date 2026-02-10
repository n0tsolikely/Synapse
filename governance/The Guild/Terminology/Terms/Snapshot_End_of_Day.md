# TERM — End-of-Day Snapshot

## Definition
An End-of-Day Snapshot is the **Snapshot file** written at the end of an execution
session/day.

It records execution reality: what was implemented, what was verified, what failed
(or was blocked), and which artifacts changed.

## Artifact Law
- If the Snapshot file does not exist on disk in `<Subject>_Data/Snapshots/End of Day/`,
  the Snapshot does not exist.
- Chat summaries are not Snapshots.

## Trigger (hard anchor; no interpretation)
- Every execution session/day MUST end with an End-of-Day Snapshot file
  (written before STOP).

## Minimum Contents (hard anchor)
- What Quests were executed (IDs) and what work was performed (high-level steps)
- Verification performed and where receipts live (paths)
- Failures/blockers (what happened, why, and the next action)
- Artifact changes (paths) and why they were changed
- If zero execution occurred: explicitly state that and reference the latest
  Control Sync Snapshot (if one exists)

## Not This
- Not a planning document
- Not a scope redefinition artifact
- Not a substitute for per-quest audit bundles

## Interactions
- Reviewed after the prior Control Sync Snapshot during rehydration
- Feeds the next Control Sync (decide what to do next)

## Authority
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt`
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt`

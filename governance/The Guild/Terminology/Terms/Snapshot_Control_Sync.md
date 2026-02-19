# TERM — Control Sync Snapshot

## Definition
A Control Sync Snapshot is the **Snapshot file** written at the end of a Control Sync.

It records the **binding outcome** of the Control Sync: decisions, scope commitment,
constraints, and references to updated artifacts.

## Artifact Law
- If the Snapshot file does not exist on disk in `<Subject>_Data/Snapshots/Control Sync/`,
  the Snapshot does not exist.
- Chat summaries are not Snapshots.

## Trigger (hard anchor; no interpretation)
- A Control Sync MUST end with exactly one Snapshot file:
  - Control Sync Snapshot if any binding decision was made
  - General Snapshot if no binding decisions were made (alignment/context only)

## Minimum Contents (hard anchor)
- What is now binding (decisions / scope / constraints)
- What is explicitly **NOT** decided (deferrals)
- References to affected artifacts (paths)
- If Quests were accepted or re-scoped: list IDs + intended outcomes (not receipts)
- If an Execution Pack was activated/changed: name + canonical path

## Not This
- Not an execution receipt (execution reality belongs in End-of-Day Snapshots and per-quest audits)
- Not a transcript
- Not brainstorming

## Interactions
- Reviewed first during session start rehydration (before planning/accepting/implementing)
- May be referenced by the Continuity Lock
- A Control Sync is not considered closed until this Snapshot exists as a file

## Authority
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt`
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt`


## AI11: Draftshot source
If a Draftshot is ACTIVE during the Control Sync, the Control Sync Snapshot is a formalization of that Draftshot and MUST reference the Draftshot path + REV.

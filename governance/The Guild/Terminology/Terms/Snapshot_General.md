# TERM — General Snapshot

## Definition
A General Snapshot is the **Snapshot file** used for continuity capture that is
neither:
- a Control Sync Snapshot (binding outcome), nor
- an End-of-Day Snapshot (execution reality).

## Artifact Law
- If the Snapshot file does not exist on disk in `<Subject>_Data/Snapshots/General/`,
  the Snapshot does not exist.
- Chat summaries are not Snapshots.

## Trigger (hard anchor; no interpretation)
- Used for ad-hoc continuity capture when neither Control Sync Snapshot nor
  End-of-Day Snapshot applies.
- If a Control Sync ends with **no binding decisions**, the Control Sync MUST end
  with a General Snapshot (this closes the Control Sync).

## Minimum Contents (hard anchor)
- The context that must survive to avoid re-discovery
- References to relevant artifacts (paths)
- If used to close a non-binding Control Sync: explicitly state
  `NO BINDING DECISIONS`.

## Not This
- Not a Control Sync Snapshot (it must not claim binding scope)
- Not an execution receipt

## Interactions
- May be referenced during Control Sync or rehydration to restore context.
- Lower authority than the latest Control Sync Snapshot and End-of-Day Snapshot
  when conflicts exist.

## Authority
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt`
→ `Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt`

# TERM — Engine and Data

## Definition (Subject scope)
- **Engine** = the deliverable workspace (the thing being built).
- **Data** = the subject’s continuity + governance artifacts that describe, constrain, and audit the work.

## In any Subject
- `<Subject>_Engine/` contains the deliverable (codebase, manuscript, game project, etc.).
- `<Subject>_Data/` contains Codex, TOC, Snapshots, Quest Board, Audits, Guild Orders, Buffs, Rehydration artifacts, Talent Tree, etc.

## Governance pack
The Synapse Governance Pack (this pack) is governance law + processes.
- It is not a Subject’s Engine and it is not a Subject’s Data.
- It may be injected into a session to govern behavior.

## Separation law (anti-drift)
- Do not store continuity artifacts inside `<Subject>_Engine/`.
- Do not store deliverable implementation inside `<Subject>_Data/`.
- If an artifact appears in both places, it is a parallel state and MUST be resolved (Disclosure Gate).
- If you are unsure where something belongs, default to **NOT MOVING IT** and trigger Disclosure Gate.

## Related locks (authority above this term)
- `LOCK__ENGINE_VS_DATA.md`
- `LOCK__CANONICAL_WORKING_TREE.md`
- `LOCK__SUBJECT_DATA_SKELETON.md`

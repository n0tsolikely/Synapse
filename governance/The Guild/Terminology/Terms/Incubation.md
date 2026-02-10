# TERM — Incubation

## Definition
Incubation is the **Fog of War** lifecycle phase for a Subject where the Codex/Map is not yet frozen.

Draft TOC/Codex content MAY exist during Incubation, but it is **non-authoritative** until Codex Freeze is recorded.

Incubation ends only when Fog Lifted is true:
- `<Subject>_Data/Codex/CODEX_FREEZE.md` exists.

## Applicability / Preconditions
Incubation is active when:
- A Subject is being created or refined, and
- Fog Lifted is not true (no Codex Freeze marker exists).

## Allowed Work (Fog of War)
- Exploration (questions, tradeoffs, constraint discovery)
- Recording Discoveries into artifacts (Snapshots / Codex drafts)
- Drafting and iterating TOC and Codex sections
- Producing continuity artifacts (Snapshots, Rehydration Pack artifacts)

## Forbidden (execution commitments)
- Starting Raids / executing Guild Orders
- Accepting Quests (moving any Quest into `Accepted/`)
- Treating draft notes as authoritative constraints for execution
- Claiming “implemented”, “tested”, or “verified” without executable receipts

## Purpose
Prevent premature execution and refactors by forcing meaning, constraints, and structure to crystallize before building.

## Authority
→ `Processes/SYNAPSE_GUILD__SUBJECT_INITIALIZATION_AND_INCUBATION.txt`  
→ `The Guild/Terminology/Locks/LOCK__FOG_OF_WAR.md`  
→ `The Guild/Terminology/Locks/LOCK__CODEX_FREEZE_FOG_LIFTED.md`

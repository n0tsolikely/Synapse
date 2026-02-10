# TERM — Exploration

## Definition
Exploration is the set of allowed behaviors under **Fog of War** used to reveal the Subject’s constraints, invariants, requirements, risks, and structure.

Exploration is how the map is discovered before it is frozen.

## Applicability
- World State: Fog of War
- During Incubation
- During rehydration when a Codex Freeze marker does not exist

## Output / Artifact Law
Exploration only “counts” when its results are captured into filesystem artifacts, such as:
- Snapshots (General or Control Sync)
- Draft TOC/Codex updates

Chat-only exploration is non-authoritative and MUST NOT be treated as state.

## Do Not Assume
- Exploration is not execution.
- Exploration does not start Raids.
- Exploration does not accept Quests.
- Exploration does not create commitments unless elevated into a binding artifact.

## Interactions
- Exploration produces Discoveries.
- Discoveries inform TOC and Codex construction.
- Once the Codex is sufficiently complete, Hands may freeze it (Fog Lifted) to authorize execution.

## Authority
→ `The Guild/Terminology/Locks/LOCK__FOG_OF_WAR.md`  
→ `Processes/SYNAPSE_GUILD__SUBJECT_INITIALIZATION_AND_INCUBATION.txt`

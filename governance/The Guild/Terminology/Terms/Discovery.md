# TERM — Discovery

## Definition
A Discovery is a single unit of revealed truth about the Subject uncovered during Exploration while **Fog of War** is active.

A Discovery should be phrased as a testable statement (not a vague idea), e.g.:
- constraint
- invariant
- requirement
- dependency
- risk
- structural insight

## Artifact Law
A Discovery is only authoritative if it is recorded in a filesystem artifact, such as:
- a Snapshot (Control Sync / General), and/or
- the Codex (as an explicit rule/constraint)

If it only exists in conversation, it is non-authoritative and MUST NOT be treated as a hard constraint for execution.

## Do Not Assume
- Discovery ≠ Task
- Discovery ≠ Quest
- Discovery ≠ Commitment
- Discovery does not authorize execution.

## Interactions
- Discoveries accumulate during Fog of War.
- Conflicting Discoveries must be resolved before Codex Freeze.
- After Codex Freeze, new Discoveries must be integrated via Codex updates + Snapshots (no ad-hoc rule injection).

## Authority
→ `The Guild/Terminology/Locks/LOCK__FOG_OF_WAR.md`  
→ `Guild Docs/SYNAPSE_GUILD__CODEX.txt`

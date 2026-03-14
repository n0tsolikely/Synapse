# TERM — Build Manual

## Definition
A Build Manual is an **optional construction guide** for a Subject.

It defines **HOW** to make the Codex true, for example:
- build steps and sequencing
- scaffolds and wiring strategy
- operational construction rules
- verification expectations (what to run, when)
- maintenance and repair guidance when structure must change without drifting

The Codex defines **WHAT** the system is.
The Build Manual defines **HOW** it should be built, changed, or repaired without redefining that truth.

## Purpose
Reduce ambiguity and drift by making the intended build path repeatable for any compliant operator (Hands or Brains).

A Build Manual is especially useful when:
- the Subject has multiple structural slices that can be built in the wrong order
- verification expectations need to stay repeatable
- the system needs stable operator guidance beyond one Quest or one Execution Pack

## When It Applies
- If a Build Manual exists for a Subject, Hands follows it as the default HOW guidance unless superseded by a lawful Control Sync decision.
- In Dailies System Verification:
  - **Codex Alignment** is always required.
  - **Build Manual Alignment** is required only if a Build Manual exists.
- Build Manual guidance may evolve over time as the Subject becomes more understood, but those changes remain subordinate to Codex law.

## Do Not Assume
- A Build Manual is not required for every Subject.
- Absence of a Build Manual is not a failure.
  - It means execution guidance comes from Quests, Buffs, Execution Packs, continuity surfaces, and currently active canonical constraints.
- A Build Manual MUST NOT redefine Codex laws.
- A Build Manual is not the Talent Tree.
  - It does not exist to list capabilities.
- A Build Manual is not the Vision surface.
  - It does not exist to summarize identity.

## Interactions
- Pairs with Codex (WHAT) and Buffs / Execution Packs / Quests (operational HOW for bounded work).
- Build Manual guidance is broader and more durable than a single Execution Pack.
- Execution Packs may point at Build Manual guidance when a currently active slice needs deterministic operational clarity.
- Referenced by Dailies System Verification (alignment checks).
- If Build Manual guidance conflicts with Codex or active Control Sync outputs, escalate; do not improvise.

## Recommended location
- `<Subject>_Data/Build_Manual/`

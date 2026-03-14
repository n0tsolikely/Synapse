# LOCK — Fog of War (World State)
**Locked:** 2026-03-12 00:00:00 (America/Toronto assumed)

## Canon meaning
Fog of War is the **default World State** when Codex Freeze is not proven.

It means the Subject is **not yet legal for governed execution**.
The Subject may still be explored, drafted, mapped, clarified, and structurally improved,
but it is not yet stable enough to turn execution into binding canonical commitments.

Fog of War is **GLOBAL**: it constrains what all other modes may claim.

What Fog of War means in one sentence:
- **Structure may grow; governed execution may not begin.**

## Proof rule (how to determine state)
Fog of War MUST be treated as ACTIVE unless **Codex Freeze is proven** per:
- `LOCK__CODEX_FREEZE_FOG_LIFTED.md`

Minimum proof check (non-negotiable):
- the marker file exists on disk at:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`
- and the marker contains explicit Brains approval (per the Codex Freeze lock)

If proof cannot be produced in the current canonical working tree:
- Fog of War remains ACTIVE (default)

## Allowed while Fog of War is active (structure formation / non-governed motion)
Allowed:
- Exploration / Incubation / Discovery capture
- Subject initialization and `<Subject>_Data` skeleton setup
- Drafting and revising the TOC / Legend
- Drafting and revising Codex sections (including seed, draft, and spine work; no Freeze claim)
- Drafting Build Manual material
- Drafting Guild Orders in **PAUSED**
- Drafting Quests and Side-Quests on **BOARD** as proposals / canonical board artifacts
- Ambient quest detection, candidate clustering, and lawful BOARD drafting when done truthfully
- Control Sync sessions for alignment (Control Sync may occur under Fog)
- Required snapshots + continuity artifacts
- Ambient capture of decisions, discoveries, disclosures, run state, changed files, and verification surfaces
- Non-governed exploratory implementation or prototyping, if it occurs, provided it is treated as exploratory motion rather than governed quest execution

Clarification:
- Fog of War does **not** require inactivity.
- Fog of War does **not** forbid the system from learning what the Subject is.
- Fog of War does **not** forbid the system from writing down emerging structure.

## Forbidden while Fog of War is active (execution commitments)
Forbidden (no exceptions):
- Accepting Quests (BOARD → ACCEPTED)
- Starting a Raid / executing Guild Orders as governed work (PAUSED → ACTIVE)
- Claiming `governed_execution_ready` status
- Claiming that exploratory work completed an Accepted Quest or fulfilled a Raid
- Claiming "execution-ready" status (Freeze implied) without proving Codex Freeze

Forbidden by default:
- Creating `<Subject>_Engine/` during Fog of War
  - Exception: allowed only if Brains explicitly orders it OR Brains provides an existing Engine to treat as canonical
  - This exception does NOT lift Fog of War

## Doctrine note — what Fog governs
Fog of War governs **legality of governed execution**.
It is not the whole life of a Subject.

While Fog is active, Synapse may still:
- observe movement
- preserve continuity
- detect and cluster work
- draft structure
- prepare the Subject for later governed execution

What Synapse may not do is present that movement as already authorized governed history.

## Exit condition (Fog Lifted)
Fog of War ends ONLY when Codex Freeze is proven (marker file + Brains approval).

If Codex Freeze becomes stale, missing, unreadable, or contradictory:
- Fog of War MUST be treated as ACTIVE again immediately (Disclosure Gate)

## Do not assume
- Fog of War does not mean "no progress" — it means "no governed execution commitments."
- Chat statements do not lift Fog — artifacts do.
- "We have a Codex" does not lift Fog — proven Freeze does.
- Drafted BOARD quests do not lift Fog.
- Exploratory implementation under Fog does not count as governed execution unless and until later lawfully accepted and recorded.

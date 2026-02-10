# LOCK — Fog of War (World State)
**Locked:** 2026-02-08 00:00:00 (America/Toronto assumed)

## Canon meaning
Fog of War is the **default World State** when Codex Freeze is not proven.

It means the Subject’s structure, constraints, and safe execution paths are not yet fixed enough to safely make execution commitments.

Fog of War is **GLOBAL**: it constrains what all other modes may do.

## Proof rule (how to determine state)
Fog of War MUST be treated as ACTIVE unless **Codex Freeze is proven** per:
- `LOCK__CODEX_FREEZE_FOG_LIFTED.md`

Minimum proof check (non-negotiable):
- the marker file exists on disk at:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`
- and the marker contains explicit Hands approval (per the Codex Freeze lock)

If proof cannot be produced in the current canonical working tree:
- Fog of War remains ACTIVE (default)

## Allowed while Fog of War is active (non-execution work)
Allowed:
- Exploration / Incubation / Discovery capture
- Subject initialization and `<Subject>_Data` skeleton setup
- Drafting TOC and Codex sections (including revisions; no Freeze claim)
- Drafting Guild Orders in **PAUSED**
- Drafting Quests on **BOARD** as proposals
- Control Sync sessions for alignment (Control Sync may occur under Fog)
- Required snapshots + continuity artifacts

## Forbidden while Fog of War is active (execution commitments)
Forbidden (no exceptions):
- Accepting Quests (BOARD → ACCEPTED)
- Starting a Raid / executing Guild Orders (PAUSED → ACTIVE)
- Claiming "execution-ready" status (Freeze implied) without proving Codex Freeze

Forbidden by default:
- Creating `<Subject>_Engine/` during Fog of War
  - Exception: allowed only if Hands explicitly orders it OR Hands provides an existing Engine to treat as canonical
  - This exception does NOT lift Fog of War

## Exit condition (Fog Lifted)
Fog of War ends ONLY when Codex Freeze is proven (marker file + Hands approval).

If Codex Freeze becomes stale, missing, unreadable, or contradictory:
- Fog of War MUST be treated as ACTIVE again immediately (Disclosure Gate)

## Do not assume
- Fog of War does not mean "no progress" — it means "no execution commitments."
- Chat statements do not lift Fog — artifacts do.
- "We have a Codex" does not lift Fog — proven Freeze does.

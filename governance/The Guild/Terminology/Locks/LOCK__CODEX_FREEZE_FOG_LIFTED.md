# LOCK — Codex Freeze (Fog Lifted)
**Locked:** 2026-02-08 00:00:00 (America/Montreal assumed)

## Canon meaning
Codex Freeze is the ONLY gate that lifts World State from **Fog of War** to **execution-legal**.

If Codex Freeze cannot be proven, World State MUST be treated as Fog of War.

## Gate Condition (Fog Lifted)
Fog is lifted ONLY when ALL of the following are true:

1) **Marker file exists on disk** at:
   - `<Subject>_Data/Codex/CODEX_FREEZE.md`

2) **Hands approval is proven by the marker content**.
   - Chat statements ("freeze it") are not sufficient.
   - The marker MUST contain:
     - a freeze timestamp (date/time)
     - an explicit Hands approval line (e.g., `Hands: <name>` or `Hands Approval: YES`)

3) **Codex Freeze is not contradicting known Codex reality**.
   If the current Codex structure/constraints/meaning have changed since the marker was written
   and the marker was not updated accordingly, then Freeze is **STALE** and must be treated as **not proven**
   until corrected (Disclosure Gate).

If any condition above is missing, unreadable, or ambiguous:
- Fog of War remains active
- any attempt to accept Quests / start a Raid / execute must trigger Disclosure Gate

## Effects (Once Closed)
When Codex Freeze is proven (Fog Lifted):
- Quests may be ACCEPTED for execution (BOARD → ACCEPTED) under Quest Validation Rules
- Guild Orders may be executed as a Raid (ACTIVE state)
- Execution is permitted under Dailies, with Truth Gate + Execution Audits enforced

Codex Freeze does NOT override:
- Truth Gate
- Disclosure Gate
- Risk Rubric + Consent Gate
- Canonical Working Tree / Engine vs Data boundaries

## What is allowed BEFORE Freeze (Fog of War)
Allowed:
- Exploration / Incubation / Discoveries
- Drafting TOC and Codex sections
- Drafting Guild Orders in PAUSED
- Drafting Quests on BOARD as proposals (not execution commitments)
- Snapshots and continuity artifacts

Forbidden by default (until Freeze is proven):
- Accepting Quests (BOARD → ACCEPTED)
- Starting a Raid / executing Guild Orders
- Claiming execution readiness

## Controlled changes AFTER Freeze
Codex changes are allowed, but MUST be deliberate:
- changes occur during Control Sync
- the Control Sync Snapshot MUST record what changed and why

If a Codex change affects structure, constraints, or meaning:
- Hands must explicitly re-authorize Freeze
- `<Subject>_Data/Codex/CODEX_FREEZE.md` MUST be updated

If the marker cannot be updated or cannot be proven:
- treat World State as Fog of War until corrected

## Do not assume
- Do not infer Freeze from "we have a Codex".
- Do not infer Freeze from an assistant claiming it.
- Do not treat partial drafts as execution readiness.

# TERM — Codex (Map)

## Definition
The Codex is the authoritative map of a Subject: what exists, how it is structured, what is allowed, and what is forbidden.

**Alias (conversation):** The Codex may be referred to as the **Map**.

Artifact law:
- The Codex is a Subject-state artifact and lives in `<Subject>_Data/Codex/`.
- Conversation is input. The Codex artifact is authority.

World State gate:
- Execution is legal only after Codex Freeze.
- Codex Freeze is proven only by the existence of:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`

## Purpose
The Codex eliminates ambiguity before execution by freezing an agreed structure, meaning-set, and constraint set.

## When It Applies
- During Incubation: the TOC and Codex may be drafted while Fog of War is active.
- After Codex Freeze (Fog Lifted): the Codex constrains Guild Orders, Dungeons, and Quests.
- During ongoing work: Codex changes are allowed only as deliberate changes recorded in Control Sync + Snapshot.

## What It Enables
- Deterministic scope selection via Guild Orders
- Deterministic decomposition (Guild Orders → Dungeons → Quests)
- Shared meaning anchors (definitions + invariants)
- “Painting by numbers” implementation bounded by declared intent

## Do Not Assume
- The Codex is not execution and is not a backlog.
- A draft TOC or draft Codex is not execution authority.
- The Codex does not change implicitly.
  - If it is not written into the Codex artifact, it is not a binding Codex rule.
- The Codex does not guarantee correctness of implementation—only structure, intent, and constraints.

## Interactions
- The TOC (Legend) is the navigational contract for the Codex and provides the canonical section numbering.
- Guild Orders, Dungeons, and Quests MUST reference Codex sections by ID (TOC numbering) where applicable.
- Codex Freeze transitions World State: Fog of War → Fog Lifted.
- If work cannot be traced back to a Codex section (or an explicitly deferred decision), it is not execution-ready.

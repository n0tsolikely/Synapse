# TERM — Dungeon

## Definition
A Dungeon is a **major slice of scope** inside a Guild Orders artifact, executed under a Raid.

A Dungeon exists as a named/ID’d section within the Guild Orders artifact.
Conversation does not create a Dungeon. The artifact does.

## Purpose
- Partition a Raid’s scope into coherent objective areas
- Provide a deterministic bridge from Guild Orders → atomic Quests

## When It Applies
- After Codex Freeze (Fog Lifted)
- During Guild Orders authoring
- During Quest derivation and execution planning

## What It Enables
- Deterministic Quest derivation (one Dungeon → one or many Quests)
- Dependency-aware ordering (Dungeons do not imply sequence unless explicitly stated)
- Reduced context switching by grouping related Quests

## Do Not Assume
- A Dungeon is not a Raid
- A Dungeon is not a Quest and is not atomic
- A Dungeon is not a backlog bucket; it MUST define an objective and DONE criteria
- A Dungeon does not authorize execution by itself; only Quests are executed
- Dungeons do not imply priority or sequence unless explicitly stated
- If another compliant operator must ask “what did you mean?” to derive Quests, the Dungeon is incomplete

## Interactions
- Guild Orders contain Dungeons (identified by Dungeon ID within the Orders document)
- A Raid executes Guild Orders; Dungeons are satisfied by decomposing into Quests
- Dungeons decompose into Quests
- Quest execution is governed by Quest Validation Rules + Execution Audits

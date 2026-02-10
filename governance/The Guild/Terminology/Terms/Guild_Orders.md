# TERM — Guild Orders

## Definition
Guild Orders are a **scope-defining governance artifact** that selects a bounded subset of Codex intent to build now and defines what **DONE** means for that build window.

Conversation is input.
The Guild Orders artifact is authority.

## Purpose
Guild Orders prevent scope drift and preserve intent across handoff by converting planning decisions into a durable, parseable reference for execution.

## When It Applies
- After Codex Freeze (Fog Lifted)
- Before Raids, Dungeons, and Quest acceptance/execution
- Whenever Hands re-scopes the build window (via Control Sync)

## What It Enables
- Raid creation (execution state for the Orders)
- Dungeon partitioning (major slices of scope inside the Orders)
- Deterministic Quest derivation (atomic, independently verifiable units)

## Do Not Assume
- Guild Orders are not execution
- Guild Orders are not a Quest backlog and are not atomic tasks
- Guild Orders do not override the Codex
- Guild Orders do not guarantee completion
- If another compliant operator must ask "what did you mean?", the Orders are incomplete

## Interactions
- Guild Orders reference Codex sections by ID (TOC numbering)
- A Raid executes Guild Orders (a Raid is not a section; it is the act/state of execution)
- Guild Orders contain Dungeons
- Dungeons decompose into Quests
- State is defined by location under `<Subject>_Data/Guild Orders/{ACTIVE|PAUSED|COMPLETED}/`

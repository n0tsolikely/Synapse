# TERM — Raid

## Definition
A Raid is the execution state of a Guild Orders artifact.

A Raid is defined by artifact state (state by location):
- **ACTIVE** Raid: a valid Guild Orders file exists in `<Subject>_Data/Guild Orders/ACTIVE/`
- **PAUSED** Raid: the Orders exist in `<Subject>_Data/Guild Orders/PAUSED/`
- **COMPLETED** Raid: the Orders exist in `<Subject>_Data/Guild Orders/COMPLETED/`

Conversation does not start, pause, or complete a Raid. Artifact state does.

## Purpose
- Bind execution to declared scope (Guild Orders) and prevent drift
- Coordinate Dungeons → Quests toward an explicit definition of DONE
- Provide a stable execution target across multiple sessions (Dailies)

## When It Applies
- After Codex Freeze (Fog Lifted)
- When a valid Guild Orders artifact exists for the current build scope
- During execution sessions until the Orders are PAUSED or COMPLETED

## What It Enables
- Dungeon grouping under one scope boundary
- Quest acceptance and execution (via Dailies)
- Auditable progress tracking (Execution Audits + Snapshots)

## Do Not Assume
- A Raid is not a plan, a document section, or a single task
- A Raid does not override the Codex
- A Raid does not authorize silent scope changes
- A Raid does not make Quests valid or complete (Quests still require Validation + Verification)
- A Raid does not exempt Risk / Consent Gates

## Interactions
- Raids execute Guild Orders
- Raids contain Dungeons
- Dungeons decompose into Quests
- Quests are executed via Dailies (Quest mini-loop)

# LOCK — Codex Freeze (Fog Lifted)

Codex Freeze is the gate that transitions World State from Fog of War to execution-ready.

## Gate Condition
The gate closes only when:
- Hands explicitly declares the Codex frozen, **and**
- the freeze is recorded by writing the marker file:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`

If the marker file does not exist, the system MUST assume World State remains Fog of War.

## Effects (Once Closed)
- Quests may be generated (Guild Orders → Dungeons → Quests)
- Raids may begin
- Execution is permitted under Dailies, with Truth Gate + Execution Audits enforced

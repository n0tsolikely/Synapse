# TERM — World State

## Definition
World State is a **binary legality flag** that governs what Synapse OS is allowed to do for a Subject.

- **Fog of War**: exploration / incubation. **Execution is illegal.**
- **Fog Lifted**: Codex is frozen. **Execution is legal** (under Dailies + gates).

World State is a condition, not a deliverable and not a folder.
It is not set by conversation. It is derived from canonical artifacts.

## Machine-checkable derivation
World State MUST be derivable from artifacts without guesswork:

- **Fog Lifted** IFF the Codex Freeze marker exists at:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`
- Otherwise: **Fog of War**.

## Enforcement notes
- If World State is **Fog of War**:
  - Brains MUST NOT accept quests.
  - Brains MUST NOT execute Guild Orders / Raids / Quests.
  - Allowed work is Incubation: exploration, discovery capture, TOC/Codex drafting, non-executing Control Sync.
- If required artifacts conflict (e.g., `CODEX_FREEZE.md` exists but the Codex is missing/contradictory):
  - This is an **INCONSISTENT STATE**.
  - Disclosure Gate MUST trigger.
  - Default to **Fog of War** until Hands resolves the inconsistency.

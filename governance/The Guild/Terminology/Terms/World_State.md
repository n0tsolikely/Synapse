# TERM — World State

## Definition
World State is a binary condition that governs what the system is allowed to do.

- **Fog of War**: exploration / incubation. Execution is forbidden.
- **Fog Lifted**: Codex is frozen. Execution is allowed under dailies.

World State is a *condition*, not a project deliverable.
Do not treat it as "yet another folder." It should be *inferred* from canonical markers.

## Machine-checkable inference
World State MUST be derivable from artifacts without guesswork:

- **Fog Lifted** iff the Codex Freeze marker exists:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`
- Otherwise, assume **Fog of War**.

## Notes
- World State is enforced by locks and gates, not by vibes.
- If there is any ambiguity, default to **Fog of War** and request Hands direction.

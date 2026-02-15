# TERM — Vision Delta

## Definition
**Vision Delta** classifies how a requested capability relates to the system’s existing Codex-defined vision.

Allowed values:
- **ALIGNED**
  - Directly consistent with Codex intent and constraints (no change to what the system is).
- **VARIATION**
  - Not literally named in Codex, but fits an existing Codex **intent class** (e.g., “Door/UI channel”) and does not mutate platform/module boundaries.
  - Allowed only with explicit anchoring and a codification path.
- **SHIFT**
  - Changes what the system *is* (primary purpose/identity mutation).
  - Execution is blocked until Hands explicitly updates vision via Control Sync / Codex changes.

Default rule:
- If unsure, treat as **SHIFT** (fail closed) and trigger Disclosure Gate.

## Purpose
- Allow safe evolution without requiring the Codex to name every possible instance (e.g., Telegram → Discord).
- Block silent product mutation (e.g., turning a meetings pipeline into a generic translator bot).
- Force explicit authority + codification when the vision expands.

## When It Applies
- Quest Creation Vision Alignment (Quest file must declare Vision Delta).
- Pre‑Quest Vision Alignment (execution gate must confirm classification).
- Any time Guild Orders introduce a new capability that may not be explicitly named in the Codex.

## Do Not Assume
- “User asked for it” automatically makes it ALIGNED.
- VARIATION means “invent architecture freely.”
- SHIFT can proceed without Hands decision + Codex update.

## Interactions
- Codex Anchors + Constraint Summary: anchor VARIATION to the correct intent class.
- Repo Orientation: prevents VARIATION from creating duplicates or parallel systems.
- Disclosure Gate: triggers when classification is ambiguous.
- Side Quests: VARIATION requires a codification Side‑Quest (approved by Hands) to make the expansion first‑class.

## Authority
→ `Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt`  
→ `Processes/SYNAPSE_GUILD__EXECUTION_AUDITS.txt`  
→ `Processes/SYNAPSE_GUILD__DISCLOSURE_GATE.txt`

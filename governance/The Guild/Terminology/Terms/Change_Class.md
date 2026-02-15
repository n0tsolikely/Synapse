# TERM — Change Class

## Definition
**Change Class** is the classification of a Quest by how much it can reshape the system.

It exists to make “how strict do we need to be?” deterministic.

Allowed values:
- **TRIVIAL**
  - Small contained change (docs/formatting/local refactor/local bugfix) that should not create new structural components.
- **FEATURE**
  - New capability inside an existing structure/boundary (adds behavior; does not add a new system shape).
- **STRUCTURAL**
  - Changes the system’s shape (new Door, adapter, runtime, module boundary, registry/entrypoint, new top-level component).

Default rule:
- If unsure, classify as **STRUCTURAL**.

## Purpose
- Keep governance lightweight for small changes.
- Enforce strict orientation + anti-duplication checks for structural work.
- Prevent “tiny fix” framing from being used to smuggle in new architecture.

## When It Applies
- Quest creation (Quest file must declare Change Class).
- Pre‑Quest Vision Alignment (determines how heavy Repo Orientation must be).
- Execution Audits + Dailies enforcement.

## Do Not Assume
- TRIVIAL waives Truth Gate / Disclosure Gate / Verification Ladder (it does not).
- FEATURE is “safe enough to skip repo discovery” (it is not).
- STRUCTURAL is a moral judgment (it is not).

## Interactions
- Quest Validation Rules: defines allowed values and acceptance behavior.
- Execution Audits: requires receipts based on Change Class.
- Disclosure Gate: triggers when Change Class is ambiguous or contested.

## Authority
→ `Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt`  
→ `Processes/SYNAPSE_GUILD__EXECUTION_AUDITS.txt`

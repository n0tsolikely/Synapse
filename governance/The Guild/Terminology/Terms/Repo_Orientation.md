# TERM — Repo Orientation (Gate / Receipt)

## Definition
**Repo Orientation** is the deterministic “reality check” performed before execution to prevent structural drift and duplication.

It answers:
- What already exists?
- Where do changes belong?
- Should we reuse/extend instead of creating new components?

Repo Orientation is recorded as a **Repo Orientation Receipt** during Pre‑Quest Vision Alignment.

## Purpose
- Prevent accidental duplication (two runtimes, two doors, parallel web apps, etc.).
- Prevent misplacement (putting module code in platform, or vice versa).
- Force decisions to be grounded in repo reality, not memory.

## When It Applies
- **STRUCTURAL:** mandatory (FULL) before execution.
- **FEATURE:** mandatory (LIGHT) before execution.
- **TRIVIAL:** optional/lightweight unless the change touches risky boundaries.

## Receipt (what it includes)
At minimum:
- Canonical roots confirmed (ENGINE/DATA/GOV).
- Repo map snapshot (tree/listing or stored map file).
- Existing artifact discovery (search for related components; list candidates).
- Decision: reuse / extend / new (with placement decision and target paths).

## Do Not Assume
- “I remember the repo” is sufficient.
- “New is default.”
- Passing unit tests means no duplication occurred.

## Interactions
- Pre‑Quest Vision Alignment (Execution Audits): requires this receipt by Change Class.
- Disclosure Gate: triggers when placement/duplication risk is ambiguous.
- Codex Anchors: prevents Repo Orientation from drifting from intent into arbitrary design.

## Authority
→ `Processes/SYNAPSE_GUILD__EXECUTION_AUDITS.txt`  
→ `Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt`  
→ `Processes/SYNAPSE_GUILD__DISCLOSURE_GATE.txt`

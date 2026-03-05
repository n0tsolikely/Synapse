# TERM — Canonical Working Tree

## Definition
The Canonical Working Tree is the **single authoritative filesystem tree** where Synapse work is performed and audited.

If something is not in the Canonical Working Tree, it is not authoritative.

## Purpose
Prevents parallel states, hidden forks, and contradictory truths.

## Requirements
- All edits, executions, and receipts MUST be performed from the Canonical Working Tree.
- All claims MUST reference paths inside the Canonical Working Tree.
- Pack ZIPs are inert once extracted; the extracted directory is canonical.

## Violation handling
If multiple competing trees/copies exist (duplicate extracted packs, copied `<Subject>_Data`, copied `<Subject>_Engine`):
- Disclosure Gate MUST trigger.
- Brains MUST NOT proceed until Hands selects the canonical tree.

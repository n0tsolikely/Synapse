# TERM — Talent Tree

## Definition
The Talent Tree is the Subject’s capability ledger: a curated index of what has been proven (via Completed Quests) that Brains can reliably do for this Subject.

## Artifact
The Talent Tree is a filesystem artifact.
- If the Talent Tree files do not exist on disk, the Talent Tree does not exist.

Canonical location (Subject):
- `<Subject>_Data/Talent Tree/`
  - `TALENT_TREE.txt`
  - `TALENT_LOG.txt`
  - `RESPEC_RULES.txt`

## Purpose
- Reduce rehydration cost by summarizing proven capabilities.
- Enable deterministic planning (what is safe to attempt without rediscovery).

## Law
- Talents are awarded only as a result of Completed Quests (or explicit Hands directive recorded in a Snapshot).
- A Talent entry MUST reference proof:
  - Quest ID
  - Audit bundle path (or Snapshot path) that evidences the capability
- Absence of a Talent means “not proven” (default = NO).

## Do Not Assume
- Talents do not replace receipts.
- Talents do not guarantee the current Engine state; they describe capability, not correctness.
- “We have the talent” is not a license to skip verification.

# TERM — World State

## Definition
World State is a **binary legality flag** that governs whether Synapse may enter governed execution for a Subject.

- **Fog of War**: governed execution is illegal.
- **Fog Lifted**: governed execution is legal (under Dailies + gates).

World State is a condition, not a deliverable and not a folder.
It is not set by conversation. It is derived from canonical artifacts.

World State answers one question:

> "May Synapse lawfully treat this Subject as execution-legal yet?"

It does **not** answer every other question about the Subject.
It does not by itself define:
- whether drafting may continue
- whether discoveries are still being made
- whether the Codex is complete in every detail
- whether ambient structure formation is still occurring

## Machine-checkable derivation
World State MUST be derivable from artifacts without guesswork:

- **Fog Lifted** IFF the Codex Freeze marker exists at:
  - `<Subject>_Data/Codex/CODEX_FREEZE.md`
  - and remains valid under the Codex Freeze lock
- Otherwise: **Fog of War**

## Operating interpretation
Synapse now operates in two layers:

### 1) Ambient structural layer
This includes things such as:
- discovery capture
- decision capture
- Codex drafting and revision
- Build Manual drafting
- ambient quest and side-quest detection
- BOARD quest drafting when lawful
- snapshots and continuity artifacts
- exploratory work that has not yet become governed execution

### 2) Governed execution layer
This includes things such as:
- Accepted Quests
- Raids / execution of ACTIVE Guild Orders
- governed execution readiness claims
- execution audited as official committed work

World State governs **layer 2 directly**.
It constrains layer 1 only when another lock or process explicitly says so.

## Enforcement notes
- If World State is **Fog of War**:
  - Hands MUST NOT accept quests.
  - Hands MUST NOT execute Guild Orders / Raids / Accepted Quests as governed work.
  - Synapse MAY still preserve continuity, draft structure, and form canonical BOARD artifacts where law allows.
  - Any movement under Fog must remain non-governed until later legalized.

- If World State is **Fog Lifted**:
  - Governed execution becomes legal, subject to all remaining gates.
  - Freeze does not cancel Truth Gate, Disclosure Gate, audit law, or verification requirements.

- If required artifacts conflict (for example, `CODEX_FREEZE.md` exists but the Codex is missing, stale, or contradictory):
  - this is an **INCONSISTENT STATE**
  - Disclosure Gate MUST trigger
  - default to **Fog of War** until Brains resolves the inconsistency

## Do not confuse
- World State is not a measure of how much code exists.
- World State is not a measure of how many quests are drafted.
- World State is not a measure of whether the system has already begun learning what the Subject is.
- World State is the legality flag for governed execution.

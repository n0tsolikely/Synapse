# TERM — Rehydration (Bootstrap / Locks / Packs)

## Definition
Rehydration is restoring authoritative shared understanding from **artifacts**
(not memory) so work resumes deterministically.

## Artifact Law
Rehydration is performed from two classes of artifacts:

1) Governance (definition + law)
- The Governance Pack defines what artifacts mean and how the system operates.

2) Subject State (active continuity)
- Subject-state artifacts live in `<Subject>_Data/` and govern the current work.
- If any required subject artifact is missing or cannot be proven accessible:
  - Rehydration is INCOMPLETE
  - execution authority does not advance

Minimum subject artifacts (common):
- Latest Rehydration Pack (Bootstrap Prompt + Continuity Lock)
- Buffs (execution protocol + map + session start check)
- Snapshots (intent + execution reality)
- Codex + TOC (meaning anchors)
- Quest Board state (what is actionable)
- Talent Tree (capability ledger)

## “Latest” Resolution (anti-guess)
“Latest” is resolved only by explicit naming/path references from:
- Continuity Lock
- Bootstrap Prompt
- Control Sync Snapshot
- `SYNAPSE_STATE.yaml`
- Brains

Guessing “latest” by timestamp, filename pattern, or intuition is prohibited.

## Purpose
- Prevent context loss across chats/days/operators
- Prevent drift and hallucinated state
- Make Control Sync and Dailies start from the same truth surface every time

## Output
Rehydration produces a shared baseline:
- what is true now
- what is active (world state, active orders, accepted quests)
- what is next

Rehydration usually culminates in starting (or resuming) a Control Sync.

## Do Not Assume
- Rehydration is not execution.
- Rehydration does not “fix” the project; it restores state so fixes can be made.
- Conversation memory does not substitute for artifacts.

## Interactions
- Rehydration precedes Control Sync.
- Rehydration consumes Snapshots in locked order (intent → reality).

## Authority
→ `Continuity/SYNAPSE_GUILD__REHYDRATION_PACK_CHECKLIST.txt`
→ `Continuity/SYNAPSE_GUILD__BOOTSTRAP_PROMPT.txt`
→ `Continuity/SYNAPSE_GUILD__BUFFS.txt`
→ `Continuity/SYNAPSE_GUILD__CONTINUITY_LOCK.txt`

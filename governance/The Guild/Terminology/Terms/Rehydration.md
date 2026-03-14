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
- Latest Rehydration Pack (active Bootstrap Prompt + active Continuity Lock)
- Buffs (execution protocol + map + session start check)
- Snapshots (intent + execution reality)
- Codex + related truth surfaces (what execution must obey)
- Quest Board state (what is actionable)
- Talent Tree (capability ledger)
- Active Execution Pack pointer only when such a pack truly exists

## Active-Set Resolution (anti-guess)
“Latest” is resolved by explicit active-set pointers first.

Valid active sources include:
- `SUBJECT_STATE.yaml`
- the active Continuity Lock
- the active Bootstrap Prompt
- explicit active-state pointers in the Subject sidecar/manifold

Filename patterns and timestamps are storage aids, not authority.

Guessing “latest” by timestamp, filename pattern, or intuition is prohibited
when an explicit pointer or active-set artifact exists.

## Purpose
- Prevent context loss across chats/days/operators
- Prevent drift and hallucinated state
- Make Control Sync and Dailies start from the same truth surface every time

## Output
Rehydration produces a shared baseline:
- what is true now
- what is active (world state, active orders, accepted quests, active execution pack if any)
- what is next

Rehydration usually culminates in starting (or resuming) a Control Sync or governed execution window.

## Do Not Assume
- Rehydration is not execution.
- Rehydration does not “fix” the project; it restores state so fixes can be made.
- Conversation memory does not substitute for artifacts.
- If no active Execution Pack is named, do not assume one exists.
- If multiple “latest” artifacts appear active, rehydration is incomplete until repaired.

## Interactions
- Rehydration precedes Control Sync.
- Rehydration consumes Snapshots in locked order (intent → reality).
- Rehydration applies the active Bootstrap Prompt and the active Continuity Lock as a paired surface.
- Rehydration may include an Execution Pack pointer when current execution is bounded and active.

## Authority
→ `Continuity/SYNAPSE_GUILD__REHYDRATION_PACK_CHECKLIST.txt`
→ `Continuity/SYNAPSE_GUILD__BOOTSTRAP_PROMPT.txt`
→ `Continuity/SYNAPSE_GUILD__BUFFS.txt`
→ `Continuity/SYNAPSE_GUILD__CONTINUITY_LOCK.txt`
→ `Continuity/SYNAPSE_GUILD__EXECUTION_PACKS.txt`

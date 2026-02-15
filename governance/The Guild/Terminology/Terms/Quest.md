# TERM — Quest (including Side Quests)

## Definition
A Quest is the **atomic executable unit** of work.

A Quest is valid only if it is:
- independently completable (one bounded commitment)
- independently verifiable (can PASS/FAIL on its own)
- handoff-safe (another compliant operator can execute it without asking “what did you mean?”)

A Quest exists as a **Quest file artifact** on the Quest Board.

A Side Quest is a Quest created outside the planned Dungeon line (e.g., a bug found during a Raid).
It is not a different type of work; it is a Quest with a different origin.

Conversation is input.
The Quest artifact is authority.

## Vision Alignment Fields
Each Quest MUST declare the governance alignment fields used to prevent drift:
- **Change Class** (TRIVIAL / FEATURE / STRUCTURAL)
- **Vision Delta** (ALIGNED / VARIATION / SHIFT)

These fields constrain execution and determine which Pre‑Quest receipts are mandatory (Orientation + Repo Orientation).

## Purpose
Quests make execution deterministic, auditable, and bounded by forcing:
- one unit of work
- one definition of DONE
- one independently verifiable outcome

## When It Applies
- Under Fog of War: Quests MAY be drafted on BOARD, but MUST NOT be ACCEPTED or executed.
- Under Fog Lifted (Codex Freeze): Quests MAY be ACCEPTED and executed (subject to validation + risk/consent).
- During a Raid (Guild Orders execution), and when issues/opportunities are discovered during execution (Side Quests).

## What It Enables
- Deterministic daily execution via Dailies (Quest Mini-Loop)
- Evidence-based completion via Execution Audits
- Safe scope control (acceptance is explicit; scope changes are recorded)

## Artifact Law (State by Location)
Quest state is defined by WHERE the Quest file lives:
- BOARD:     <Subject>_Data/Quest Board/
- ACCEPTED:  <Subject>_Data/Quest Board/Accepted/
- COMPLETED: <Subject>_Data/Quest Board/Completed/
- ABANDONED: <Subject>_Data/Quest Board/Abandoned/

Conversation does not change Quest state. File location does.

## Do Not Assume
- A Quest is not a Dungeon and is not a multi-deliverable project.
  - If it contains multiple independent outcomes, it is NOT a Quest. Split it or reclassify as a Dungeon.
- “Accepted in chat” is not accepted. Acceptance is the file move to ACCEPTED.
- A Quest is not complete without verification evidence.
  - Verification must be defined (in the Quest file or the Pre-Quest Audit) and recorded in the audit bundle.
- If the work cannot be traced to a Codex section (or an explicitly deferred decision), it is not execution-ready.

## Interactions
- Quests are validated by Quest Validation Rules.
- Quests are executed under Dailies and require an Execution Audit bundle.
- Quests commonly derive from Dungeons inside Guild Orders, but may also exist independently (Side Quests).
- Side Quest promotion / scope attribution is recorded via Control Sync + Control Sync Snapshot.

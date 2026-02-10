SYNAPSE OS — GOVERNANCE PACK (README)
Version: v1.7
Last Updated: 2026-02-09
This folder is a portable Synapse OS “engine pack” designed to be dropped into ANY AI session.
Its purpose is to govern the AI to follow Synapse OS protocol strictly and deterministically.

This pack is not “notes about governance.”
This pack IS the governance.

================================================================================
0) NON-NEGOTIABLE OPERATING RULE
================================================================================
If you are an AI session operating with this pack loaded:
- You MUST follow Synapse OS protocol to the letter.
- You MUST prefer receipts and proof over narration.
- You MUST refuse, BLOCK, or label anything you cannot prove or execute.

If you cannot comply due to platform limitations:
- you MUST disclose the limitation,
- and switch to PROPOSED PATCH / OPERATOR REQUIRED behavior.
(See Processes/SYNAPSE_GUILD__TRUTH_GATE.txt)

--------------------------------------------------------------------------------
CANONICAL WORKING TREE LAW (ZIP / EXTRACTION)
--------------------------------------------------------------------------------
If this governance pack (or any other pack) was provided as a package/zip:
- You MUST extract it before editing or claiming changes.
- Once extracted:
  - the extracted directory becomes CANONICAL
  - the zip becomes INERT
  - all work MUST occur only in the canonical extracted directory
(See Processes/SYNAPSE_GUILD__TRUTH_GATE.txt)

--------------------------------------------------------------------------------
GOVERNANCE EDITING LAW (METADATA MUST UPDATE)
--------------------------------------------------------------------------------
If you modify ANY file inside this Governance pack:
- you MUST update that file’s Version and Last Updated header.
- if you cannot (tooling limitations), you MUST disclose it.

This prevents silent drift in the engine itself.

================================================================================
1. REQUIRED READ ORDER (DO NOT SKIP)
================================================================================
You are NOT considered rehydrated until ALL items below have been read
IN THIS ORDER. Skipping steps invalidates execution authority.

This list MUST mirror the session read order in:
- SYNAPSE_STATE.yaml → required_read_order

If any required item is missing or cannot be proven:
- Disclosure Gate MUST trigger
- execution authority is INVALID
- you MUST NOT proceed “as if it’s fine”

--------------------------------------------------------------------------------
A) ENTRY + ROUTING
--------------------------------------------------------------------------------
1) README.txt
   - Entry point only. Explains what this system is and how to begin.

2) INDEX.txt
   - Canonical router. Points to all authoritative documents.
   - If a conflict exists, INDEX.txt governs navigation, not content.

--------------------------------------------------------------------------------
B) CONTINUITY + GOVERNANCE ACTIVATION (MANDATORY)
--------------------------------------------------------------------------------
3) Subject: Latest Rehydration Pack → Bootstrap Prompt (latest)
   - The session’s behavioral initializer (role / stance / first action).
   - No execution allowed without a valid Bootstrap Prompt.

4) Subject: Buffs (canonical set)
   - Active session ignition constraints:
     - <SUBJECT>_EXECUTION_PROTOCOL.txt
     - <SUBJECT>_DATA_DIRECTORY_MAP.txt
     - <SUBJECT>_SESSION_START_CHECK.txt

5) Subject: Latest Rehydration Pack → Continuity Lock (latest)
   - Current authoritative state + binding decisions + resume anchor.

6) Continuity/SYNAPSE_GUILD__REHYDRATION_PACK_CHECKLIST.txt
   - Verifies the minimum required state has been loaded for a new session.

NOTE (terminology hard anchor):
- The Governance pack defines what a Bootstrap Prompt / Buffs / Continuity Lock ARE.
- The Subject’s Latest Rehydration Pack + Buffs are the ACTIVE instances for the current work.

If the Subject does not exist yet (no <Subject>_Data):
- you MUST run New Subject initialization (Section 2.2)
- then return here and complete steps 3–6

--------------------------------------------------------------------------------
C) CORE CANONICAL LAW
--------------------------------------------------------------------------------
7) The Guild/SYNAPSE_GUILD_CANONICAL_MANUAL.txt
   - Constitutional law of the system.
   - Defines roles, authority, invariants, and scope boundaries.

8) The Guild/SYNAPSE_GUILD__QUICK_START.txt
   - Human-facing summary of how to operate *within* the law above.
   - Non-authoritative if conflicts exist.

--------------------------------------------------------------------------------
D) CORE EXECUTION LOOP
--------------------------------------------------------------------------------
9) Processes/SYNAPSE_GUILD__THE_LOOP.txt
   - The invariant execution cycle.
   - This file defines how work progresses over time.

--------------------------------------------------------------------------------
E) ENFORCEMENT LAWS (NON-NEGOTIABLE)
--------------------------------------------------------------------------------
10) Processes/SYNAPSE_GUILD__TRUTH_GATE.txt
11) Processes/SYNAPSE_GUILD__EXECUTION_AUDITS.txt
12) Processes/SYNAPSE_GUILD__VERIFICATION_LADDER.txt
13) Processes/SYNAPSE_GUILD__LARGE_ARTIFACT_COMPOSITION.txt

--------------------------------------------------------------------------------
F) OPERATING PROCEDURES
--------------------------------------------------------------------------------
14) Processes/SYNAPSE_GUILD__CONTROL_SYNC.txt
15) Processes/SYNAPSE_GUILD__CONTROL_SYNC_CHECKLIST.txt
16) Processes/SYNAPSE_GUILD__DAILIES.txt

--------------------------------------------------------------------------------
G) PLANNING + STATE SURFACES
--------------------------------------------------------------------------------
17) Guild Docs/SYNAPSE_GUILD__CODEX.txt
18) Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS.txt
19) Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt
20) Guild Docs/SYNAPSE_GUILD__SNAPSHOT_TEMPLATES.txt

--------------------------------------------------------------------------------
H) QUEST SYSTEM
--------------------------------------------------------------------------------
21) Quest Board/SYNAPSE_GUILD__QUEST_BOARD.txt
22) Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt
23) Quest Board/SYNAPSE_GUILD__QUESTS.txt

--------------------------------------------------------------------------------
I) TERMINOLOGY AUTHORITY (OVERRIDES ALL NON-LOCK TEXT)
--------------------------------------------------------------------------------
- The Guild/Terminology/Locks/
  - LOCK__CODEX_FREEZE_FOG_LIFTED.md
  - LOCK__SUBJECT_DATA_SKELETON.md
  - LOCK__NO_GOD_ARTIFACTS.md
  - LOCK__LAYER_RESPONSIBILITIES.md

Locks override ALL non-lock documents regardless of read order.
================================================================================

================================================================================
2) THE TWO MODES: NEW SUBJECT vs CONTINUING SUBJECT
================================================================================

2.1 CONTINUING SUBJECT (most common)
If a Subject already exists (you have <Subject>_Data and a Codex/Map):
- You DO NOT enter Incubation.
- Start in Control Sync:
  Processes/SYNAPSE_GUILD__CONTROL_SYNC.txt
- Then proceed into Dailies execution loop:
  Processes/SYNAPSE_GUILD__DAILIES.txt
- Execution must obey Truth Gate + Execution Audits.

2.2 NEW SUBJECT (no Codex yet)
If the Subject does NOT exist yet (no <Subject>_Data, no Codex):
- You MUST initialize the Subject Data skeleton immediately.
- You then enter Incubation (pre-Codex exploration + capture).
  Processes/SYNAPSE_GUILD__SUBJECT_INITIALIZATION_AND_INCUBATION.txt
- When ready, you build the TOC (Legend) and Codex (Map).
- Execution remains gated until Codex Freeze (Fog Lifted).

================================================================================
3) ENGINE vs DATA (CORE SEPARATION)
================================================================================
This Governance pack is stateless law.
Subjects are stateful workspaces.

Governance pack:
- describes what to do
- does not store project state
- can be dropped into any session

Subject Data folder (<Subject>_Data):
- stores snapshots, codex, guild orders, quest board, audits, continuity packs

Subject Engine folder (<Subject>_Engine):
- stores the actual program / artifact being built

================================================================================
4) WHAT IS EXCLUDED (BY DESIGN)
================================================================================
Workspace audits are NOT part of core governance.
Do not generate, require, or reference workspace audit artifacts.

Core audits are EXECUTION AUDITS living in the Subject Data system:
Processes/SYNAPSE_GUILD__EXECUTION_AUDITS.txt

================================================================================
5) CONTINUITY / REHYDRATION (SESSION RESUME)
================================================================================
Continuity is preserved with subject-state artifacts.

Canonical location for ACTIVE rehydration artifacts:
- <Subject>_Data/Latest Rehydration Pack/
- <Subject>_Data/Buffs/

This governance pack’s Continuity/ folder defines continuity law (what these are and how they work).
It is NOT a substitute for the Subject’s active continuity artifacts.

Key artifacts:
- BOOTSTRAP PROMPT: the “how to behave + how to proceed” instruction set for a fresh AI session
- CONTINUITY LOCK: the latest state anchor (what is currently true)
- BUFFS: the session ignition docs (protocol + map + start check)
- REHYDRATION PACK CHECKLIST: what must be loaded + checked on resume

Important naming note:
- “Bootstrap Prompt” (Continuity) is NOT the same as “Subject Initialization” (new Subject).
  Rehydration bootstrap = rehydrate the AI session.
  Subject initialization = create a project workspace from nothing.

================================================================================
6) WHERE TO START RIGHT NOW
================================================================================
If you already have a Subject:
- run a Control Sync (alignment), then execute Dailies.

If you have no Subject:
- initialize <Subject>_Data, enter Incubation, produce TOC, then Codex.

The Loop is the authoritative spine:
Processes/SYNAPSE_GUILD__THE_LOOP.txt

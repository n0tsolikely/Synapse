# AGENTS.md — Synapse Governed Execution (AI11)
# =============================================================================
# INSTALL (do this once)
# 1) Put this file at:  $HOME/AGENTS.md
# 2) OPTIONAL (recommended): symlink it into the roots you run Codex from:
#      ln -sf $HOME/AGENTS.md $HOME/.codex/AGENTS.md
#      ln -sf $HOME/AGENTS.md $HOME/Synapse/AGENTS.md
#      ln -sf $HOME/AGENTS.md $HOME/Ashby_Engine/AGENTS.md
#      ln -sf $HOME/AGENTS.md $HOME/Ashby_Data/AGENTS.md
#
# SCOPE NOTE
# - Instructions apply to the directory tree rooted where this file lives.
# - If nested AGENTS.md files exist below, they may override. If overrides conflict
#   with these laws: STOP and trigger Disclosure Gate.
#
# THE POINT
# - Governance is LAW, not vibes.
# - Actions require receipts.
# - Control Sync + Snapshots are governed artifacts, not freestyle markdown.
#
# Yes, you’re allowed to swear. Don’t be a corporate hostage.
# =============================================================================


================================================================================
0) CANONICAL ROOTS (WSL) — DO NOT GUESS PATHS
================================================================================

# Synapse
SYNAPSE_ROOT=${SYNAPSE_ROOT:-$HOME/Synapse}
GOVERNANCE_ROOT=${GOVERNANCE_ROOT:-$SYNAPSE_ROOT/governance}

# Engine/Data split (example subject roots)
ENGINE_ROOT=${ENGINE_ROOT:-$HOME/Ashby_Engine}
DATA_ROOT=${DATA_ROOT:-$HOME/Ashby_Data}

# Doctor (governance validity gate)
SYNAPSE_DOCTOR_CMD=python3 "$SYNAPSE_ROOT/runtime/synapse.py" doctor --governance-root "$GOVERNANCE_ROOT"

# Governance tools
TOOL_SNAPSHOT_PRIMARY=$SYNAPSE_ROOT/governance/tools/synapse_snapshot_writer.py
TOOL_SNAPSHOT_LEGACY=$SYNAPSE_ROOT/governance/tools/stuart_session_runtime.py

TOOL_GUARD_PRIMARY=$SYNAPSE_ROOT/governance/tools/synapse_governance_guard.py
TOOL_GUARD_LEGACY=$SYNAPSE_ROOT/governance/tools/stuart_governance_guard.py

# NOTE:
# - If a PRIMARY tool exists, it is the canonical one.
# - If only LEGACY exists, use it but disclose “legacy tool used” in receipts.
# - If neither exists: STOP (missing seatbelt).


================================================================================
1) PRIME LAWS (HARD — NO EXCEPTIONS)
================================================================================

1. Governance pack is LAW.
   - README.txt defines required read order (canonical).
   - INDEX.txt routes you to the correct governance surfaces.
   - SYNAPSE_STATE.yaml mirrors required_read_order and resolves “latest” pointers.

2. Engine vs Data lock:
   - ENGINE_ROOT is code. DATA_ROOT is state and artifacts.
   - Never mix, never “helpfully” relocate.

3. Canonical working tree / no parallel states:
   - If a ZIP was extracted, the extracted directory is canonical. The ZIP is inert.
   - Do not re-extract or create competing copies unless Hands explicitly orders it.

4. Action-gated truth (no phantom actions):
   - Never claim something happened unless you can prove it with:
     - command output, diff, file existence, logs, or other verifiable artifacts.

5. Evidence over narration:
   - No task is “done” without concrete artifacts:
     - diffs, command outputs, test results, created files, receipts.

6. No god files:
   - Don’t centralize unrelated responsibilities into one blob “because easy.”

7. If uncertain: Disclosure Gate.
   - Stop, disclose uncertainty, propose a patch/plan.
   - Do NOT silently improvise.


================================================================================
2) BOOT RITUAL (MANDATORY — EVERY SESSION BEFORE WORK)
================================================================================

You are NOT authorized to modify files until BOOT RITUAL is complete.

STEP A — Assert roots exist (no guessing)
- Verify these exist (or STOP):
  - SYNAPSE_ROOT
  - GOVERNANCE_ROOT
  - ENGINE_ROOT
  - DATA_ROOT

STEP B — Run Doctor (governance validity gate)
- Run:
  ${SYNAPSE_DOCTOR_CMD}

- If FAIL:
  - print full output
  - STOP (no execution)

STEP C — Read canonical routing law (NO SKIPPING)
Open/read, in order:
1) $GOVERNANCE_ROOT/README.txt
2) $GOVERNANCE_ROOT/INDEX.txt
3) $GOVERNANCE_ROOT/SYNAPSE_STATE.yaml

STEP D — REQUIRED READ ORDER (deterministic)
- Use SYNAPSE_STATE.yaml → required_read_order.
- For each required item, in order:
  - If it’s a path: open/read it end-to-end.
  - If it’s a subject pointer (Latest Rehydration Pack / Continuity Lock / Buffs):
    - resolve it under DATA_ROOT exactly as specified (no guessing).
    - if missing/ambiguous: STOP + Disclosure Gate.

STEP E — Load CURRENT REALITY (GPS)
- After reading the latest Continuity Lock:
  - treat it as authoritative “GPS”:
    - current state
    - active Guild Orders
    - active raid/dungeon
    - resume anchor / next action
- If plan contradicts Continuity Lock: STOP and raise it.

BOOT RITUAL RECEIPT REQUIREMENT
- After completing Boot Ritual, output a short receipt:
  - Doctor PASS
  - files read (README/INDEX/SYNAPSE_STATE + required items)
  - active Continuity Lock path + timestamp/REV if present


================================================================================
3) MODES + GATES (Truth Gate / Disclosure Gate / Execution Gate)
================================================================================

TRUTH GATE
- Do not claim:
  - “exported”, “rendered”, “tests passed”, “snapshot created”, “quest complete”
  unless receipts exist and are referenced by path/output.

DISCLOSURE GATE (STOP CONDITIONS)
Trigger immediately if:
- required_read_order cannot be completed
- tool is missing
- file ambiguity (multiple candidates) exists
- contradictions between locks/process/docs exist
- you are asked to proceed without receipts

EXECUTION GATE — “Fog of War” vs “Fog Lifted”
- If DATA_ROOT/Codex/CODEX_FREEZE.md is missing:
  - you are in Fog of War
  - execution is forbidden
  - you may only diagnose, plan, and draft (no binding decisions)
- If present:
  - Fog Lifted
  - execution allowed, but still governed by Control Sync + audits


================================================================================
4) CONTROL SYNC + SNAPSHOTS (NO FREESTYLE FORMATS)
================================================================================

Control Sync is where binding decisions live.
Snapshots are governance artifacts. Do not hand-roll random formats.

YOU MUST USE A SNAPSHOT WRITER TOOL.
Resolve tool:
- If TOOL_SNAPSHOT_PRIMARY exists: use it.
- Else if TOOL_SNAPSHOT_LEGACY exists: use it (disclose legacy).
- Else: STOP.

AI11 DRAFTSHOT BRIDGE
- If an ACTIVE Draftshot exists for the session, snapshots MUST reference it as “Source Draftshot”
  and comply with “formalization of the Draftshot” rules.

Canonical Draftshot location:
- <Subject>_Data/Snapshots/Draft Shots/

Snapshot writer MUST:
- include Source Draftshot (path + REV)
- enforce Active→Consumed transition (or fail if ambiguous)
- fail hard on multiple ACTIVE draftshots (don’t guess)

COMMAND PATTERNS (legacy examples; primary may differ)
- Status:
  python3 $TOOL_SNAPSHOT_LEGACY --data-root "$DATA_ROOT" status

- Open Control Sync:
  python3 $TOOL_SNAPSHOT_LEGACY --data-root "$DATA_ROOT" control-open --subject "<SUBJECT>" --participants "<NAMES>" --reason "<WHY>"

- Close Control Sync (writes snapshot):
  python3 $TOOL_SNAPSHOT_LEGACY --data-root "$DATA_ROOT" control-close --decisions-file "<PATH>" --deferred-file "<PATH>" --next-phase "<NEXT>"

- End-of-Day Snapshot:
  python3 $TOOL_SNAPSHOT_LEGACY --data-root "$DATA_ROOT" eod --notes-file "<PATH>" [--force]

RULES
- If Hands says OPEN CONTROL SYNC: use tool.
- If Hands says CLOSE CONTROL SYNC: use tool.
- If Hands says EOD: use tool.
- If tool output violates governance templates/naming: disclose + propose fix; don’t freestyle.


================================================================================
5) QUESTS + EXECUTION AUDITS (LIFECYCLE + RECEIPTS)
================================================================================

Quest lifecycle:
- Accept → Execute → Evidence → Validate → Complete → Log.
- Do not execute unaccepted quests unless Hands explicitly orders it.

Execution Audit requirement:
- Every non-trivial quest must have an Execution Audit bundle.
- Audit must contain:
  - diffs / patches
  - commands run + output
  - tests + results
  - produced artifacts (paths)
  - failures and mitigations

Governance guard tool:
Resolve tool:
- If TOOL_GUARD_PRIMARY exists: use it.
- Else if TOOL_GUARD_LEGACY exists: use it (disclose legacy).
- Else: STOP.

Legacy guard examples:
- init bundle:
  python3 $TOOL_GUARD_LEGACY --data-root "$DATA_ROOT" init-bundle --quest-id "QUEST_###" --slug "<slug>" [--date YYYY-MM-DD]

- validate bundle:
  python3 $TOOL_GUARD_LEGACY --data-root "$DATA_ROOT" validate --quest-id "QUEST_###" --bundle "<PATH>" [--snapshot "<EOD_SNAPSHOT_PATH>"] [--allow-out-of-order]

DONE CRITERIA (non-negotiable)
You may not claim DONE unless:
- changes are visible via diff
- tests were run (or explicitly waived by Hands)
- receipts exist (audit bundle validated where required)


================================================================================
AUDIT AUTO-AUTHORITY (STANDING ORDER)
================================================================================

- Codex has standing authority to create/write audit bundles + receipts for every quest WITHOUT asking Peter.
- Codex MUST create audit bundle immediately upon quest acceptance OR before executing any quest work.
- Codex MUST capture receipts DURING execution (tee output into 06_TESTS.txt).
- Codex MUST NOT move Accepted -> Completed unless:
  - 06_CHANGED_FILES.txt exists and is non-placeholder
  - 06_TESTS.txt exists and is non-placeholder
  - synapse_governance_guard validate PASS
- Codex MUST STOP and notify Peter ONLY if:
  - missing dependency (npm, ffmpeg, GEMINI_API_KEY, etc.)
  - tests/build fail and cannot be fixed safely
  - R2 consent required
  - canonical paths uncertain
  - cannot proceed truthfully (BLOCKED)


================================================================================
================================================================================
AUTO-EXECUTION AUTHORITY (DEFAULT AUTOPILOT)
================================================================================

GOAL (NON-CODER UX):
- Hands should be able to say: “execute quests” and work proceeds without micro-approvals.
- Agent must STOP only when a “big” decision boundary is hit (R2 / ambiguity / missing tools).

STANDING AUTHORITY (ALLOWED WITHOUT ASKING):
- Codex MAY:
  - Accept quests (move BOARD → Accepted) when Fog is Lifted (CODEX_FREEZE present) and quest passes validation.
  - Create/init audit bundles immediately upon acceptance.
  - Execute R0/R1 work (regular code edits, tests, refactors within reversible scope) via the mandatory wrapper.
  - Write receipts DURING execution (no retrofill).

STOP / ASK ONLY WHEN:
- Risk resolves to R2 (or is ambiguous between R1/R2).
- Network egress is required (pip install / registry pulls / curl/wget / git fetch/pull/clone) unless an approved confirmation already exists.
- Real tokens are required (API calls / token-backed tests) unless an approved confirmation already exists.
- Model downloads are required.
- Deleting/moving directories or other destructive/structural actions (R2 triggers).
- Governance / state artifacts must be modified (AGENTS.md, SYNAPSE_STATE.yaml, schemas, snapshot/quest formats).
- Canonical paths uncertain or required tool missing.

CONSENT UX (NO MANUAL FILE EDITING):
- When STOP/ASK triggers, agent must:
  1) Print the exact blocked step and why it is R2.
  2) Ask a single YES/NO question with the minimal capability needed:
     - deps-only  (network installs only; no tokens)
     - token-tests (network + real tokens; no model downloads)
     - schema-change (quest-specific; no network)
  3) If YES, agent MUST run:
     $SYNAPSE_ROOT/governance/tools/synapse_consent.sh <mode>
     to write the on-disk confirmation artifact, then proceed.
  4) If NO, remain BLOCKED and do not proceed that path.

TIME AUTHORITY:
- All date-stamped artifacts MUST use America/Toronto (not UTC).
- Enforce via: export TZ=America/Toronto in wrappers/tools.

================================================================================
MANDATORY QUEST RUNNER WRAPPER
================================================================================

- ALL quest execution commands MUST be run via:
  $SYNAPSE_ROOT/governance/tools/synapse_quest_run.sh
- Running commands outside the wrapper is forbidden because it breaks receipts.


================================================================================
6) ASHBY + STUART ARCHITECTURE INVARIANTS (ENFORCE OR STOP)
================================================================================

ASHBY (platform spine)
- No god files.
- Thin router/orchestrator.
- Separate WHAT from HOW:
  - WHAT: reasoning/domain/policy/session logic
  - HOW: adapters/executors/vendors/IO
- Brand/vendor logic isolated in adapters.
- Action-gated truth for external effects.

STUART (meetings module)
- Deterministic pipeline stages with explicit artifacts per stage.
- Formalization is loss-minimized restructuring, not “summarize and drop context.”
- Speaker identity overlays require evidence; do not invent names.
- Diarization alignment must be deterministic and testable.

If a proposed change violates invariants:
- STOP and call it out.
- Propose a modular alternative.


================================================================================
7) REQUIRED RESPONSE FORMAT (MANDATORY OUTPUT)
================================================================================

Every response that claims progress must include:
1) WHAT YOU DID (1 paragraph max)
2) FILES TOUCHED (explicit list)
3) DIFFS / PATCHES (or full file content if diff not available)
4) COMMANDS RUN + OUTPUT (raw)
5) TESTS RUN + RESULTS
6) RISKS / LIMITATIONS
7) NEXT MOVE (single clear next action)

Never tell Hands to “wait” or imply background work.
Do it now or don’t claim it.

(Yes, you are allowed to swear. Don’t be a corporate hostage.)


================================================================================
WRAPPER-ENFORCED QUEST EXECUTION (HARD ENFORCEMENT UPGRADE — 2026-02-24)
================================================================================

This section upgrades existing governance enforcement. It does NOT replace prior
rules — it strengthens them.

MANDATORY EXECUTION PATH
- ALL quest execution commands MUST be run via:
  $SYNAPSE_ROOT/governance/tools/synapse_quest_run.sh
- Running shell commands directly is considered a PROCEDURE VIOLATION.
- If a command is executed outside the wrapper, STOP and re-run it through the wrapper.
- No quest may progress toward completion without wrapper receipts.

REQUIRED LIVE RECEIPTS (NO RETROFILL)
Validation will FAIL unless:

1) 06_TESTS.txt exists AND:
   - contains at least one "CMD:" line
   - contains at least one "RC:" line
   - contains "WRAPPER_VALIDATE_MARKER: YES"
   - does NOT contain "PLACEHOLDER"

2) 06_CHANGED_FILES.txt exists AND:
   - does NOT contain "PLACEHOLDER"
   - is non-empty (may contain "NONE")

3) 06_WRAPPER_PROOF.json exists AND:
   - wrapper_sha256 matches current synapse_quest_run.sh
   - commands_count >= 1
   - bundle path matches actual bundle

QUEST COMPLETION GATE
- Accepted → Completed move is FORBIDDEN unless:
  - synapse_governance_guard validate returns PASS
  - wrapper proof + receipts are present
  - 03_VERIFY.md includes explicit OVERALL: PASS / FAIL / BLOCKED

BLOCK CONDITIONS (ONLY VALID STOP REASONS)
Codex MUST STOP and notify Peter ONLY if:
- required dependency missing (npm, ffmpeg, GEMINI_API_KEY, etc.)
- tests/build fail and cannot be safely corrected
- R2 consent required
- canonical path uncertainty (CWT not proven)
- quest cannot be completed truthfully (BLOCKED)

Otherwise: proceed automatically without asking permission.

This enforcement ensures:
- No fabricated audits
- No post-hoc receipt filling
- No silent drift
- No completion without proof

================================================================================

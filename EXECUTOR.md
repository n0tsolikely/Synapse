# EXECUTOR.md — Synapse Executor Contract
# =============================================================================
# PURPOSE
# - Canonical, executor-agnostic governance contract for this repo.
# - Shims (AGENTS.md, CLAUDE.md, Copilot/Cursor/Cline/Continue/Roo/Windsurf/JetBrains) MUST point here.
# - Synapse governs execution and continuity; it does not replace your runtime identity by default.
# =============================================================================

================================================================================
INSTALL / BRIDGE
================================================================================
- This copy in the repo root is canonical.
- Repo shims should stay tiny and point here.
- Global runtime bridges should stay thin; do NOT drop the full Synapse contract into global executor startup files.
- Scope: applies to the directory tree where it lives; nested instructions override; on conflict STOP and disclose.

================================================================================
RUNTIME / PERSONA COMPATIBILITY
================================================================================

- Synapse governs execution, continuity, proof requirements, subject focus, wrappers, receipts, audits, and drift.
- Synapse does NOT require replacing the current agent/runtime persona or identity.
- If a runtime already has a persona or identity system, keep it.
- Synapse-managed persona overlays are OPTIONAL.
- Persona affects style only. Governance wins on conflict.
- Reference docs:
  - `docs/PERSONAS.md`
  - `docs/INTEGRATIONS.md`

================================================================================
0) CANONICAL ROOTS — DO NOT GUESS PATHS
================================================================================

# Synapse
SYNAPSE_ROOT=${SYNAPSE_ROOT:-$HOME/Synapse}
GOVERNANCE_ROOT=${GOVERNANCE_ROOT:-$SYNAPSE_ROOT/governance}

# Subject / Engine / Data are resolved at session start.
# Use:
# - `python3 runtime/synapse.py engage`
# - `python3 runtime/synapse.py resolve-subject`
# `<SUBJECT>` and literal `Subject` are documentation placeholders, not runtime defaults.

# Doctor (governance validity gate)
SYNAPSE_DOCTOR_CMD=python3 "$SYNAPSE_ROOT/runtime/synapse.py" doctor --governance-root "$GOVERNANCE_ROOT"

# Governance tools (primary only — no legacy paths)
TOOL_SNAPSHOT_PRIMARY=$SYNAPSE_ROOT/runtime/tools/synapse_snapshot_writer.py
TOOL_GUARD_PRIMARY=$SYNAPSE_ROOT/runtime/tools/synapse_governance_guard.py

# If a tool is missing: STOP (missing seatbelt).

================================================================================
SUBJECT FOCUS LOCK (SINGLE SOURCE OF TRUTH)
================================================================================

- Subject selection is owned by the runtime resolver in `runtime/synapse.py`.
- Canonical continuity authority lives in `<Subject>_Data/` and `<Subject>_Data/.synapse/`.
- External lockfiles are session/runtime cursors only (not canonical continuity).
- Resolution order: `--subject` flag → session lock (`--session-id` / `SYNAPSE_SESSION_ID`) → legacy lockfile cursor → `SUBJECT` env → infer only if exactly one `*_Data` exists → otherwise STOP and run `python3 runtime/synapse.py engage`.
- No silent switching once set. Switching subjects MUST use the focus command.
- Literal placeholders such as `Subject` and `<SUBJECT>` are RESERVED and must never be treated as a real active subject.
- Derived roots (ENGINE_ROOT, DATA_ROOT) come from the resolved subject; do not guess them.

================================================================================
CANONICAL TOOL SURFACE
================================================================================

Runtime CLI (`runtime/synapse.py`)
- `doctor`: run deterministic governance checks; use `--no-subject` for governance-only work on the Synapse repo itself.
- `engage`: session-start helper; interactive continue/change flow, or explicit non-interactive intent (`--continue-active` / `--adopt-current-repo`).
- `focus`: explicitly set or switch the persistent active subject lock.
- `resolve-subject`: deterministic subject receipt for scripts and wrappers.
- `record-raw-turn`: append one raw user/executor turn into `.synapse/RAW/CONVERSATION_TURNS/`.
- `record-raw-execution`: append one raw execution/tool/import receipt into `.synapse/RAW/*` using the canonical event spine path.
- `close-turn`: validate the current close-turn boundary, surface blocker-class continuity obligations, and fail closed only when the invoked boundary is honest and strict.
- `install-local-integration`: explicitly install or refresh optional repo-local `.codex` integration assets.
- `persona`: resolve the optional Synapse-managed persona overlay.
- `mode`: get/set elastic governance mode.
- `drift`: inspect governance drift status and show diff commands.
- `acknowledge`: record the current governance commit as acknowledged.
- `enforce`: internal execution gate helper for risk/consent checks.
- `scaffold-subject`: create incubation and Codex scaffolding under the resolved Subject Data root.
- `live-bootstrap`: scaffold the live subject-memory sidecar under Subject_Data.
- `run-start`: start the active run record (live execution memory).
- `run-update`: update the active run record with progress/notes.
- `run-finalize`: archive the active run record into RUNS/.
- `log-decision`: capture a discrete decision into DECISIONS/.
- `render-rehydrate`: rebuild REHYDRATE.md from live sidecar state.
- `plan-sidequests`: draft SIDE-QUEST files from a short plan (BOARD state only).

Runtime tools (`runtime/tools/`)
- `synapse_snapshot_writer.py`: canonical snapshot writer for Control Sync, General, and End-of-Day receipts.
- `synapse_governance_guard.py`: validate governed audit bundles and quest-state transitions.
- `synapse_quest_run.sh`: mandatory wrapper for governed quest execution and live receipts.
- `synapse_consent.sh`: record explicit R2 consent artifacts.
- `require_r2_confirmation.sh`: helper gate for explicit high-risk confirmations.
- `synapse_codex_gate.py`: Codex/canon gating helper when governed workflows require it.
- `require_r2_confirmation_README.md`: helper/reference doc for the R2 confirmation gate.
- `synapse_consent_README.md`: helper/reference doc for consent recording flow.

================================================================================
RUNTIME TOOL COMPATIBILITY
================================================================================

- External agents and runtimes may use their own read/edit/search/shell tools.
- When Synapse defines a canonical governed operation, the Synapse tool/wrapper is mandatory.
- Canonical governed operations include:
  - subject resolution / focus
  - doctor
  - explicit raw boundary capture when using optional local integration hooks
  - snapshots
  - consent recording
  - quest execution
  - audit bundle validation
  - codex/canon gating when applicable

- Optional local `.codex` integration is a local install/refresh path, not universal law.
- If the repo/client does not load those local assets, Synapse is in degraded posture rather than hooked posture.
- Hook-backed close-turn validation is only real when the local integration assets are installed and the client actually runs them.
- Strict commit/push backstops may fail closed on blocker-class continuity obligations; warning-only conditions remain detection/reporting only.

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
   - Do not re-extract or create competing copies unless Brains explicitly orders it.

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

STEP A — Assert repo roots exist (no guessing)
- Verify these exist (or STOP):
  - `$SYNAPSE_ROOT`
  - `$GOVERNANCE_ROOT`

STEP B — Resolve session subject context
- Preferred interactive:
  - `python3 runtime/synapse.py engage`
- Preferred non-interactive / receipt-friendly:
  - `python3 runtime/synapse.py resolve-subject --shell`
  - `python3 runtime/synapse.py engage --continue-active --shell`
  - `python3 runtime/synapse.py engage --adopt-current-repo --shell`
- Bare `engage --shell` is not allowed to silently reuse an existing active lock.
- If working on Synapse governance itself (no subject work), explicitly allow:
  - `python3 runtime/synapse.py doctor --governance-root "$GOVERNANCE_ROOT" --no-subject`

STEP C — Assert resolved ENGINE_ROOT / DATA_ROOT only if subject work is intended
- If subject work is intended, require resolved `ENGINE_ROOT` and `DATA_ROOT` from `engage` / `resolve-subject`.
- If subject is unresolved for subject work: STOP.

STEP D — Run Doctor (governance validity gate)
- Run:
  - `${SYNAPSE_DOCTOR_CMD}`
- Or, for governance-only work on this repo:
  - `python3 runtime/synapse.py doctor --governance-root "$GOVERNANCE_ROOT" --no-subject`

- If FAIL:
  - print full output
  - STOP (no execution)

STEP E — Read canonical routing law (NO SKIPPING)
Open/read, in order:
1) $GOVERNANCE_ROOT/README.txt
2) $GOVERNANCE_ROOT/INDEX.txt
3) $GOVERNANCE_ROOT/SYNAPSE_STATE.yaml

STEP F — REQUIRED READ ORDER (deterministic)
- Use SYNAPSE_STATE.yaml → required_read_order.
- For each required item, in order:
  - If it’s a path: open/read it end-to-end.
  - If it’s a subject pointer (Latest Rehydration Pack / Continuity Lock / Buffs):
    - resolve it under DATA_ROOT exactly as specified (no guessing).
    - if missing/ambiguous: STOP + Disclosure Gate.

STEP G — Load CURRENT REALITY (GPS)
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
  - subject
  - selection_method
  - source_detail
  - active focus lock path if available
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

MODES (Elastic Governance)
- INCUBATION: non-executing; no engine edits; no commits/push; capture discoveries/questions only.
- PLAN: non-executing; draft Guild Orders/Dungeons/Quests and plans; defer non-blocking questions.
- EXECUTE: R0/R1 auto with receipts; R2+ requires explicit consent once per batch.

================================================================================
4) CONTROL SYNC + SNAPSHOTS (NO FREESTYLE FORMATS)
================================================================================

Control Sync is where binding decisions live.
Snapshots are governance artifacts. Do not hand-roll random formats.

YOU MUST USE A SNAPSHOT WRITER TOOL.
Resolve tool:
- TOOL_SNAPSHOT_PRIMARY must exist; otherwise STOP (missing seatbelt).

AI11 DRAFTSHOT BRIDGE
- If an ACTIVE Draftshot exists for the session, snapshots MUST reference it as “Source Draftshot”
  and comply with “formalization of the Draftshot” rules.

Canonical Draftshot location:
- <Subject>_Data/Snapshots/Draft Shots/

Snapshot writer MUST:
- include Source Draftshot (path + REV)
- enforce Active→Consumed transition (or fail if ambiguous)
- fail hard on multiple ACTIVE draftshots (don’t guess)

COMMAND PATTERNS (primary)
- Status:
  python3 $TOOL_SNAPSHOT_PRIMARY --data-root "$DATA_ROOT" status

- Open Control Sync:
  python3 $TOOL_SNAPSHOT_PRIMARY --data-root "$DATA_ROOT" control-open --subject "<SUBJECT>" --participants "<NAMES>" --reason "<WHY>"

- Close Control Sync (writes snapshot):
  python3 $TOOL_SNAPSHOT_PRIMARY --data-root "$DATA_ROOT" control-close --decisions-file "<PATH>" --deferred-file "<PATH>" --next-phase "<NEXT>"

- End-of-Day Snapshot:
  python3 $TOOL_SNAPSHOT_PRIMARY --data-root "$DATA_ROOT" eod --notes-file "<PATH>" [--force]

RULES
- If Brains says OPEN CONTROL SYNC: use tool.
- If Brains says CLOSE CONTROL SYNC: use tool.
- If Brains says EOD: use tool.
- If tool output violates governance templates/naming: disclose + propose fix; don’t freestyle.

================================================================================
5) QUESTS + EXECUTION AUDITS (LIFECYCLE + RECEIPTS)
================================================================================

Quest lifecycle:
- Accept → Execute → Evidence → Validate → Complete → Log.
- Do not execute unaccepted quests unless Brains explicitly orders it.

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
- TOOL_GUARD_PRIMARY must exist; otherwise STOP (missing seatbelt).

Guard examples (primary):
- init bundle:
  python3 $TOOL_GUARD_PRIMARY --data-root "$DATA_ROOT" init-bundle --quest-id "QUEST_###" --slug "<slug>" [--date YYYY-MM-DD]

- validate bundle:
  python3 $TOOL_GUARD_PRIMARY --data-root "$DATA_ROOT" validate --quest-id "QUEST_###" --bundle "<PATH>" [--snapshot "<EOD_SNAPSHOT_PATH>"] [--allow-out-of-order]

DONE CRITERIA (non-negotiable)
You may not claim DONE unless:
- changes are visible via diff
- tests were run (or explicitly waived by Brains)
- receipts exist (audit bundle validated where required)

================================================================================
AUDIT AUTO-AUTHORITY (STANDING ORDER)
================================================================================

- Hands (AI executor) has standing authority to create/write audit bundles + receipts for every quest WITHOUT asking Brains.
- Hands MUST create audit bundle immediately upon quest acceptance OR before executing any quest work.
- Hands MUST capture receipts DURING execution (tee output into 06_TESTS.txt).
- Hands MUST NOT move Accepted -> Completed unless:
  - 06_CHANGED_FILES.txt exists and is non-placeholder
  - 06_TESTS.txt exists and is non-placeholder
  - synapse_governance_guard validate PASS
- Hands MUST STOP and notify Brains ONLY if:
  - missing dependency (npm, ffmpeg, GEMINI_API_KEY, etc.)
  - tests/build fail and cannot be fixed safely
  - R2 consent required
  - canonical path uncertain
  - cannot proceed truthfully (BLOCKED)

================================================================================
================================================================================
AUTO-EXECUTION AUTHORITY (DEFAULT AUTOPILOT)
================================================================================

GOAL (NON-CODER UX):
- Brains should be able to say: “execute quests” and work proceeds without micro-approvals.
- Agent must STOP only when a “big” decision boundary is hit (R2 / ambiguity / missing tools).

STANDING AUTHORITY (ALLOWED WITHOUT ASKING):
- Hands MAY:
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
     $SYNAPSE_ROOT/runtime/tools/synapse_consent.sh <mode>
     to write the on-disk confirmation artifact, then proceed.
  4) If NO, remain BLOCKED and do not proceed that path.

TIME AUTHORITY:
- All date-stamped artifacts MUST use America/Toronto (not UTC).
- Enforce via: export TZ=America/Toronto in wrappers/tools.

================================================================================
MANDATORY QUEST RUNNER WRAPPER
================================================================================

- ALL quest execution commands MUST be run via:
  $SYNAPSE_ROOT/runtime/tools/synapse_quest_run.sh
- Running commands outside the wrapper is forbidden because it breaks receipts.

================================================================================
6) SUBJECT ARCHITECTURE INVARIANTS (ENFORCE OR STOP)
================================================================================

<SUBJECT> (platform spine)
- No god files.
- Thin router/orchestrator.
- Separate WHAT from HOW:
  - WHAT: reasoning/domain/policy/session logic
  - HOW: adapters/executors/vendors/IO
- Brand/vendor logic isolated in adapters.
- Action-gated truth for external effects.

<SUBJECT> (meetings module)
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

Never tell Brains to “wait” or imply background work.
Do it now or don’t claim it.

(Yes, you are allowed to swear. Don’t be a corporate hostage.)

================================================================================
WRAPPER-ENFORCED QUEST EXECUTION (HARD ENFORCEMENT UPGRADE — 2026-02-24)
================================================================================

This section upgrades existing governance enforcement. It does NOT replace prior
rules — it strengthens them.

MANDATORY EXECUTION PATH
- ALL quest execution commands MUST be run via:
  $SYNAPSE_ROOT/runtime/tools/synapse_quest_run.sh
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
Hands MUST STOP and notify Brains ONLY if:
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
DRIFT POLICY (COMMIT-BASED; NO HASH BRICKS)
================================================================================

- Track `last_ack_commit` in `.synapse/STATE.json` (or the focus lock if present).
- Commands:
  - `python3 $SYNAPSE_ROOT/runtime/synapse.py drift`
  - `python3 $SYNAPSE_ROOT/runtime/synapse.py acknowledge`
- INCUBATION/PLAN: warnings only, never block.
- EXECUTE: block R2+ only if governance changed and drift is unacknowledged.
- Warn once per session; no stop-spam.

================================================================================
RUNTIME AUDIT MANDATE (<SUBJECT>) — ALWAYS ON
================================================================================

- For any <SUBJECT> debugging/execution session, Hands MUST inspect runtime telemetry first.
- Required env:
  - export SUBJECT_EVENT_LOGGING=1
  - export SUBJECT_ROOT="${SUBJECT_ROOT:-$HOME/${SUBJECT}_runtime/${SUBJECT,,}}"
- Required checks before diagnosis claims:
  - Preferred command (mandatory when available):
    - bash "$ENGINE_ROOT/tools/subject_runtime_audit_watch.sh"
  - tail -n 120 "$SUBJECT_ROOT/realtime_log/events.jsonl"
  - tail -n 120 "$SUBJECT_ROOT/realtime_log/alerts.jsonl"
  - tail -n 120 "$SUBJECT_ROOT/realtime_log/ui.jsonl"
  - tail -n 120 "$SUBJECT_ROOT/realtime_log/llm.jsonl"
- Required doctor run for incidents:
  - python3 "$ENGINE_ROOT/tools/realtime_log_doctor.py" --subject-root "$SUBJECT_ROOT" --lines 400
- If logs are missing, Hands MUST state that explicitly and treat diagnosis as provisional.
- If the watcher script cannot be run, Hands MUST disclose why and run the four tail commands manually.
- Hands MUST cite correlation_id evidence when explaining “why X happened / why Y didn’t”.

================================================================================

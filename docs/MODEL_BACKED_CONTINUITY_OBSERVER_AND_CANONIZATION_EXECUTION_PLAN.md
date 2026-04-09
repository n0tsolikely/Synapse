# 1. Executive Judgment

The correct next Synapse program remains the one locked in the source plan: build a model-backed continuity observer and canonization pipeline on top of the engaged-kernel substrate that already exists.

Repo grounding tightens that judgment in three ways.

1. The main missing layer is upstream judgment and authored continuity, not storage.
   - VERIFIED existing substrate already covers raw capture, semantic reduction, governed working-record persistence, Draftshots, typed snapshot candidates, publication candidates, proposal/formalization surfaces, truth compilation, and current-context projections.
   - The plan must therefore extend existing owners instead of inventing a second memory system.

2. The first hard blocker is not storage, but lawful model invocation.
   - UNRESOLVED repo truth does not currently expose an internal model-calling adapter in `runtime/synapse_runtime/` or `runtime/` that can power a runtime-owned observer/canonizer.
   - The hardened program therefore starts by creating a provider seam and deterministic fixture backend before any slice may truthfully claim "model-backed" behavior is complete.

3. Canonical identity publication must remain gated.
   - VERIFIED canonical project identity publication remains owned by `runtime/synapse_runtime/repo_onboarding.py` and readiness evaluation remains owned by `runtime/synapse_runtime/project_model.py`.
   - The observer/canonizer program may author drafts and candidates, but it must not directly mutate sovereign canon (`PROJECT_MODEL.yaml`, `PROJECT_STORY.md`, `VISION.md`, `CODEX_CURRENT.md`, `CODEX_FUTURE.md`) without the existing owner-gated publish path.

The minimum-safe execution order is therefore:
- Phase A: continuity observer packet, backend seam, boundary wiring, intent routing
- Phase B: working canonizer and richer working-memory artifacts
- Phase C: operational canonization into snapshots, proposals, codex working updates, and truth drafts
- Phase D: archive / cooling / compaction after lineage-safe promotion exists
- Phase E: feed model-authored outputs into stronger-gated sovereign publication surfaces without bypassing existing owners

# 2. Source-of-Truth Inputs and Authority Order

## Materials used

### Source plan
- `docs/MODEL_BACKED_CONTINUITY_OBSERVER_AND_CANONIZATION_BUILD_SPEC.md`

### Repo truth inspected
- `runtime/synapse.py`
- `runtime/synapse_runtime/automation_orchestrator.py`
- `runtime/synapse_runtime/semantic_classifier.py`
- `runtime/synapse_runtime/semantic_intake.py`
- `runtime/synapse_runtime/promotion_engine.py`
- `runtime/synapse_runtime/live_journal.py`
- `runtime/synapse_runtime/draftshots.py`
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/truth_compiler.py`
- `runtime/synapse_runtime/session_modes.py`
- `runtime/synapse_runtime/quest_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`
- `runtime/synapse_runtime/raw_store.py`
- `runtime/synapse_runtime/lineage_store.py`
- `runtime/synapse_runtime/continuity_obligations.py`
- `runtime/synapse_runtime/repo_onboarding.py`
- `runtime/synapse_runtime/project_model.py`
- `runtime/synapse_runtime/governance_model.py`

### Tests inspected / grounded
- `tests/test_automation_orchestration.py`
- `tests/test_close_turn_validation.py`
- `tests/test_current_context_projection.py`
- `tests/test_draftshot_runtime.py`
- `tests/test_event_spine.py`
- `tests/test_live_memory.py`
- `tests/test_mcp_integration.py`
- `tests/test_publication_candidates.py`
- `tests/test_repo_onboarding.py`
- `tests/test_semantic_classifier.py`
- `tests/test_semantic_intake.py`
- `tests/test_session_modes.py`
- `tests/test_snapshot_candidates.py`
- `tests/test_synthesis_refresh.py`
- `tests/test_truth_compiler.py`

### Vision / governance context read for hardening
- `AGENTS.md`
- `EXECUTOR.md`
- `governance/README.txt`
- `governance/INDEX.txt`
- `governance/SYNAPSE_STATE.yaml`
- `governance/Processes/SYNAPSE_GUILD__TRUTH_GATE.txt`
- `governance/Processes/SYNAPSE_GUILD__DISCLOSURE_GATE.txt`
- `governance/Processes/SYNAPSE_GUILD__DRAFTSHOTS.txt`
- `governance/Guild Docs/SYNAPSE_GUILD__SNAPSHOTS.txt`
- `governance/Guild Docs/SYNAPSE_GUILD__CODEX.txt`
- `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS.txt`
- `governance/Quest Board/SYNAPSE_GUILD__QUESTS.txt`
- `governance/The Guild/Terminology/Locks/LOCK__LAYER_RESPONSIBILITIES.md`
- `governance/The Guild/Terminology/Locks/LOCK__NO_GOD_ARTIFACTS.md`
- `governance/The Guild/Terminology/Locks/LOCK__SNAPSHOTS.md`

### Governance receipt
- `python3 runtime/synapse.py doctor --governance-root governance --no-subject` -> PASS

## Authority order

A. Explicit repo truth
- Existing runtime owners, tests, command surfaces, and filesystem artifact models in this repository

B. Governing / vision docs
- `EXECUTOR.md`
- governance locks and processes listed above

C. Source plan
- `docs/MODEL_BACKED_CONTINUITY_OBSERVER_AND_CANONIZATION_BUILD_SPEC.md`

D. Inference
- Used only to fill execution details the repo and source plan leave unstated
- Any such inference is called out explicitly as VERIFIED / PARTIAL / NET-NEW / CONTRADICTED / UNRESOLVED rather than silently treated as truth

# 3. Repo Grounding Matrix

## 3.1 Raw evidence capture and event spine
- Source plan claim: raw conversation/tool/execution capture already exists and should remain the evidence floor.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/raw_store.py`
  - `runtime/synapse_runtime/conversation_ingest.py`
  - `runtime/synapse_runtime/execution_observer.py`
  - `runtime/synapse.py`
  - `tests/test_event_spine.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Raw capture is append-only and already lawfully stored under `.synapse/RAW/`.
  - Archive/compaction work must preserve this evidence floor rather than replacing it.

## 3.2 Semantic classification and current automation heuristics
- Source plan claim: current significance detection is too heuristic.
- Repo-grounded status: PARTIAL
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/semantic_classifier.py`
  - `runtime/synapse_runtime/automation_orchestrator.py`
  - `tests/test_semantic_classifier.py`
  - `tests/test_automation_orchestration.py`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/continuity_observer.py` (NET-NEW; justified because current classifier/orchestrator are cue-based and not model-backed)
- Notes on contradictions or constraints:
  - Existing cue lists and lightweight classification are real and must remain readable/fallback behavior until the observer is proven.
  - The new observer must extend rather than silently replace the current heuristic path in one jump.

## 3.3 Semantic capture batch owner
- Source plan claim: semantic capture should remain a lawful storage family, not a freeform dump.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/semantic_intake.py`
  - `tests/test_semantic_intake.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Observer/canonizer may request `semantic_capture`, but `write_capture_batch(...)` remains the owner for batch persistence.

## 3.4 Governed working-record promotion
- Source plan claim: working records already exist and should not be replaced.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/promotion_engine.py`
  - `runtime/synapse_runtime/lineage_store.py`
  - `runtime/synapse_runtime/continuity_obligations.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Existing governed record families and lineage edges must remain authoritative.
  - The observer/canonizer may enrich upstream meaning, but persistence of working-record families remains with the current owner path.

## 3.5 Decision and disclosure journaling
- Source plan claim: decisions and disclosures should be auto-authored when confidence and evidence support them.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/live_journal.py`
  - `runtime/synapse.py`
  - `tests/test_live_memory.py`
  - `tests/test_automation_orchestration.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - `log_decision(...)` and `log_disclosure(...)` already exist and remain the artifact owners.
  - The observer should route high-confidence intents into these owners rather than writing decision/disclosure files directly.

## 3.6 Discovery journaling
- Source plan claim: discoveries should become authored durable memory, not stay implicit.
- Repo-grounded status: PARTIAL
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/live_journal.py` (quest-acceptance discovery entry only)
  - `runtime/synapse_runtime/run_lifecycle.py`
  - `runtime/synapse_runtime/rehydrate_renderer.py`
- Exact missing files/modules if justified:
  - Extend `runtime/synapse_runtime/live_journal.py` with a general-purpose discovery owner path instead of burying discovery authoring inside unrelated lifecycle code
- Notes on contradictions or constraints:
  - Discovery ledger infrastructure exists, but a general-purpose authored discovery path is not yet first-class.
  - This is a real gap, not a reason to invent a second ledger.

## 3.7 Draftshots
- Source plan claim: Draftshots already exist and should become better-authored working canon.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/draftshots.py`
  - `tests/test_draftshot_runtime.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Draftshot lifecycle owner already exists.
  - Draftshot law requires one active Draftshot per session, noncanonical status, and bridge behavior into snapshots.
  - Any improved authoring must preserve source-signature gating and Draftshot noncanonical status.

## 3.8 Snapshot candidates
- Source plan claim: typed noncanonical snapshot candidates already exist and should remain distinct from canonical snapshots.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/snapshot_candidates.py`
  - `runtime/tools/synapse_snapshot_writer.py`
  - `tests/test_snapshot_candidates.py`
  - `tests/test_candidate_sludge_controls.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Canonical snapshot writing stays in `synapse_snapshot_writer.py`.
  - The new program may improve candidate authoring and draft-to-canon flow, but may not auto-write canonical snapshots outside existing owner-gated rules.

## 3.9 Publication candidates
- Source plan claim: story / vision / codex candidates already exist and should remain noncanonical until published through existing owners.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/publication_candidates.py`
  - `tests/test_publication_candidates.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Publication candidates are already stamped noncanonical.
  - Stronger identity publication must stay gated through onboarding-owned publication paths.

## 3.10 Proposal / formalization surfaces for quests, guild orders, codex, disclosures, build manual, talent
- Source plan claim: operational canonization should draft guild orders, quest candidates, codex working updates, and related proposal surfaces.
- Repo-grounded status: PARTIAL
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/governance_model.py`
  - `runtime/synapse_runtime/quest_candidates.py`
  - `runtime/synapse_runtime/sidecar_projection.py`
  - `runtime/synapse_runtime/quest_board.py`
  - `runtime/synapse.py`
  - `runtime/synapse_runtime/session_modes.py`
- Exact missing files/modules if justified: none required for basic proposal storage
- Notes on contradictions or constraints:
  - Proposal surfaces already exist for quest, side-quest, snapshot, control_sync, guild_orders, codex, build_manual, talent, and disclosure kinds.
  - Current proposal shaping is still heuristic/ambient and not model-authored at the level the source plan requires.
  - Session-mode policy and allowed proposal kinds already constrain lawful proposal mutation and must remain authoritative.

## 3.11 Truth compilation and truth publications
- Source plan claim: truth statement drafts / working truth deltas should eventually feed stronger truth surfaces.
- Repo-grounded status: PARTIAL
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/truth_compiler.py`
  - `runtime/synapse_runtime/truth_sources.py`
  - `tests/test_truth_compiler.py`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/truth_drafts.py` (NET-NEW; justified to keep noncanonical truth drafts distinct from compiled truth publications)
- Notes on contradictions or constraints:
  - Truth compiler already exists and remains the owner of compiled current-state truth.
  - The source plan requires noncanonical truth drafts / working truth deltas upstream of compilation; those are not first-class yet.

## 3.12 Sidecar projection and rehydration surfaces
- Source plan claim: active memory should stay slim and project into current-context / rehydrate surfaces.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/sidecar_projection.py`
  - `runtime/synapse_runtime/rehydrate_renderer.py`
  - `runtime/synapse_runtime/synthesis_refresh.py`
  - `tests/test_current_context_projection.py`
  - `tests/test_synthesis_refresh.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Active-memory projections already exist.
  - New observer/canonizer outputs must feed these projections through existing owners rather than adding parallel projection files.

## 3.13 Sovereign publication / onboarding gate
- Source plan claim: stronger-gated identity publication must remain explicit and owner-gated.
- Repo-grounded status: VERIFIED
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/repo_onboarding.py`
  - `runtime/synapse_runtime/project_model.py`
  - `tests/test_repo_onboarding.py`
  - `tests/test_automation_orchestration.py`
- Exact missing files/modules if justified: none
- Notes on contradictions or constraints:
  - Existing confirm/publish path remains authoritative.
  - No phase in this program may bypass `onboarding-confirm` or equivalent publish gates.

## 3.14 Model-backed continuity observer
- Source plan claim: Synapse needs a first-class observer that reasons about unfolding work and emits structured intents.
- Repo-grounded status: NET-NEW
- Exact existing files/modules involved:
  - Integration seams exist in `runtime/synapse.py`
  - Existing policy/routing seam exists in `runtime/synapse_runtime/automation_orchestrator.py`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/continuity_observer.py`
  - `tests/test_continuity_observer.py`
- Notes on contradictions or constraints:
  - This must be a bounded domain/orchestration service, not business logic scattered into CLI doors.

## 3.15 Model-backed canonizer
- Source plan claim: Synapse needs a canonizer that writes authored working canon while preserving runtime-owned lawfulness.
- Repo-grounded status: NET-NEW
- Exact existing files/modules involved:
  - Existing owners that must be fed, not replaced: `live_journal.py`, `draftshots.py`, `snapshot_candidates.py`, `publication_candidates.py`, `quest_candidates.py`, `truth_compiler.py`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/canonizer.py`
  - `tests/test_canonizer.py`
- Notes on contradictions or constraints:
  - Canonizer is justified as a separate owner because authored artifact text is a bounded responsibility distinct from raw capture, persistence routing, and read-model projection.

## 3.16 Model invocation surface
- Source plan claim: a reasoning model must periodically review continuity and author stronger artifacts.
- Repo-grounded status: UNRESOLVED
- Exact existing files/modules involved:
  - No repo-grounded internal model adapter was found in `runtime/` or `runtime/synapse_runtime/`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/continuity_model_adapter.py` or equivalent provider seam (name may differ, but an explicit adapter boundary is required)
- Notes on contradictions or constraints:
  - This is the first real blocker for claiming end-to-end model-backed behavior.
  - Minimum lawful resolution: create a provider-agnostic adapter interface plus deterministic fixture backend first; production model backend requires explicit approval of the invocation surface.

## 3.17 Hot / warm / cold memory and archive policy
- Source plan claim: active memory should stay hot and slim; older lower-level material should cool or archive after lineage-safe promotion.
- Repo-grounded status: PARTIAL
- Exact existing files/modules involved:
  - `runtime/synapse_runtime/raw_store.py`
  - `runtime/synapse_runtime/draftshots.py`
  - `runtime/synapse_runtime/snapshot_candidates.py`
  - `runtime/synapse_runtime/publication_candidates.py`
  - `runtime/synapse_runtime/lineage_store.py`
  - `runtime/synapse_runtime/continuity_obligations.py`
  - `runtime/synapse_runtime/sidecar_projection.py`
- Exact missing files/modules if justified:
  - `runtime/synapse_runtime/compaction_policy.py`
  - `tests/test_compaction_policy.py`
- Notes on contradictions or constraints:
  - The repo already has implicit hot/warm/cold layers by artifact type and projection, but not an explicit archive/cooling policy.
  - Deletion remains unsafe until lineage-safe retention checks exist.

# 4. Global Invariants and Boundary Rules

## 4.1 Owner boundaries
- `runtime/synapse.py` remains a door/interface layer. It may parse args, assemble orchestration inputs, and emit receipts. It must not become the continuity-reasoning engine.
- `runtime/synapse_runtime/automation_orchestrator.py` remains orchestration/policy. It may call the observer/canonizer and enforce workflow ordering. It must not absorb raw provider IO or become a catch-all god file.
- `runtime/synapse_runtime/semantic_intake.py` remains the owner for semantic capture batch persistence.
- `runtime/synapse_runtime/live_journal.py` remains the owner for discrete decision/disclosure artifacts and should be extended, not bypassed, for discovery artifacts.
- `runtime/synapse_runtime/promotion_engine.py` remains the owner for governed working-record persistence from semantic / source-linked inputs.
- `runtime/synapse_runtime/draftshots.py` remains the owner for Draftshot lifecycle, revisioning, and active-session constraints.
- `runtime/synapse_runtime/snapshot_candidates.py` remains the owner for typed noncanonical snapshot candidate families.
- `runtime/synapse_runtime/publication_candidates.py` remains the owner for typed noncanonical story / vision / codex candidate families.
- `runtime/synapse_runtime/quest_candidates.py` and `runtime/synapse_runtime/quest_board.py` remain the owners for proposal and quest-draft surfaces.
- `runtime/synapse_runtime/truth_compiler.py` remains the owner for compiled truth statements and truth publications.
- `runtime/synapse_runtime/repo_onboarding.py` and `runtime/synapse_runtime/project_model.py` remain the owners for sovereign identity publication and its readiness gate.

## 4.2 Authority boundaries
- Raw evidence is the evidence floor. It is not active memory, but it remains audit authority.
- Normalized evidence, working records, proposal surfaces, typed candidates, compiled truth, and sovereign canon are distinct layers. They must not be collapsed into a single artifact family.
- Conversation remains input. Stored artifacts and receipts remain authority.
- Locks and governance docs outrank conversational intent when they conflict.

## 4.3 Canonical vs noncanonical rules
- Draftshots, semantic capture batches, proposal records, snapshot candidates, publication candidates, and truth drafts are noncanonical or working-canon surfaces unless an existing owner explicitly formalizes or publishes them.
- Canonical snapshots remain owned by `runtime/tools/synapse_snapshot_writer.py`.
- Sovereign identity canon remains owned by onboarding publication flows.
- No phase may silently promote noncanonical observer output into canonical publication without the existing owner gate.

## 4.4 Mutation rules
- Observer output must be structured intent, not direct arbitrary file writes.
- Canonizer may author body text, but runtime owners still assign file family, ids, revision numbers, lineage edges, and publication receipts.
- Low-confidence observer results must resolve to `noop`, `semantic_capture`, or `open_obligation`; they must not silently mutate strong canon.
- Existing identical-source-signature no-op behavior for Draftshots and candidates must be preserved or tightened, not weakened.

## 4.5 Read-model / projection rules
- `STATE.yaml`, `MANIFOLD.yaml`, REHYDRATE/current-context projections remain derived read-models.
- New observer/canonizer state may be projected into those surfaces, but the projections must remain derived from stored artifacts and manifests, not manually maintained summaries.
- If a new artifact family is introduced, projection updates must be added in the current read-model owners rather than creating parallel read models.

## 4.6 Degradation honesty rules
- If the model backend is unavailable, misconfigured, or blocked, Synapse must say so explicitly in receipts and projections.
- It is illegal to report model-backed continuity behavior when only heuristic fallback ran.
- A fixture backend or deterministic noop backend is valid for tests. It is not valid proof of production model-backed behavior.

## 4.7 Anti-sludge rules
- No new revision when source signatures are unchanged.
- No repeated observer side effects for identical fingerprinted activity.
- No candidate churn when thresholds are not met.
- No archive/deletion without proving lineage-safe supersession and source-ref coverage.

## 4.8 Anti-duplicate-owner rules
- Do not create a second decision store, a second discovery store, a second candidate family, a second truth compiler, or a second onboarding publisher.
- If a gap exists, extend the current owner or add the narrowest justified upstream service boundary.

## 4.9 No-god-artifact rule
- `continuity_observer.py` must remain the bounded assessment domain service.
- Provider IO, prompt transport, or model vendor details must live behind an adapter boundary.
- `canonizer.py` must remain the authored-artifact generator/orchestrator. If it starts handling unrelated retention, routing, projection, or CLI concerns, split it.

## 4.10 Migration compatibility rules
- New schema fields must be additive where possible.
- Existing manifests, ledgers, proposal records, and read models must remain readable without bulk migration.
- No phase in this program requires deleting or rewriting historical artifacts in place.
- If any slice would require a destructive migration, stop and escalate instead of guessing.

# 5. Canonical Phase Program

## Phase A — Continuity Observer

### Objective
Build the bounded, model-backed continuity observer and wire it into real Synapse runtime boundaries, starting with `close-turn`, without bypassing existing artifact owners.

### Why this phase exists
Current Synapse already captures and reduces evidence, but it still decides significance mostly through cues, summary presence, thresholds, and direct operator commands. The observer is the missing upstream judgment layer.

### What repo truth already provides
- Raw turn/tool/execution capture
- Event spine and automation side-effect receipts
- Cue-based runtime activity classification
- Existing owners for semantic capture, decisions, disclosures, obligations, Draftshots, snapshot candidates, publication candidates, and projections
- Existing `close-turn` boundary behavior that already refreshes Draftshots, snapshot candidates, and publication candidates
- Existing `run-finalize`, `import-continuity`, and `session-tick` command surfaces

### Exact scope of this phase
- Create the bounded continuity packet builder
- Create a structured observer intent schema
- Create a lawful provider seam for model-backed assessment
- Integrate observer invocation into the minimum trigger set defined by the source plan:
  - `close-turn`
  - `run-finalize`
  - `import-continuity`
  - `session-tick`
- Preserve the source plan’s optional later expansion surfaces explicitly as follow-on work rather than dropping them:
  - `session-start` for stale consolidation / carry-forward
  - explicit `refresh-continuity-observer`
- Route only the first safe intent classes through existing owners:
  - `noop`
  - `semantic_capture`
  - `decision_log`
  - `disclosure_log`
  - `open_obligation`
- Persist observer receipts into existing event/receipt surfaces
- Preserve degraded honesty when the model backend is not available

### What this phase will not do
- It will not directly write canonical snapshots.
- It will not directly write canonical story/vision/codex/project identity files.
- It will not implement archive/deletion.
- It will not yet author guild orders, quest candidates, codex working updates, story candidates, vision candidates, or truth drafts.
- It will not replace the heuristic classifier outright; it will add a stronger bounded path above it.

### Existing owners being extended
- `runtime/synapse.py`
- `runtime/synapse_runtime/automation_orchestrator.py`
- `runtime/synapse_runtime/semantic_intake.py`
- `runtime/synapse_runtime/live_journal.py`
- `runtime/synapse_runtime/continuity_obligations.py`

### Net-new owners/modules justified
- `runtime/synapse_runtime/continuity_observer.py`
  - Justification: bounded domain/orchestration service for packet assembly, observer invocation, schema normalization, and intent validation.
- `runtime/synapse_runtime/continuity_model_adapter.py`
  - Justification: adapter/boundary layer for model invocation so provider IO does not leak into domain/orchestration logic.
- `tests/test_continuity_observer.py`
  - Justification: isolated tests for packet bounds, intent normalization, degraded/backend behavior, and routing decisions.

### Exact files/modules to modify
- `runtime/synapse.py`
- `runtime/synapse_runtime/automation_orchestrator.py`
- `runtime/synapse_runtime/live_journal.py` only if needed for routing parity / receipts in this phase
- `tests/test_automation_orchestration.py`
- `tests/test_close_turn_validation.py`
- `tests/test_event_spine.py`
- `tests/test_mcp_integration.py`

### Exact files/modules to create
- `runtime/synapse_runtime/continuity_observer.py`
- `runtime/synapse_runtime/continuity_model_adapter.py`
- `tests/test_continuity_observer.py`

### Artifact/state/schema changes
- Add observer continuity-packet schema with bounded inputs only
- Add observer intent schema with required fields:
  - `artifact_family`
  - `action_type`
  - `confidence`
  - `rationale`
  - `source_refs`
  - `truth_state_label`
  - `uncertainty_markers`
  - `draft_safe`
  - `gated_publication`
  - `supersedes`
  - `updates`
- Add additive event payload fields so observer activity is auditable in current receipts
- No new canonical artifact family is required in Phase A

### Command surfaces affected
- `close-turn`
- `run-finalize`
- `import-continuity`
- `session-tick`
- `session-start` only as explicit optional later expansion in this phase, not part of the minimum completion bar
- explicit `refresh-continuity-observer` only as explicit optional later expansion in this phase, not part of the minimum completion bar
- `record-activity` via MCP/runtime bridge parity if those flows reuse automation helpers

### Trigger/orchestration behavior
- `close-turn` is the first mandatory trigger and must be implemented first.
- The minimum phase-complete trigger set is:
  - `close-turn`
  - `run-finalize`
  - `import-continuity`
  - `session-tick`
- `session-start` stale carry-forward and explicit `refresh-continuity-observer` must remain explicitly tracked as optional follow-on surfaces, not silently omitted.
- Observer invocation runs after the current boundary has enough persisted context to build a packet, but before stronger continuity refresh claims are finalized.
- If the backend is unavailable, the receipt must expose explicit degraded observer status rather than pretending model-backed behavior ran.
- Weak observer confidence must downgrade to `semantic_capture` or `open_obligation` rather than stronger mutation.

### Data migration / compatibility behavior
- Additive only.
- Historical events lacking observer fields remain valid and readable.
- No bulk migration script is required.
- Existing automation fingerprints and duplicate-suppression logic must continue to work.

### Dependency on prior phases
- None. This is the first execution phase.

### Merge-safe execution slices / PR units
- A0 — Observer backend contract and fixture backend
  - Create `continuity_model_adapter.py` with provider-agnostic contract and deterministic fixture/noop backend.
  - Do not claim production model-backed behavior yet.
- A1 — Continuity packet builder and intent schema
  - Create `continuity_observer.py` packet assembly and intent validation with exhaustive tests.
- A2 — `close-turn` integration and auditable receipts
  - Wire observer invocation into `cmd_close_turn` and event receipts while preserving current validation behavior.
- A3 — Safe intent routing
  - Route `semantic_capture`, `decision_log`, `disclosure_log`, and `open_obligation` through existing owners.
- A4 — Secondary trigger expansion
  - Extend the same observer path to `run-finalize`, `import-continuity`, and `session-tick` only after `close-turn` is green.
- A5 — Optional trigger preservation
  - Implement or explicitly defer with tracked receipts:
    - `session-start` stale consolidation / carry-forward
    - explicit `refresh-continuity-observer`

### Tests to keep green
- `python3 -m unittest tests/test_automation_orchestration.py -v`
- `python3 -m unittest tests/test_close_turn_validation.py -v`
- `python3 -m unittest tests/test_event_spine.py -v`
- `python3 -m unittest tests/test_mcp_integration.py -v`
- `python3 -m unittest tests/test_semantic_intake.py -v`
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`

### Tests to add
- `python3 -m unittest tests/test_continuity_observer.py -v`
- Add new assertions to `tests/test_automation_orchestration.py` for degraded observer honesty and observer-intent routing
- Add new assertions to `tests/test_event_spine.py` for observer receipt fields
- Add new assertions to `tests/test_close_turn_validation.py` for close-turn observer integration without validation drift
- Add new assertions or coverage proving `close-turn` still refreshes Draftshots, snapshot candidates, and publication candidates correctly after observer wiring

### Exact verification commands
- `python3 runtime/synapse.py doctor --governance-root governance --no-subject`
- `python3 -m unittest tests/test_continuity_observer.py -v`
- `python3 -m unittest tests/test_automation_orchestration.py -v`
- `python3 -m unittest tests/test_close_turn_validation.py -v`
- `python3 -m unittest tests/test_event_spine.py -v`
- `python3 -m unittest tests/test_mcp_integration.py -v`
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m py_compile runtime/synapse.py runtime/synapse_runtime/automation_orchestrator.py runtime/synapse_runtime/continuity_observer.py runtime/synapse_runtime/continuity_model_adapter.py`
- `git diff --check`

### Receipts required to claim completion
- Test receipts for all listed Phase A commands
- A `close-turn` receipt showing:
  - observer status
  - routed action kinds
  - Draftshot refresh outcome
  - snapshot candidate refresh outcome
  - publication candidate refresh outcome
- Event payload receipt proving observer metadata is stored, not narrated
- Paths for any automatically written decision/disclosure/capture/obligation artifacts
- Explicit degraded receipt when the model backend is unavailable
- Explicit receipt for whether A5 optional trigger surfaces were implemented now or deferred deliberately

### Acceptance criteria
- `close-turn` invokes the observer path with a bounded continuity packet.
- Observer intents are structured, evidence-backed, and validated before routing.
- Only the allowed Phase A intent families are routed.
- Low-confidence results do not silently mutate strong artifacts.
- Degraded/backend-unavailable posture is explicit.
- Existing close-turn validation, provenance, Draftshot refresh, snapshot candidate refresh, and publication candidate refresh remain honest.
- The source plan’s optional observer trigger surfaces are either implemented or explicitly deferred as tracked follow-on work, not silently dropped.

### Non-goals
- Full artifact-body authoring for snapshots, codex, guild orders, quests, story candidates, vision candidates, or truth drafts
- Sovereign publication
- Archive/cooling

### Risks / failure modes
- Hidden provider IO inside observer domain code
- Over-triggering observer runs and creating automation sludge
- Claiming model-backed behavior when only fixture/noop backend exists
- Breaking close-turn validation receipts while adding observer wiring
- Breaking Draftshot/snapshot/publication candidate boundary behavior through `close-turn` integration drift

### Exact stop conditions / not-done conditions
- Phase A is not done if no explicit provider seam exists.
- Phase A is not done if `close-turn` does not emit auditable observer receipts.
- Phase A is not done if low-confidence results can still write strong artifacts.
- Phase A is not done if the observer writes files directly instead of routing through current owners.
- Phase A is not done if `close-turn` regresses Draftshot, snapshot-candidate, or publication-candidate refresh behavior.
- Phase A is not done if the source plan’s optional later trigger surfaces are silently omitted rather than explicitly implemented or deferred.

### Fake-success traps
- `continuity_observer.py` exists but no real boundary invokes it
- “model-backed” claims proven only by fixture backend tests
- decision/disclosure/capture files written directly by observer code instead of through current owners
- added receipts that narrate actions without file/test evidence
- Phase A declared complete even though close-turn-owned Draftshot/snapshot/publication flows quietly regressed

### Rollback / containment notes
- Keep the observer behind additive wiring and feature-gated backend selection until the production backend is proven.
- If routing causes noise or drift, disable observer invocation and keep existing heuristic automation path intact while preserving test coverage.
- If A5 optional trigger surfaces are not implemented in the first pass, keep them explicitly tracked as follow-on work rather than deleting them from the program.

## Phase B — Working Canonizer

### Objective
Add the model-backed canonizer that authors durable working-canon artifacts from observer intents while feeding existing owners instead of replacing them.

### Why this phase exists
Phase A only decides what happened and safely routes a narrow set of intents. Synapse still needs authored working memory that is better than raw chat, better than cue-based summaries, and still noncanonical where governance requires it.

### What repo truth already provides
- Decision/disclosure artifact owners
- Discovery ledger infrastructure
- Draftshot owner and revisioning
- Working-record persistence and lineage
- Snapshot candidate bodies and noncanonical publication candidate surfaces
- Read-model projections already consuming those families

### Exact scope of this phase
- Create `canonizer.py`
- Add model-authored artifact body generation for:
  - decisions
  - discoveries
  - disclosures
  - architecture evolution records
  - scope campaign updates
  - richer Draftshots
  - richer noncanonical snapshot candidate bodies
- Extend discovery handling into a first-class authored artifact path
- Preserve truth / vision / unresolved separation in authored bodies

### What this phase will not do
- It will not publish sovereign identity canon.
- It will not implement archive/deletion.
- It will not auto-complete or auto-accept quests.
- It will not treat authored working canon as proof without evidence refs.

### Existing owners being extended
- `runtime/synapse_runtime/live_journal.py`
- `runtime/synapse_runtime/promotion_engine.py`
- `runtime/synapse_runtime/draftshots.py`
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`

### Net-new owners/modules justified
- `runtime/synapse_runtime/canonizer.py`
  - Justification: authored working-canon text generation is a separate bounded responsibility from persistence routing and raw capture.
- Extend `runtime/synapse_runtime/live_journal.py` with general-purpose discovery writing rather than inventing a second discovery store.
- `tests/test_canonizer.py`

### Exact files/modules to modify
- `runtime/synapse_runtime/live_journal.py`
- `runtime/synapse_runtime/promotion_engine.py`
- `runtime/synapse_runtime/draftshots.py`
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`
- `runtime/synapse.py`
- `tests/test_live_memory.py`
- `tests/test_draftshot_runtime.py`
- `tests/test_snapshot_candidates.py`
- `tests/test_synthesis_refresh.py`

### Exact files/modules to create
- `runtime/synapse_runtime/canonizer.py`
- `tests/test_canonizer.py`

### Artifact/state/schema changes
- Add canonizer-authored body generation inputs/receipts for decisions, disclosures, and discoveries
- Extend discovery persistence from ledger-only behavior into authored artifact + ledger behavior
- Add additive Draftshot manifest/body metadata linking canonizer source refs and truth-state labels
- Add additive snapshot-candidate manifest/body metadata for canonizer-authored sections where needed
- Keep all of these noncanonical unless existing owners already define them as binding artifacts

### Command surfaces affected
- `close-turn`
- `run-finalize`
- `refresh-draftshot`
- `refresh-snapshot-candidates`
- `log-decision` and `log-disclosure` indirectly through owner routing

### Trigger/orchestration behavior
- Observer output feeds canonizer only after Phase A intent validation succeeds.
- Canonizer writes text, but current owners still persist/revise artifacts.
- Draftshot refresh continues to obey source-signature gating and one-active-per-session constraints.
- Snapshot candidate refresh continues to obey threshold and source-signature gating; only body authoring becomes richer.

### Data migration / compatibility behavior
- Additive only.
- Existing decision/disclosure artifacts remain readable.
- Historical discovery ledgers remain readable even before authored discovery artifacts exist.
- No rewrite of historical Draftshots or snapshot candidates.

### Dependency on prior phases
- Requires Phase A observer packet, provider seam, and safe intent routing.

### Merge-safe execution slices / PR units
- B1 — Canonizer skeleton and schema
  - Create `canonizer.py` with deterministic input/output contracts and fixture-backed tests.
- B2 — Discovery owner gap closure
  - Add general-purpose discovery artifact persistence under current discovery surfaces.
- B3 — Decision/disclosure authored body integration
  - Route observer/canonizer output through `live_journal.py` while preserving existing receipts.
- B4 — Draftshot and snapshot-candidate authored-body upgrade
  - Improve Draftshot and candidate body authoring without breaking source-signature no-op logic.
- B5 — Working-record enrichment
  - Extend architecture/scope record authoring with explicit truth-state and evidence markers where justified.

### Tests to keep green
- `python3 -m unittest tests/test_live_memory.py -v`
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_synthesis_refresh.py -v`
- `python3 -m unittest tests/test_automation_orchestration.py -v`

### Tests to add
- `python3 -m unittest tests/test_canonizer.py -v`
- Extend `tests/test_live_memory.py` for discovery artifact authoring
- Extend `tests/test_draftshot_runtime.py` for canonizer-authored Draftshot body behavior without revision sludge
- Extend `tests/test_snapshot_candidates.py` for richer candidate body rendering with unchanged-source no-op protection

### Exact verification commands
- `python3 -m unittest tests/test_canonizer.py -v`
- `python3 -m unittest tests/test_live_memory.py -v`
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_synthesis_refresh.py -v`
- `python3 -m unittest tests/test_automation_orchestration.py -v`
- `python3 -m py_compile runtime/synapse_runtime/canonizer.py runtime/synapse_runtime/live_journal.py runtime/synapse_runtime/draftshots.py runtime/synapse_runtime/snapshot_candidates.py`
- `git diff --check`

### Receipts required to claim completion
- Paths to authored discovery, decision, disclosure, Draftshot, and snapshot-candidate artifacts written through current owners
- Receipts proving unchanged inputs do not emit new revisions
- Test receipts for all listed commands
- Projection receipt showing new authored outputs appear in current-context / rehydrate surfaces via existing projections

### Acceptance criteria
- Canonizer produces authored working-canon text with explicit truth / vision / unresolved separation.
- Discovery artifacts become first-class without creating a second discovery store.
- Draftshots and snapshot candidates improve in authored quality while remaining noncanonical and signature-gated.
- Existing owner boundaries and projections remain intact.

### Non-goals
- Guild Orders / quest / codex working proposals
- truth drafts
- archive/cooling
- sovereign publication

### Risks / failure modes
- discovery authoring becoming a second journal instead of extending current owner
- canonizer mixing routing/persistence logic with text authoring
- authored bodies drifting away from source refs or truth-state labels

### Exact stop conditions / not-done conditions
- Phase B is not done if discoveries still lack a general-purpose authored path.
- Phase B is not done if Draftshots or candidate bodies are authored by bypassing their current owners.
- Phase B is not done if authored bodies lose evidence refs or truth-state labels.
- Phase B is not done if revision sludge appears on unchanged signatures.

### Fake-success traps
- prettier Draftshots with no source-ref or evidence discipline
- discovery text dumped into ledgers without a durable artifact path
- snapshot candidate body upgrades that silently mutate canonical snapshot behavior

### Rollback / containment notes
- Keep new authored-body generation behind owner-controlled calls so reverting canonizer logic does not orphan persisted artifacts.
- If authored discovery path proves too invasive, preserve ledger behavior and defer body generation rather than inventing a second store.

## Phase C — Operational Canonization

### Objective
Promote observer/canonizer output into stronger operational working memory: Control Sync and EOD snapshot candidate authoring, guild order drafts, quest candidate drafts, story candidates, vision candidates, codex working updates, and truth drafts.

### Why this phase exists
Phase B improves local working canon, but Synapse still needs richer operational artifacts that tell future sessions what scope exists, what execution state exists, what codex/story/vision working updates are emerging, and what truth deltas are ready for compilation.

### What repo truth already provides
- Typed snapshot candidate families
- Typed publication candidate families for story, vision, and codex
- Proposal kinds and proposal stores for quest/control_sync/guild_orders/codex/build_manual/talent/disclosure
- Formalization pipeline for proposals
- Session-mode gate over allowed proposal kinds
- Truth compiler and truth-source infrastructure

### Exact scope of this phase
- Upgrade noncanonical Control Sync and EOD candidate authoring from observer/canonizer outputs
- Improve guild order and quest candidate drafting so proposal bodies are authored from evidence and current state rather than only heuristic summaries
- Improve story, vision, and codex candidate authoring through `publication_candidates.py` while preserving their noncanonical status
- Add noncanonical truth draft storage upstream of `truth_compiler.py`
- Preserve proposal-state and formalization gates

### What this phase will not do
- It will not publish sovereign identity canon.
- It will not auto-accept or auto-complete quests.
- It will not auto-formalize proposals beyond current lawful rules.
- It will not delete evidence or superseded records.

### Existing owners being extended
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/quest_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`
- `runtime/synapse_runtime/truth_compiler.py`
- `runtime/synapse_runtime/session_modes.py`
- `runtime/synapse.py`

### Net-new owners/modules justified
- `runtime/synapse_runtime/truth_drafts.py`
  - Justification: noncanonical truth drafts must remain distinct from compiled truth publications.
- No new guild-order, quest, snapshot, or publication-candidate owner modules are justified.

### Exact files/modules to modify
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/quest_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`
- `runtime/synapse_runtime/truth_compiler.py`
- `runtime/synapse_runtime/session_modes.py`
- `runtime/synapse.py`
- `tests/test_snapshot_candidates.py`
- `tests/test_publication_candidates.py`
- `tests/test_candidate_sludge_controls.py`
- `tests/test_session_modes.py`
- `tests/test_truth_compiler.py`
- `tests/test_current_context_projection.py`

### Exact files/modules to create
- `runtime/synapse_runtime/truth_drafts.py`
- `tests/test_truth_drafts.py`

### Artifact/state/schema changes
- Add richer authored sections and truth-state labels to snapshot candidate manifests/bodies
- Add richer authored sections and truth-state labels to publication candidate bodies/manifests for:
  - story
  - vision
  - codex
- Add richer authored proposal fields for guild orders / quest / codex working proposals while preserving existing proposal ids and states
- Add noncanonical truth draft family and lineage/source-ref requirements
- Add projection fields for current truth drafts / operational canon where useful

### Command surfaces affected
- `close-turn`
- `run-finalize`
- `refresh-snapshot-candidates`
- `refresh-publication-candidates`
- `formalize`
- `compile-current-state`

### Trigger/orchestration behavior
- Snapshot candidate authoring remains threshold-gated and source-signature-gated.
- Publication candidate authoring remains threshold-gated, source-signature-gated, and explicitly noncanonical.
- Proposal drafting must respect `SessionModePolicy.allowed_proposal_kinds` and must not mutate blocked proposal kinds for the active mode.
- Truth draft creation happens before compilation; `truth_compiler.py` remains the compiler, not the draft author.

### Data migration / compatibility behavior
- Additive manifest/proposal fields only.
- Existing proposal records remain readable.
- Existing snapshot/publication candidate revisions remain readable.
- Historical truth publications remain valid even before truth drafts exist.
- No bulk migration script is required.

### Dependency on prior phases
- Requires Phase A observer routing and Phase B canonizer-authored working canon.

### Merge-safe execution slices / PR units
- C1 — Truth draft family and compiler ingestion seam
  - Create `truth_drafts.py` and teach the truth compiler to consume drafts lawfully without treating them as sovereign truth by default.
- C2 — Snapshot candidate canonization upgrade
  - Upgrade Control Sync and EOD candidate bodies from canonizer outputs while preserving threshold/signature gating.
- C3 — Publication candidate canonization upgrade
  - Upgrade story, vision, and codex candidate bodies/manifests from canonizer outputs while preserving noncanonical status and source-signature gating.
- C4 — Guild order / quest / codex working proposal upgrade
  - Improve authored proposal payloads and projection surfaces without bypassing session-mode gating.
- C5 — Current-context projection upgrade
  - Surface richer operational canon state in `STATE.yaml`, `MANIFOLD.yaml`, and rehydrate/current-context outputs.

### Tests to keep green
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_candidate_sludge_controls.py -v`
- `python3 -m unittest tests/test_session_modes.py -v`
- `python3 -m unittest tests/test_truth_compiler.py -v`
- `python3 -m unittest tests/test_current_context_projection.py -v`
- `python3 -m unittest tests/test_mcp_integration.py -v`

### Tests to add
- `python3 -m unittest tests/test_truth_drafts.py -v`
- Extend `tests/test_snapshot_candidates.py` for authored Control Sync / EOD candidate details with truth-state separation
- Extend `tests/test_publication_candidates.py` for authored story / vision / codex candidate details with unchanged-source-signature no-op protection
- Extend `tests/test_session_modes.py` for observer/canonizer proposal gating
- Extend `tests/test_current_context_projection.py` for truth-draft and operational-canon projections

### Exact verification commands
- `python3 -m unittest tests/test_truth_drafts.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_candidate_sludge_controls.py -v`
- `python3 -m unittest tests/test_session_modes.py -v`
- `python3 -m unittest tests/test_truth_compiler.py -v`
- `python3 -m unittest tests/test_current_context_projection.py -v`
- `python3 -m unittest tests/test_mcp_integration.py -v`
- `python3 -m py_compile runtime/synapse_runtime/truth_drafts.py runtime/synapse_runtime/snapshot_candidates.py runtime/synapse_runtime/publication_candidates.py runtime/synapse_runtime/quest_candidates.py runtime/synapse_runtime/truth_compiler.py`
- `git diff --check`

### Receipts required to claim completion
- Paths to richer snapshot candidate bodies and manifests
- Paths to richer publication candidate bodies/manifests for story, vision, and codex
- Paths to authored proposal records for guild orders / quest / codex working surfaces
- Paths to truth draft artifacts and compiled truth outputs that reference them
- Projection receipts showing current-context / REHYDRATE surfaces updated from stored artifacts

### Acceptance criteria
- Control Sync and EOD candidate bodies are authored from evidence/current state, not raw sentence soup.
- Story, vision, and codex candidate bodies are authored from evidence/current state while remaining explicitly noncanonical.
- Proposal surfaces for guild orders / quest / codex working updates are richer and still gated by session mode and formalization rules.
- Truth drafts exist as noncanonical upstream inputs and do not bypass the truth compiler.

### Non-goals
- Sovereign publication
- Quest acceptance/completion automation
- Archive/cooling/deletion

### Risks / failure modes
- Truth drafts being mistaken for compiled truth
- Proposal drafting bypassing session-mode gating
- Story/vision candidate upgrades being mistaken for sovereign publication
- Snapshot candidate upgrades smuggling canonical snapshot behavior

### Exact stop conditions / not-done conditions
- Phase C is not done if truth drafts are stored in the same family as compiled truth.
- Phase C is not done if proposal surfaces bypass session-mode policy.
- Phase C is not done if story/vision/codex candidate upgrades bypass `publication_candidates.py`.
- Phase C is not done if snapshot or publication candidates lose explicit noncanonical status.
- Phase C is not done if authored operational artifacts cannot cite evidence/source refs.

### Fake-success traps
- Nicer proposal prose with no effect on lawful proposal fields or gating
- Truth compiler consuming generated text as if it were automatically high-confidence truth
- Snapshot candidate upgrades that write canonical snapshots implicitly
- Story/vision candidate upgrades deferred to the sovereign publication phase and therefore implemented in the wrong owner boundary

### Rollback / containment notes
- Keep truth drafts in a separate family so they can be ignored/disabled without corrupting compiled truth.
- Keep authored proposal enrichment additive to existing proposal records for safe rollback.
- Keep story/vision/codex candidate upgrades inside `publication_candidates.py` so Phase E only consumes them through current publish gates.

## Phase D — Compaction And Archive Policy

### Objective
Implement explicit hot / warm / cold memory policy, cooling/archival rules, and lineage-safe compaction for lower-level artifacts after stronger artifacts exist.

### Why this phase exists
Without compaction, Synapse accumulates evidence forever and eventually drowns future sessions in low-level material. Without lawful retention checks, it risks deleting the only evidence for stronger claims. This phase makes the memory ladder operational.

### What repo truth already provides
- Raw evidence store
- Draftshot and candidate revision families
- Lineage edge store
- Continuity obligations
- Sidecar projections that can expose current vs historical state

### Exact scope of this phase
- Define and persist hot / warm / cold classification rules
- Add superseded / archived / cooled state for eligible low-level material
- Add archive manifests and retention checks
- Prevent deletion/cooling when the artifact is still the only evidence for a stronger claim or is still referenced by lineage/source refs
- Keep active projections focused on hot memory

### What this phase will not do
- It will not delete raw evidence just because stronger artifacts exist.
- It will not rewrite history in place.
- It will not change sovereign publication gates.

### Existing owners being extended
- `runtime/synapse_runtime/raw_store.py`
- `runtime/synapse_runtime/lineage_store.py`
- `runtime/synapse_runtime/continuity_obligations.py`
- `runtime/synapse_runtime/draftshots.py`
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/sidecar_projection.py`

### Net-new owners/modules justified
- `runtime/synapse_runtime/compaction_policy.py`
  - Justification: archive/cooling rules are a bounded domain concern and must not be scattered across raw/candidate owners.
- `tests/test_compaction_policy.py`

### Exact files/modules to modify
- `runtime/synapse_runtime/raw_store.py`
- `runtime/synapse_runtime/draftshots.py`
- `runtime/synapse_runtime/snapshot_candidates.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/lineage_store.py`
- `runtime/synapse_runtime/sidecar_projection.py`
- `tests/test_draftshot_runtime.py`
- `tests/test_snapshot_candidates.py`
- `tests/test_publication_candidates.py`
- `tests/test_current_context_projection.py`

### Exact files/modules to create
- `runtime/synapse_runtime/compaction_policy.py`
- `tests/test_compaction_policy.py`

### Artifact/state/schema changes
- Add archive/cooling manifest schema
- Add additive lifecycle/status fields for cooled/superseded eligible artifacts where justified
- Add projection fields for hot/warm/cold counts and recent cooled artifacts if useful
- No destructive deletion is required to complete this phase

### Command surfaces affected
- `close-turn`
- `run-finalize`
- `refresh-draftshot`
- `refresh-snapshot-candidates`
- `refresh-publication-candidates`
- any future explicit compaction command only if later justified; not required for initial completion

### Trigger/orchestration behavior
- Cooling/archival happens only after stronger artifacts exist and retention checks pass.
- Active-memory projections must prefer hot-memory artifacts first.
- If an artifact is still referenced by source refs, lineage edges, unresolved contradictions, or obligations, compaction must refuse to cool/delete it.

### Data migration / compatibility behavior
- Additive manifesting only.
- Historical artifacts remain readable in place.
- Cooling may mark or manifest supersession without relocating artifacts initially if relocation would risk compatibility.

### Dependency on prior phases
- Requires Phase B and Phase C because compaction depends on stronger authored artifacts and lineage/source refs being in place.

### Merge-safe execution slices / PR units
- D1 — Compaction policy and retention-check engine
  - Create `compaction_policy.py` and prove it refuses unsafe archive/delete decisions.
- D2 — Candidate and Draftshot cooling state
  - Add superseded/cooling manifests for Draftshots and candidate revisions.
- D3 — Raw/warm/cold projection update
  - Project hot/warm/cold state into current-context / rehydrate surfaces.
- D4 — Optional relocation/cold-storage mechanics
  - Only if needed after D1-D3 are stable; otherwise keep cold storage logical/manifest-based first.

### Tests to keep green
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_current_context_projection.py -v`
- `python3 -m unittest tests/test_truth_compiler.py -v`

### Tests to add
- `python3 -m unittest tests/test_compaction_policy.py -v`
- Extend `tests/test_candidate_sludge_controls.py` for cooled/superseded revisions
- Extend `tests/test_current_context_projection.py` for hot/warm/cold projection truth

### Exact verification commands
- `python3 -m unittest tests/test_compaction_policy.py -v`
- `python3 -m unittest tests/test_draftshot_runtime.py -v`
- `python3 -m unittest tests/test_snapshot_candidates.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_current_context_projection.py -v`
- `python3 -m py_compile runtime/synapse_runtime/compaction_policy.py runtime/synapse_runtime/raw_store.py runtime/synapse_runtime/draftshots.py runtime/synapse_runtime/snapshot_candidates.py runtime/synapse_runtime/publication_candidates.py`
- `git diff --check`

### Receipts required to claim completion
- Archive/cooling manifests or equivalent receipts showing why each cooled artifact was safe
- Proof that referenced/source-linked artifacts were not cooled unsafely
- Projection receipts showing hot/warm/cold state is visible without reading raw archives first
- Test receipts for all listed commands

### Acceptance criteria
- Synapse can mark/archive/cool superseded lower-level material only when stronger lineage-safe artifacts exist.
- Raw evidence remains preserved as cold evidence, not deleted by default.
- Current-context / rehydrate surfaces emphasize hot memory and do not require loading cold history first.

### Non-goals
- Mass deletion of historical evidence
- rewriting historical artifacts
- sovereign publication changes

### Risks / failure modes
- deleting or cooling the only evidence for a stronger claim
- breaking historical readability by relocating artifacts too early
- compaction rules buried inside unrelated owners

### Exact stop conditions / not-done conditions
- Phase D is not done if any archive/cooling action can remove the only supporting evidence for a stronger artifact.
- Phase D is not done if hot/warm/cold state exists only as narration and not as stored/projected receipts.
- Phase D is not done if compaction requires destructive migration.

### Fake-success traps
- calling a projection filter "archive policy" without any retention checks
- marking artifacts cooled while active projections still depend on them as first-load memory
- deleting raw evidence because a later artifact merely exists

### Rollback / containment notes
- Prefer logical cooling manifests before physical moves.
- If relocation causes compatibility risk, keep artifacts in place and mark/archive logically first.

## Phase E — Stronger Canon Publication Integration

### Objective
Feed model-authored noncanonical outputs from earlier phases into stronger-gated sovereign publication flows without bypassing current canonical owners.

### Why this phase exists
Phases A-D create better noncanonical and operational memory, but Synapse still needs those stronger authored outputs to improve project-model/story/vision/codex publication quality while preserving lawful publication gates.

### What repo truth already provides
- Onboarding draft/update/respond/confirm pipeline
- Publication candidate families for story/vision/codex
- Project identity readiness gate
- Truth compilation after publication

### Exact scope of this phase
- Consume canonizer-authored noncanonical outputs from prior phases as upstream draft inputs for:
  - project model
  - story
  - vision
  - codex canonical publication paths
- Tighten publication receipts and review requirements where needed
- Preserve explicit confirm/publish authority for sovereign identity artifacts
- Ensure compiled truth and projections consume newly published outputs correctly

### What this phase will not do
- It will not author or upgrade noncanonical story/vision/codex candidates; that belongs to Phase C.
- It will not auto-publish sovereign canon on a timer or because a session ended.
- It will not bypass `onboarding-confirm` or equivalent lawful publish gates.
- It will not make noncanonical candidates pretend to be published canon.

### Existing owners being extended
- `runtime/synapse_runtime/repo_onboarding.py`
- `runtime/synapse_runtime/project_model.py`
- `runtime/synapse_runtime/publication_candidates.py` as upstream input source only
- `runtime/synapse_runtime/truth_compiler.py`
- `runtime/synapse_runtime/automation_orchestrator.py`

### Net-new owners/modules justified
- No new sovereign publication owner is justified.
- Any helper created here must be narrowly scoped to draft adaptation and must not become a parallel publisher.

### Exact files/modules to modify
- `runtime/synapse_runtime/repo_onboarding.py`
- `runtime/synapse_runtime/project_model.py`
- `runtime/synapse_runtime/publication_candidates.py`
- `runtime/synapse_runtime/truth_compiler.py`
- `runtime/synapse_runtime/automation_orchestrator.py`
- `tests/test_repo_onboarding.py`
- `tests/test_publication_candidates.py`
- `tests/test_truth_compiler.py`
- `tests/test_automation_orchestration.py`

### Exact files/modules to create
- None required unless a narrow draft-adaptation helper proves necessary during implementation

### Artifact/state/schema changes
- Add additive source-ref / authored-draft metadata in onboarding drafts where useful
- Preserve current canonical publication file set and paths
- Preserve current publication candidate noncanonical status and publish receipts
- Preserve separation between:
  - upstream noncanonical candidates/drafts
  - published sovereign canon

### Command surfaces affected
- `onboard-repo`
- `onboarding-update`
- `onboarding-respond`
- `onboarding-confirm`
- `refresh-publication-candidates`
- `compile-current-state`

### Trigger/orchestration behavior
- Model-authored outputs from earlier phases may improve draft generation and review inputs.
- Publication still requires existing owner-gated confirmation.
- If model confidence/evidence is insufficient for sovereign publication, the pipeline must remain in draft/candidate posture or open obligations.
- Phase E starts only after Phases A-D are complete; it does not overlap with Phase C.

### Data migration / compatibility behavior
- Additive only.
- Existing onboarding sessions, drafts, and confirmed publications remain readable.
- No bulk migration script is required.

### Dependency on prior phases
- Requires Phases A, B, C, and D completed in order.
- Uses story/vision/codex candidate outputs from Phase C as upstream inputs, not as replacement publication owners.

### Merge-safe execution slices / PR units
- E1 — Canonizer-authored onboarding draft integration
  - Feed stronger authored draft content into onboarding draft generation without changing publish law.
- E2 — Publish-gate hardening and receipts
  - Tighten publish receipts, review markers, and uncertainty handling for sovereign publication.
- E3 — Post-publication truth/projection synchronization
  - Ensure published artifacts update compiled truth and projections cleanly.

### Tests to keep green
- `python3 -m unittest tests/test_repo_onboarding.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_truth_compiler.py -v`
- `python3 -m unittest tests/test_automation_orchestration.py -v`

### Tests to add
- Extend `tests/test_repo_onboarding.py` for model-authored draft inputs and publish-gate preservation
- Extend `tests/test_publication_candidates.py` for source-ref / authored-draft metadata parity at the publish handoff seam
- Extend `tests/test_truth_compiler.py` for post-publication truth-source precedence with authored drafts upstream

### Exact verification commands
- `python3 -m unittest tests/test_repo_onboarding.py -v`
- `python3 -m unittest tests/test_publication_candidates.py -v`
- `python3 -m unittest tests/test_truth_compiler.py -v`
- `python3 -m unittest tests/test_automation_orchestration.py -v`
- `python3 -m py_compile runtime/synapse_runtime/repo_onboarding.py runtime/synapse_runtime/project_model.py runtime/synapse_runtime/publication_candidates.py runtime/synapse_runtime/truth_compiler.py`
- `git diff --check`

### Receipts required to claim completion
- Draft receipt proving onboarding-generated drafts incorporate authored inputs with evidence refs
- Publish receipt proving existing confirmation gate still owns sovereign publication
- Truth/projection receipts showing published artifacts are reflected in compiled truth and current-context surfaces
- Test receipts for all listed commands

### Acceptance criteria
- Sovereign publication quality improves through model-authored upstream draft inputs.
- Existing publish gates remain intact.
- Noncanonical candidates remain distinct from published canon.
- Post-publication truth compilation and projections remain correct.
- Story/vision/codex candidate authoring remains in Phase C and is only consumed here through current publish gates.

### Non-goals
- Auto-publish timers
- Bypassing onboarding confirmation
- Collapsing candidate and canonical identity layers
- Moving noncanonical publication-candidate authoring into this phase

### Risks / failure modes
- Model-authored drafts treated as already-published truth
- Onboarding draft integration accidentally mutating canonical files before confirmation
- Truth compiler precedence skewed by upstream generated drafts
- Candidate/publication boundary collapse

### Exact stop conditions / not-done conditions
- Phase E is not done if `PROJECT_MODEL.yaml`, `PROJECT_STORY.md`, `VISION.md`, `CODEX_CURRENT.md`, or `CODEX_FUTURE.md` can change without the current publish gate.
- Phase E is not done if publication candidates or onboarding drafts are indistinguishable from published canon.
- Phase E is not done if published truth loses precedence ordering or source refs.
- Phase E is not done if story/vision/codex candidate authoring had to move into this phase to make the plan work.

### Fake-success traps
- Nicer onboarding drafts with no evidence/source-ref discipline
- Calling candidate generation “publication integration” without touching the actual owner-gated publication path
- Implicit publish-on-refresh behavior
- Quietly doing Phase C work here because the earlier phase boundary was underspecified

### Rollback / containment notes
- Keep all authored draft improvements upstream of confirmation so they can be disabled without invalidating existing canon.
- If draft integration proves unstable, preserve current onboarding publication behavior and keep new authored content in candidates only.

# 6. Cross-Phase Dependency Graph

## Order constraints
- Phase A -> Phase B
  - Reason: canonizer requires observer packets, structured intents, and backend/degraded honesty to exist first.
- Phase B -> Phase C
  - Reason: operational canonization depends on authored working canon and a lawful discovery/decision/disclosure/Draftshot upgrade path.
- Phase C -> Phase D
  - Reason: compaction must not run until stronger operational artifacts, richer candidate families, and truth drafts exist.
- Phase D -> Phase E
  - Reason: sovereign publication integration must consume stabilized upstream artifacts after archive/retention law is in place, not while memory-layer boundaries are still moving.

## Why the order is minimum-safe
- Starting before Phase A would force model-backed claims without a lawful backend seam.
- Starting Phase C before Phase B would create operational artifacts without a mature authored working-memory layer underneath them.
- Starting Phase D before stronger authored artifacts exist would either archive too little to matter or delete/cool evidence unsafely.
- Starting Phase E before Phase D would blur noncanonical candidate work with sovereign publication and weaken deterministic phase boundaries.

## What cannot be started before what
- No slice may claim model-backed observer behavior before A0/A1 exist.
- No slice may claim authored working canon before Phase B.
- No slice may claim richer snapshot/publication candidate canonization, guild-order/quest/codex working proposal upgrades, or truth drafts before Phase C.
- No slice may cool/archive artifacts before Phase D retention checks exist.
- No slice may start sovereign publication integration before Phases A-D are complete.
- Phase E does not overlap with Phase C or Phase D. If implementation pressure suggests overlap, stop and escalate instead of silently changing phase order.

# 7. Global Verification Matrix

## 7.1 Consolidated test matrix
- Observer / boundary routing
  - `tests/test_continuity_observer.py`
  - `tests/test_automation_orchestration.py`
  - `tests/test_close_turn_validation.py`
  - `tests/test_event_spine.py`
  - `tests/test_mcp_integration.py`
  - `tests/test_draftshot_runtime.py`
  - `tests/test_snapshot_candidates.py`
  - `tests/test_publication_candidates.py`
- Working canon / local authored artifacts
  - `tests/test_canonizer.py`
  - `tests/test_live_memory.py`
  - `tests/test_draftshot_runtime.py`
  - `tests/test_snapshot_candidates.py`
  - `tests/test_synthesis_refresh.py`
- Operational canon / proposal gating / truth drafts
  - `tests/test_snapshot_candidates.py`
  - `tests/test_publication_candidates.py`
  - `tests/test_candidate_sludge_controls.py`
  - `tests/test_session_modes.py`
  - `tests/test_current_context_projection.py`
  - `tests/test_truth_drafts.py`
  - `tests/test_truth_compiler.py`
- Sovereign publication integration
  - `tests/test_repo_onboarding.py`
  - `tests/test_publication_candidates.py`
  - `tests/test_truth_compiler.py`
  - `tests/test_automation_orchestration.py`

## 7.2 Consolidated command matrix
- Governance validity
  - `python3 runtime/synapse.py doctor --governance-root governance --no-subject`
- Syntax sanity on touched runtime/test files
  - `python3 -m py_compile <touched files>`
- Diff hygiene
  - `git diff --check`
- Slice-specific unit suites
  - Run the phase-specific unittest commands listed in Section 5 for the current slice only plus required keep-green regressions.
- Optional observer surfaces, if implemented
  - `session-start` stale carry-forward path must have a dedicated verification receipt
  - `refresh-continuity-observer` must have a dedicated verification receipt

## 7.3 Artifact receipt matrix
- Observer slices
  - `close-turn` / `run-finalize` / `import-continuity` / `session-tick` receipts with observer status and action kinds
  - event payload receipts showing stored observer metadata
  - `close-turn` receipts showing Draftshot, snapshot-candidate, and publication-candidate refresh outcomes remained correct
- Working canon slices
  - artifact paths for decisions, disclosures, discoveries, Draftshots, snapshot candidates
  - source-ref / evidence binding in authored artifacts
- Operational canon slices
  - snapshot candidate manifest/body paths
  - publication candidate manifest/body paths for story, vision, and codex
  - proposal paths for guild orders / quest / codex working surfaces
  - truth draft artifact paths and compiled truth publication receipts
- Compaction slices
  - archive/cooling manifest paths
  - proof that no cooled artifact is the sole evidence for a stronger claim
- Publication integration slices
  - onboarding draft paths / publish receipts / truth compile receipts

## 7.4 Manual inspection points
- Inspect that noncanonical artifacts are clearly labeled as such and are not confused with published canon.
- Inspect that story/vision/codex candidate authoring remains in the noncanonical candidate layer before sovereign publication integration.
- Inspect `STATE.yaml`, `MANIFOLD.yaml`, and rehydrate/current-context surfaces after each projection-affecting slice.
- Inspect a representative authored artifact body to verify truth / vision / unresolved separation is explicit.
- Inspect a representative degraded receipt to confirm the system does not overclaim model-backed behavior when the backend is unavailable.

# 8. Global Not-Done Conditions

The overall program is not complete if any of the following remain true.

- Synapse still lacks a lawful internal model invocation seam, but claims end-to-end model-backed continuity anyway.
- The observer or canonizer bypasses current owners and writes canonical/working artifacts directly without lineage-safe routing.
- Low-confidence or weakly evidenced material can still mutate strong working canon or canonical publication without obligation fallback.
- Draftshots, snapshot candidates, publication candidates, or truth drafts can churn revisions without real source delta.
- Discovery remains ledger-only with no general-purpose authored path.
- Operational canonization bypasses session-mode gating for proposal kinds.
- Truth drafts and compiled truth are collapsed into one layer.
- Sovereign identity publication can change without current publish gates.
- Archive/cooling can hide or delete the only evidence supporting a stronger claim.
- Current-context / rehydrate surfaces cannot show the current observer/canonizer state and current hot memory without loading cold history.
- Required tests are red or missing for a claimed-complete phase.
- Completion claims lack artifact-path receipts, command receipts, or projection receipts.

# 9. Codex Execution Handoff

## Where to start first
Start with Phase A, slice A0/A1. Do not touch later phases before the observer backend contract, continuity packet, and explicit degraded honesty are in place.

## What first merge-safe slice to implement
First merge-safe slice:
- A0 — Observer backend contract and fixture backend
Then immediately:
- A1 — Continuity packet builder and intent schema

This is the minimum lawful foothold because:
- repo truth has no sanctioned model adapter yet
- every later slice depends on a bounded packet and validated intent contract
- it adds no new canonical mutation risk by itself

## What to audit before touching code
- Re-run governance doctor for repo-governance work.
- Inspect current owners and tests before editing:
  - `runtime/synapse.py`
  - `runtime/synapse_runtime/automation_orchestrator.py`
  - `runtime/synapse_runtime/semantic_intake.py`
  - `runtime/synapse_runtime/live_journal.py`
  - `runtime/synapse_runtime/draftshots.py`
  - `runtime/synapse_runtime/snapshot_candidates.py`
  - `runtime/synapse_runtime/publication_candidates.py`
  - `runtime/synapse_runtime/quest_candidates.py`
  - `runtime/synapse_runtime/truth_compiler.py`
  - `tests/test_automation_orchestration.py`
  - `tests/test_close_turn_validation.py`
  - `tests/test_event_spine.py`
  - `tests/test_draftshot_runtime.py`
  - `tests/test_snapshot_candidates.py`
  - `tests/test_publication_candidates.py`
  - `tests/test_truth_compiler.py`
- Confirm whether the current slice requires a new module or can extend an existing owner cleanly.

## What invariants must never be violated
- Model decides meaning; runtime persists lawfully.
- No direct mutation of sovereign canon outside current publish gates.
- No second parallel memory system.
- No god files.
- No claim without receipts.
- No fake model-backed claims when only heuristic or fixture backend ran.
- No archive/delete without lineage-safe proof.
- No collapse of raw evidence, working canon, candidates, projections, and sovereign canon into one layer.

## What evidence must be returned after each slice
- exact files changed/created
- exact tests run
- exact verification commands run
- exact artifact paths written or receipts proving no-op/degraded behavior
- explicit audit result against the slice acceptance criteria
- explicit note of any remaining UNRESOLVED item for that slice

## When to stop and escalate instead of guessing
- No lawful model invocation surface can be chosen from repo truth and explicit operator approval is needed.
- A slice would require bypassing existing owners instead of extending them.
- A slice would require destructive migration or deletion of historical artifacts.
- A slice would force noncanonical artifacts to masquerade as canonical publication.
- A slice would require changing governance law rather than implementing within it.
- Repo truth contradicts the source plan in a way that cannot be resolved by a narrow extension.

# Applied Audit Corrections

- Restored optional observer trigger preservation as explicit follow-on work in Phase A:
  - `session-start` stale consolidation / carry-forward
  - explicit `refresh-continuity-observer`
- Restored Phase A keep-green regression coverage for close-turn-owned families:
  - `tests/test_draftshot_runtime.py`
  - `tests/test_snapshot_candidates.py`
  - `tests/test_publication_candidates.py`
- Restored Phase A receipt requirements proving `close-turn` still refreshes:
  - Draftshots
  - snapshot candidates
  - publication candidates
- Restored noncanonical story/vision/codex candidate authoring to Phase C under `runtime/synapse_runtime/publication_candidates.py`
- Removed Phase E overlap with late Phase C and restored strict phase order:
  - `Phase A -> Phase B -> Phase C -> Phase D -> Phase E`
- Restored strict boundary between:
  - noncanonical candidate authoring in Phase C
  - sovereign publication integration in Phase E
- Restored missing verification coverage for publication candidates in Phase C and the global verification matrix
- Restored verification/receipt requirements for optional observer trigger surfaces if they are implemented
- Preserved repo-relative references and removed host-specific pathing from the revised artifact

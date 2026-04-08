# 07 Model-Backed Continuity Observer And Canonization Build Spec

## 1. Executive Lock

The following decisions are now locked for Synapse design and execution:

1. Synapse must evolve from automatic raw capture plus heuristic promotion into a model-backed continuity system that can reason about unfolding work and decide what deserves durable memory.
2. The model should author continuity and canon artifacts. The runtime should own capture, routing, storage family, lineage, validation, receipts, and guardrails.
3. Synapse should canonize upward periodically and automatically at real boundaries. It should not depend on the operator remembering manual commands for ordinary continuity preservation.
4. Raw evidence should remain the evidence floor. It should move into cold storage or archival posture after lineage-safe promotion, not be treated as the main active memory forever.
5. Active project memory should be kept slim by promoting upward into better artifacts, then compacting/archive-marking older lower-level material.
6. Synapse, not the subject repo, is the subsystem that must become smarter. Wingman merely exposed the gap.

This is not a proposal draft. It is the design direction to endorse and execute.

## 2. Problem Statement

Current Synapse behavior is good at capture but weak at judgment.

What already works:
- automatic raw turn capture
- automatic raw tool / execution capture
- automatic close-turn boundary execution
- semantic event generation
- some governed promotion
- Draftshot and candidate refresh from synthesized deltas

What does not yet work strongly enough:
- reasoning about whether a conversation moment is a real decision, discovery, scope shift, architecture shift, disclosure, guild-order change, quest movement, or codex-worthy continuity event
- writing strong authored artifacts without the user explicitly telling the system to log them
- periodically consolidating noisy accumulated continuity into durable canon and working memory
- keeping active memory slim while preserving auditability and recoverability

The result today is a split-brain system:
- capture is increasingly automatic
- high-value continuity formalization is still too heuristic or too manual

That is the wrong steady state for a repo as large and long-lived as Synapse is meant to support.

## 3. Current Repo Truth

Synapse already has the necessary lower layers:
- raw conversation capture
- raw execution capture
- semantic segmentation and event classification
- governed working-record families
- Draftshots
- typed snapshot candidates
- publication candidates
- sidecar projections and rehydrate surfaces
- onboarding-anchored canonical publication paths

The missing layer is not storage. The missing layer is model-backed continuity judgment.

The current system largely decides significance using:
- lexical cues
- summary-presence checks
- source-signature changes
- simple threshold logic
- explicit direct CLI actions

That is better than nothing, but it is not the intended final behavior.

## 4. Locked Architecture Principle

### 4.1 The model is the author of meaning

A reasoning model should determine:
- what happened
- what changed
- what matters
- what is truth
- what is vision
- what is unresolved
- what belongs in which artifact family
- how the artifact body should be written

### 4.2 The runtime is the author of lawfulness

The runtime should determine:
- which owner module stores the artifact
- which schema and family it belongs to
- ids, pointers, and paths
- lineage and supersession
- evidence binding
- confidence / uncertainty metadata
- publication gating
- archive and retention policy
- receipts and audit trails

### 4.3 Rejected bad split

Reject the idea that the runtime alone can infer meaning from heuristics.

Reject the idea that an unconstrained model should directly mutate canonical memory with no deterministic ledger around it.

The correct split is:
- model decides meaning
- runtime persists lawfully

## 5. Continuity Observer: Required New Synapse Subsystem

Synapse needs a first-class model-backed subsystem tentatively named:
- `continuity_observer.py`

Its job is to act like the intelligent project historian in the corner of the room.

It should run at real boundaries and periodically review recent work to decide what deserves durable storage.

### 5.1 Trigger surfaces

The observer should run at minimum on:
- `close-turn`
- `run-finalize`
- `import-continuity`
- `session-tick` when enough material accumulated

Optional later expansion:
- `session-start` for stale consolidation / carry-forward
- explicit `refresh-continuity-observer`

### 5.2 Observer input packet

The observer must not read the whole universe every time. It should receive a bounded continuity packet containing:
- recent raw user / executor turns
- recent raw tool and execution events
- recent changed files
- recent semantic events
- current active run metadata
- session mode
- current active plan delta
- current active scope delta
- current architecture / identity / narrative deltas
- current obligations
- current Draftshot state
- current snapshot / publication candidate state
- recent decisions / disclosures / discoveries
- imported continuity confidence markers when relevant

### 5.3 Observer output schema

The observer should return structured intents, not freeform prose only.

Each intent should include:
- artifact family
- action type
- confidence
- rationale
- source refs
- truth-state label
- uncertainty markers
- draft-safe vs gated-publication status
- supersedes / updates hints where relevant

Example action kinds:
- `semantic_capture`
- `decision_log`
- `disclosure_log`
- `discovery_log`
- `architecture_evolution`
- `scope_campaign_update`
- `draftshot_refresh`
- `snapshot_eod`
- `snapshot_control_sync`
- `guild_order_draft`
- `quest_candidate`
- `quest_state_update_draft`
- `story_candidate`
- `vision_candidate`
- `codex_candidate`
- `truth_statement_update`
- `open_obligation`
- `noop`

### 5.4 Non-negotiable observer rules

The observer must:
- distinguish observed truth from inferred truth
- distinguish implemented reality from intended future
- cite evidence
- admit uncertainty
- avoid fake certainty
- avoid silent canonization of weak material
- prefer opening an obligation when confidence is not high enough for stronger storage

## 6. Canonizer: Required New Synapse Behavior

Synapse needs a model-backed canonizer layer that consumes observer intents and writes the actual artifact bodies.

Tentative module:
- `canonizer.py`

The canonizer should not replace current owners. It should sit above them and feed them.

### 6.1 What the canonizer should do

The canonizer should:
- produce authored artifact text from evidence + current state
- separate truth / vision / unresolved / superseded states explicitly
- avoid dumping raw chat into artifacts
- write concise but high-fidelity durable memory
- maintain stable structure for downstream rehydration

### 6.2 What the canonizer should not do

It should not:
- pick arbitrary file paths
- bypass lineage stores
- bypass publication owners
- rewrite history without supersession linkage
- collapse uncertainty into certainty

## 7. Artifact Classes And Automation Policy

### 7.1 Auto-authored working canon

These families should be eligible for model-authored automatic writing when evidence and confidence support it:
- Draftshots
- Control Sync snapshot candidates
- EOD snapshot candidates
- discoveries
- decisions
- disclosures
- architecture evolution records
- scope campaign updates
- quest candidates
- guild order drafts
- codex candidates
- story candidates
- vision candidates
- truth statement drafts / working truth deltas

These are the core working memory surfaces.

### 7.2 Stronger-gated canonical identity / sovereign outputs

These should remain behind a stronger publication gate even if the model writes the content:
- `PROJECT_MODEL.yaml`
- `PROJECT_STORY.md`
- `VISION.md`
- `CODEX_CURRENT.md`
- `CODEX_FUTURE.md`
- accepted / completed quest state transitions with irreversible consequences
- any publication that changes sovereign repo identity or operator commitments

Important nuance:
- the model should still author the draft or publication text
- the stronger gate is about lawful publication, not about forbidding model authorship

## 8. Upward Canonization Ladder

Synapse should adopt an explicit upward memory ladder:

1. Raw evidence
- turns, tools, execution, imports

2. Normalized evidence
- segments, semantic events, capture batches

3. Working canon
- decisions, discoveries, disclosures, scope, architecture, Draftshots, snapshots, quest/guild/codex working artifacts

4. Identity / sovereign canon
- project model, story, vision, codex canon, accepted quest canon

5. Projections
- rehydrate, current context, manifold/state surfaces

The model-backed observer and canonizer should move material upward through this ladder.

## 9. Hot / Warm / Cold Memory Policy

### 9.1 Hot memory

This is what future sessions should load first.
It should stay small and high-signal.

Examples:
- current active plan
- current scope campaigns
- current decisions and disclosures that still matter
- current Draftshot
- current EOD / Control Sync state
- current guild orders
- current quests
- current codex and truth deltas
- current open obligations and blockers

### 9.2 Warm memory

Useful recent history, not first-load mandatory.

Examples:
- recent Draftshots
- recent snapshot candidates
- recent decision / discovery / disclosure batches
- recent architecture / scope shifts
- recent superseded but still relevant canon

### 9.3 Cold memory

Preserved evidence floor and old history.

Examples:
- raw turns
- raw tool events
- raw execution events
- imported raw evidence
- stale capture batches
- old candidate revisions
- superseded lower-level records no longer needed for first-pass rehydration

The purpose is not to delete history. It is to stop treating low-level history as the active brain.

## 10. Archive And Deletion Policy

### 10.1 Archive, not reckless deletion

After successful upward promotion, lower-level material should generally become:
- archived
- compacted
- marked superseded
- moved to cold storage posture

It should not be blindly deleted.

### 10.2 Safe archive targets

Safe to archive or cool aggressively after lineage-safe promotion:
- superseded Draftshots
- superseded snapshot candidates
- superseded publication candidates
- stale semantic capture batches already incorporated into stronger artifacts
- old raw evidence beyond the hot/warm window

### 10.3 Dangerous deletion targets

Do not delete if any of these are true:
- it is the only evidence for a stronger claim
- it is still referenced by source refs / lineage
- it contains unresolved contradiction context
- it contains unresolved imported continuity or review debt
- it has not yet been superseded by a stronger durable artifact

### 10.4 Compaction policy

Compaction should:
- preserve lineage edges
- preserve provenance pointers
- preserve source signatures or archival manifests
- preserve the ability to re-open old evidence when canon quality is questioned

## 11. Why This Needs A Model And Not Just Runtime Heuristics

The following judgments are inherently model tasks:
- whether a conversation crossed a real decision boundary
- whether architecture meaning changed versus surface implementation details merely changed
- whether a statement is observed truth, repo hypothesis, operator intent, or future vision
- whether a scope statement should become a Guild Order, Quest candidate, Codex entry, or simply a Draftshot note
- whether a repo review result materially changes the project picture
- how to author a good Control Sync, EOD, Story, Vision, or Codex section without turning it into sentence soup

The runtime can store. It cannot reason at that level by itself.

## 12. What Must Stay Deterministic

Even after introducing model-backed canonization, these must remain deterministic and runtime-owned:
- file family routing
- schema validation
- ids and revision numbering
- lineage and supersession edges
- sidecar projections
- gate decisions for strong publication
- retention and archive rules
- publication receipts
- obligation creation when confidence is not sufficient

## 13. Implementation Program

### Phase A — Continuity Observer

Build the observer and wire it into `close-turn` first.

Scope:
- bounded continuity packet builder
- model-backed intent schema
- no-op / capture / decision / disclosure outputs
- confidence + evidence refs required
- obligation fallback on weak certainty

### Phase B — Working Canonizer

Expand the observer outputs into authored working-canon artifact generation.

Scope:
- decisions
- discoveries
- disclosures
- architecture evolution
- scope updates
- Draftshot improvement
- better snapshot authoring

### Phase C — Operational Canonization

Add authored automation for:
- Control Sync snapshots
- EOD snapshots
- Guild Order drafts
- Quest candidate drafts
- Codex working updates
- truth statement drafts

### Phase D — Compaction And Archive Policy

Add lineage-safe archive / cooling logic.

Scope:
- hot / warm / cold tagging
- superseded lower-level material cooling
- archive manifests
- source-retention checks before deletion

### Phase E — Stronger Canon Publication Integration

Use the same model-backed authored content to feed gated sovereign publication paths.

Scope:
- project model / story / vision / codex publication pipeline improvements
- stronger review / publish gates
- no bypass of existing canonical owners

## 14. Acceptance Standard

This direction is complete only when Synapse can:
- watch normal governed work unfold
- reason about what mattered
- write high-quality durable memory automatically
- keep truth / vision / uncertainty separated
- update active project memory without operator babysitting
- archive older low-level material without losing provenance
- keep sovereign canon safe behind lawful gates

## 15. Explicit Rejections

Reject:
- raw chat forever as the active memory system
- keyword-only automation as the final intelligence layer
- forcing the operator to remember continuity commands during normal work
- unconstrained model-only canon with no deterministic ledger around it
- deleting evidence just because a later artifact exists
- subject-specific hacks instead of fixing Synapse itself

## 16. Final Lock

The endorsed direction is:
- automatic capture
- model-backed continuity judgment
- model-authored working canon
- runtime-owned lineage and lawfulness
- periodic upward canonization
- archive / compaction after lineage-safe promotion
- strong publication gates only where sovereign identity or irreversible canon is at stake

That is the system Synapse needs to become.

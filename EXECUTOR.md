```
Synapse Executor Contract
```

This file is the canonical, executor-agnostic contract. Shims (AGENTS.md, CLAUDE.md, Copilot/Cursor/Cline/Continue/Roo/Windsurf/JetBrains) must point here. No vendor-specific behavior lives outside this contract.

## 1) Purpose
- Keep work deterministic, receipt-backed, and resumable across sessions.
- Replace chat memory with governed artifacts (Guild Orders, Quests, Snapshots, Audits, Codex).
- Enable safe handoff between runtimes and operators without drift.

## 2) Canonical Sources
- Canonical governance content: `/home/notsolikely/AGENTS.md` (subject-agnostic). Repo-level AGENTS.md is a shim to this contract.
- Do not create alternative instruction files; shims must only redirect here.

## 3) Roots & Subject Focus (single source of truth)
- Subject selection is owned by the existing focus lock in `runtime/synapse.py`.
- Resolution order: `--subject` flag → focus lock → `SUBJECT` env → infer only when exactly one `*_Data` exists → otherwise FAIL with “run synapse focus”.
- No silent switching once set; switching must happen via the focus command.
- Derived roots after focus: `SYNAPSE_ROOT`, `GOVERNANCE_ROOT`, `ENGINE_ROOT`, `DATA_ROOT`.

## 4) Boot Ritual (deterministic)
1. Assert roots exist (`SYNAPSE_ROOT`, `GOVERNANCE_ROOT`, `ENGINE_ROOT`, `DATA_ROOT`).
2. Run governance doctor (`python3 runtime/synapse.py doctor --governance-root governance`).
3. Read, in order: `governance/README.txt`, `governance/INDEX.txt`, `governance/SYNAPSE_STATE.yaml`.
4. Follow `required_read_order` from `SYNAPSE_STATE.yaml`; resolve subject pointers under `<Subject>_Data` exactly.
5. Load the latest Continuity/Lock artifact as the “GPS”.
6. Emit a Boot Ritual receipt (doctor status + files read + active lock path/timestamp).

## 5) Modes (Elastic Governance)
- **INCUBATION**: non-executing. No engine edits, no commits/push. Capture discoveries/questions under `<Subject>_Data` only.
- **PLAN**: non-executing. Draft Guild Orders/Dungeons/Quests and plans. Defer non-blocking questions.
- **EXECUTE**: R0/R1 auto with receipts. R2+ requires explicit consent once per batch.

## 6) Gates & Stop Conditions
- **Truth Gate**: status must be `VERIFIED` (has receipts), `PROPOSED`, or `BLOCKED`.
- **Disclosure Gate**: STOP if required_read_order incomplete, tools missing, path ambiguity, governance contradictions, or receipts absent for claimed actions.
- **Execution Gate (Fog)**: If `<Subject>_Data/Codex/CODEX_FREEZE.md` is missing → Fog of War → execution forbidden; only diagnose/plan/draft. If present → Fog Lifted → execution allowed under governance.
- Stop only on R2+ actions or BLOCKING ambiguity; do not spam low-risk stops.

## 7) Consent (R2+)
- Ask once per batch when risk is R2+ or destructive. Use `runtime/tools/synapse_consent.sh <mode>` when present to record consent. No per-step nagging.

## 8) Routing Table (authoritative)
- **Guild Orders**: `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS.txt`, `governance/Guild Docs/SYNAPSE_GUILD__GUILD_ORDERS_TEMPLATE__SELF_CONTAINED.txt`.
- **Quests**: `governance/Quest Board/QUEST_TEMPLATE.txt`, `governance/Quest Board/SYNAPSE_GUILD__QUEST_VALIDATION_RULES.txt`; execute only via `runtime/tools/synapse_quest_run.sh`.
- **Snapshots / Control Sync**: `runtime/tools/synapse_snapshot_writer.py` (primary). If a legacy writer exists, disclose legacy use.
- **Governance Guard / Audits**: `runtime/tools/synapse_governance_guard.py` (or legacy) for audit validation/bundles.
- **Codex build**: section-by-section; keep `ANCHOR_INDEX`/contracts aligned after each section; use gates under `runtime/tools/*gate*` if present.

## 9) Receipts & Required Response Format
Every claim of progress must include: what you did, files touched, diffs/patches, commands run + output, tests + results, risks/limits, next move. No “done” without receipts (paths/output/diffs/tests).

## 10) Incubation Scribe Rules
Capture only decisions, constraints, definitions, non-goals, risks, dependencies, boundaries/interfaces. Exclude chatter. `DISCOVERIES.md` holds final decisions; exploratory ideas live in session logs/draftshots or are marked `SUPERSEDED_BY`. `OPEN_QUESTIONS.md`: label `BLOCKING` vs `NONBLOCKING`.

## 11) Drift Policy (commit-based, no hash brick)
- State anchor: `.synapse/STATE.json` (or focus lock) stores `last_ack_commit`.
- Commands: `python3 runtime/synapse.py drift`, `python3 runtime/synapse.py acknowledge`.
- INCUBATION/PLAN: warnings only. EXECUTE: block R2+ if governance changed and drift unacknowledged. Warn once per session.

## 12) Clean Architecture / Invariants
- Modularize only when it improves cadence, failure isolation, reuse, security, or performance. Avoid god files.
- Engine vs Data separation is strict; do not mix code and state.
- Subject-specific invariants belong in subject data/engine docs, not in this contract.

## 13) Mandatory Execution Paths
- All quest execution must go through `runtime/tools/synapse_quest_run.sh`; direct shell execution is a procedure violation.
- Snapshots/Control Sync must use the snapshot writer tool; no freestyle formats.
- Audits must be validated with the governance guard tool where applicable.

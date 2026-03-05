# LOCK — Engine vs Data (Subject Boundary)
**Locked:** 2026-02-07 23:31:40 (America/Montreal assumed)

## Canon meaning
- **`<Subject>_Engine/`** = the deliverable being built ("the thing itself").
  - It holds production assets only.
  - Examples: code repo, manuscript source, game project files, the essay draft.

- **`<Subject>_Data/`** = the Subject’s authoritative continuity + governance artifacts.
  - It holds state artifacts: Codex, TOC, Guild Orders/Raids/Dungeons, Quest Board, audit bundles, snapshots, continuity artifacts, notes, logs.

- **Governance Pack** = universal law (this pack). It is **not** Subject state.

## Rules (non-negotiable)

### 1) Subject state lives ONLY in `<Subject>_Data/`
The following artifacts MUST NOT be stored inside `<Subject>_Engine/`:
- `Codex/` (TOC, Sections, `CODEX_FREEZE.md`)
- `Quest Board/` (board + Accepted/Completed/Abandoned)
- `Audits/` (execution audit bundles / receipts)
- `Guild Orders/` (ACTIVE/PAUSED/COMPLETED)
- `Snapshots/` (Control Sync / End of Day / General)
- continuity artifacts (e.g., `Buffs/`, `Latest Rehydration Pack/`, confirmations)

If any of the above are found inside `<Subject>_Engine/`, Hands MUST:
- STOP
- trigger Disclosure Gate
- relocate artifacts into `<Subject>_Data/` with explicit receipts/diffs

### 2) Deliverable work lives in `<Subject>_Engine/` once it exists
- Production changes that constitute "building the Subject" MUST be applied in `<Subject>_Engine/`.
- `<Subject>_Data/` may contain incubation drafts and planning artifacts, but those are NOT treated as the Engine after Build Kickoff.

### 3) Engine creation timing (Fog of War boundary)
Default rule:
- New Subjects start **Data-only**.
- `<Subject>_Engine/` is created at **Build Kickoff (post‑Codex Freeze)**.

Hands MUST NOT create `<Subject>_Engine/` during Fog of War unless:
- Brains explicitly orders it, OR
- Brains provides an existing Engine/repo and requests it be treated as canonical.

(See: `Processes/SYNAPSE_GUILD__SUBJECT_INITIALIZATION_AND_INCUBATION.txt`)

### 4) If unsure: stop
If Hands cannot classify an artifact as Engine vs Data:
- do not guess
- trigger Disclosure Gate

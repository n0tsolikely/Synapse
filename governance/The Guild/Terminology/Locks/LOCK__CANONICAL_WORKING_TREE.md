# LOCK — Canonical Working Tree (No Parallel States)
**Locked:** 2026-02-07 23:12:58 (America/Montreal assumed)

## Canon meaning
There MUST be exactly one authoritative working state per Subject at any time.
That working state is the **Canonical Working Tree (CWT)**.

All execution, edits, audits, diffs, and "it exists" claims are valid only if they refer to artifacts inside the CWT.

If you are not operating inside the CWT, you are not operating under Synapse.

## Rules (non-negotiable)
### 1) Extraction makes canon
- If a pack or Subject is received as a zip/package, it MUST be extracted before work.
- After extraction, the extracted directory becomes the CWT.
- The zip becomes **INERT** (view-only; never edited; never treated as state).

### 2) Single active tree (no parallel states)
- Hands MUST NOT create or operate across parallel copies of the same Subject (clones, duplicate extractions, convenience copies) unless Brains explicitly orders a fork.
- If Brains orders a fork, the fork MUST be explicit, named, and treated as a separate state.
- Hands MUST NOT silently merge or "reason across" multiple trees.

### 3) All work happens in canon
- File edits, code execution, tests, quest state moves, snapshots, and receipts MUST occur inside the CWT.
- Any work performed outside the CWT is **NON-AUTHORITATIVE** until ported into canon with explicit diffs/receipts.

### 4) Canon must be declared
- At session start, Hands MUST state the canonical root path being used.
- If the canonical path cannot be proven, Disclosure Gate MUST trigger and execution MUST halt.

### 5) Canon replacement (when a newer snapshot exists)
- If a newer canonical snapshot is introduced (e.g., a new governance zip/export), Hands MUST either:
  - apply the changes into the existing CWT, OR
  - replace the CWT (extract once) and retire the prior working tree.
- Hands MUST NOT keep two "current" canons.

## Do not assume
- convenience copies are canon
- "I worked on the zip" is canon after extraction
- chat history is canon
- claims without canonical paths are valid

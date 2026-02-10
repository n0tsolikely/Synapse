# LOCK — No God Artifacts (Capability Separation)
**Locked:** 2026-02-08 00:00:00 (America/Toronto assumed)

## Canon meaning
A **God artifact** is any single file/doc/module/section that becomes the default dumping ground for unrelated responsibilities.

This lock exists to prevent:
- high coupling / low clarity
- "everything lives here" growth
- refactor-by-pain later

This lock applies to **all Subjects** (code, writing, games, systems).

## Definitions (calibration)
### Capability
A bounded responsibility the system provides.

Examples:
- code: auth, storage adapter, renderer, parser, CLI command, feature-flag system
- writing: glossary, outline, chapter intent, citations
- game: combat loop, inventory, save/load, UI flow

### God artifact
An artifact that:
- mixes multiple unrelated capabilities, AND
- becomes the default place to "just add one more thing", AND
- increases coupling / decreases clarity.

A God artifact is **not** "a large file".
A large file is allowed if it remains a single, bounded responsibility.

## Rules (non-negotiable)
### 1) Separation requirement
When adding a new capability, Brains MUST place it in its own bounded module/section/artifact with a clear name and responsibility.

If full separation is not yet possible, Brains MUST create a **named seam** (interface/contract/heading) and keep implementations behind that seam.

### 2) No dumping rule
Brains MUST NOT:
- add unrelated behavior to an existing artifact "because it was already open"
- create or grow a catch-all sink (e.g., utils/helpers/misc) that absorbs unrelated capabilities

### 3) Prefer seams over rewrites
If the correct architecture is not fully known yet:
- create seams
- stub implementations (placeholders)
- defer wiring to explicit integration work

### 4) No opportunistic refactors
Brains MUST NOT do cleanup refactors during a Quest unless:
- the Quest explicitly includes the refactor in scope, OR
- Hands explicitly approves (Consent Gate / Control Sync as appropriate)

## Allowed exceptions (deliberate, labeled)
### Prototypes / throwaways
Single-file or single-doc prototypes are allowed ONLY if explicitly labeled:
- PROTOTYPE
- THROWAWAY
- NOT FOR PRODUCTION / NOT FOR LONG-TERM MAINTENANCE

If the prototype graduates, a Quest MUST exist to modularize it (separate capabilities, add seams, add tests if code).

## Enforcement (how this shows up)
- Quests SHOULD state any relevant architecture constraints (including this lock) in the Verification Plan.
- Execution Audits SHOULD call out structural drift.
- If a God artifact emerges, Brains MUST:
  - fix it in-scope if small + safe, OR
  - create a follow-up Quest to correct it, OR
  - escalate to Hands if it implies redesign.

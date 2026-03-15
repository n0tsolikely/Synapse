# LOCK — SUBJECT DATA SKELETON
**Version:** v1.3  
**Last Updated:** 2026-02-09  
**Status:** Terminology Lock (Authoritative / Overrides all non-lock text)

---

## 0) PURPOSE
This lock defines the **universal minimum skeleton** for `<Subject>_Data/`.

It exists to prevent drift:
- across subjects
- across sessions
- across AIs

If any non-lock document conflicts with this skeleton, this lock wins.

---

## 1) CANONICAL RULE
Every Subject MUST have a `<Subject>_Data/` folder that contains the **canonical
minimum skeleton** defined below.

This lock exists to prevent drift across subjects/sessions/AIs.

### 1.1 Name exactness (no synonyms)
Directory names in this skeleton are **canonical and exact** (including
capitalization and spaces).

If you see duplicates like any of the following, the state is INVALID until
corrected:
- `QuestBoard/` vs `Quest Board/`
- `control sync/` vs `Control Sync/`
- `Talent_Tree/` vs `Talent Tree/`

### 1.2 Additions allowed, replacements forbidden
Additional subject-specific directories are allowed, but **may not replace**,
rename, or shadow any part of the canonical skeleton.

If any non-lock document conflicts with this skeleton, this lock wins.

---

## 2) MINIMUM REQUIRED STRUCTURE (CANON)

```
<Subject>_Data/
  confirmations/              # Consent Gate artifacts (R2)

  Snapshots/
    General/
    Control Sync/
    End of Day/

  Guild Orders/
    ACTIVE/
    PAUSED/
    COMPLETED/

  Quest Board/
    Accepted/
    Completed/
    Abandoned/
    # Quest files may also live at the root of Quest Board when "on the board"

  Audits/
    Execution/
    # Execution audits live here (see Execution Audits law)

  Codex/
    Sections/

  .synapse/
    EVENTS/
    # append-only raw runtime events (non-canonical, reducer input)

  Docs/
  Buffs/
  To Do/
  Talent Tree/
  Latest Rehydration Pack/
  Incubation/
  Archive/
```

Notes:
- Folder names with spaces are canonical (e.g., `Control Sync`, `End of Day`, `Quest Board`).
- `.synapse/` is the canonical live sidecar for repo-local runtime continuity under Subject Data.
- `.synapse/EVENTS/` stores append-only raw runtime events. These are not canon; they are reducer inputs.
- `confirmations/` may be empty, but it MUST exist as the canonical home for Consent Gate artifacts.
- `Archive/` exists for long-term retention but is not required to be populated.
- `Incubation/` may remain empty for continuing subjects. It still exists as a stable home for
  pre-Codex capture when needed.

### 2.0.1 REQUIRED SUBJECT STATE FILE (CANON)

Every Subject MUST contain a subject-local state manifest at:

- `<Subject>_Data/SUBJECT_STATE.yaml`

Purpose (strict):
- Acts as a **pointer registry** for the Subject (identity + roots + canonical pointers).
- Prevents the runtime/AI from guessing "latest" artifacts across sessions.
- MUST remain small; it MUST NOT duplicate artifact contents.

Hard rules:
- `SUBJECT_STATE.yaml` is **subject-scoped** and MUST NOT live in the governance pack.
- Governance-level `SYNAPSE_STATE.yaml` is universal and MUST NOT hardcode a specific Subject.
- Subject state is updated only when:
  - a new Snapshot is written
  - a new Rehydration Pack is created/activated
  - a new Continuity Lock is written
  - Guild Orders move between ACTIVE/PAUSED/COMPLETED
- Subject state MUST NOT be updated for every individual Quest execution.

Minimum required keys (schema v1):
- `schema_version`
- `subject.name`
- `subject.key`
- `roots.data_root`
- `roots.engine_root`
- `pointers` (paths to latest canonical artifacts, or directory rules if "latest" is derived)

### 2.1 Canonical Codex artifacts (phase-dependent)
The `Codex/` directory MUST exist. Specific Codex files have strict meaning:

- `TOC.md` — the canonical TOC once a TOC exists.
- `TOC_DRAFT.md` — optional during incubation.
- `<Subject>_Codex_Full.txt` — exists once a stitched Codex exists (draft or final).
- `CODEX_FREEZE.md` — **world-state marker**:
  - MUST NOT exist before Brains freezes the Codex.
  - MUST exist after Brains freezes the Codex.

---

## 3) SUBJECT BUFFS (REQUIRED FILES)
Inside `<Subject>_Data/Buffs/`, the following three files MUST exist:

- `<SUBJECT>_EXECUTION_PROTOCOL.txt`
- `<SUBJECT>_DATA_DIRECTORY_MAP.txt`
- `<SUBJECT>_SESSION_START_CHECK.txt`

These implement the “Buff up” ritual.

---

## 4) NO-DRIFT PRINCIPLE
If an operator is unsure where to store an artifact, the answer is:

- If it is law: Governance Pack.
- If it is subject state: `<Subject>_Data/`.
- If it is the built system: `<Subject>_Engine/`.

If still unsure, stop and trigger Disclosure Gate.

---
- Snapshots/Draft Shots/          # Draftshot artifacts (append-only formalizations)

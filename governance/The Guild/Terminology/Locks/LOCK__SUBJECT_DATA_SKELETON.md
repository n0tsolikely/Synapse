# LOCK — SUBJECT DATA SKELETON
**Version:** v1.1  
**Last Updated:** 2026-02-02  
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
Every Subject MUST have a `<Subject>_Data/` folder that contains (at minimum) the
directories below.

Additional subject-specific directories are allowed, but this minimum skeleton
must always exist.

---

## 2) MINIMUM REQUIRED STRUCTURE (CANON)

```
<Subject>_Data/
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
    TOC.md                     # the TOC / Legend
    TOC_DRAFT.md               # optional during incubation
    CODEX_FREEZE.md            # exists only after Hands freezes the Codex
    Sections/
    <Subject>_Codex_Full.txt

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
- `Archive/` exists for long-term retention but is not required to be populated.
- `Incubation/` may remain empty for continuing subjects. It still exists as a stable home for
  pre-Codex capture when needed.

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
- If it is subject state: Subject_Data.
- If it is the built system: Subject_Engine.

If still unsure, stop and trigger Disclosure Gate.

---

# TERM — God Artifact

## Definition
A **God Artifact** is any single artifact (file/doc/module/section) that becomes the default dumping ground for **unrelated capabilities**, producing high coupling and low clarity.

A God Artifact is **not** defined by size. It is defined by responsibility collapse:
- multiple unrelated concerns co-located
- “just add it here” becomes the default pattern
- changes in one area frequently break unrelated areas

Examples:
- a `utils.py` file that grows to include auth, storage, parsing, formatting, orchestration
- a “Notes” doc that becomes outline + draft + citations + glossary

## Purpose
Prevent long-term maintenance traps and refactor blowups by enforcing early capability separation.

## Do Not Assume
- Big artifact ≠ God artifact.
  - A large artifact can still be valid if it maintains a single bounded responsibility.
- God artifacts are not “style” issues; they are architecture/structure failures.

## Interactions
- The “No God Artifacts” rule enforces how new capabilities are placed.
- “What vs How” separation helps prevent god artifacts in governance docs.

## Authority
→ `The Guild/Terminology/Locks/LOCK__NO_GOD_ARTIFACTS.md`

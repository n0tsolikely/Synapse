# LOCK — Canonical Working Tree (No Parallel States)
**Locked:** 2026-01-31 19:20:21 (America/Montreal assumed)

## Canon meaning
There must be one authoritative working state per Subject (Engine/Data). No silent forks.

## Rules
- After extraction, the extracted directory becomes canonical.
- Do not create competing copies and reason across them.
- If branching is needed, it must be explicit and named.

## Do not assume
- convenience copies are not canon
- “I worked on the zip” is not canon once extracted
- claims require referencing the canonical tree

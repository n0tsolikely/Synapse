# Terminology (Governance Pack)
**Updated:** 2026-02-02

This folder defines Synapse OS terminology in two layers:

- `Locks/` — **Authoritative locks** for high-risk, cross-cutting terms that must not drift.
  These are concise, enforceable definitions plus assumption-guards.

- `Terms/` — Routing definitions (optional). If present, they must not contradict Locks.
  If a Lock exists for a term, the Lock wins.

These definitions are portable and belong in the Governance Pack (stateless canon).
Session-specific notes, examples, and evolving drafts belong in Subject Data.

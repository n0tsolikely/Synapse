# Terminology
**Updated:** 2026-02-08

This folder defines canonical meanings for Synapse OS terms.

Terminology exists to prevent drift, “helpful” reinterpretation, and cross-session ambiguity.

## Authority
- **Locks are enforcement authority.** If a Lock exists, it overrides all other text.
- **Terms are meaning anchors.** They are used to write and interpret artifacts, but they do not override Locks.
- **Conversation is not a definition source.** Chat can propose language, but it does not establish meaning.

## Structure
- `Locks/LOCK__*.md`
  - Cross-cutting enforcement rules that must not drift.
  - If a Lock exists for a concept, treat the Lock as the single source of truth.
- `Terms/*.md`
  - Definitions and meaning anchors used when drafting and reading artifacts (Codex, Guild Orders, Quests, Snapshots, etc.).
  - Terms may elaborate, but MUST NOT loosen, replace, or contradict any Lock.
- `README.md`
  - This map.

## Usage rules
- If a term is used in an artifact, its meaning is the content of the corresponding Term or Lock files, not “what we meant in chat.”
- If a needed term is not defined here, treat it as undefined.
  - Subject-specific definitions belong in the Subject Codex.
  - Governance-wide meanings require a governance change and Hands approval.

## Conflict handling
- If a Term conflicts with a Lock:
  - The Lock wins.
  - Trigger Disclosure Gate.
  - Do not proceed by “blending” definitions.

## Scope boundary
- This folder is Governance Pack scoped and stateless.
- Subject-specific world rules, tone rules, constraints, and domain definitions belong in `<Subject>_Data/` artifacts, especially the Codex.

## Non-negotiables
- **File existence rule:** if a Term or Lock file does not exist on disk, that definition does not exist.
- **No soft overrides:** Terms cannot override Locks; conversation cannot override either.
- **No hidden assumptions:** if you are unsure which definition applies, you are unsure. Trigger Disclosure Gate and stop.

## Added Terms
- Door
- Smoke_Test
- God_Artifact
- Verification_Ladder
- Build_Manual

## Added Locks
- LOCK__NO_GOD_ARTIFACTS
- LOCK__LAYER_RESPONSIBILITIES

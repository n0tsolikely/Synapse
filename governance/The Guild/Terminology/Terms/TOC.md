# TERM — Table of Contents (Legend)

## Definition
The Table of Contents (TOC) is the navigational contract of the Codex.
It defines section numbering, titles, and scopes so Codex construction and reference is deterministic.

**Alias (conversation):** The TOC may be referred to as the **Legend**.

Artifact law:
- The TOC is a Subject-state artifact.
- Canonical location (post-incubation): `<Subject>_Data/Codex/TOC.md`.
- During Fog of War, a draft is permitted: `<Subject>_Data/Codex/TOC_DRAFT.md`.
- Conversation is input. The TOC file is authority.

Section numbering law:
- TOC numbering is the canonical reference ID for the Codex.
- Each TOC entry MUST map to exactly one section file under `<Subject>_Data/Codex/Sections/`.
- Section file numbering MUST match the TOC numbering.

## Purpose
The TOC makes the Codex navigable and prevents structural drift by making “write section X” unambiguous.

## When It Applies
- During Codex formation (TOC creation and refinement)
- During section-by-section Codex writing
- Whenever Guild Orders / Dungeons / Quests reference Codex structure

Structural change rule:
- Renumbering, adding/removing entries, or changing an entry’s scope is a structural change.
- Structural changes MUST be recorded in Control Sync + Snapshot.

## What It Enables
- Section-by-section Codex construction
- Stable reference points for Guild Orders, Dungeons, and Quests
- Deterministic stitching into a “Codex Full” artifact

## Do Not Assume
- The TOC is not execution authority.
- The TOC is not a commitment to implement everything immediately.
- A TOC entry does not “exist” as a Codex section until the corresponding section file exists.
- Renumbering is not cosmetic; it changes reference IDs and must update the section files.

## Interactions
- TOC entries map to Codex section files under `<Subject>_Data/Codex/Sections/`.
- Guild Orders reference TOC/Codex sections by ID (TOC numbering).
- Large Artifact Composition protocol applies when the TOC/sections are large.

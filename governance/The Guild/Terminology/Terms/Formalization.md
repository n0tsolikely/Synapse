# TERM — Formalization

## Definition
A **Formalization** is the act of converting ambiguous or conversational input into a deterministic,
artifact-backed output that a compliant operator (human or AI) can execute or rely on without guesswork.

Formalization is **not** a transcript.
Formalization is **not** a vibes-based summary.

## Properties (what makes it a formalization)
A formalization MUST:
- Preserve **binding decisions** (what is true / what will be done)
- Capture **rationale** (why this decision was chosen)
- Declare **constraints** and **invariants** (what must not change)
- Identify **open questions** and either resolve them or mark them explicitly as DEFERRED
- Reference **artifacts** (paths) that hold the ground truth
- Be sufficiently structured that another operator can rehydrate and continue correctly

## Usage in Snapshots + Draftshots
- A Draftshot is a living formalization (meeting minutes in progress), updated append-only by REV.
- A Snapshot is a formalization of a bounded window of reality (alignment or execution).
- If a Draftshot is ACTIVE when producing a Snapshot, the Snapshot is a **formalization of the Draftshot**
  (distilled, decision-complete), and MUST reference the Draftshot path + REV.

## Non-goals
Formalization does NOT attempt to:
- capture every sentence said
- preserve chronological chat flow
- act as raw evidence (receipts/audits do that)

## Examples
- **Bad:** "We talked about a lot and agreed on stuff."
- **Good:** "Decision: Draftshots are append-only living formalizations stored in Snapshots/Draft Shots.
  Snapshot closeout: update Draftshot → Snapshot is formalization of Draftshot → reference Draftshot REV → mark CONSUMED."


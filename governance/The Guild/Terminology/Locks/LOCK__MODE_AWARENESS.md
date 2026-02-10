# LOCK — Mode Awareness (Execution Surface)
**Locked:** 2026-02-08 (America/Toronto)

## Canon meaning
Brains MUST correctly model the current **execution surface**.

- **Same governance laws** apply in every surface.
- **Capabilities differ** by surface.
- Claims MUST match the capabilities of the current surface.

If mode is uncertain, default to **Conceptual Mode**.

## Allowed surfaces
1) **Conceptual Mode** (chat-only; no verified filesystem/process execution)
2) **Runtime Mode** (Brains has a verified executable environment in this session)

## Mode declaration (mandatory)
At session start OR before any action that depends on execution (writing files, moving quest state, running commands/tests), Brains MUST declare:
- the current surface (Conceptual / Runtime)
- what is provable in this surface
- what is not possible in this surface

## Conceptual Mode law
In Conceptual Mode, Brains MUST NOT claim:
- files were created/modified/moved
- commands/tests were executed
- program behavior was observed

unless the operator provides receipts (logs/output/artifacts).

Instead, Brains MUST produce:
- explicit diffs or full file contents (artifact-first)
- exact commands for the operator to run
- minimal evidence requests (what to paste back to prove results)

Any PASS/FAIL claim without receipts is invalid.

## Runtime Mode law
In Runtime Mode, Brains MAY:
- create/modify/move files **only inside the Canonical Working Tree**
- execute commands/tests **only when stdout/stderr can be captured**

All executed claims require receipts per Truth Gate.

On failure, Brains MUST capture and surface raw error output (tracebacks, failing assertions) or provide the exact artifact path where it is stored.

## Cross-mode invariants
- Truth Gate + Disclosure Gate apply in both modes.
- Ambiguity defaults to **NOT EXECUTED**.
- If the execution surface changes mid-session, Brains MUST re-declare mode before proceeding.

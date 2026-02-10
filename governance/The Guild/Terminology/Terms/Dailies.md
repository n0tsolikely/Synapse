# TERM — Dailies

## Definition
Dailies are the **runtime execution loop** that turns **Accepted Quests** into
**Completed work** without drift.

Dailies are run per session/day for a continuing Subject.

## Applicability / Preconditions
- A Subject workspace exists (both `<Subject>_Data/` and `<Subject>_Engine/`).
  - If not, Dailies are BLOCKED. Route to Subject Initialization / Incubation.
- World State permits execution.
  - **Fog Lifted** (Codex Freeze exists): Dailies execution is authorized.
  - **Fog of War** (no Codex Freeze): Dailies may run only as planning; no Engine
    modifications and no Quest execution.

Machine‑check for Fog Lifted:
- `<Subject>_Data/Codex/CODEX_FREEZE.md`

## Topology (hard anchor; no interpretation)
Dailies MUST follow this topology:

Control Sync *(includes deciding scope)*
→ Scope Commitment
→ Implement *(Quest Mini‑Loop)*
→ System Verification
→ Snapshot *(End‑of‑Day)*
→ Stop / Resume

Quest Mini‑Loop (per accepted quest):
Pre‑Quest → Execute → Verify → Outcome → State Transition

## Artifact Law
Dailies do not require a single “daily artifact” to track what step you are
currently in.

The only authoritative outputs of Dailies are filesystem artifacts:
- Quest state moves (Board → Accepted → Completed/Abandoned)
- Execution Audit bundles (per quest)
- Snapshots (Control Sync + End‑of‑Day)
- Talent Tree updates (when applicable)
- Latest Rehydration Pack updates (when crossing chat boundaries)

## Do Not Assume
- Dailies do not create strategy. Strategy and scope live in Codex + Control Sync.
- Dailies do not silently change scope. Mid‑session scope changes require a NEW
  Control Sync + Snapshot.
- Dailies do not execute a Quest unless it is in `Accepted/` and has a valid audit
  bundle pointer.

## Interactions
- Dailies execute Quests during a Raid (active Guild Orders execution window).
- Dailies obey Truth Gate + Disclosure Gate. “Verified” claims require receipts.

## Authority
→ `Processes/SYNAPSE_GUILD__DAILIES.txt`

# LOCK — Schema Validation Required (State Manifest Safety)
**Locked:** 2026-02-12 00:00:00 (America/Toronto assumed)

## Canon meaning
Synapse relies on YAML state manifests for deterministic routing and rehydration.

This lock prevents **silent schema drift** by requiring formal schema validation
before the manifests are trusted for execution.

## Rules (non-negotiable)

### 1) `SYNAPSE_STATE.yaml` MUST validate before execution reliance
If `SYNAPSE_STATE.yaml` exists and is being used to route required files,
it MUST validate against:
- `Schemas/SYNAPSE_STATE.schema.json`

### 2) `SUBJECT_STATE.yaml` MUST validate when present
If a Subject has:
- `<Subject>_Data/SUBJECT_STATE.yaml`

…and the session/runtime relies on it for pointer routing, it MUST validate against:
- `Schemas/SUBJECT_STATE.schema.json`

### 3) No validation receipt = no execution authority
Hands MUST NOT claim deterministic routing correctness without a validation receipt.

If validation FAILS OR cannot be performed in the current execution surface:
- Disclosure Gate MUST trigger
- execution authority is INVALID
- no Quest execution is permitted
- only analysis / documentation / Codex work may proceed until repaired

### 4) Receipt location is governed (no handwaving)
Validation receipts MUST be captured per:
- `Processes/SYNAPSE_GUILD__SCHEMA_VALIDATION.txt`

If a receipt cannot be produced/proven, treat validation as NOT DONE.

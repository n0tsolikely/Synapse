# Synapse OS — Schema Contracts
**Version:** v1.0  
**Last Updated:** 2026-02-12  
**Status:** Governance Support Artifact (Referenced by Lock + Process)

## Purpose
This folder contains **formal schema contracts** for Synapse OS state manifests.

These contracts exist to prevent **silent schema drift** in:
- `SYNAPSE_STATE.yaml` (governance routing + rehydration resolver)
- `<Subject>_Data/SUBJECT_STATE.yaml` (subject-local pointer registry)

## Authority
- The requirement to validate schemas is enforced by:
  - `Processes/SYNAPSE_GUILD__SCHEMA_VALIDATION.txt`
  - `The Guild/Terminology/Locks/LOCK__SCHEMA_VALIDATION_REQUIRED.md`

## Notes
- Schemas are expressed as **JSON Schema (Draft 2020-12)**.
- YAML manifests are validated by parsing YAML → JSON, then validating against the schema.
- These schemas are intentionally permissive (`additionalProperties: true`) to allow evolution,
  while still enforcing the minimum required contract.

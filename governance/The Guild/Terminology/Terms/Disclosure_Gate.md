# TERM — Disclosure Gate (Mandatory Disclosure)

## Definition
Disclosure Gate is the mandatory operator notification required when Truth Gate prevents, invalidates,
or introduces uncertainty that changes the next safe action.

It is event-driven and must occur **before** proceeding.

## Purpose
Prevent silent failure, hidden drift, and “discover truth later.”

## Trigger Events (non-exhaustive)
- expected artifact/path missing
- canonical directory cannot be proven
- environment invalidated/wiped after prior actions
- execution/verification cannot be proven
- continuity uncertainty that affects resume or scope

## Required Disclosure Contents
A disclosure MUST include:
- what was expected vs what is provable
- what is now BLOCKED/UNVERIFIED and why
- impact on continuity/next steps
- safe options (halt, rehydrate, re-run, re-extract, etc.)

## Do Not Assume
- do not spam “all good” messages
- do not log silently without telling Brains
- do not guess to fill gaps
- do not proceed as if nothing happened

## Interactions
- Disclosure Gate is triggered by Truth Gate interventions.
- Disclosure events are referenced in Execution Audits and Snapshots when they affect work state.

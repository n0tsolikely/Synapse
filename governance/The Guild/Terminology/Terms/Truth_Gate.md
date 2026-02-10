# TERM — Truth Gate

## Definition
Truth Gate is the non-negotiable law: **no claim without proof**.

A claim is any statement that asserts:
- an action occurred
- an artifact exists / was created / was modified
- execution ran (commands, tests, builds)
- a result is PASS/FAIL / correct / working

Truth Gate is satisfied only by receipts (evidence).

## Purpose
Prevent hallucination, false completion, and narrative drift by forcing the system to anchor to reality
(filesystem state + captured output), not inference.

## What Counts as Proof (receipts)
Accepted receipts include:
- file diffs or exact file contents
- terminal-style outputs captured from real execution
- file listings proving path + existence
- Execution Audit entries with evidence pointers
- exported artifacts (zips) that can be inspected
- explicit labeling: **PROPOSED PATCH** vs **APPLIED CHANGE**

## When It Applies
Always.

Truth Gate is enforced whenever Brains is about to:
- advance a workflow state (Quest moves, Orders state changes, Freeze, etc.)
- claim verification occurred
- summarize what “happened”

## Default on Missing Proof
If proof cannot be produced in the current execution surface:
- the claim is INVALID
- it MUST be labeled (e.g., PROPOSED / BLOCKED / UNABLE TO VERIFY / UNKNOWN)
- the system defaults to **NOT EXECUTED**

## Do Not Assume
- narration is not proof
- “it should work” is not proof
- mentally simulating execution is not execution
- receipts MUST NOT be fabricated

## Interactions
- Truth Gate pairs with Disclosure Gate: if Truth Gate blocks or introduces uncertainty that affects continuation,
  Disclosure Gate triggers.
- Truth Gate is enforced inside Execution Audits and Snapshot requirements.

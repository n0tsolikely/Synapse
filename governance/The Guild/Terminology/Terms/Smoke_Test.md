# TERM — Smoke Test

## Definition
A **Smoke Test** is a minimal, fast, deterministic check that the system (or a Door) is not obviously broken.

A Smoke Test answers:
- “Does it boot?”
- “Does the entrypoint respond?”
- “Does the happy-path flow produce expected artifacts/outputs?”

It does **not** attempt to prove deep correctness.

## Purpose
To catch wiring/entrypoint breakage early (imports, configs, routing, subprocess/env issues) even when unit tests pass.

## Properties (recommended)
- fast (seconds to a minute)
- deterministic (no randomness)
- offline by default (no network egress)
- minimal fixtures

## Do Not Assume
- Smoke tests are not a replacement for integration/e2e suites.
- “Smoke passed” does not mean “no bugs.”

## Interactions
- Smoke tests are the default verification for **Doors**.
- Smoke tests should be runnable without secrets/tokens when possible.

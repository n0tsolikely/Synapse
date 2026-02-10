# TERM — Door

## Definition
A Door is an external entrypoint into a Subject: a boundary where outside input enters and causes the system to act.

Doors are interfaces. They are not “the system”; they are ways *into* the system.

Common software Doors:
- CLI commands
- Web/API routes (FastAPI, etc.)
- Web app entrypoints
- Chat/Bot handlers (Telegram, Slack, Discord)
- Schedulers/cron jobs
- Library APIs consumed by other code

## Purpose
- Make “system works” verifiable: each Door should be smoke-testable.
- Prevent the illusion that unit tests imply the app starts or the entrypoint works.
- Force clarity about what is an interface boundary vs internal implementation.

## When It Applies
- Any time the Subject has one or more external entrypoints.
- Any time a Quest adds/changes/removes an entrypoint.

## Do Not Assume
- A Door being present does not mean it is wired correctly.
- A Door being tested does not imply the entire system is correct; it only proves the Door boots and can execute a representative flow.

## Interactions
- Doors are a key input to the Verification Ladder / Testing Protocol (smoke coverage per Door).
- Layer responsibilities: Door code should orchestrate, not contain domain execution.

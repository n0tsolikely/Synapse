# Synapse + OpenClaw

OpenClaw users can keep their own workspace persona and identity files.

That means:

- keep `SOUL.md`
- keep `USER.md`
- keep `IDENTITY.md`
- keep runtime-specific tool semantics

Synapse should be added as a governance overlay or skill, not as a replacement personality.

When operating inside a Synapse repo:

- load repo `AGENTS.md`
- load repo `EXECUTOR.md`
- resolve subject with `python3 runtime/synapse.py engage --shell` or `resolve-subject --shell`
- run `doctor`
- use Synapse tools for governed operations

Governed operations include:

- snapshots
- consent
- quest execution
- audit validation
- codex gate

If subject is unresolved, stop cleanly and ask the human to continue, switch, or create a subject.

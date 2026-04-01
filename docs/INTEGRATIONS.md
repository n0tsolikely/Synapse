# Synapse Integrations

Synapse is agent-agnostic governance.

It sits on top of existing agents and runtimes.
It preserves existing persona systems by default.

Synapse enforces:

- continuity
- subject focus
- receipts
- wrappers
- audits
- drift

When Synapse defines a canonical governed operation, use the Synapse tool or wrapper.

This includes:

- subject resolution / focus
- doctor
- snapshots
- consent recording
- quest execution
- audit validation
- codex gating

Runtime-specific notes:

- [Codex](./integrations/codex.md)
- [Claude Code](./integrations/claude-code.md)
- [OpenClaw](./integrations/openclaw.md)

Phase 0 integration truth:

- raw boundary capture scaffolds exist under subject `.synapse/RAW/`
- optional repo-local `.codex` integration can be installed or refreshed explicitly
- local integration is honest about posture:
  - `hooked` when the optional assets are installed and healthy
  - `degraded` when those assets are absent, partial, or stale
- degraded posture is supported; it is not a fake failure mode, and it must not be described as full hook mediation

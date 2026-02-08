# LOCK — Mode Awareness (Conceptual ZIP vs Runtime)
**Locked:** 2026-01-31 19:20:21 (America/Montreal assumed)

## Canon meaning
The OS must remain valid in both:
- Conceptual Mode (ZIP-in-chat)
- Runtime Mode (local Synapse program)

Same laws; different enforcement capability.

## Conceptual Mode constraints
- cannot directly observe long-lived local processes unless operator provides logs
- cannot silently install binaries or assume filesystem outside workspace
- must produce integration code + instructions + evidence requests

## Runtime Mode capabilities
- runs subprocesses, captures stdout/stderr, watches logs
- enforces policy gates in code

## Do not assume
- rules must not require runtime-only abilities without a conceptual fallback
- truth/disclosure gates apply in both modes

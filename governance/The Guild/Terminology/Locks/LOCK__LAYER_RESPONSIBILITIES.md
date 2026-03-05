# LOCK — Layer Responsibilities (No Router Execution)
**Locked:** 2026-02-08 00:00:00 (America/Toronto assumed)

## Canon meaning
Complex systems stay maintainable when responsibilities are separated by layer.

This lock prevents:
- business logic hidden inside routers/handlers
- normalization mixed into execution
- IO and policy leaking across boundaries
- accidental God artifacts

## Layers (canonical)
### Door / Interface layer
Examples:
- FastAPI routes / web handlers
- CLI commands
- Telegram/Discord bot handlers
- UI event handlers

Responsibilities:
- parse input
- validate input
- call orchestrator/service
- return output

Door/Interface code MUST be thin.

### Orchestration / Service layer
Responsibilities:
- coordinate domain steps
- call adapters
- enforce workflow ordering
- translate domain results into interface-ready outputs

### Domain layer
Responsibilities:
- core rules, invariants, and behaviors
- pure decision logic

Domain code SHOULD be as IO-free as practical.

### Adapter / Boundary layer
Examples:
- filesystem, database, HTTP clients
- external vendors/APIs

Responsibilities:
- perform IO
- translate external formats to internal contracts

### Normalization / Transformation layer
Responsibilities:
- cleaning, parsing, normalization
- deterministic transforms

Normalization MUST be callable as a standalone unit (testable in isolation).

## Rules (non-negotiable)
### 1) No router execution
Door/Interface layer MUST NOT contain business logic or multi-step workflows.
It may only validate/orchestrate by calling services.

### 2) No hidden normalization
Normalization MUST NOT be embedded inside routers/handlers "for convenience".
Normalization belongs in a dedicated module/layer callable by services.

### 3) IO stays behind adapters
Services/domains MUST NOT embed direct vendor calls or raw IO details.
Those belong in adapters.

### 4) Exceptions (tiny glue only)
Small glue code is allowed in interfaces (e.g., mapping a request model to a service call),
so long as it does not implement domain behavior.

## Enforcement
Violations are treated as architectural drift.
If drift is detected:
- fix in-scope if small + safe, OR
- create a dedicated refactor Quest, OR
- escalate to Brains if redesign is implied.

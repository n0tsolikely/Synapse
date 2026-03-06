# Security Policy

Synapse is an active public project. Responsible security reporting is appreciated.

If you believe you have found a real security vulnerability, please do not open a public issue first. Report it privately so there is time to assess it and reduce the chance of unsafe disclosure.

## How to report a vulnerability

Send security reports to:

- notsolikelynotsolikely@gmail.com

Please do not post exploit details in a public GitHub issue before the issue has been reviewed.

## What to include in a report

The more concrete the report, the faster it can be assessed. Include what you can:
- what you found
- affected files, components, or commands
- reproduction steps, if available
- expected behavior vs actual behavior
- impact
- proof-of-concept, if it is safe to share
- environment or context that matters

If you are unsure whether something is exploitable, it is still worth reporting clearly.

## What counts as a security issue here

Examples of relevant issues for Synapse include:
- vulnerabilities in runtime tools or wrappers
- command injection or unsafe execution paths
- path traversal or unsafe file handling
- secrets or token handling issues
- consent-gate or governance-gate bypasses that create unsafe execution behavior
- anything that could cause unsafe or unintended privileged behavior

Not every bug is a security issue, but if it creates a realistic safety, trust, or execution-boundary problem, report it.

## What not to send publicly first

Please avoid publishing exploit details, payloads, or step-by-step abuse paths in a public issue before there has been a chance to review the report.

Public bug reports are still useful for non-sensitive issues. Security-sensitive details should come through private reporting first.

## Response expectations

Reports will be reviewed as quickly as possible.

This is an active project with a best-effort maintainer response model, not an enterprise security desk. Severity, clarity, and reproduction quality will affect turnaround.

If a report is actionable and well-supported, it is much easier to assess and fix quickly.

## Scope and project maturity

Synapse is still evolving. Responsible disclosure helps harden the project while the runtime, wrappers, and governance surfaces continue to mature.

That is part of building this in public: problems can be found earlier, fixed earlier, and documented more clearly.

## Thanks

Good-faith security reports are appreciated.
They help make the project safer for everyone using it, testing it, or building on top of it.

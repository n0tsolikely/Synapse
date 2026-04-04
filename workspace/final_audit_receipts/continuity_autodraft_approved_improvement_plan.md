# Continuity Autodraft Final Audit — Approved Improvement Plan

Approved fix:
1. Update the onboarding regression to assert the thing that actually matters:
   - `session-start` produced a current story candidate
   - explicit refresh may be `written` or lawful `noop`
   - `formalize --candidate-handle story` still publishes through the onboarding owner

Rejected as unnecessary or architecture-drifting:
- changing publication-candidate model precedence to force candidate rewrites
- weakening session-start auto-refresh behavior
- bypassing current canonical publication owners

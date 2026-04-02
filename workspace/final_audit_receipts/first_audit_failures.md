# First Whole-System Audit Failures

Branch: codex/engaged-kernel-final-audit
Baseline merge SHA: b934deffc9a649e21170d6d663a999a0a5043c97
First validation-matrix result: 10 pass / 4 fail

Failed scenarios:
- `architecture_pivot`
  - no supersession lineage edge recorded for the architecture pivot
  - no review-required artifact was opened when authoritative architecture meaning shifted
- `blocker_disclosure_case`
  - no obligation or disclosure artifact surfaced for unsafe blocker language
- `quest_lifecycle_regression`
  - accept-quest failed because the audit runner drafted a quest without required codex anchors / constraint summary
- `truth_compile_regression`
  - audit runner checked an obsolete top-level `CURRENT_STATE.md` path and a nonexistent top-level `compile_status` field instead of current runtime payload truth

Classification:
- real runtime gaps: `architecture_pivot`, `blocker_disclosure_case`
- audit-harness gaps: `quest_lifecycle_regression`, `truth_compile_regression`

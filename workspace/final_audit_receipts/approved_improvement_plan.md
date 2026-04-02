# Approved Improvement Plan

1. Patch `runtime/synapse_runtime/promotion_engine.py`
- add architecture-pivot detection cues
- record supersession lineage from prior architecture record to replacement record
- open `architecture.review.required` obligation on pivot-like architecture meaning shifts
- open `disclosure.review.required` obligation for unsafe blocker language
- Receipt: new promotion-engine tests plus passing validation-matrix scenarios

2. Extend `tests/test_promotion_engine.py`
- cover architecture pivot supersession + review obligation
- cover unsafe blocker disclosure-review obligation
- Receipt: targeted unit suite passes

3. Patch `workspace/final_audit_receipts/run_final_audit.py`
- make `quest_lifecycle_regression` use lawful anchors/constraint summary
- make `truth_compile_regression` validate the current runtime publication path and operation-status field
- Receipt: post-improvement validation matrix passes 14/14

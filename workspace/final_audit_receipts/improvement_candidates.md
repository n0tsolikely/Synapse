# Improvement Candidates

1. Architecture pivot supersession + review obligation
- Category: correctness
- Files: `runtime/synapse_runtime/promotion_engine.py`, `tests/test_promotion_engine.py`
- Benefit: prevents silent overwrite of prior architecture meaning during engaged semantic promotion.
- Screen result: APPROVED

2. Unsafe blocker disclosure-review obligation
- Category: safety
- Files: `runtime/synapse_runtime/promotion_engine.py`, `tests/test_promotion_engine.py`
- Benefit: surfaces disclosure-worthy unsafe blocker language as durable review-required continuity instead of leaving it as only a failure chain.
- Screen result: APPROVED

3. Quest lifecycle scenario legality fix in final audit harness
- Category: clarity
- Files: `workspace/final_audit_receipts/run_final_audit.py`
- Benefit: exercises existing BOARD -> ACCEPTED -> COMPLETED law with lawful quest inputs instead of relying on an invalid acceptance attempt.
- Screen result: APPROVED

4. Truth compile scenario payload/path fix in final audit harness
- Category: correctness
- Files: `workspace/final_audit_receipts/run_final_audit.py`
- Benefit: validates current runtime publication paths and payload shape instead of obsolete assumptions.
- Screen result: APPROVED

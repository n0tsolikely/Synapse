# Post-Improvement Test Summary

1. `python3 -m py_compile runtime/synapse_runtime/promotion_engine.py tests/test_promotion_engine.py workspace/final_audit_receipts/run_final_audit.py`
- PASS

2. `python3 -m unittest tests.test_promotion_engine -v`
- Ran 4 tests in 0.116s
- OK

3. `python3 workspace/final_audit_receipts/run_final_audit.py`
- Validation matrix: 14 pass / 0 fail
- PASS

4. `python3 -m unittest tests.test_engage_subject_selection tests.test_phase0_runtime_hardening tests.test_event_spine tests.test_live_memory tests.test_raw_ingest tests.test_hook_entrypoints tests.test_subject_repo_codex_integration tests.test_automation_orchestration tests.test_semantic_intake tests.test_rehydration_lifecycle tests.test_conversation_segmentation tests.test_semantic_classifier tests.test_imported_continuity tests.test_quest_detection tests.test_quest_acceptance tests.test_quest_runtime_refactor tests.test_repo_onboarding tests.test_truth_compiler tests.test_build_plan_persistence tests.test_promotion_engine tests.test_lineage_store tests.test_continuity_obligations tests.test_codex_packets tests.test_synthesis_refresh tests.test_provenance tests.test_missed_capture_detection tests.test_close_turn_validation tests.test_degraded_mode_enforcement tests.test_governance_guard_wrapper_proof -q`
- Ran 232 tests in 168.293s
- OK

5. `/home/notsolikely/commercial_filmcrew/.venv/bin/python -m unittest tests.test_mcp_integration tests.test_current_context_projection -q`
- Ran 22 tests in 39.189s
- OK

6. `python3 runtime/synapse.py doctor --governance-root governance --no-subject`
- Overall Status: PASS

7. `git diff --check`
- PASS

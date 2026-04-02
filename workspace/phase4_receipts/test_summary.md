# Phase 4 test summary

- `python3 -m py_compile runtime/synapse.py runtime/synapse_runtime/repo_state.py runtime/synapse_runtime/provenance.py runtime/synapse_runtime/doctor.py runtime/synapse_runtime/sidecar_store.py runtime/synapse_runtime/sidecar_projection.py runtime/synapse_runtime/rehydrate_renderer.py runtime/synapse_mcp/runtime_bridge.py runtime/tools/synapse_hook_user_prompt_submit.py runtime/tools/synapse_hook_pre_tool.py runtime/tools/synapse_hook_post_tool.py runtime/tools/synapse_hook_stop.py tests/test_close_turn_validation.py tests/test_degraded_mode_enforcement.py tests/test_missed_capture_detection.py tests/test_provenance.py tests/test_event_spine.py tests/test_mcp_integration.py`
  - PASS
- `python3 -m unittest tests.test_close_turn_validation tests.test_degraded_mode_enforcement tests.test_missed_capture_detection tests.test_provenance tests.test_hook_entrypoints tests.test_subject_repo_codex_integration -v`
  - `Ran 26 tests in 18.553s`
  - `OK`
- `/home/notsolikely/commercial_filmcrew/.venv/bin/python -m unittest tests.test_mcp_integration tests.test_current_context_projection -q`
  - `Ran 22 tests in 32.135s`
  - `OK`
- `python3 -m unittest tests.test_engage_subject_selection tests.test_phase0_runtime_hardening tests.test_event_spine tests.test_live_memory tests.test_raw_ingest tests.test_hook_entrypoints tests.test_subject_repo_codex_integration tests.test_automation_orchestration tests.test_semantic_intake tests.test_rehydration_lifecycle tests.test_conversation_segmentation tests.test_semantic_classifier tests.test_imported_continuity tests.test_quest_detection tests.test_quest_acceptance tests.test_quest_runtime_refactor tests.test_repo_onboarding tests.test_truth_compiler tests.test_build_plan_persistence tests.test_promotion_engine tests.test_lineage_store tests.test_continuity_obligations tests.test_codex_packets tests.test_synthesis_refresh tests.test_provenance tests.test_missed_capture_detection tests.test_close_turn_validation tests.test_degraded_mode_enforcement tests.test_governance_guard_wrapper_proof -q`
  - `Ran 230 tests in 146.721s`
  - `OK`
- `python3 runtime/synapse.py doctor --governance-root governance --no-subject`
  - `Overall Status: PASS`
- `git diff --check`
  - PASS

# Continuity Autodraft Final Audit — First Failure

Saved governing artifact:
- `/home/notsolikely/Synapse/workspace/06_CONTINUITY_AUTODRAFT_AND_PUBLICATION_BUILD_SPEC__SOURCE_VERBATIM.md`

Failure found during whole-wave regression sweep:
- `tests.test_repo_onboarding.RepoOnboardingCommandTests.test_formalize_candidate_handle_publishes_story_candidate_via_repo_onboarding_owner`

Root cause:
- The test still assumed `refresh_publication_candidates()` must return `written` after `session-start`.
- Current repo truth now auto-refreshes publication candidates at `session-start`, so the explicit refresh can lawfully return `noop` with an unchanged source signature while still leaving a current story candidate available for `formalize`.

Classification:
- stale test assumption
- not a canonical-owner regression
- not a continuity drafting runtime failure

import unittest

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.governance_model import ProposalKind
from synapse_runtime.session_modes import (
    SESSION_MODE_POLICY_VERSION,
    SessionMode,
    backfill_mode_from_active_run,
    default_mode_for_command,
    policy_for,
    policy_summary,
    session_mode_signal_fields,
    validate_transition,
)


class SessionModePolicyTests(unittest.TestCase):
    def test_canonical_registry_contains_all_six_modes(self) -> None:
        expected = {
            "onboarding_existing_repo",
            "brainstorm_spec",
            "control_sync",
            "scope_planning",
            "execution",
            "closeout",
        }
        self.assertEqual({mode.value for mode in SessionMode}, expected)

    def test_each_policy_exposes_required_fields(self) -> None:
        for mode in SessionMode:
            policy = policy_for(mode)
            summary = policy_summary(mode)
            self.assertEqual(policy.mode, mode)
            self.assertTrue(policy.description)
            self.assertIsInstance(policy.allowed_proposal_kinds, tuple)
            self.assertIn("description", summary)
            self.assertIn("blocked_mutation_commands", summary)
            self.assertIn("allowed_next_modes", summary)
            self.assertIn("auto_formalize_ready_quests", summary)
            self.assertIn("manual_formalize_allowed", summary)
            self.assertIn("quest_acceptance_allowed", summary)
            self.assertIn("allowed_proposal_kinds", summary)

    def test_default_mode_resolution_is_deterministic(self) -> None:
        self.assertEqual(default_mode_for_command("session-start"), SessionMode.BRAINSTORM_SPEC)
        self.assertEqual(default_mode_for_command("session-tick"), SessionMode.BRAINSTORM_SPEC)
        self.assertEqual(default_mode_for_command("run-start"), SessionMode.EXECUTION)

    def test_execution_policy_allows_talent_and_closeout_blocks_quest_like_outputs(self) -> None:
        self.assertIn(ProposalKind.TALENT, policy_for(SessionMode.EXECUTION).allowed_proposal_kinds)
        closeout_kinds = set(policy_for(SessionMode.CLOSEOUT).allowed_proposal_kinds)
        self.assertNotIn(ProposalKind.QUEST, closeout_kinds)
        self.assertNotIn(ProposalKind.SIDE_QUEST, closeout_kinds)
        self.assertNotIn(ProposalKind.GUILD_ORDERS, closeout_kinds)

    def test_transition_validation_matches_graph(self) -> None:
        allowed, next_modes = validate_transition(SessionMode.BRAINSTORM_SPEC, SessionMode.SCOPE_PLANNING)
        self.assertTrue(allowed)
        self.assertIn(SessionMode.SCOPE_PLANNING, next_modes)

        blocked, next_modes = validate_transition(SessionMode.BRAINSTORM_SPEC, SessionMode.EXECUTION)
        self.assertFalse(blocked)
        self.assertNotIn(SessionMode.EXECUTION, next_modes)

        blocked, next_modes = validate_transition(SessionMode.CLOSEOUT, SessionMode.EXECUTION)
        self.assertFalse(blocked)
        self.assertNotIn(SessionMode.EXECUTION, next_modes)

    def test_backfill_maps_decision_to_control_sync(self) -> None:
        run_data, changed = backfill_mode_from_active_run({"interaction_mode": "decision"}, "2026-03-16T12:00:00-04:00")
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.CONTROL_SYNC.value)
        self.assertEqual(run_data["session_mode_source"], "legacy_backfill")
        self.assertEqual(run_data["session_mode_policy_version"], SESSION_MODE_POLICY_VERSION)

    def test_backfill_maps_missing_or_maintenance_to_brainstorm_spec(self) -> None:
        run_data, changed = backfill_mode_from_active_run({"interaction_mode": "maintenance"}, "2026-03-16T12:00:00-04:00")
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

        run_data, changed = backfill_mode_from_active_run({}, "2026-03-16T12:00:00-04:00")
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

    def test_backfill_is_noop_when_session_mode_already_exists(self) -> None:
        run_data = {
            "session_mode": SessionMode.EXECUTION.value,
            "session_mode_source": "explicit",
            "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
        }
        normalized, changed = backfill_mode_from_active_run(run_data, "2026-03-16T12:00:00-04:00")
        self.assertFalse(changed)
        self.assertEqual(normalized, run_data)

    def test_signal_fields_return_only_posture_context(self) -> None:
        self.assertEqual(session_mode_signal_fields(None), {})
        self.assertEqual(session_mode_signal_fields({}), {})
        self.assertEqual(
            session_mode_signal_fields(
                {
                    "session_mode": SessionMode.SCOPE_PLANNING.value,
                    "session_mode_source": "explicit",
                    "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
                    "session_mode_reason": "ignored here",
                }
            ),
            {
                "session_mode": "scope_planning",
                "session_mode_source": "explicit",
                "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
            },
        )


if __name__ == "__main__":
    unittest.main()

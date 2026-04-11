import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.snapshot_candidates import CONTROL_SYNC_KIND, EOD_KIND
from synapse_runtime.snapshot_checkpoint_policy import (
    GENERAL_KIND,
    MULTI_KIND,
    evaluate_snapshot_checkpoint,
    materialize_snapshot_checkpoint_decision,
)


class SnapshotCheckpointPolicyTests(unittest.TestCase):
    def test_session_start_rollover_targets_prior_day_eod(self) -> None:
        decision = evaluate_snapshot_checkpoint(
            boundary="session-start",
            requested_candidate_kinds=[],
            target_day_hint=None,
            current_summary={"stale_prior_day_candidate_required": True},
            draftshot={"refreshed_at": "2026-04-03T23:45:00-04:00"},
            session_anchor_present=True,
        )
        self.assertEqual(decision.snapshot_kind, EOD_KIND)
        self.assertEqual(decision.target_day, "2026-04-03")
        self.assertEqual(decision.candidate_action, "refresh")
        self.assertEqual(decision.canonical_action, "defer")
        self.assertEqual(decision.draftshot_action, "preserve")
        self.assertEqual(decision.required_candidate_kinds, (EOD_KIND,))

    def test_passive_multikind_boundary_uses_multi_snapshot_kind(self) -> None:
        decision = evaluate_snapshot_checkpoint(
            boundary="close-turn",
            requested_candidate_kinds=[EOD_KIND, CONTROL_SYNC_KIND],
            target_day_hint=None,
            current_summary={},
            draftshot={"refreshed_at": "2026-04-10T10:15:00-04:00"},
            session_anchor_present=True,
        )
        self.assertEqual(decision.snapshot_kind, MULTI_KIND)
        self.assertEqual(decision.target_day, "2026-04-10")
        self.assertEqual(decision.candidate_action, "refresh")
        self.assertEqual(decision.required_candidate_kinds, (EOD_KIND, CONTROL_SYNC_KIND))

    def test_missing_anchor_blocks_passive_candidate_refresh(self) -> None:
        decision = evaluate_snapshot_checkpoint(
            boundary="close-turn",
            requested_candidate_kinds=[EOD_KIND],
            target_day_hint=None,
            current_summary={},
            draftshot=None,
            session_anchor_present=False,
        )
        self.assertEqual(decision.blocked_reason, "missing_session_anchor")
        self.assertEqual(decision.candidate_action, "skip")
        self.assertEqual(decision.draftshot_action, "blocked")

    def test_explicit_general_canonical_write_maps_writer_command(self) -> None:
        decision = evaluate_snapshot_checkpoint(
            boundary="explicit-snapshot-write",
            requested_candidate_kinds=[],
            target_day_hint="2026-04-10",
            current_summary={},
            draftshot=None,
            session_anchor_present=False,
            decision_mode="explicit_canonical",
            requested_snapshot_kind=GENERAL_KIND,
        )
        self.assertEqual(decision.snapshot_kind, GENERAL_KIND)
        self.assertEqual(decision.canonical_action, "write")
        self.assertEqual(decision.writer_command, "general")
        self.assertEqual(decision.candidate_action, "skip")
        self.assertEqual(decision.draftshot_action, "not_required")

    def test_materialize_unchanged_candidate_refresh_as_reuse(self) -> None:
        decision = evaluate_snapshot_checkpoint(
            boundary="close-turn",
            requested_candidate_kinds=[EOD_KIND],
            target_day_hint="2026-04-10",
            current_summary={},
            draftshot={"refreshed_at": "2026-04-10T10:15:00-04:00"},
            session_anchor_present=True,
        )
        materialized = materialize_snapshot_checkpoint_decision(
            decision,
            snapshot_candidate_payload={
                "candidates": [{"candidate_kind": EOD_KIND, "status": "noop", "reason": "unchanged_source_signature"}],
            },
            target_day="2026-04-10",
        )
        self.assertEqual(materialized["candidate_action"], "reuse")
        self.assertEqual(materialized["target_day"], "2026-04-10")
        self.assertEqual(materialized["draftshot_action"], "preserve")


if __name__ == "__main__":
    unittest.main()

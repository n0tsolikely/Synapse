import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_observer import (
    ContinuityObserverError,
    build_continuity_packet,
    observe_continuity,
)
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class ContinuityObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "ObserverSubject"
        self.engine_root = self.root / "engine"
        self.data_root = self.root / f"{self.subject}_Data"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_continuity_packet_is_bounded_and_fingerprinted(self) -> None:
        packet = build_continuity_packet(
            subject=self.subject,
            data_root=self.data_root,
            trigger="close-turn",
            summary="Validate the close-turn boundary.",
            notes=["risk: observer inputs must stay bounded"],
            changed_files=["runtime/synapse.py"],
            session_id="SID-1",
            run_id="RUN-1",
            boundary="strict",
            decision_boundary=True,
            uncertainty_present=True,
            source_refs=[{"kind": "raw_turn", "id": "RAW-1"}],
            accepted_context={"current_accepted_quest_id": "QUEST-1"},
            session_mode_fields={"session_mode": "scope_planning"},
        )
        self.assertEqual(packet["packet_schema_version"], 1)
        self.assertEqual(packet["subject"], self.subject)
        self.assertEqual(packet["trigger"], "close-turn")
        self.assertEqual(packet["boundary"], "strict")
        self.assertEqual(packet["session_id"], "SID-1")
        self.assertEqual(packet["run_id"], "RUN-1")
        self.assertEqual(packet["notes"], ["risk: observer inputs must stay bounded"])
        self.assertEqual(packet["changed_files"], ["runtime/synapse.py"])
        self.assertTrue(packet["decision_boundary"])
        self.assertTrue(packet["uncertainty_present"])
        self.assertEqual(packet["accepted_context"]["current_accepted_quest_id"], "QUEST-1")
        self.assertEqual(packet["session_mode_fields"]["session_mode"], "scope_planning")
        self.assertIn("draftshot_summary", packet)
        self.assertIn("snapshot_candidate_summary", packet)
        self.assertIn("publication_candidate_summary", packet)
        self.assertIn("obligation_summary", packet)
        self.assertEqual(len(packet["packet_fingerprint"]), 64)

    def test_observe_continuity_noop_backend_is_explicitly_degraded(self) -> None:
        with mock.patch.dict(os.environ, {"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "noop"}, clear=False):
            observed = observe_continuity(
                subject=self.subject,
                data_root=self.data_root,
                trigger="run-finalize",
                summary="Finalize the active run.",
            )
        self.assertEqual(observed["observer_status"], "degraded")
        self.assertEqual(observed["backend"], "noop")
        self.assertEqual(observed["provider_status"], "not_configured")
        self.assertTrue(observed["degraded"])
        self.assertEqual(observed["degraded_reason"], "observer_backend_not_configured")
        self.assertFalse(observed["observer_triggered"])
        self.assertEqual(observed["observer_action_kinds"], [])
        self.assertEqual(observed["observer_intents"], [])

    def test_observe_continuity_fixture_backend_normalizes_supported_intents(self) -> None:
        with mock.patch.dict(os.environ, {"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture"}, clear=False):
            observed = observe_continuity(
                subject=self.subject,
                data_root=self.data_root,
                trigger="session-tick",
                summary="Lock the observer seam.",
                notes=["Captured repo truth for the observer."],
                changed_files=["runtime/synapse.py"],
                session_id="SID-1",
                run_id="RUN-1",
                decision_boundary=True,
                uncertainty_present=True,
                source_refs=[{"kind": "semantic_event", "id": "SEMEVT-1"}],
            )
        self.assertEqual(observed["observer_status"], "ok")
        self.assertEqual(observed["backend"], "fixture")
        self.assertFalse(observed["degraded"])
        self.assertTrue(observed["observer_triggered"])
        self.assertEqual(
            observed["observer_action_kinds"],
            ["semantic_capture", "decision_log", "disclosure_log"],
        )
        self.assertEqual(observed["observer_context"]["session_id"], "SID-1")
        self.assertEqual(observed["observer_context"]["run_id"], "RUN-1")
        self.assertEqual(observed["observer_context"]["changed_files"], ["runtime/synapse.py"])
        self.assertEqual(len(observed["observer_intents"]), 3)
        self.assertEqual(observed["observer_intents"][0]["artifact_family"], "semantic_capture")
        self.assertEqual(observed["observer_intents"][1]["artifact_family"], "decision_log")
        self.assertEqual(observed["observer_intents"][2]["artifact_family"], "disclosure_log")

    def test_observe_continuity_rejects_unsupported_intents(self) -> None:
        fixture_json = (
            '{"observer_status":"ok","provider_status":"fixture","intents":'
            '[{"artifact_family":"publish_truth","rationale":"bad"}]}'
        )
        with mock.patch.dict(
            os.environ,
            {
                "SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture",
                "SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON": fixture_json,
            },
            clear=False,
        ):
            with self.assertRaises(ContinuityObserverError):
                observe_continuity(
                    subject=self.subject,
                    data_root=self.data_root,
                    trigger="close-turn",
                    summary="Should fail validation.",
                )


if __name__ == "__main__":
    unittest.main()

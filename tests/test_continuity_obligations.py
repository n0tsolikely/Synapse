import tempfile
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_obligations import load_obligations, obligation_summary, open_obligation, resolve_matching_obligations
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class ContinuityObligationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "ObligationSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_open_and_resolve_obligation(self) -> None:
        opened = open_obligation(
            subject=self.subject,
            data_root=self.data_root,
            recorded_at="2026-04-01T12:00:00-04:00",
            obligation_kind="plan.capture.required",
            severity="blocker",
            summary="Missing lawful persisted plan.",
            required_record_families=["SCOPE_CAMPAIGNS"],
            source_segment_ids=["SEG-1"],
            source_semantic_event_ids=["SEMEVT-1"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-1"}],
            metadata={"phase": "p2"},
        )
        self.assertTrue(Path(opened["path"]).exists())

        summary = obligation_summary(self.data_root)
        self.assertEqual(summary["open_count"], 1)
        self.assertEqual(summary["blocker_count"], 1)

        resolved = resolve_matching_obligations(
            data_root=self.data_root,
            recorded_at="2026-04-01T12:05:00-04:00",
            source_segment_ids=["SEG-1"],
            resolution_record_ids=["PLAN-1::REVISION-001"],
            obligation_kinds=["plan.capture.required"],
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["state"], "resolved")
        self.assertIn("PLAN-1::REVISION-001", resolved[0]["resolution_record_ids"])

        loaded = load_obligations(self.data_root)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["state"], "resolved")
        self.assertEqual(obligation_summary(self.data_root)["open_count"], 0)

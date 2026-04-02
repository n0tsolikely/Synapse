import tempfile
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.promotion_engine import load_working_records, promote_semantic_events, promotion_summary
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class PromotionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "PromotionSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str, *, segment_id: str = "SEG-1", imported_limited: bool = False) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase1",
            "recorded_at": "2026-04-01T12:00:00-04:00",
            "subject": self.subject,
            "class_label": topic_key,
            "topic_key": topic_key,
            "confidence_band": "high",
            "materiality_band": "high",
            "summary": summary,
            "transient_noise": False,
            "imported_limited": imported_limited,
            "source_segment_ids": [segment_id],
            "source_refs": [{"kind": "conversation_segment", "id": segment_id, "path": f"/tmp/{segment_id}.json"}],
            "related_paths": [],
        }

    def test_promotes_working_records_and_lineage(self) -> None:
        receipt = promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-DEC", "decision.locked", "We decided to use account-based auth."),
                self._event("SEMEVT-ARCH", "architecture.shape", "This installable web app will use a web app plus API layout."),
                self._event("SEMEVT-RISK", "risk.blocker", "Blocked on provider credentials."),
                self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system."),
            ],
        )
        families = {item["family"] for item in receipt["promoted_records"]}
        self.assertIn("DECISION_GRAPH", families)
        self.assertIn("ARCHITECTURE_EVOLUTION", families)
        self.assertIn("FAILURE_CHAINS", families)
        self.assertIn("NARRATIVE_CLAIMS", families)
        self.assertIn("PROJECT_IDENTITY_CLAIMS", families)
        self.assertGreaterEqual(len(receipt["lineage_edges"]), 4)
        self.assertEqual(receipt["opened_obligations"], [])

        summary = promotion_summary(self.data_root)
        self.assertGreaterEqual(summary["working_record_count"], 5)
        self.assertGreaterEqual(summary["lineage_edge_count"], 4)
        self.assertEqual(summary["open_count"], 0)

    def test_imported_limited_opens_review_obligation(self) -> None:
        receipt = promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event(
                    "SEMEVT-IMP",
                    "project.vision",
                    "Imported project notes mention an installable web app and investor story.",
                    imported_limited=True,
                )
            ],
        )
        self.assertEqual(len(receipt["promoted_records"]), 1)
        self.assertEqual(receipt["promoted_records"][0]["family"], "IMPORTED_EVIDENCE")
        self.assertEqual(len(receipt["opened_obligations"]), 1)
        self.assertEqual(receipt["opened_obligations"][0]["obligation_kind"], "import.review.required")

        records = load_working_records(self.data_root, "IMPORTED_EVIDENCE")
        self.assertEqual(len(records), 1)

    def test_architecture_pivot_records_supersession_and_review_obligation(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event(
                    "SEMEVT-ARCH-1",
                    "architecture.shape",
                    "We will build this as a local-only desktop app.",
                    segment_id="SEG-ARCH-1",
                )
            ],
        )

        receipt = promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event(
                    "SEMEVT-ARCH-2",
                    "architecture.shape",
                    "We are rejecting the desktop path. The plan is now an installable web app with separate user accounts.",
                    segment_id="SEG-ARCH-2",
                )
            ],
        )

        supersedes = [item for item in receipt["lineage_edges"] if item.get("relation") == "supersedes"]
        self.assertEqual(len(supersedes), 1)
        self.assertEqual(len(receipt["opened_obligations"]), 1)
        self.assertEqual(receipt["opened_obligations"][0]["obligation_kind"], "architecture.review.required")

    def test_unsafe_blocker_opens_disclosure_review_obligation(self) -> None:
        receipt = promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event(
                    "SEMEVT-RISK-UNSAFE",
                    "risk.blocker",
                    "We are blocked on provider credentials and it would be unsafe to claim the feature works.",
                    segment_id="SEG-RISK-UNSAFE",
                )
            ],
        )

        families = {item["family"] for item in receipt["promoted_records"]}
        self.assertIn("FAILURE_CHAINS", families)
        self.assertEqual(len(receipt["opened_obligations"]), 1)
        self.assertEqual(receipt["opened_obligations"][0]["obligation_kind"], "disclosure.review.required")

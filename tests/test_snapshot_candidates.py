import tempfile
from pathlib import Path
import sys
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.draftshots import refresh_draftshot
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.snapshot_candidates import refresh_snapshot_candidates, snapshot_candidate_summary
from synapse_runtime.subject_bootstrap import initialize_subject_state


class SnapshotCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "SnapshotCandidateSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase2",
            "recorded_at": "2026-04-04T12:00:00-04:00",
            "subject": self.subject,
            "class_label": topic_key,
            "topic_key": topic_key,
            "confidence_band": "high",
            "materiality_band": "high",
            "summary": summary,
            "transient_noise": False,
            "imported_limited": False,
            "source_segment_ids": [f"SEG-{semantic_event_id}"],
            "source_refs": [{"kind": "conversation_segment", "id": f"SEG-{semantic_event_id}", "path": f"/tmp/{semantic_event_id}.json"}],
            "related_paths": [],
        }

    def test_refresh_snapshot_candidates_writes_typed_families_and_projection(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE", "project.scope", "Scope the product around installable web workflows."),
                self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system."),
                self._event("SEMEVT-ARCH", "architecture.shape", "Use a web app plus API architecture."),
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Installable workflow foundation",
            summary="Plan the installable workflow foundation.",
            origin="test",
            objective="Support account-backed installable flows.",
            coherent_outcome="A persisted installable workflow foundation exists.",
            closure_statement="The installable workflow foundation is captured and testable.",
            out_of_scope="Payments.",
            dependencies=["Auth service"],
            risk="R1",
            verification_plan="Run installability and auth checks.",
            milestones=["Installable shell", "Signed-in workflow"],
            split_triggers=["Split when payments are introduced."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-snap-001",
            run_id="RUN-SNAP-001",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        first = refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-snap-001",
        )
        self.assertEqual(first["status"], "written")
        self.assertEqual({item["candidate_kind"] for item in first["candidates"]}, {"EOD", "CONTROL_SYNC"})
        for item in first["candidates"]:
            self.assertTrue(Path(item["manifest_path"]).exists())
            self.assertTrue(Path(item["body_path"]).exists())

        second = refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-snap-001",
        )
        self.assertEqual(second["status"], "noop")
        self.assertTrue(all(item["status"] == "noop" for item in second["candidates"]))

        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        summary = snapshot_candidate_summary(self.data_root)
        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))

        self.assertTrue(summary["current_eod_candidate_path"])
        self.assertTrue(summary["current_control_sync_candidate_path"])
        self.assertEqual(state["current_eod_candidate_path"], summary["current_eod_candidate_path"])
        self.assertEqual(manifold["current_control_sync_candidate_path"], summary["current_control_sync_candidate_path"])
        self.assertEqual(manifold["current_snapshot_candidate_path"], summary["current_snapshot_candidate_path"])
        self.assertIn("End Of Day Snapshot Candidate", Path(summary["current_eod_candidate_path"]).read_text(encoding="utf-8"))
        self.assertIn(
            "Control Sync Snapshot Candidate",
            Path(summary["current_control_sync_candidate_path"]).read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

import tempfile
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.compaction_policy import evaluate_compaction_candidate
from synapse_runtime.continuity_obligations import open_obligation
from synapse_runtime.draftshots import refresh_draftshot
from synapse_runtime.lineage_store import build_lineage_edge, persist_lineage_edge
from synapse_runtime.compaction_policy import refresh_superseded_revision_manifests
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.publication_candidates import refresh_publication_candidates
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.snapshot_candidates import refresh_snapshot_candidates
from synapse_runtime.subject_bootstrap import initialize_subject_state


class CompactionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name) / "CompactionSubject_Data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.subject = "CompactionSubject"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _artifact_path(self, name: str) -> Path:
        path = self.data_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n", encoding="utf-8")
        return path

    def _bootstrap_subject(self) -> Path:
        engine_root = self.data_root.parent / self.subject
        engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        return engine_root

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase-d",
            "recorded_at": "2026-04-09T10:00:00-04:00",
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

    def test_refuses_current_artifact(self) -> None:
        artifact_path = self._artifact_path(".synapse/DRAFTSHOT_INDEX/REVISIONS/current.yaml")
        decision = evaluate_compaction_candidate(
            data_root=self.data_root,
            artifact_family="draftshot_revision",
            artifact_id="DRAFTREV-CURRENT",
            artifact_path=str(artifact_path),
            is_current=True,
            stronger_successor_ids=["DRAFTREV-NEXT"],
        )
        self.assertFalse(decision["allowed_to_cool"])
        self.assertIn("current_artifact", decision["blockers"])

    def test_refuses_canonical_artifact(self) -> None:
        artifact_path = self._artifact_path("Truth/current_state.md")
        decision = evaluate_compaction_candidate(
            data_root=self.data_root,
            artifact_family="truth_publication",
            artifact_id="TRUTH-PUB-001",
            artifact_path=str(artifact_path),
            is_canonical=True,
            stronger_successor_ids=["TRUTH-PUB-002"],
        )
        self.assertFalse(decision["allowed_to_cool"])
        self.assertIn("canonical_artifact", decision["blockers"])

    def test_refuses_open_obligation_reference(self) -> None:
        artifact_path = self._artifact_path(".synapse/RAW/TURNS/TURN-001.json")
        source_ref = {"kind": "conversation_turn", "id": "TURN-001", "path": str(artifact_path)}
        open_obligation(
            subject=self.subject,
            data_root=self.data_root,
            recorded_at="2026-04-09T10:00:00-04:00",
            obligation_kind="continuity.review.required",
            severity="blocker",
            summary="Do not cool the only evidence until reviewed.",
            required_record_families=["semantic_capture"],
            source_segment_ids=["SEG-001"],
            source_semantic_event_ids=["SEMEVT-001"],
            source_refs=[source_ref],
        )
        decision = evaluate_compaction_candidate(
            data_root=self.data_root,
            artifact_family="raw_turn",
            artifact_id="TURN-001",
            artifact_path=str(artifact_path),
            source_refs=[source_ref],
            stronger_successor_ids=["CAPTURE-001"],
        )
        self.assertFalse(decision["allowed_to_cool"])
        self.assertIn("open_obligation_reference", decision["blockers"])
        self.assertEqual(len(decision["open_obligation_hits"]), 1)

    def test_refuses_lineage_dependents_without_covered_successor(self) -> None:
        artifact_path = self._artifact_path(".synapse/DRAFTSHOT_INDEX/REVISIONS/old.yaml")
        persist_lineage_edge(
            self.data_root,
            build_lineage_edge(
                subject=self.subject,
                recorded_at="2026-04-09T10:00:00-04:00",
                source_kind="draftshot_revision",
                source_id="DRAFTREV-OLD",
                target_kind="snapshot_candidate",
                target_id="SNAPSHOTCAND-NEW",
                relation="supports_candidate",
            ),
        )
        decision = evaluate_compaction_candidate(
            data_root=self.data_root,
            artifact_family="draftshot_revision",
            artifact_id="DRAFTREV-OLD",
            artifact_path=str(artifact_path),
        )
        self.assertFalse(decision["allowed_to_cool"])
        self.assertIn("no_stronger_successor", decision["blockers"])
        self.assertIn("uncovered_lineage_dependents", decision["blockers"])

    def test_allows_cooling_superseded_artifact_with_replacement(self) -> None:
        artifact_path = self._artifact_path(".synapse/DRAFTSHOT_INDEX/REVISIONS/old.yaml")
        persist_lineage_edge(
            self.data_root,
            build_lineage_edge(
                subject=self.subject,
                recorded_at="2026-04-09T10:00:00-04:00",
                source_kind="draftshot_revision",
                source_id="DRAFTREV-OLD",
                target_kind="draftshot_revision",
                target_id="DRAFTREV-NEW",
                relation="superseded_by",
            ),
        )
        decision = evaluate_compaction_candidate(
            data_root=self.data_root,
            artifact_family="draftshot_revision",
            artifact_id="DRAFTREV-OLD",
            artifact_path=str(artifact_path),
            stronger_successor_ids=["DRAFTREV-NEW"],
        )
        self.assertTrue(decision["allowed_to_cool"])
        self.assertFalse(decision["allowed_to_delete"])
        self.assertEqual(decision["blockers"], [])
        self.assertEqual(decision["stronger_successor_ids"], ["DRAFTREV-NEW"])
        self.assertEqual(
            decision["required_receipts"],
            ["lineage_safe_supersession", "open_obligation_clear", "archive_manifest_entry"],
        )

    def test_refresh_superseded_revision_manifests_writes_draftshot_manifest(self) -> None:
        self._bootstrap_subject()
        synthesis_one = {
            "active_plan_delta": {
                "summary": "First draftshot basis.",
                "source_refs": [{"kind": "conversation_segment", "id": "SEG-001", "path": "/tmp/SEG-001.json"}],
            }
        }
        synthesis_two = {
            "active_plan_delta": {
                "summary": "Second draftshot basis.",
                "source_refs": [{"kind": "conversation_segment", "id": "SEG-002", "path": "/tmp/SEG-002.json"}],
            }
        }
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-compaction-001",
            run_id="RUN-COMPACTION-001",
            synthesis=synthesis_one,
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-compaction-001",
            run_id="RUN-COMPACTION-001",
            synthesis=synthesis_two,
        )
        result = refresh_superseded_revision_manifests(self.data_root)
        draftshot_receipts = [item for item in result["receipts"] if item.get("artifact_family") == "draftshot_revision"]
        self.assertEqual(len(draftshot_receipts), 1)
        self.assertEqual(draftshot_receipts[0]["decision_status"], "eligible")
        self.assertEqual(draftshot_receipts[0]["decision"]["allowed_to_delete"], False)
        self.assertTrue(Path(draftshot_receipts[0]["manifest_path"]).exists())

    def test_refresh_superseded_revision_manifests_writes_candidate_manifests(self) -> None:
        self._bootstrap_subject()
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE-1", "project.scope", "Scope iteration one."),
                self._event("SEMEVT-VISION-1", "project.vision", "Vision iteration one."),
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Compaction plan v1",
            summary="First compaction-backed plan.",
            origin="test",
            objective="Create first candidate revisions.",
            coherent_outcome="First candidate revisions exist.",
            closure_statement="First revisions exist.",
            out_of_scope="Deletion.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Refresh candidates twice.",
            milestones=["First revision"],
            split_triggers=["Split if archive logic becomes destructive."],
            source_segment_ids=["SEG-PLAN-1"],
            source_semantic_event_ids=["SEMEVT-PLAN-1"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN-1", "path": "/tmp/SEG-PLAN-1.json"}],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-compaction-002",
            run_id="RUN-COMPACTION-002",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        refresh_snapshot_candidates(subject=self.subject, data_root=self.data_root, session_id="syn-compaction-002")
        refresh_publication_candidates(subject=self.subject, data_root=self.data_root)

        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE-2", "project.scope", "Scope iteration two."),
                self._event("SEMEVT-VISION-2", "project.vision", "Vision iteration two."),
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Compaction plan v2",
            summary="Second compaction-backed plan.",
            origin="test",
            objective="Create superseding candidate revisions.",
            coherent_outcome="Second candidate revisions exist.",
            closure_statement="Second revisions exist.",
            out_of_scope="Deletion.",
            dependencies=["None"],
            risk="R2",
            verification_plan="Refresh candidates a second time.",
            milestones=["Second revision"],
            split_triggers=["Split if candidate families stop versioning."],
            source_segment_ids=["SEG-PLAN-2"],
            source_semantic_event_ids=["SEMEVT-PLAN-2"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN-2", "path": "/tmp/SEG-PLAN-2.json"}],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-compaction-002",
            run_id="RUN-COMPACTION-002",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        refresh_snapshot_candidates(subject=self.subject, data_root=self.data_root, session_id="syn-compaction-002")
        refresh_publication_candidates(subject=self.subject, data_root=self.data_root)

        result = refresh_superseded_revision_manifests(self.data_root)
        artifact_families = {item.get("artifact_family") for item in result["receipts"]}
        self.assertIn("snapshot_candidate_revision", artifact_families)
        self.assertIn("publication_candidate_revision", artifact_families)
        for receipt in result["receipts"]:
            self.assertTrue(Path(receipt["manifest_path"]).exists())
            self.assertEqual(receipt["decision"]["allowed_to_delete"], False)


if __name__ == "__main__":
    unittest.main()

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
from synapse_runtime.lineage_store import build_lineage_edge, persist_lineage_edge


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


if __name__ == "__main__":
    unittest.main()

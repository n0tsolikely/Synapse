import tempfile
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.lineage_store import build_lineage_edge, ensure_lineage_scaffold, lineage_summary, load_lineage_edges, persist_lineage_edge
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class LineageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "LineageSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persist_and_summarize_lineage_edges(self) -> None:
        ensure_lineage_scaffold(self.data_root)

        edge = build_lineage_edge(
            subject=self.subject,
            recorded_at="2026-04-01T12:00:00-04:00",
            source_kind="semantic_event",
            source_id="SEMEVT-1",
            target_kind="plan_revision",
            target_id="PLAN-1::REVISION-001",
            relation="promoted_to_plan",
            metadata={"phase": "p2"},
        )
        receipt = persist_lineage_edge(self.data_root, edge)
        self.assertTrue(Path(receipt["path"]).exists())

        loaded = load_lineage_edges(self.data_root)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["relation"], "promoted_to_plan")

        summary = lineage_summary(self.data_root)
        self.assertEqual(summary["lineage_edge_count"], 1)
        self.assertEqual(summary["lineage_relation_counts"]["promoted_to_plan"], 1)
        self.assertEqual(summary["recent_lineage_edge_ids"], [edge.edge_id])

import tempfile
from pathlib import Path
import sys
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.truth_drafts import (
    TruthDraftError,
    list_truth_draft_revisions,
    load_current_truth_drafts,
    truth_draft_summary,
    write_truth_draft,
)
from synapse_runtime.truth_sources import truth_draft_evidence
from synapse_runtime.truth_statements import StatementKind, TruthLayer


class TruthDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "TruthDraftSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _statements(self) -> list[dict]:
        return [
            {
                "statement_kind": StatementKind.CAPABILITY.value,
                "summary": "Truth drafts exist as noncanonical compiler inputs.",
                "detail": "Stored separately from compiled truth outputs.",
                "truth_layer": TruthLayer.PARTIAL.value,
                "confidence": "medium",
                "topic_key": "truth-draft-inputs",
            },
            {
                "statement_kind": StatementKind.CONSTRAINT.value,
                "summary": "Truth drafts must not masquerade as compiled truth.",
                "detail": "Compiler still owns publication.",
                "truth_layer": TruthLayer.IMPLEMENTED.value,
                "confidence": "high",
                "topic_key": "truth-draft-boundary",
            },
        ]

    def test_write_truth_draft_writes_revision_and_noops_on_unchanged_signature(self) -> None:
        source_refs = [{"kind": "conversation_segment", "id": "SEG-TRUTH", "path": "/tmp/SEG-TRUTH.json"}]
        first = write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            summary="Capture current-state truth draft inputs.",
            family_key="current-state",
            statements=self._statements(),
            source_refs=source_refs,
            run_context={"run_id": "RUN-TRUTH-001", "session_id": "SESSION-TRUTH-001", "session_mode": "control_sync"},
        )
        self.assertEqual(first["status"], "written")
        first_path = Path(first["draft_path"])
        self.assertTrue(first_path.exists())
        payload = yaml.safe_load(first_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["noncanonical"])
        self.assertEqual(payload["statement_count"], 2)
        self.assertEqual(payload["run_context"]["session_mode"], "control_sync")

        second = write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            summary="Capture current-state truth draft inputs.",
            family_key="current-state",
            statements=self._statements(),
            source_refs=source_refs,
        )
        self.assertEqual(second["status"], "noop")
        self.assertEqual(second["reason"], "unchanged_source_signature")
        self.assertEqual(len(list_truth_draft_revisions(self.data_root)), 1)

    def test_write_truth_draft_revision_increments_on_material_change(self) -> None:
        first = write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            family_key="current-state",
            statements=self._statements(),
        )
        updated_statements = list(self._statements())
        updated_statements.append(
            {
                "statement_kind": StatementKind.WORKFLOW.value,
                "summary": "Truth compile should consume current truth drafts.",
                "detail": "Compiler ingestion seam exists.",
                "truth_layer": TruthLayer.INTENDED.value,
                "confidence": "medium",
                "topic_key": "truth-draft-ingestion",
            }
        )
        second = write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            family_key="current-state",
            statements=updated_statements,
        )
        self.assertEqual(first["revision_number"], 1)
        self.assertEqual(second["revision_number"], 2)
        self.assertEqual(len(list_truth_draft_revisions(self.data_root)), 2)
        current = load_current_truth_drafts(self.data_root)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["revision_number"], 2)

    def test_truth_draft_evidence_normalizes_current_revision_only(self) -> None:
        write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            family_key="current-state",
            statements=self._statements(),
            source_refs=[{"kind": "conversation_segment", "id": "SEG-TRUTH", "path": "/tmp/SEG-TRUTH.json"}],
        )
        records, warnings = truth_draft_evidence(data_root=self.data_root)
        self.assertFalse(warnings)
        self.assertEqual(len(records), 2)
        summaries = {record.summary: record for record in records}
        self.assertIn("Truth drafts exist as noncanonical compiler inputs.", summaries)
        self.assertEqual(summaries["Truth drafts exist as noncanonical compiler inputs."].source_type, "truth_draft")
        self.assertEqual(summaries["Truth drafts must not masquerade as compiled truth."].truth_layer_hint, TruthLayer.IMPLEMENTED.value)
        self.assertTrue(summaries["Truth drafts exist as noncanonical compiler inputs."].metadata["noncanonical"])

    def test_truth_draft_summary_reports_current_paths(self) -> None:
        write_truth_draft(
            subject=self.subject,
            data_root=self.data_root,
            title="Current truth draft",
            family_key="current-state",
            statements=self._statements(),
        )
        summary = truth_draft_summary(self.data_root)
        self.assertEqual(summary["truth_draft_count"], 1)
        self.assertEqual(len(summary["current_truth_draft_paths"]), 1)
        self.assertEqual(summary["recent_truth_draft_details"][0]["statement_count"], 2)

    def test_truth_draft_requires_statements(self) -> None:
        with self.assertRaises(TruthDraftError):
            write_truth_draft(
                subject=self.subject,
                data_root=self.data_root,
                title="Empty truth draft",
                statements=[],
            )


if __name__ == "__main__":
    unittest.main()

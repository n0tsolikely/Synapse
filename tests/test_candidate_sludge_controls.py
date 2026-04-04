import tempfile
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import synapse as synapse_cli

from synapse_runtime.continuity_obligations import load_obligations
from synapse_runtime.draftshots import refresh_draftshot
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.run_lifecycle import run_start
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.snapshot_candidates import list_snapshot_candidate_revisions, refresh_snapshot_candidates
from synapse_runtime.subject_bootstrap import initialize_subject_state


class CandidateSludgeControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "CandidateSludgeSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refresh_snapshot_candidates_noops_without_active_draftshot(self) -> None:
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        result = refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-sludge-001",
        )
        self.assertEqual(result["status"], "noop")
        self.assertEqual(result["reason"], "no_active_draftshot")
        self.assertEqual(list_snapshot_candidate_revisions(self.data_root), [])

    def test_refresh_snapshot_candidates_does_not_emit_new_revision_without_source_delta(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                {
                    "semantic_event_id": "SEMEVT-SCOPE",
                    "schema_version": 1,
                    "classifier_version": "v1-phase2",
                    "recorded_at": "2026-04-04T12:00:00-04:00",
                    "subject": self.subject,
                    "class_label": "project.scope",
                    "topic_key": "project.scope",
                    "confidence_band": "high",
                    "materiality_band": "high",
                    "summary": "Scope the project around continuity-safe daily closeout.",
                    "transient_noise": False,
                    "imported_limited": False,
                    "source_segment_ids": ["SEG-SCOPE"],
                    "source_refs": [{"kind": "conversation_segment", "id": "SEG-SCOPE", "path": "/tmp/SEG-SCOPE.json"}],
                    "related_paths": [],
                }
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Candidate sludge control",
            summary="Plan the sludge-control fixture.",
            origin="test",
            objective="Keep candidate revisioning quiet when nothing changed.",
            coherent_outcome="Candidate refresh stays stable on unchanged sources.",
            closure_statement="No extra candidate revisions are written without new source refs.",
            out_of_scope="Extra architecture work.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Refresh twice and compare revision counts.",
            milestones=["First refresh", "Second refresh noop"],
            split_triggers=["Split if the fixture stops being self-contained."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-sludge-002",
            run_id="RUN-SLUDGE-002",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        first = refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-sludge-002",
        )
        self.assertEqual(first["status"], "written")
        first_revisions = list_snapshot_candidate_revisions(self.data_root)
        self.assertEqual(len(first_revisions), 2)

        second = refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-sludge-002",
        )
        self.assertEqual(second["status"], "noop")
        second_revisions = list_snapshot_candidate_revisions(self.data_root)
        self.assertEqual(len(second_revisions), len(first_revisions))

    def test_boundary_fallback_opens_blocker_obligation_when_typed_candidate_cannot_be_drafted(self) -> None:
        run_start(
            subject=self.subject,
            data_root=self.data_root,
            title="Fallback boundary",
            goal="Force typed candidate fallback behavior.",
            items=["Need an EOD candidate"],
            mutate_proposals=False,
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Fallback candidate plan",
            summary="There is durable closeout work but no draftshot yet.",
            origin="test",
            objective="Open a blocker obligation when the typed candidate cannot be drafted lawfully.",
            coherent_outcome="The boundary records obligation debt instead of inventing a candidate.",
            closure_statement="A blocker obligation exists for the missing typed candidate.",
            out_of_scope="Actually drafting the candidate.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Invoke the boundary helper without a draftshot and inspect obligations.",
            milestones=["Persist durable source", "Open fallback obligation"],
            split_triggers=["Split if obligation fallback requires canonical snapshot writing."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        ctx = {
            "subject": self.subject,
            "data_root": str(self.data_root),
            "engine_root": str(self.engine_root),
        }

        result = synapse_cli._refresh_snapshot_candidate_boundary(
            ctx=ctx,
            boundary="close_turn",
            candidate_kinds=["EOD"],
            refresh_draftshot_first=False,
        )

        self.assertEqual(result["snapshot_candidates"]["status"], "noop")
        self.assertEqual(result["snapshot_candidates"]["reason"], "no_active_draftshot")
        obligations = load_obligations(self.data_root)
        open_snapshot_obligations = [
            item
            for item in obligations
            if str(item.get("state") or "").lower() == "open"
            and str(item.get("obligation_kind") or "").startswith("snapshot.candidate.")
        ]
        self.assertEqual(len(open_snapshot_obligations), 1)
        self.assertEqual(open_snapshot_obligations[0]["obligation_kind"], "snapshot.candidate.eod.required")


if __name__ == "__main__":
    unittest.main()

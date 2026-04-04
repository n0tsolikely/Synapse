import tempfile
from pathlib import Path
import sys
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.publication_candidates import refresh_publication_candidates, resolve_publication_candidate
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.repo_onboarding import (
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
    publish_publication_candidate,
)
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class PublicationCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "PublicationSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        self._write_canonical_baseline()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase3",
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

    def _write_canonical_baseline(self) -> None:
        canonical_project_model_path(self.data_root).write_text(
            yaml.safe_dump(
                {
                    "project_identity": "Baseline installable website system",
                    "purpose": "Help operators deliver installable client websites cleanly.",
                    "vision": "Become the reusable baseline for installable customer-facing web systems.",
                    "confirmed_at": "2026-04-04T10:00:00-04:00",
                    "implemented_truths": [{"summary": "The repo already tracks governed continuity."}],
                    "partial_truths": [],
                    "intended_capabilities": [],
                    "future_ideas_needing_expansion": [],
                    "superseded_directions": [],
                    "constraints": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        canonical_project_story_path(self.data_root).write_text("# Project Story\n\nBaseline story.\n", encoding="utf-8")
        canonical_vision_path(self.data_root).write_text("# Vision\n\nBaseline vision.\n", encoding="utf-8")
        canonical_codex_current_path(self.data_root).write_text("# Current Codex\n\nBaseline current codex.\n", encoding="utf-8")
        canonical_codex_future_path(self.data_root).write_text("# Future Codex\n\nBaseline future codex.\n", encoding="utf-8")

    def test_refresh_publication_candidates_writes_story_vision_and_codex_revisions(self) -> None:
        baseline_story = canonical_project_story_path(self.data_root).read_text(encoding="utf-8")
        baseline_vision = canonical_vision_path(self.data_root).read_text(encoding="utf-8")
        baseline_codex_current = canonical_codex_current_path(self.data_root).read_text(encoding="utf-8")
        baseline_codex_future = canonical_codex_future_path(self.data_root).read_text(encoding="utf-8")

        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE", "project.scope", "Scope the product around installable account-backed workflows."),
                self._event("SEMEVT-ARCH", "architecture.shape", "Use a web app plus API layout for installable customer flows."),
                self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system."),
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Installable workflow publication candidate plan",
            summary="Capture installable workflow direction for later publication review.",
            origin="test",
            objective="Keep story, vision, and codex candidate state readable without mutating canon.",
            coherent_outcome="Publication candidates exist as durable noncanonical records.",
            closure_statement="Publication candidates are source-linked and reviewable.",
            out_of_scope="Canonical publication.",
            dependencies=["Continuity synthesis"],
            risk="R1",
            verification_plan="Refresh synthesis, then publication candidates, and inspect outputs.",
            milestones=["Story candidate", "Vision candidate", "Codex candidate"],
            split_triggers=["Split if candidate storage needs independent compatibility handling."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        payload = refresh_publication_candidates(subject=self.subject, data_root=self.data_root)
        self.assertEqual(payload["status"], "written")
        self.assertEqual(
            {item["candidate_kind"] for item in payload["candidates"] if item["status"] == "written"},
            {"STORY", "VISION", "CODEX"},
        )

        summary = payload["summary"]
        self.assertTrue(summary["current_story_candidate_path"])
        self.assertTrue(summary["current_vision_candidate_path"])
        self.assertEqual(len(summary["current_codex_candidate_paths"]), 1)

        story_text = Path(summary["current_story_candidate_path"]).read_text(encoding="utf-8")
        vision_text = Path(summary["current_vision_candidate_path"]).read_text(encoding="utf-8")
        codex_manifest = yaml.safe_load(Path(summary["recent_codex_candidate_details"][-1]["manifest_path"]).read_text(encoding="utf-8"))
        self.assertIn("## Canonical Baseline Refs", story_text)
        self.assertIn(str(canonical_project_story_path(self.data_root)), story_text)
        self.assertIn("## Source Refs", vision_text)
        self.assertTrue(codex_manifest["source_refs"])
        self.assertTrue(codex_manifest["baseline_refs"])

        self.assertEqual(canonical_project_story_path(self.data_root).read_text(encoding="utf-8"), baseline_story)
        self.assertEqual(canonical_vision_path(self.data_root).read_text(encoding="utf-8"), baseline_vision)
        self.assertEqual(canonical_codex_current_path(self.data_root).read_text(encoding="utf-8"), baseline_codex_current)
        self.assertEqual(canonical_codex_future_path(self.data_root).read_text(encoding="utf-8"), baseline_codex_future)

    def test_refresh_publication_candidates_is_noop_without_source_delta_change(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system.")],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Publication candidate noop guard",
            summary="Refresh once, then verify the second refresh is stable.",
            origin="test",
            objective="Avoid candidate spam when nothing changed.",
            coherent_outcome="The second refresh does not mint extra revisions.",
            closure_statement="Candidate revisioning stays source-delta gated.",
            out_of_scope="Canonical publication.",
            dependencies=["Continuity synthesis"],
            risk="R1",
            verification_plan="Refresh twice without changing source refs.",
            milestones=["Initial candidate refresh", "Stable second refresh"],
            split_triggers=["Split if per-kind cooldown logic becomes necessary."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        first = refresh_publication_candidates(subject=self.subject, data_root=self.data_root)
        second = refresh_publication_candidates(subject=self.subject, data_root=self.data_root)

        self.assertEqual(first["status"], "written")
        self.assertEqual(second["status"], "noop")
        self.assertTrue(all(item["reason"] == "unchanged_source_signature" for item in second["candidates"]))

    def test_publish_publication_candidate_clears_pending_state_and_prevents_immediate_redraft(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system.")],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Publication candidate publish path",
            summary="Refresh then publish a publication candidate canonically.",
            origin="test",
            objective="Verify owner-gated publication clears pending state without re-drafting immediately.",
            coherent_outcome="Publishing a candidate updates canon and resolves the pending candidate.",
            closure_statement="Canon updates while pending candidate state clears cleanly.",
            out_of_scope="Onboarding confirmation.",
            dependencies=["Continuity synthesis"],
            risk="R1",
            verification_plan="Refresh candidates, publish story, then refresh again.",
            milestones=["Candidate refresh", "Canonical publish", "No-op refresh after publish"],
            split_triggers=["Split if publication handoff needs owner-boundary hardening."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        first = refresh_publication_candidates(subject=self.subject, data_root=self.data_root)
        self.assertEqual(first["status"], "written")
        story_candidate = resolve_publication_candidate(self.data_root, "story")
        published = publish_publication_candidate(
            subject=self.subject,
            data_root=self.data_root,
            active_run={"session_id": "SESSION-PUBLISH-001", "run_id": "RUN-PUBLISH-001"},
            candidate_handle="story",
        )

        self.assertEqual(published["candidate_kind"], "STORY")
        self.assertTrue(Path(published["publication_receipt_path"]).exists())
        self.assertTrue(published["canonical_paths"]["PROJECT_STORY"])
        self.assertNotEqual(
            canonical_project_story_path(self.data_root).read_text(encoding="utf-8"),
            "# Project Story\n\nBaseline story.\n",
        )
        self.assertIn("Baseline installable website system", canonical_project_story_path(self.data_root).read_text(encoding="utf-8"))

        second = refresh_publication_candidates(subject=self.subject, data_root=self.data_root, candidate_kinds=["story"])
        self.assertEqual(second["status"], "noop")
        self.assertEqual(second["candidates"][0]["reason"], "already_canonical")
        self.assertIsNone(second["summary"]["current_story_candidate_path"])
        self.assertEqual(story_candidate["revision_id"], published["candidate_revision_id"])


if __name__ == "__main__":
    unittest.main()

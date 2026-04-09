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
from synapse_runtime.publication_candidates import refresh_publication_candidates
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.repo_onboarding import (
    canonical_codex_current_path,
    canonical_codex_future_path,
    canonical_project_model_path,
    canonical_project_story_path,
    canonical_vision_path,
)
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


class SynthesisRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "SynthesisSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str, *, imported_limited: bool = False) -> dict:
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
            "source_segment_ids": [f"SEG-{semantic_event_id}"],
            "source_refs": [{"kind": "conversation_segment", "id": f"SEG-{semantic_event_id}", "path": f"/tmp/{semantic_event_id}.json"}],
            "related_paths": [],
        }

    def test_refresh_projects_source_linked_deltas_into_state_manifold_and_rehydrate(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE", "project.scope", "Scope the installable web app around separate user accounts."),
                self._event("SEMEVT-ARCH", "architecture.shape", "Use a web app plus API layout for the installable product."),
                self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system."),
                self._event(
                    "SEMEVT-IMP",
                    "project.vision",
                    "Imported continuity mentions investor-facing positioning for the website system.",
                    imported_limited=True,
                ),
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Installable web app foundation",
            summary="Ship the installable web app foundation.",
            origin="test",
            objective="Support accounts and audio transcription intake.",
            coherent_outcome="Users can sign in and submit transcription work.",
            closure_statement="Foundation supports authenticated transcription intake.",
            out_of_scope="Billing and team administration.",
            dependencies=["Auth provider", "Transcription queue"],
            risk="R2",
            verification_plan="Run auth flow tests and transcription intake checks.",
            milestones=["Account auth", "Audio/link transcription intake"],
            split_triggers=["Split if billing enters scope."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )

        projection = refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))

        self.assertTrue(projection["active_plan_delta"]["summary"])
        self.assertTrue(projection["active_scope_delta"]["summary"])
        self.assertTrue(projection["architecture_delta"]["summary"])
        self.assertTrue(projection["identity_delta"]["summary"])
        self.assertTrue(projection["narrative_delta"]["summary"])
        self.assertTrue(projection["imported_continuity_delta"]["summary"])
        self.assertTrue(any(line.startswith("[TRUTH]") for line in projection["active_scope_delta"]["detail_lines"]))
        self.assertTrue(any(line.startswith("[TRUTH]") for line in projection["architecture_delta"]["detail_lines"]))
        self.assertTrue(any(line.startswith("[VISION]") for line in projection["narrative_delta"]["detail_lines"]))
        self.assertIn("open continuity obligations", projection["obligation_delta"]["summary"])
        self.assertGreaterEqual(state["codex_packet_count"], 5)
        self.assertEqual(state["codex_packet_count"], manifold["codex_packet_count"])
        self.assertTrue(manifold["current_active_plan_delta"]["source_refs"])
        self.assertTrue(manifold["current_imported_continuity_delta"]["source_refs"])
        self.assertTrue(manifold["recent_codex_packet_details"])

        render_rehydrate(subject=self.subject, data_root=self.data_root)
        rendered = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Derived synthesis", rendered)
        self.assertIn("## Codex section packets", rendered)
        self.assertIn("Ship the installable web app foundation.", rendered)
        self.assertIn("Scope the installable web app around separate user accounts.", rendered)
        self.assertIn("The product becomes a reusable website business system.", rendered)

        canonical_project_model_path(self.data_root).write_text(
            yaml.safe_dump(
                {
                    "project_identity": "Baseline installable website system",
                    "purpose": "Help operators ship installable client websites cleanly.",
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
        refresh_publication_candidates(subject=self.subject, data_root=self.data_root)
        render_rehydrate(subject=self.subject, data_root=self.data_root)
        rendered = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Publication candidates", rendered)
        self.assertIn("Story candidate:", rendered)
        self.assertIn("Vision candidate:", rendered)
        self.assertIn("Codex candidate:", rendered)
        self.assertIn("formalize --candidate-handle {story|vision|codex}", rendered)


if __name__ == "__main__":
    unittest.main()

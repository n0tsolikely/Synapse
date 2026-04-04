import importlib.util
import json
import tempfile
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

PYDANTIC_AVAILABLE = importlib.util.find_spec("pydantic") is not None

if PYDANTIC_AVAILABLE:
    from synapse_mcp.connection_state import ConnectionState
    from synapse_mcp.runtime_bridge import build_current_context_bundle, read_resource, resource_catalog
from synapse_runtime.draftshots import refresh_draftshot
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.publication_candidates import refresh_publication_candidates
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.snapshot_candidates import refresh_snapshot_candidates
from synapse_runtime.subject_bootstrap import initialize_subject_state


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed in the active interpreter.")
class CurrentContextProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "ContextSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        self.state = ConnectionState(workspace_root=str(self.engine_root))
        self.state.update_subject_defaults(
            subject=self.subject,
            engine_root=str(self.engine_root),
            data_root=str(self.data_root),
        )
        self.state.update_session_default("syn-context-001")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
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
            "imported_limited": False,
            "source_segment_ids": [f"SEG-{semantic_event_id}"],
            "source_refs": [{"kind": "conversation_segment", "id": f"SEG-{semantic_event_id}", "path": f"/tmp/{semantic_event_id}.json"}],
            "related_paths": [],
        }

    def test_current_context_and_resources_expose_phase3_synthesis(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                self._event("SEMEVT-SCOPE", "project.scope", "Scope the product around installable web workflows."),
                self._event("SEMEVT-VISION", "project.vision", "The product becomes a reusable website business system."),
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
            session_id="syn-context-001",
            run_id="RUN-CONTEXT-001",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)
        refresh_snapshot_candidates(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-context-001",
        )
        refresh_publication_candidates(
            subject=self.subject,
            data_root=self.data_root,
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        _, bundle = build_current_context_bundle(state=self.state, context=None, include_rehydrate=False, include_project_story=False)
        context = bundle["context"]
        self.assertIn("derived_synthesis", context)
        self.assertIn("codex_packets", context)
        self.assertIn("draftshot", context)
        self.assertIn("snapshot_candidates", context)
        self.assertIn("publication_candidates", context)
        self.assertEqual(context["codex_packets"]["codex_packet_count"], 4)
        self.assertTrue(context["derived_synthesis"]["active_plan_delta"]["summary"])
        self.assertTrue(context["derived_synthesis"]["identity_delta"]["summary"])
        self.assertEqual(context["draftshot"]["current_active_draftshot_session_id"], "syn-context-001")
        self.assertTrue(context["draftshot"]["current_active_draftshot_path"])
        self.assertTrue(context["snapshot_candidates"]["current_eod_candidate_path"])
        self.assertTrue(context["snapshot_candidates"]["current_control_sync_candidate_path"])
        self.assertTrue(context["publication_candidates"]["current_story_candidate_path"])
        self.assertTrue(context["publication_candidates"]["current_vision_candidate_path"])
        self.assertTrue(context["publication_candidates"]["current_codex_candidate_paths"])

        resources = {item["uri"] for item in resource_catalog(state=self.state)}
        self.assertIn("synapse://current/synthesis-summary.json", resources)
        self.assertIn("synapse://current/codex-packets.json", resources)
        self.assertIn("synapse://current/draftshot-state.json", resources)
        self.assertIn("synapse://current/snapshot-candidates.json", resources)
        self.assertIn("synapse://current/publication-candidates.json", resources)
        self.assertIn("synapse://current/publication-candidates/story.md", resources)
        self.assertIn("synapse://current/publication-candidates/vision.md", resources)
        self.assertIn("synapse://current/publication-candidates/codex.md", resources)

        _, synthesis_text, _ = read_resource(state=self.state, uri="synapse://current/synthesis-summary.json")
        _, packets_text, _ = read_resource(state=self.state, uri="synapse://current/codex-packets.json")
        _, draftshot_text, _ = read_resource(state=self.state, uri="synapse://current/draftshot-state.json")
        _, snapshot_candidates_text, _ = read_resource(state=self.state, uri="synapse://current/snapshot-candidates.json")
        _, publication_candidates_text, _ = read_resource(state=self.state, uri="synapse://current/publication-candidates.json")
        _, story_candidate_text, _ = read_resource(state=self.state, uri="synapse://current/publication-candidates/story.md")
        _, vision_candidate_text, _ = read_resource(state=self.state, uri="synapse://current/publication-candidates/vision.md")
        _, codex_candidate_text, _ = read_resource(state=self.state, uri="synapse://current/publication-candidates/codex.md")
        synthesis_payload = json.loads(synthesis_text)
        packets_payload = json.loads(packets_text)
        draftshot_payload = json.loads(draftshot_text)
        snapshot_candidates_payload = json.loads(snapshot_candidates_text)
        publication_candidates_payload = json.loads(publication_candidates_text)
        self.assertEqual(synthesis_payload["active_plan_delta"]["summary"], "Plan the installable workflow foundation.")
        self.assertEqual(packets_payload["codex_packet_count"], 4)
        self.assertIn("ACTIVE_PLAN", packets_payload["packet_section_keys"])
        self.assertEqual(draftshot_payload["current_active_draftshot_session_id"], "syn-context-001")
        self.assertTrue(snapshot_candidates_payload["current_eod_candidate_path"])
        self.assertTrue(snapshot_candidates_payload["current_control_sync_candidate_path"])
        self.assertTrue(publication_candidates_payload["current_story_candidate_path"])
        self.assertTrue(publication_candidates_payload["current_vision_candidate_path"])
        self.assertTrue(publication_candidates_payload["current_codex_candidate_paths"])
        self.assertIn("# Project Story Candidate", story_candidate_text)
        self.assertIn("# Vision Candidate", vision_candidate_text)
        self.assertIn("# Codex Candidate", codex_candidate_text)


if __name__ == "__main__":
    unittest.main()

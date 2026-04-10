import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.artifact_router import build_artifact_routing_context, evaluate_artifact_routing
from synapse_runtime.draftshots import refresh_draftshot
from synapse_runtime.governance_model import ProposalKind, ProposalState
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
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
from synapse_runtime.subject_bridge import install_local_codex_integration
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class ArtifactRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "ArtifactRouterRepo"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        write_focus_lock(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            cwt=self.engine_root,
            home=self.home,
            selection_method="test",
            source_detail="test_artifact_router",
        )
        self._write_publication_baseline()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_publication_baseline(self) -> None:
        canonical_project_model_path(self.data_root).write_text(
            json.dumps(
                {
                    "onboarding_id": "ONBOARDING-ARTIFACT-ROUTER-FIXTURE",
                    "project_identity": "Artifact router fixture",
                    "purpose": "Exercise routed publication candidates.",
                    "vision": "Keep routing explicit.",
                    "confirmed_at": "2026-04-10T01:00:00-04:00",
                    "implemented_truths": [{"summary": "The repo already tracks governed continuity."}],
                    "partial_truths": [],
                    "intended_capabilities": [],
                    "future_ideas_needing_expansion": [],
                    "superseded_directions": [],
                    "constraints": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        canonical_project_story_path(self.data_root).write_text("# Project Story\n\nBaseline story.\n", encoding="utf-8")
        canonical_vision_path(self.data_root).write_text("# Vision\n\nBaseline vision.\n", encoding="utf-8")
        canonical_codex_current_path(self.data_root).write_text("# Current Codex\n\nBaseline current codex.\n", encoding="utf-8")
        canonical_codex_future_path(self.data_root).write_text("# Future Codex\n\nBaseline future codex.\n", encoding="utf-8")

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase2",
            "recorded_at": "2026-04-10T01:00:00-04:00",
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

    def _seed_durable_continuity(self) -> None:
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
            title="Artifact router fixture plan",
            summary="Capture enough durable continuity to exercise routed candidate refresh.",
            origin="test",
            objective="Exercise routed snapshot and publication candidate refresh.",
            coherent_outcome="Typed candidates exist after routed boundaries.",
            closure_statement="The routed boundary writes noncanonical artifacts without mutating canon.",
            out_of_scope="Canonical publication.",
            dependencies=["Continuity synthesis"],
            risk="R1",
            verification_plan="Run the routed boundary and inspect artifact paths.",
            milestones=["Persist durable continuity", "Run routed boundary"],
            split_triggers=["Split if routed mutation crosses into canonical surfaces."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

    def test_identical_context_produces_identical_routing_result(self) -> None:
        active_run = {
            "run_id": "RUN-ROUTER-001",
            "session_id": "sid-router-001",
            "session_mode": "execution",
            "interaction_mode": "execution",
        }
        context_one = build_artifact_routing_context(
            subject=self.subject,
            data_root=self.data_root,
            trigger="session-tick",
            boundary="session-tick",
            invoke_reason="test_idempotence",
            active_run=active_run,
            accepted_context={},
            summary="Runtime capability expansion in routing.",
            changed_files=["runtime/synapse.py"],
            requested_snapshot_kinds=[],
            requested_publication_candidate_kinds=[],
        )
        context_two = build_artifact_routing_context(
            subject=self.subject,
            data_root=self.data_root,
            trigger="session-tick",
            boundary="session-tick",
            invoke_reason="test_idempotence",
            active_run=active_run,
            accepted_context={},
            summary="Runtime capability expansion in routing.",
            changed_files=["runtime/synapse.py"],
            requested_snapshot_kinds=[],
            requested_publication_candidate_kinds=[],
        )
        self.assertEqual(context_one.envelope_fingerprint, context_two.envelope_fingerprint)
        self.assertEqual(evaluate_artifact_routing(context_one).to_dict(), evaluate_artifact_routing(context_two).to_dict())

    def test_missing_execution_pack_owner_is_explicitly_blocked(self) -> None:
        context = build_artifact_routing_context(
            subject=self.subject,
            data_root=self.data_root,
            trigger="session-tick",
            boundary="session-tick",
            invoke_reason="test_missing_owner",
            active_run={"run_id": "RUN-ROUTER-002", "session_id": "sid-router-002", "session_mode": "execution"},
            accepted_context={},
            requested_snapshot_kinds=[],
            requested_publication_candidate_kinds=[],
            requested_missing_owner_families=["execution_pack"],
        )
        result = evaluate_artifact_routing(context).to_dict()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intents"][0]["intent_kind"], "blocked_missing_owner")
        self.assertEqual(result["intents"][0]["blocking_reason"], "missing_owner:execution_pack")

    def test_onboarding_session_blocks_governance_proposal_mutation_but_not_candidate_refresh(self) -> None:
        context = build_artifact_routing_context(
            subject=self.subject,
            data_root=self.data_root,
            trigger="session-tick",
            boundary="session-tick",
            invoke_reason="test_onboarding_gate",
            active_run={
                "run_id": "RUN-ROUTER-ONBOARDING",
                "session_id": "sid-router-onboarding",
                "session_mode": "onboarding_existing_repo",
            },
            accepted_context={},
            summary="Guild orders scope changed materially.",
            requested_snapshot_kinds=[],
            requested_publication_candidate_kinds=["STORY"],
        )
        gated_context = replace(
            context,
            promotion_payloads=(
                {
                    "kind": ProposalKind.GUILD_ORDERS.value,
                    "state": ProposalState.DRAFT.value,
                    "title": "Bind scope into guild orders",
                    "summary": "Stable governed scope should move into a guild-orders proposal.",
                    "reason": "test fixture",
                    "blockers": [],
                    "evidence": [],
                    "codex_implications": [],
                },
            ),
        )
        result = evaluate_artifact_routing(gated_context).to_dict()
        intent_kinds = [item["intent_kind"] for item in result["intents"]]
        self.assertIn("refresh_publication_candidate", intent_kinds)
        self.assertIn("blocked_gate", intent_kinds)
        blocked = next(item for item in result["intents"] if item["intent_kind"] == "blocked_gate")
        self.assertEqual(blocked["blocking_reason"], "proposal_mutation_not_allowed")
        self.assertEqual(blocked["metadata"]["requested_family"], "governance_proposal")

    def test_session_tick_routes_non_snapshot_candidate_through_shared_contract(self) -> None:
        result = run_synapse(
            [
                "session-tick",
                "--summary",
                "Runtime capability expansion in routing.",
                "--file",
                "runtime/synapse.py",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        routing = payload["artifact_routing"]
        intent_kinds = {item["intent_kind"] for item in routing["result"]["intents"]}
        self.assertIn("upsert_quest_candidate", intent_kinds)
        self.assertTrue(
            any(item["target_family"] == "quest_candidate" for item in routing["result"]["intents"])
        )
        proposal_results = routing["dispatch"]["proposal_results"]
        self.assertTrue(any(Path(item["path"]).exists() for item in proposal_results if item.get("path")))

    def test_close_turn_routes_snapshot_and_publication_candidates_through_shared_contract(self) -> None:
        install_local_codex_integration(
            subject=self.subject,
            repo_root=self.engine_root,
            data_root=self.data_root,
            synapse_root=REPO_ROOT,
        )
        hooks = run_synapse(["install-hooks", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(hooks.returncode, 0, hooks.stdout + hooks.stderr)
        started = run_synapse(
            [
                "run-start",
                "--title",
                "Router close-turn fixture",
                "--plan-item",
                "Refresh routed candidates",
                "--session-id",
                "sid-router-close-turn",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self._seed_durable_continuity()
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="sid-router-close-turn",
            run_id="RUN-ROUTER-CLOSE-TURN",
        )

        result = run_synapse(["close-turn", "--strict", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        routing = payload["artifact_routing"]
        families = {item["target_family"] for item in routing["result"]["intents"]}
        self.assertIn("snapshot_candidate", families)
        self.assertIn("publication_candidate", families)
        self.assertEqual(payload["snapshot_candidates"]["snapshot_candidates"]["status"], "written")
        self.assertEqual(payload["publication_candidates"]["publication_candidates"]["status"], "written")
        self.assertTrue(Path(payload["snapshot_candidates"]["summary"]["current_eod_candidate_path"]).exists())
        self.assertTrue(Path(payload["publication_candidates"]["summary"]["current_story_candidate_path"]).exists())

    def test_run_finalize_routes_snapshot_and_publication_candidates_through_shared_contract(self) -> None:
        started = run_synapse(
            ["run-start", "--title", "Router finalize fixture", "--session-id", "sid-router-finalize", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self._seed_durable_continuity()
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="sid-router-finalize",
            run_id="RUN-ROUTER-FINALIZE",
        )

        result = run_synapse(["run-finalize", "--status", "completed", "--summary", "done", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        routing = payload["artifact_routing"]
        families = {item["target_family"] for item in routing["result"]["intents"]}
        self.assertIn("snapshot_candidate", families)
        self.assertIn("publication_candidate", families)
        self.assertTrue(Path(payload["snapshot_candidates"]["summary"]["current_eod_candidate_path"]).exists())
        self.assertTrue(Path(payload["publication_candidates"]["summary"]["current_story_candidate_path"]).exists())


if __name__ == "__main__":
    unittest.main()

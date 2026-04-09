import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.continuity_obligations import open_obligation
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_bridge import install_local_codex_integration
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(
    args: list[str],
    *,
    cwd: Path,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class CloseTurnValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "CloseTurnRepo"
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
            source_detail="test_close_turn_validation",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_close_turn_strict_stays_clear_for_noise_when_hooked(self) -> None:
        install_local_codex_integration(
            subject=self.subject,
            repo_root=self.engine_root,
            data_root=self.data_root,
            synapse_root=REPO_ROOT,
        )
        hooks = run_synapse(["install-hooks", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(hooks.returncode, 0, hooks.stdout + hooks.stderr)
        captured = run_synapse(
            ["record-raw-turn", "--role", "user", "--text", "ok", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)

        result = run_synapse(["close-turn", "--strict", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["validation_status"], "clear")
        self.assertEqual(payload["integration_posture"], "hooked")
        self.assertEqual(payload["open_continuity_obligation_count"], 0)
        self.assertEqual(payload["blocker_continuity_obligation_count"], 0)
        observer = payload["continuity_observer"]
        self.assertEqual(observer["observer_status"], "degraded")
        self.assertEqual(observer["observer_backend"], "noop")
        self.assertEqual(observer["observer_action_kinds"], [])

    def test_close_turn_strict_blocks_on_open_blocker_obligation(self) -> None:
        install_local_codex_integration(
            subject=self.subject,
            repo_root=self.engine_root,
            data_root=self.data_root,
            synapse_root=REPO_ROOT,
        )
        open_obligation(
            subject=self.subject,
            data_root=self.data_root,
            recorded_at="2026-04-01T10:00:00-04:00",
            obligation_kind="plan.capture.required",
            severity="blocker",
            summary="High-signal build plan still needs a lawful persisted plan revision.",
            required_record_families=["plan_revision"],
            source_segment_ids=["SEGMENT-001"],
            source_semantic_event_ids=["SEMANTIC-001"],
            source_refs=[{"kind": "semantic_event", "id": "SEMANTIC-001"}],
            metadata={"topic_key": "build.plan"},
        )

        result = run_synapse(["close-turn", "--strict", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["validation_status"], "blocked")
        self.assertTrue(payload["continuation_required"])
        self.assertEqual(payload["integration_posture"], "hooked")
        self.assertEqual(payload["blocker_continuity_obligation_count"], 1)
        self.assertEqual(payload["continuity_blockers"][0]["obligation_kind"], "plan.capture.required")

    def test_close_turn_refreshes_typed_snapshot_candidates_when_session_is_hooked(self) -> None:
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
                "Hooked boundary session",
                "--plan-item",
                "Refresh snapshot candidates",
                "--session-id",
                "sid-close-turn",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)

        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                {
                    "semantic_event_id": "SEMEVT-SCOPE",
                    "schema_version": 1,
                    "classifier_version": "v1-phase2",
                    "recorded_at": "2026-04-04T14:00:00-04:00",
                    "subject": self.subject,
                    "class_label": "project.scope",
                    "topic_key": "project.scope",
                    "confidence_band": "high",
                    "materiality_band": "high",
                    "summary": "Scope the session around installable web workflows.",
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
            title="Hooked close-turn fixture",
            summary="Create enough durable continuity to refresh typed candidates at close-turn.",
            origin="test",
            objective="Refresh typed snapshot candidates from a hooked close-turn boundary.",
            coherent_outcome="The close-turn boundary writes typed noncanonical snapshot candidates.",
            closure_statement="Typed candidate artifacts exist without mutating canonical snapshots.",
            out_of_scope="Canonical snapshot publication.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Run close-turn and inspect typed candidate paths.",
            milestones=["Persist durable sources", "Refresh typed candidates"],
            split_triggers=["Split if close-turn orchestration leaves the CLI owner."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )

        result = run_synapse(
            ["close-turn", "--strict", "--json"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["integration_posture"], "hooked")
        observer = payload["continuity_observer"]
        self.assertEqual(observer["observer_status"], "ok")
        self.assertEqual(observer["observer_backend"], "fixture")
        self.assertEqual(observer["observer_action_kinds"], ["semantic_capture"])
        self.assertTrue(Path(observer["observer_capture_artifact_path"]).exists())
        event_payload = payload["event"]["payload"]
        self.assertEqual(event_payload["signals"]["observer_action_kinds"], ["semantic_capture"])
        self.assertTrue(event_payload["signals"]["observer_triggered"])
        self.assertEqual(event_payload["outputs"]["observer_status"], "ok")
        self.assertEqual(event_payload["outputs"]["observer_backend"], "fixture")
        self.assertEqual(
            event_payload["outputs"]["capture_artifact_path"],
            observer["observer_capture_artifact_path"],
        )
        summary = payload["snapshot_candidates"]["summary"]
        self.assertTrue(summary["current_eod_candidate_path"])
        self.assertTrue(summary["current_control_sync_candidate_path"])
        self.assertTrue(Path(summary["current_eod_candidate_path"]).exists())
        self.assertTrue(Path(summary["current_control_sync_candidate_path"]).exists())

    def test_close_turn_downgrades_low_confidence_observer_decisions_to_obligations(self) -> None:
        install_local_codex_integration(
            subject=self.subject,
            repo_root=self.engine_root,
            data_root=self.data_root,
            synapse_root=REPO_ROOT,
        )
        fixture_json = json.dumps(
            {
                "observer_status": "ok",
                "provider_status": "fixture",
                "intents": [
                    {
                        "artifact_family": "decision_log",
                        "confidence": "low",
                        "rationale": "Low-confidence decision should not write the decision ledger directly.",
                        "payload": {
                            "title": "Premature decision",
                            "summary": "This should downgrade into review-safe follow-up instead.",
                        },
                    }
                ],
            }
        )
        result = run_synapse(
            ["close-turn", "--json"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={
                "SYNAPSE_CONTINUITY_OBSERVER_BACKEND": "fixture",
                "SYNAPSE_CONTINUITY_OBSERVER_FIXTURE_JSON": fixture_json,
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        observer = payload["continuity_observer"]
        self.assertEqual(observer["observer_action_kinds"], ["open_obligation"])
        self.assertIsNone(observer["observer_decision_path"])
        self.assertTrue(Path(observer["observer_obligation_path"]).exists())
        self.assertEqual(payload["event"]["payload"]["outputs"]["observer_obligation_path"], observer["observer_obligation_path"])


if __name__ == "__main__":
    unittest.main()

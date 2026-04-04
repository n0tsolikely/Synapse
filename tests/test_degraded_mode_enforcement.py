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
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class DegradedModeEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "DegradedRepo"
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
            source_detail="test_degraded_mode_enforcement",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_provenance_status_reports_degraded_mode_without_blocking_when_clean(self) -> None:
        result = run_synapse(["provenance-status", "--strict", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["integration_posture"], "degraded")
        self.assertEqual(payload["local_integration_health"], "missing")
        self.assertTrue(payload["degraded_mode"])
        self.assertEqual(payload["blocker_continuity_obligation_count"], 0)
        self.assertEqual(payload["provenance_status"], "caution")

    def test_degraded_mode_remains_explicit_when_strict_boundary_blocks_on_real_blocker(self) -> None:
        open_obligation(
            subject=self.subject,
            data_root=self.data_root,
            recorded_at="2026-04-01T10:30:00-04:00",
            obligation_kind="plan.capture.required",
            severity="blocker",
            summary="Persist the execution-grade build plan before leaving the boundary.",
            required_record_families=["plan_revision"],
            source_segment_ids=["SEGMENT-002"],
            source_semantic_event_ids=["SEMANTIC-002"],
            source_refs=[{"kind": "semantic_event", "id": "SEMANTIC-002"}],
            metadata={"topic_key": "build.plan"},
        )

        result = run_synapse(["provenance-status", "--strict", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["integration_posture"], "degraded")
        self.assertTrue(payload["degraded_mode"])
        self.assertEqual(payload["provenance_status"], "blocked")
        self.assertEqual(payload["blocker_continuity_obligation_count"], 1)
        self.assertEqual(payload["continuity_blockers"][0]["obligation_kind"], "plan.capture.required")

    def test_manual_close_turn_can_refresh_typed_candidates_while_staying_honest_about_degraded_posture(self) -> None:
        started = run_synapse(
            ["run-start", "--title", "Degraded boundary session", "--plan-item", "Refresh candidates manually", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)

        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                {
                    "semantic_event_id": "SEMEVT-ARCH",
                    "schema_version": 1,
                    "classifier_version": "v1-phase2",
                    "recorded_at": "2026-04-04T14:10:00-04:00",
                    "subject": self.subject,
                    "class_label": "architecture.shape",
                    "topic_key": "architecture.shape",
                    "confidence_band": "high",
                    "materiality_band": "high",
                    "summary": "Architecture direction moved toward installable account-backed workflows.",
                    "transient_noise": False,
                    "imported_limited": False,
                    "source_segment_ids": ["SEG-ARCH"],
                    "source_refs": [{"kind": "conversation_segment", "id": "SEG-ARCH", "path": "/tmp/SEG-ARCH.json"}],
                    "related_paths": [],
                }
            ],
        )
        persist_execution_plan(
            subject=self.subject,
            data_root=self.data_root,
            title="Degraded close-turn fixture",
            summary="Refresh typed candidates from an explicit degraded close-turn boundary.",
            origin="test",
            objective="Prove degraded posture stays honest while explicit close-turn refreshes candidates.",
            coherent_outcome="Manual close-turn writes typed candidates without pretending hook mediation existed.",
            closure_statement="Typed candidate artifacts exist and degraded posture remains explicit.",
            out_of_scope="Hook installation.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Run close-turn and inspect posture plus candidate paths.",
            milestones=["Persist durable sources", "Refresh candidates manually"],
            split_triggers=["Split if degraded posture begins implying automatic hook mediation."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )

        result = run_synapse(["close-turn", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["integration_posture"], "degraded")
        self.assertTrue(payload["degraded_mode"])
        summary = payload["snapshot_candidates"]["summary"]
        self.assertTrue(summary["current_eod_candidate_path"])
        self.assertTrue(summary["current_control_sync_candidate_path"])
        publication_summary = payload["publication_candidates"]["summary"]
        self.assertTrue(publication_summary["current_story_candidate_path"])


if __name__ == "__main__":
    unittest.main()

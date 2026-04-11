import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.draftshots import load_active_draftshot, refresh_draftshot
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class StaleDayRolloverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "StaleDaySubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        self.subject_args = [
            "--subject",
            self.subject,
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mark_draftshot_as_prior_day(self, *, session_id: str, prior_day: str) -> None:
        draftshot = load_active_draftshot(self.data_root, session_id=session_id)
        assert draftshot is not None
        prior_timestamp = f"{prior_day}T23:45:00-04:00"

        revision_path = Path(str(draftshot["path"]))
        revision_payload = yaml.safe_load(revision_path.read_text(encoding="utf-8"))
        revision_payload["created_at"] = prior_timestamp
        revision_payload["refreshed_at"] = prior_timestamp
        revision_path.write_text(yaml.safe_dump(revision_payload, sort_keys=False), encoding="utf-8")

        state_path = self.data_root / ".synapse" / "DRAFTSHOT_INDEX" / "STATE.yaml"
        state_payload = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        state_payload["active_sessions"][session_id]["refreshed_at"] = prior_timestamp
        state_payload["latest_revision"]["refreshed_at"] = prior_timestamp
        state_path.write_text(yaml.safe_dump(state_payload, sort_keys=False), encoding="utf-8")

    def test_session_start_refreshes_prior_day_eod_candidate_without_merging_into_new_day(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[
                {
                    "semantic_event_id": "SEMEVT-SCOPE",
                    "schema_version": 1,
                    "classifier_version": "v1-phase2",
                    "recorded_at": "2026-04-04T14:15:00-04:00",
                    "subject": self.subject,
                    "class_label": "project.scope",
                    "topic_key": "project.scope",
                    "confidence_band": "high",
                    "materiality_band": "high",
                    "summary": "Carry the website builder work forward as an installable product system.",
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
            title="Prior-day closeout",
            summary="Preserve yesterday's closeout context cleanly.",
            origin="test",
            objective="Refresh the prior-day EOD candidate on the next session start.",
            coherent_outcome="Yesterday's EOD candidate remains tied to yesterday.",
            closure_statement="The next session start refreshes the prior-day EOD candidate instead of merging it into today.",
            out_of_scope="Today's canonical snapshot.",
            dependencies=["None"],
            risk="R1",
            verification_plan="Start a new session and inspect the candidate target day.",
            milestones=["Seed durable sources", "Refresh prior-day candidate"],
            split_triggers=["Split if rollover requires canonical snapshot publication."],
            source_segment_ids=["SEG-PLAN"],
            source_semantic_event_ids=["SEMEVT-PLAN"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-PLAN", "path": "/tmp/SEG-PLAN.json"}],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="sess-yesterday",
            run_id="RUN-YESTERDAY",
        )
        prior_day = "2026-04-03"
        self._mark_draftshot_as_prior_day(session_id="sess-yesterday", prior_day=prior_day)

        result = run_synapse(
            ["session-start", "--title", "Today session", "--session-id", "sess-today", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        snapshot_candidates = payload["run"]["snapshot_candidates"]
        summary = snapshot_candidates["summary"]
        decision = dict(snapshot_candidates.get("decision") or {})

        self.assertEqual(snapshot_candidates["boundary"], "session-start")
        self.assertEqual(snapshot_candidates["target_day"], prior_day)
        self.assertEqual(decision["trigger_boundary"], "session-start")
        self.assertEqual(decision["snapshot_kind"], "EOD")
        self.assertEqual(decision["target_day"], prior_day)
        self.assertEqual(decision["candidate_action"], "refresh")
        self.assertEqual(decision["canonical_action"], "defer")
        self.assertEqual(decision["draftshot_action"], "preserve")
        self.assertTrue(summary["current_eod_candidate_path"])
        self.assertEqual(summary["current_eod_candidate_target_day"], prior_day)
        self.assertFalse(summary["stale_prior_day_candidate_required"])
        self.assertIn(
            f"Target Day: {prior_day}",
            Path(summary["current_eod_candidate_path"]).read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

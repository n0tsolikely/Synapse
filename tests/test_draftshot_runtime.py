import os
import re
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.draftshots import draftshot_summary, refresh_draftshot
from synapse_runtime.promotion_engine import promote_semantic_events
from synapse_runtime.quest_plans import persist_execution_plan
from synapse_runtime.sidecar_projection import refresh_synthesis_projection
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state

SNAPSHOT_WRITER = REPO_ROOT / "runtime" / "tools" / "synapse_snapshot_writer.py"


class DraftshotRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "DraftshotSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event(self, semantic_event_id: str, topic_key: str, summary: str) -> dict:
        return {
            "semantic_event_id": semantic_event_id,
            "schema_version": 1,
            "classifier_version": "v1-phase1",
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

    def test_refresh_draftshot_revisions_only_on_material_source_change(self) -> None:
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

        first = refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-draft-001",
            run_id="RUN-001",
        )
        self.assertEqual(first["status"], "written")
        first_body = Path(first["body_path"])
        self.assertTrue(first_body.exists())
        self.assertIn("- Status: ACTIVE", first_body.read_text(encoding="utf-8"))

        second = refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-draft-001",
            run_id="RUN-001",
        )
        self.assertEqual(second["status"], "noop")
        self.assertEqual(second["draftshot"]["current_active_draftshot_revision_id"], first["revision_id"])

        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[self._event("SEMEVT-ARCH", "architecture.shape", "Switch to a web app plus API architecture.")],
        )
        third = refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-draft-001",
            run_id="RUN-001",
        )
        self.assertEqual(third["status"], "updated")
        self.assertNotEqual(third["revision_id"], first["revision_id"])
        self.assertEqual(third["revision_number"], 2)
        self.assertIn("- Status: ACTIVE", first_body.read_text(encoding="utf-8"))
        self.assertIn("- Status: ACTIVE", Path(third["body_path"]).read_text(encoding="utf-8"))

        fourth = refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-draft-002",
            run_id="RUN-002",
        )
        self.assertEqual(fourth["status"], "written")
        self.assertEqual(fourth["draftshot"]["active_draftshot_count"], 2)
        self.assertIn("- Status: ACTIVE", Path(third["body_path"]).read_text(encoding="utf-8"))
        self.assertTrue(fourth["draftshot"]["draftshot_integrity_ok"])
        draftshot_text = Path(fourth["body_path"]).read_text(encoding="utf-8")
        for heading in (
            "B) Capture Index",
            "C) Decisions",
            "D) Findings / Observations",
            "E) TODO / Follow-ups",
            "F) Risks / Blockers",
            "G) Open Questions",
            "H) Running Log",
        ):
            self.assertIn(heading, draftshot_text)
        self.assertRegex(
            draftshot_text,
            r"(?:DECISION|DISCOVERY_CAPTURE|FOLLOWUP_CAPTURE|RISK_CAPTURE|QUESTION_CAPTURE)-[A-F0-9]{16}",
        )
        self.assertIn("[TRUTH]", draftshot_text)
        self.assertIn("[VISION]", draftshot_text)
        self.assertIn("[UNRESOLVED]", draftshot_text)
        revision_payload = yaml.safe_load(Path(fourth["revision_path"]).read_text(encoding="utf-8"))
        self.assertEqual(revision_payload["canonizer_schema_version"], 1)
        self.assertIn("capture_truth_state_counts", revision_payload)
        self.assertGreaterEqual(revision_payload["capture_truth_state_counts"]["TRUTH"], 1)

        auto_detect = subprocess.run(
            [
                sys.executable,
                str(SNAPSHOT_WRITER),
                "--subject",
                self.subject,
                "--data-root",
                str(self.data_root),
                "--allow-switch",
                "eod",
            ],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(auto_detect.returncode, 2, auto_detect.stdout + auto_detect.stderr)
        self.assertIn("multiple ACTIVE Draftshots found across sessions", auto_detect.stdout + auto_detect.stderr)

        explicit = subprocess.run(
            [
                sys.executable,
                str(SNAPSHOT_WRITER),
                "--subject",
                self.subject,
                "--data-root",
                str(self.data_root),
                "--allow-switch",
                "--draftshot",
                fourth["body_path"],
                "eod",
            ],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
        consumed_text = Path(fourth["body_path"]).read_text(encoding="utf-8")
        self.assertIn("DRAFTSHOT CONSUMPTION MARKER (AI11)", consumed_text)
        self.assertRegex(consumed_text, r"(?m)^- Status: CONSUMED$")
        self.assertIn("B) Capture Index", consumed_text)
        self.assertEqual(draftshot_summary(self.data_root)["active_draftshot_count"], 1)

    def test_refresh_projection_surfaces_active_draftshot_state(self) -> None:
        promote_semantic_events(
            subject=self.subject,
            data_root=self.data_root,
            semantic_events=[self._event("SEMEVT-SCOPE", "project.scope", "Scope the system around authenticated intake.")],
        )
        refresh_draftshot(
            subject=self.subject,
            data_root=self.data_root,
            session_id="syn-draft-002",
            run_id="RUN-002",
        )
        refresh_synthesis_projection(subject=self.subject, data_root=self.data_root)

        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        summary = draftshot_summary(self.data_root, session_id="syn-draft-002")

        self.assertEqual(state["current_active_draftshot_revision_id"], summary["current_active_draftshot_revision_id"])
        self.assertEqual(manifold["current_active_draftshot_path"], summary["current_active_draftshot_path"])
        self.assertEqual(manifold["current_active_draftshot_session_id"], "syn-draft-002")
        self.assertEqual(
            state["current_active_draftshot_truth_state_counts"],
            summary["current_active_draftshot_truth_state_counts"],
        )
        self.assertEqual(
            manifold["current_active_draftshot_truth_state_counts"],
            summary["current_active_draftshot_truth_state_counts"],
        )
        self.assertFalse(manifold["draftshot_stale"])
        self.assertTrue(manifold["draftshot_integrity_ok"])
        self.assertEqual(manifold["draftshot_integrity_issues"], [])


if __name__ == "__main__":
    unittest.main()

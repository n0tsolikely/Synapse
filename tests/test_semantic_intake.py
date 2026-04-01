import tempfile
import unittest
from pathlib import Path
import sys
import json
import os
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.governance_model import ProposalKind
from synapse_runtime.semantic_intake import (
    OPEN_QUESTIONS_MANAGED_MARKER,
    OPEN_QUESTIONS_SCAFFOLD,
    CaptureKind,
    CaptureSourceRole,
    SemanticIntakeError,
    build_capture_batch,
    derive_semantic_promotions,
    is_managed_open_questions_text,
    matches_open_questions_scaffold,
    normalize_capture_payload,
    render_managed_open_questions,
    semantic_events_from_capture_batch,
    semantic_detail_lists,
    write_capture_batch,
)
from synapse_runtime.reducer import ReducerError, reduce_after_event
from synapse_runtime.rehydrate_renderer import render_rehydrate
from synapse_runtime.sidecar_projection import reduce_sidecar_from_event
from synapse_runtime.sidecar_store import _default_manifold, _default_state, ensure_live_scaffold, live_root
from synapse_runtime.subject_bootstrap import initialize_subject_state
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
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class SemanticIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine_root = self.root / "engine"
        self.data_root = self.root / "Subject_Data"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src").mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (self.data_root / "Docs").mkdir(parents=True, exist_ok=True)
        (self.data_root / "Docs" / "note.md").write_text("# note\n", encoding="utf-8")
        self.run_data = {
            "run_id": "RUN-TEST",
            "session_id": "SESSION-TEST",
            "session_mode": "brainstorm_spec",
            "session_mode_source": "explicit",
            "session_mode_policy_version": 1,
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_canonical_enums_match_phase2_spec(self) -> None:
        self.assertEqual(
            [member.value for member in CaptureKind],
            [
                "idea",
                "question",
                "constraint",
                "decision",
                "unknown",
                "risk",
                "dependency",
                "repo_fact",
                "milestone",
                "non_goal",
            ],
        )
        self.assertEqual(
            [member.value for member in CaptureSourceRole],
            ["user", "agent", "imported", "repo_scan"],
        )

    def test_payload_requires_mapping_and_nonempty_capture_list(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload([], engine_root=self.engine_root, data_root=self.data_root)
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload({"captures": []}, engine_root=self.engine_root, data_root=self.data_root)
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload({"captures": "nope"}, engine_root=self.engine_root, data_root=self.data_root)

    def test_valid_capture_payload_normalizes_correctly(self) -> None:
        normalized = normalize_capture_payload(
            {
                "title": "Batch title",
                "tags": ["alpha", "alpha", "beta"],
                "captures": [
                    {
                        "kind": "question",
                        "summary": "  What owns replay?  ",
                        "detail": "  Need a deterministic answer. ",
                        "blocking": True,
                        "confidence": "high",
                        "tags": ["one", "one", "two"],
                    }
                ],
            },
            engine_root=self.engine_root,
            data_root=self.data_root,
        )
        self.assertEqual(normalized["title"], "Batch title")
        self.assertEqual(normalized["tags"], ["alpha", "beta"])
        self.assertEqual(normalized["captures"][0]["summary"], "What owns replay?")
        self.assertEqual(normalized["captures"][0]["detail"], "Need a deterministic answer.")
        self.assertEqual(normalized["captures"][0]["confidence"], "high")
        self.assertEqual(normalized["captures"][0]["tags"], ["one", "two"])

    def test_invalid_kind_is_rejected(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload(
                {"captures": [{"kind": "not-a-kind", "summary": "bad"}]},
                engine_root=self.engine_root,
                data_root=self.data_root,
            )

    def test_empty_summary_is_rejected(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload(
                {"captures": [{"kind": "idea", "summary": "   "}]},
                engine_root=self.engine_root,
                data_root=self.data_root,
            )

    def test_invalid_confidence_is_rejected(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload(
                {"captures": [{"kind": "idea", "summary": "x", "confidence": "certain"}]},
                engine_root=self.engine_root,
                data_root=self.data_root,
            )

    def test_blocking_is_rejected_for_disallowed_kinds(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            normalize_capture_payload(
                {"captures": [{"kind": "idea", "summary": "Ship it", "blocking": True}]},
                engine_root=self.engine_root,
                data_root=self.data_root,
            )

    def test_related_paths_normalize_against_engine_then_data(self) -> None:
        normalized = normalize_capture_payload(
            {
                "captures": [
                    {
                        "kind": "question",
                        "summary": "What owns this?",
                        "related_paths": [
                            "src/main.py",
                            "Docs/note.md",
                            "/tmp/not-under-engine-or-data.txt",
                        ],
                    }
                ]
            },
            engine_root=self.engine_root,
            data_root=self.data_root,
        )
        self.assertEqual(
            normalized["captures"][0]["related_paths"],
            ["src/main.py", "Docs/note.md", "/tmp/not-under-engine-or-data.txt"],
        )

    def test_build_capture_batch_assigns_stable_batch_and_item_ids(self) -> None:
        batch = build_capture_batch(
            subject="Subject",
            run_data=self.run_data,
            raw_text="Need a better sync loop",
            payload={
                "title": "Semantic slice",
                "captures": [
                    {"kind": "idea", "summary": "Add typed capture substrate"},
                    {"kind": "question", "summary": "How should replay load artifacts?", "blocking": True},
                ],
            },
            source_role="user",
            engine_root=self.engine_root,
            data_root=self.data_root,
            capture_batch_id="CAPTURE-20260317-120000-000001",
            captured_at="2026-03-17T12:00:00-04:00",
        )
        self.assertEqual(batch["capture_batch_id"], "CAPTURE-20260317-120000-000001")
        self.assertEqual(
            [item["capture_id"] for item in batch["captures"]],
            [
                "CAPTURE-20260317-120000-000001::ITEM-001",
                "CAPTURE-20260317-120000-000001::ITEM-002",
            ],
        )
        self.assertEqual(batch["session_mode"], "brainstorm_spec")
        self.assertEqual(batch["source_role"], "user")

    def test_build_capture_batch_requires_normalized_active_run_fields(self) -> None:
        with self.assertRaises(SemanticIntakeError):
            build_capture_batch(
                subject="Subject",
                run_data={"run_id": "RUN-TEST"},
                raw_text="raw",
                payload={"captures": [{"kind": "idea", "summary": "x"}]},
                source_role="user",
                engine_root=self.engine_root,
                data_root=self.data_root,
            )

    def test_write_capture_batch_persists_raw_artifact_and_daily_ledger(self) -> None:
        ensure_live_scaffold("Subject", self.data_root)
        receipt = write_capture_batch(
            subject="Subject",
            data_root=self.data_root,
            engine_root=self.engine_root,
            run_data=self.run_data,
            raw_text="Need to map blocking unknowns.",
            payload={
                "title": "Intake batch",
                "captures": [
                    {"kind": "unknown", "summary": "Blocking ambiguity", "blocking": True},
                    {"kind": "repo_fact", "summary": "Reducer already stamps state metadata"},
                ],
            },
            source_role="agent",
        )

        artifact_path = Path(receipt["artifact_path"])
        ledger_path = Path(receipt["ledger_path"])
        self.assertTrue(artifact_path.is_absolute())
        self.assertTrue(ledger_path.is_absolute())
        self.assertTrue(artifact_path.exists())
        self.assertTrue(ledger_path.exists())

        artifact = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["raw_text"], "Need to map blocking unknowns.")
        self.assertEqual(artifact["title"], "Intake batch")

    def test_capture_batches_bridge_into_noncanonical_semantic_events(self) -> None:
        batch = build_capture_batch(
            subject="Subject",
            run_data=self.run_data,
            raw_text="Need a plan and a locked decision.",
            payload={
                "captures": [
                    {"kind": "milestone", "summary": "Plan the installable web app scope."},
                    {"kind": "decision", "summary": "Use the existing reducer spine."},
                ]
            },
            source_role="user",
            engine_root=self.engine_root,
            data_root=self.data_root,
            capture_batch_id="CAPTURE-20260401-150000-000001",
            captured_at="2026-04-01T15:00:00-04:00",
        )
        batch["artifact_path"] = "/tmp/capture.yaml"
        semantic_events = semantic_events_from_capture_batch(batch)
        self.assertTrue(any(item.topic_key == "build.plan" for item in semantic_events))
        self.assertTrue(any(item.topic_key == "decision.locked" for item in semantic_events))
        self.assertEqual(len(batch["captures"]), 2)

    def test_semantic_promotion_mapping_is_batch_level_and_deduped(self) -> None:
        batch = build_capture_batch(
            subject="Subject",
            run_data=self.run_data,
            raw_text="Lots of semantics",
            payload={
                "captures": [
                    {"kind": "idea", "summary": "Create MCP intake"},
                    {"kind": "milestone", "summary": "Phase 2 slice ready"},
                    {"kind": "constraint", "summary": "No second truth store"},
                    {"kind": "dependency", "summary": "Reducer replay support"},
                    {"kind": "decision", "summary": "Keep decisions provisional"},
                    {"kind": "question", "summary": "How should unknowns render?", "blocking": True},
                ]
            },
            source_role="user",
            engine_root=self.engine_root,
            data_root=self.data_root,
            capture_batch_id="CAPTURE-TEST",
            captured_at="2026-03-17T12:00:00-04:00",
        )
        promotions = derive_semantic_promotions(batch)
        self.assertEqual(
            [promotion.kind for promotion in promotions],
            [
                ProposalKind.QUEST,
                ProposalKind.CODEX,
                ProposalKind.BUILD_MANUAL,
                ProposalKind.CONTROL_SYNC,
                ProposalKind.DISCLOSURE,
            ],
        )

    def test_render_managed_open_questions_keeps_marker_and_sections(self) -> None:
        batch = build_capture_batch(
            subject="Subject",
            run_data=self.run_data,
            raw_text="Questions",
            payload={
                "captures": [
                    {"kind": "question", "summary": "First blocking question", "blocking": True},
                    {"kind": "question", "summary": "Second nonblocking question"},
                    {"kind": "unknown", "summary": "Second nonblocking question"},
                    {"kind": "risk", "summary": "Risk does not belong in thread", "blocking": True},
                ]
            },
            source_role="user",
            engine_root=self.engine_root,
            data_root=self.data_root,
            capture_batch_id="CAPTURE-TEST",
            captured_at="2026-03-17T12:00:00-04:00",
        )
        details = semantic_detail_lists(batch)["open_question_details"]
        rendered = render_managed_open_questions(details)

        self.assertTrue(is_managed_open_questions_text(rendered))
        self.assertIn(OPEN_QUESTIONS_MANAGED_MARKER, rendered)
        self.assertIn("## Blocking", rendered)
        self.assertIn("## Nonblocking", rendered)
        self.assertIn("- First blocking question", rendered)
        self.assertIn("- Second nonblocking question", rendered)
        self.assertNotIn("Risk does not belong in thread", rendered)

    def test_scaffold_creates_capture_layout_and_semantic_defaults(self) -> None:
        receipt = ensure_live_scaffold("Subject", self.data_root)
        live = live_root(self.data_root)
        self.assertTrue((live / "CAPTURES").exists())
        self.assertTrue((live / "CAPTURES" / "BATCHES").exists())
        capture_ledgers = sorted((live / "CAPTURES").glob("*.yaml"))
        self.assertEqual(len(capture_ledgers), 1)
        ledger_payload = yaml.safe_load(capture_ledgers[0].read_text(encoding="utf-8"))
        self.assertEqual(ledger_payload["subject"], "Subject")
        self.assertEqual(ledger_payload["entries"], [])

        state = _default_state("Subject")
        manifold = _default_manifold("Subject")
        self.assertIn("last_capture_batch_id", state)
        self.assertIn("last_capture_at", state)
        self.assertIn("open_question_count", state)
        self.assertIn("blocking_question_count", state)
        self.assertIn("recent_capture_batch_ids", manifold)
        self.assertIn("open_question_details", manifold)
        self.assertIn("candidate_decision_details", manifold)
        self.assertTrue(receipt["live_root"])

    def test_open_question_scaffold_helper_matches_original_template(self) -> None:
        self.assertTrue(matches_open_questions_scaffold(OPEN_QUESTIONS_SCAFFOLD))


class CaptureChunkCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "SemanticSubject"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
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
            source_detail="test_semantic_intake",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_start(self) -> dict:
        result = run_synapse(
            ["run-start", "--title", "Semantic intake", "--json"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_SESSION_ID": "SESSION-INTAKE"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _session_start(self, mode: str) -> dict:
        result = run_synapse(
            ["session-start", "--title", "Semantic session", "--session-mode", mode, "--json"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_SESSION_ID": "SESSION-INTAKE"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _load_state(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))

    def _load_manifold(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))

    def test_capture_chunk_requires_active_run(self) -> None:
        result = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Need semantic capture.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "idea", "summary": "Create semantic intake"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("active run", payload["error"])

    def test_capture_chunk_succeeds_after_cli_only_session_creation_without_env(self) -> None:
        start = run_synapse(
            ["session-start", "--title", "CLI session", "--session-id", "sess-cli", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        active_run_path = self.data_root / ".synapse" / "ACTIVE_RUN.yaml"
        active_run = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
        self.assertEqual(active_run["session_id"], "sess-cli")

        result = run_synapse(
            [
                "capture-chunk",
                "--text",
                "CLI-only session continuity.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "idea", "summary": "Carry session continuity from active run"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["capture_artifact_path"]).exists())
        self.assertTrue(Path(payload["capture_ledger_path"]).exists())
        self.assertEqual(payload["event"]["payload"]["session_id"], "sess-cli")

    def test_capture_chunk_records_event_metadata_without_raw_text(self) -> None:
        self._run_start()
        result = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Raw chunk that must stay out of the event spine.",
                "--captures-json",
                json.dumps(
                    {
                        "title": "Semantic capture",
                        "captures": [
                            {"kind": "idea", "summary": "Use a typed capture store"},
                            {"kind": "question", "summary": "How should replay work?", "blocking": True},
                        ],
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["capture_batch_id"])
        self.assertEqual(len(payload["capture_ids"]), 2)
        self.assertTrue(Path(payload["capture_artifact_path"]).exists())
        self.assertTrue(Path(payload["capture_ledger_path"]).exists())
        self.assertTrue(payload["proposal_paths"])
        event_payload = payload["event"]["payload"]
        self.assertEqual(event_payload["action_name"], "capture-chunk")
        self.assertNotIn("raw_text", event_payload["signals"])
        self.assertEqual(event_payload["signals"]["capture_count"], 2)
        self.assertEqual(event_payload["signals"]["capture_source_role"], "user")
        self.assertEqual(event_payload["outputs"]["capture_artifact_path"], payload["capture_artifact_path"])

    def test_capture_chunk_thread_conflict_returns_partial_after_raw_write(self) -> None:
        self._run_start()
        thread_path = self.data_root / ".synapse" / "THREADS" / "open_questions.md"
        thread_path.write_text("# Custom Questions\n\nDo not overwrite this.\n", encoding="utf-8")
        result = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Need to track an open question.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "question", "summary": "Who owns replay?"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["runtime_status"]["operation_status"], "partial")
        self.assertTrue(payload["runtime_status"]["primary_mutation_committed"])
        self.assertFalse(payload["runtime_status"]["event_recorded"])
        self.assertFalse(payload["runtime_status"]["derived_state_current"])
        self.assertEqual(payload["runtime_status"]["error_code"], "SEMANTIC_PROJECTION_FAILED")
        self.assertTrue(Path(payload["capture_artifact_path"]).exists())
        self.assertTrue(Path(payload["capture_ledger_path"]).exists())
        self.assertIsNone(payload["event"])
        self.assertEqual(thread_path.read_text(encoding="utf-8"), "# Custom Questions\n\nDo not overwrite this.\n")

    def test_legacy_active_run_backfill_still_accepts_semantic_capture(self) -> None:
        self._run_start()
        active_run_path = self.data_root / ".synapse" / "ACTIVE_RUN.yaml"
        active_run = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
        active_run["interaction_mode"] = "decision"
        for key in (
            "session_mode",
            "session_mode_source",
            "session_mode_set_at",
            "session_mode_reason",
            "session_mode_policy_version",
        ):
            active_run.pop(key, None)
        active_run_path.write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")

        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Legacy backfill capture.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "constraint", "summary": "Backfill first, then capture"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        persisted = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["session_mode"], "control_sync")
        self.assertEqual(persisted["session_mode_source"], "legacy_backfill")

    def test_capture_chunk_repairs_missing_active_run_session_id_from_cli_context(self) -> None:
        start = run_synapse(
            ["session-start", "--title", "Repair session", "--session-id", "broken-sid", "--json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        active_run_path = self.data_root / ".synapse" / "ACTIVE_RUN.yaml"
        active_run = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
        active_run["session_id"] = None
        active_run_path.write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")

        capture = run_synapse(
            [
                "capture-chunk",
                "--session-id",
                "repaired-sid",
                "--text",
                "Repair broken active run session identity.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "constraint", "summary": "Repair before capture"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        persisted = yaml.safe_load(active_run_path.read_text(encoding="utf-8"))
        payload = json.loads(capture.stdout)
        self.assertEqual(persisted["session_id"], "repaired-sid")
        self.assertEqual(payload["event"]["payload"]["session_id"], "repaired-sid")

    def test_scaffold_thread_upgrades_to_managed_thread_and_excludes_risks(self) -> None:
        self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Open questions thread sync.",
                "--captures-json",
                json.dumps(
                    {
                        "captures": [
                            {"kind": "question", "summary": "Who owns semantic replay?"},
                            {"kind": "risk", "summary": "Risk should not render in thread", "blocking": True},
                        ]
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        thread_text = (self.data_root / ".synapse" / "THREADS" / "open_questions.md").read_text(encoding="utf-8")
        self.assertIn(OPEN_QUESTIONS_MANAGED_MARKER, thread_text)
        self.assertIn("Who owns semantic replay?", thread_text)
        self.assertNotIn("Risk should not render in thread", thread_text)

    def test_state_and_manifold_receive_semantic_summary_fields(self) -> None:
        self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Summary fanout.",
                "--captures-json",
                json.dumps(
                    {
                        "captures": [
                            {"kind": "idea", "summary": "Typed intake"},
                            {"kind": "constraint", "summary": "No shadow store"},
                            {"kind": "risk", "summary": "Replay drift", "blocking": True},
                            {"kind": "dependency", "summary": "Reducer replay"},
                            {"kind": "non_goal", "summary": "No NL inference yet"},
                            {"kind": "milestone", "summary": "Phase 2 shipped"},
                            {"kind": "decision", "summary": "Keep captures provisional"},
                            {"kind": "question", "summary": "What renders open questions?", "blocking": True},
                        ]
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        state = self._load_state()
        manifold = self._load_manifold()
        self.assertEqual(state["last_capture_batch_id"], json.loads(capture.stdout)["capture_batch_id"])
        self.assertTrue(state["last_capture_at"])
        self.assertGreaterEqual(state["open_question_count"], 1)
        self.assertGreaterEqual(state["blocking_question_count"], 1)
        self.assertTrue(manifold["recent_idea_details"])
        self.assertTrue(manifold["recent_constraint_details"])
        self.assertTrue(manifold["recent_risk_details"])
        self.assertTrue(manifold["recent_dependency_details"])
        self.assertTrue(manifold["recent_non_goal_details"])
        self.assertTrue(manifold["recent_milestone_details"])
        self.assertTrue(manifold["candidate_decision_details"])

    def test_capture_chunk_emits_only_one_quest_like_output_for_idea_batch(self) -> None:
        self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Quest-like semantic batch.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "idea", "summary": "Turn this into a tracked quest"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        payload = json.loads(capture.stdout)
        self.assertEqual(len(payload["proposal_paths"]), 1)

    def test_closeout_allows_capture_chunk_but_suppresses_quest_output(self) -> None:
        self._session_start("closeout")
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Closeout semantic batch.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "idea", "summary": "Post-closeout idea"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        payload = json.loads(capture.stdout)
        self.assertEqual(payload["runtime_status"]["operation_status"], "ok")
        self.assertEqual(payload["proposal_paths"], [])

    def test_brainstorm_capture_does_not_auto_formalize_quest_candidate(self) -> None:
        self._session_start("brainstorm_spec")
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Brainstorm semantic batch.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "idea", "summary": "Spec a new runtime surface"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        quest_board_files = list((self.data_root / "Quest Board").glob("*.txt"))
        self.assertEqual(quest_board_files, [])

    def test_capture_chunk_preserves_truth_boundaries(self) -> None:
        self._run_start()
        decisions_before = yaml.safe_load((self.data_root / ".synapse" / "DECISIONS" / next((self.data_root / ".synapse" / "DECISIONS").glob("*.yaml")).name).read_text(encoding="utf-8"))["entries"]
        disclosures_before = yaml.safe_load((self.data_root / ".synapse" / "DISCLOSURES" / next((self.data_root / ".synapse" / "DISCLOSURES").glob("*.yaml")).name).read_text(encoding="utf-8"))["entries"]
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Truth boundary batch.",
                "--captures-json",
                json.dumps(
                    {
                        "captures": [
                            {"kind": "decision", "summary": "This stays provisional"},
                            {"kind": "risk", "summary": "Needs disclosure proposal only", "blocking": True},
                        ]
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        payload = json.loads(capture.stdout)
        self.assertFalse(payload["event"]["payload"]["truth_flags"]["canon_mutated"])
        decisions_after = yaml.safe_load((self.data_root / ".synapse" / "DECISIONS" / next((self.data_root / ".synapse" / "DECISIONS").glob("*.yaml")).name).read_text(encoding="utf-8"))["entries"]
        disclosures_after = yaml.safe_load((self.data_root / ".synapse" / "DISCLOSURES" / next((self.data_root / ".synapse" / "DISCLOSURES").glob("*.yaml")).name).read_text(encoding="utf-8"))["entries"]
        self.assertEqual(len(decisions_after), len(decisions_before))
        self.assertEqual(len(disclosures_after), len(disclosures_before))

    def test_reducer_replay_rebuilds_semantic_state_without_duplicate_proposals(self) -> None:
        self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Typed semantics for replay.",
                "--captures-json",
                json.dumps(
                    {
                        "captures": [
                            {"kind": "idea", "summary": "Introduce replay-backed semantic capture"},
                            {"kind": "question", "summary": "Should replay load batch artifacts?", "blocking": True},
                        ]
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        payload = json.loads(capture.stdout)
        proposal_paths = list(payload["proposal_paths"])

        state_path = self.data_root / ".synapse" / "STATE.yaml"
        manifold_path = self.data_root / ".synapse" / "MANIFOLD.yaml"
        thread_path = self.data_root / ".synapse" / "THREADS" / "open_questions.md"
        state = self._load_state()
        manifold = self._load_manifold()
        state["last_capture_batch_id"] = None
        state["last_capture_at"] = None
        state["open_question_count"] = 0
        state["blocking_question_count"] = 0
        manifold["recent_capture_batch_ids"] = []
        manifold["open_question_details"] = []
        manifold["blocking_question_details"] = []
        manifold["recent_idea_details"] = []
        state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
        manifold_path.write_text(yaml.safe_dump(manifold, sort_keys=False), encoding="utf-8")
        thread_path.write_text(OPEN_QUESTIONS_SCAFFOLD, encoding="utf-8")

        replay = reduce_sidecar_from_event(
            subject=self.subject,
            data_root=self.data_root,
            event=payload["event"]["payload"],
        )
        self.assertEqual(replay["capture_batch_id"], payload["capture_batch_id"])
        self.assertEqual(replay["proposal_paths"], [])

        rebuilt_state = self._load_state()
        rebuilt_manifold = self._load_manifold()
        self.assertEqual(rebuilt_state["last_capture_batch_id"], payload["capture_batch_id"])
        self.assertGreaterEqual(rebuilt_state["open_question_count"], 1)
        self.assertTrue(rebuilt_manifold["recent_idea_details"])
        self.assertIn(OPEN_QUESTIONS_MANAGED_MARKER, thread_path.read_text(encoding="utf-8"))
        self.assertEqual([str(Path(path)) for path in proposal_paths], proposal_paths)

    def test_reducer_replay_fails_when_capture_artifact_is_missing(self) -> None:
        start = self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Missing artifact test.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "repo_fact", "summary": "Reducer stamps metadata"}]}),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        payload = json.loads(capture.stdout)
        artifact_path = Path(payload["capture_artifact_path"])
        artifact_path.unlink()

        with self.assertRaises(ReducerError):
            reduce_after_event(
                subject=self.subject,
                data_root=self.data_root,
                engine_root=self.engine_root,
                event=payload["event"]["payload"],
            )

    def test_render_rehydrate_refreshes_semantic_sections_from_raw_truth(self) -> None:
        self._run_start()
        capture = run_synapse(
            [
                "capture-chunk",
                "--text",
                "Render semantic truth.",
                "--captures-json",
                json.dumps(
                    {
                        "captures": [
                            {"kind": "question", "summary": "What owns semantic rendering?", "blocking": True},
                            {"kind": "repo_fact", "summary": "Rehydrate now has a semantic section"},
                            {"kind": "decision", "summary": "Keep capture batches provisional"},
                        ]
                    }
                ),
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)

        state = self._load_state()
        manifold = self._load_manifold()
        state["last_capture_batch_id"] = None
        state["open_question_count"] = 0
        manifold["open_question_details"] = []
        manifold["blocking_question_details"] = []
        manifold["recent_repo_fact_details"] = []
        manifold["candidate_decision_details"] = []
        (self.data_root / ".synapse" / "STATE.yaml").write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
        (self.data_root / ".synapse" / "MANIFOLD.yaml").write_text(yaml.safe_dump(manifold, sort_keys=False), encoding="utf-8")

        render_rehydrate(subject=self.subject, data_root=self.data_root)
        rendered = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Open questions", rendered)
        self.assertIn("What owns semantic rendering?", rendered)
        self.assertIn("## Recent semantic captures", rendered)
        self.assertIn("Rehydrate now has a semantic section", rendered)
        self.assertIn("Keep capture batches provisional", rendered)


if __name__ == "__main__":
    unittest.main()

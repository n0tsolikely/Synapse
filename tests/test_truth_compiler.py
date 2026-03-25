import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.current_state_publication import (
    PUBLICATION_FILENAMES,
    read_publication_metadata,
    render_publication_set,
    write_publication_set_atomic,
)
from synapse_runtime.doctor import run_doctor
from synapse_runtime.live_journal import log_decision
from synapse_runtime.project_model import evaluate_confirmation_readiness
from synapse_runtime.repo_onboarding import (
    default_onboarding_pointer,
    default_onboarding_session,
    onboarding_draft_path,
    onboarding_question_set_path,
    save_onboarding_pointer,
    save_onboarding_session,
)
from synapse_runtime.semantic_intake import write_capture_batch
from synapse_runtime.sidecar_store import ensure_live_scaffold, live_root
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.truth_compiler import (
    TruthCompilerPartialError,
    _apply_supersession_and_contradictions,
    _build_statements,
    _current_work_summary,
    _stale_active_run,
    canonical_truth_publication_paths,
    compile_current_state,
    compiler_report_path,
    load_compiler_report,
    load_statement_store,
    refresh_truth_status,
    statements_path,
    truth_publications_dir,
)
from synapse_runtime.truth_sources import (
    EvidenceRecord,
    TruthSourceError,
    decision_evidence,
    onboarding_publication_evidence,
    semantic_capture_evidence,
    workspace_receipt_evidence,
)
from synapse_runtime.truth_statements import (
    StatementKind,
    TruthLayer,
    TruthStatementError,
    normalize_statement_record,
    normalize_topic_key,
    statement_id_for,
    validate_provenance_ref,
)


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
    env.pop("SYNAPSE_SESSION_ID", None)
    env.pop("SUBJECT", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class TruthCompilerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "TruthSubject"
        self.engine_root = (self.root / "engine").resolve()
        self.data_root = (self.root / f"{self.subject}_Data").resolve()
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        (self.engine_root / "src").mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src" / "main.py").write_text("print('truth')\n", encoding="utf-8")
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

    def _active_run_path(self) -> Path:
        return live_root(self.data_root) / "ACTIVE_RUN.yaml"

    def _state_path(self) -> Path:
        return live_root(self.data_root) / "STATE.yaml"

    def _manifold_path(self) -> Path:
        return live_root(self.data_root) / "MANIFOLD.yaml"

    def _write_active_run(self, *, run_id: str = "RUN-1", updated_at: str = "2026-03-24T09:00:00-04:00") -> None:
        payload = yaml.safe_load(self._active_run_path().read_text(encoding="utf-8"))
        payload.update(
            {
                "active": True,
                "run_id": run_id,
                "subject": self.subject,
                "session_id": "SID-1",
                "title": "Truth run",
                "goal": "Compile state truth",
                "started_at": "2026-03-24T08:00:00-04:00",
                "updated_at": updated_at,
                "status": "active",
                "interaction_mode": "execution",
                "session_mode": "execution",
                "session_mode_source": "explicit",
                "session_mode_set_at": updated_at,
                "session_mode_reason": "test",
                "session_mode_policy_version": 1,
                "plan": {"items": [{"id": "ITEM-1", "text": "Finish truth compile", "status": "todo"}]},
            }
        )
        self._active_run_path().write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _write_onboarding_publication(self) -> None:
        live = live_root(self.data_root)
        (live / "PROJECT_MODEL.yaml").write_text(
            yaml.safe_dump(
                {
                    "onboarding_id": "ONBOARDING-1",
                    "confirmed_at": "2026-03-24T09:00:00-04:00",
                    "confirmed_by": "SID-1",
                    "project_identity": "Truth Subject",
                    "purpose": "Compile current project truth deterministically.",
                    "vision": "Durable machine-readable current state.",
                    "confirmed_capabilities": [
                        {
                            "id": "cap-implemented",
                            "summary": "Compiled truth publications exist.",
                            "detail": "Compiler writes statement/report/publication artifacts.",
                        }
                    ],
                    "partial_or_intended_capabilities": [
                        {
                            "id": "cap-planned",
                            "summary": "Future codex generation is planned.",
                            "detail": "Not part of Part 1.",
                            "status": "intended",
                        }
                    ],
                    "constraints": [
                        {
                            "id": "constraint-1",
                            "summary": "Truth stays machine-backed.",
                            "detail": "No hand-written narrative replacement.",
                        }
                    ],
                    "stale_or_superseded_directions": [
                        {
                            "id": "history-1",
                            "summary": "Direct raw-evidence rendering was replaced.",
                            "detail": "Compiler-owned publications superseded it.",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (live / "PROJECT_STORY.md").write_text("# Project Story\n\nCompiled truth story.\n", encoding="utf-8")
        (live / "VISION.md").write_text("# Vision\n\nDurable truth compiler.\n", encoding="utf-8")

    def _write_receipt(self, *, title: str, filename: str) -> Path:
        receipt_dir = self.root / "truth_Workspace" / "Receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        path = receipt_dir / filename
        path.write_text(f"# {title}\n\nReceipt body.\n", encoding="utf-8")
        return path

    def _write_capture(self, *, summary: str, kind: str = "idea") -> dict:
        run_data = {
            "run_id": "RUN-1",
            "session_id": "SID-1",
            "session_mode": "brainstorm_spec",
            "session_mode_source": "explicit",
            "session_mode_policy_version": 1,
        }
        return write_capture_batch(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            run_data=run_data,
            raw_text=summary,
            payload={"captures": [{"kind": kind, "summary": summary}]},
            source_role="user",
            title_override="Truth capture",
        )

    def _run_doctor(self) -> tuple[int, str]:
        receipt = {
            "subject": self.subject,
            "data_root": str(self.data_root),
            "engine_root": str(self.engine_root),
            "selected_at": "2026-03-24T09:00:00-04:00",
            "selected_by": "Tests",
            "selection_method": "test",
            "source_detail": "test",
        }
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = run_doctor(None, receipt)
        return code, stream.getvalue()

    def _write_truth_doctor_fixture(
        self,
        *,
        cycle_id: str,
        report_overrides: dict | None = None,
        state_overrides: dict | None = None,
        publication_cycle_id: str | None = None,
    ) -> None:
        live = live_root(self.data_root)
        truth_dir = live / "TRUTH"
        truth_dir.mkdir(parents=True, exist_ok=True)
        pubs_dir = truth_dir / "PUBLICATIONS"
        pubs_dir.mkdir(parents=True, exist_ok=True)
        publication_cycle = publication_cycle_id or cycle_id
        publication_paths = canonical_truth_publication_paths(self.data_root)
        for filename, path_text in publication_paths.items():
            path = Path(path_text)
            path.write_text(
                "---\n"
                + yaml.safe_dump({"compile_cycle_id": publication_cycle, "compiled_at": "2026-03-24T10:00:00-04:00"}, sort_keys=False)
                + "---\n\n# publication\n",
                encoding="utf-8",
            )
        report = {
            "schema_version": 1,
            "compile_cycle_id": cycle_id,
            "compiled_at": "2026-03-24T10:00:00-04:00",
            "statement_count": 1,
            "active_statement_count": 1,
            "contradiction_count": 0,
            "material_contradiction_count": 0,
            "superseded_count": 0,
            "truth_compile_stale": False,
            "truth_stale_reasons": [],
            "stale_active_run_detected": False,
            "unresolved_contradictions": [],
            "source_warnings": [],
            "external_source_warning_count": 0,
            "current_work_summary": {},
            "truth_publication_paths": publication_paths,
        }
        if report_overrides:
            report.update(report_overrides)
        compiler_report_path(self.data_root).write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        statements_path(self.data_root).write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "compile_cycle_id": cycle_id,
                    "compiled_at": "2026-03-24T10:00:00-04:00",
                    "statements": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        state = yaml.safe_load(self._state_path().read_text(encoding="utf-8"))
        state.update(
            {
                "last_truth_compile_at": "2026-03-24T10:00:00-04:00",
                "last_truth_compile_cycle_id": cycle_id,
                "truth_statement_count": 1,
                "truth_active_statement_count": 1,
                "truth_contradiction_count": 0,
                "truth_superseded_count": 0,
                "truth_compile_stale": False,
                "truth_stale_reasons": [],
                "truth_stale_active_run_detected": False,
            }
        )
        if state_overrides:
            state.update(state_overrides)
        self._state_path().write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    def _ready_onboarding_draft(self) -> tuple[dict, dict, dict]:
        draft = {
            "onboarding_id": "ONBOARDING-READY",
            "revision_id": "REVISION-READY",
            "supersedes_revision_id": None,
            "created_at": "2026-03-24T09:00:00-04:00",
            "based_on_scan_ids": ["SCAN-READY"],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Truth compiler subject",
            "purpose_hypothesis": "Compile current state truth.",
            "vision_hypothesis": "Durable current-state publications.",
            "maturity_hypothesis": "Active development.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [
                {
                    "id": "CAP-READY",
                    "summary": "Compiler writes current-state artifacts.",
                    "status": "implemented",
                    "confidence": "high",
                    "claim_basis": "scan_and_user",
                    "evidence_refs": ["scan:SCAN-READY:tree_inventory:item-1"],
                    "answer_refs": [],
                    "related_paths": [],
                    "supersedes": None,
                    "notes": None,
                }
            ],
            "component_hypotheses": [],
            "interface_hypotheses": [],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [],
            "history_and_supersession_hypotheses": [],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": [],
        }
        questions = {
            "onboarding_id": "ONBOARDING-READY",
            "question_set_id": "QUESTION_SET-READY",
            "draft_revision_id": "REVISION-READY",
            "generated_at": "2026-03-24T09:00:00-04:00",
            "questions": [],
        }
        session = default_onboarding_session(
            subject=self.subject,
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-READY",
            depth="deep",
            active_run_id="RUN-READY",
            session_id="SID-READY",
        )
        session["state"] = "awaiting_confirmation"
        session["scan_ids"] = ["SCAN-READY"]
        session["current_scan_id"] = "SCAN-READY"
        session["draft_revision_ids"] = ["REVISION-READY"]
        session["current_draft_id"] = "REVISION-READY"
        session["question_set_ids"] = ["QUESTION_SET-READY"]
        session["current_question_set_id"] = "QUESTION_SET-READY"
        session["unincorporated_capture_batch_ids"] = []
        readiness_ok, readiness_errors = evaluate_confirmation_readiness(
            onboarding_state=session["state"],
            current_scan_id=session["current_scan_id"],
            unincorporated_capture_batch_ids=session["unincorporated_capture_batch_ids"],
            draft=draft,
            question_set=questions,
        )
        self.assertTrue(readiness_ok, readiness_errors)
        return draft, questions, session


class TruthStatementModelTests(TruthCompilerFixture):
    def test_deterministic_statement_id_generation(self) -> None:
        one = statement_id_for(StatementKind.CAPABILITY, "CLI Layer", "Compiler writes truth")
        two = statement_id_for(StatementKind.CAPABILITY, "cli layer", "Compiler writes truth")
        self.assertEqual(one, two)
        self.assertTrue(one.startswith("STMT-capability-cli-layer-"))

    def test_topic_key_normalization(self) -> None:
        self.assertEqual(normalize_topic_key("  CLI / Layer :: truth  "), "cli-layer-truth")

    def test_statement_validation_rejects_invalid_truth_layer(self) -> None:
        with self.assertRaises(ValueError):
            normalize_statement_record(
                {
                    "statement_kind": "capability",
                    "summary": "Bad",
                    "detail": "",
                    "truth_layer": "wrong",
                    "confidence": "low",
                    "operator_confirmed": False,
                    "needs_expansion": False,
                    "topic_key": "bad",
                    "provenance_refs": [],
                    "derived_from_statement_ids": [],
                    "supersedes": [],
                    "superseded_by": [],
                    "contradicted_by": [],
                    "first_seen_at": "2026-03-24T10:00:00-04:00",
                    "last_reconciled_at": "2026-03-24T10:00:00-04:00",
                    "last_evidence_at": "2026-03-24T10:00:00-04:00",
                    "active": True,
                }
            )

    def test_provenance_validation_rejects_malformed_refs(self) -> None:
        with self.assertRaises(TruthStatementError):
            validate_provenance_ref(
                {
                    "source_type": "semantic_capture",
                    "source_id": "CAP-1",
                    "source_path": "/tmp/x.yaml",
                    "source_time": "2026-03-24T10:00:00-04:00",
                    "evidence_kind": "capability",
                    "confidence_hint": "high",
                }
            )


class TruthSourceAdapterTests(TruthCompilerFixture):
    def test_semantic_capture_adapter_normalization(self) -> None:
        self._write_capture(summary="Compiler should write current-state artifacts.")
        records, warnings = semantic_capture_evidence(data_root=self.data_root)
        self.assertFalse(warnings)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_type, "semantic_capture")
        self.assertEqual(records[0].statement_kind_hint, StatementKind.CAPABILITY.value)
        self.assertEqual(records[0].truth_layer_hint, TruthLayer.INTENDED.value)

    def test_decision_adapter_normalization(self) -> None:
        log_decision(
            subject=self.subject,
            data_root=self.data_root,
            title="Choose compiler",
            summary="Truth compiler becomes canonical.",
            why="Need deterministic current-state truth.",
            constraints=[],
            tradeoffs=[],
            related_runs=[],
            related_quests=[],
        )
        records, warnings = decision_evidence(data_root=self.data_root)
        self.assertFalse(warnings)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].statement_kind_hint, StatementKind.DECISION_SUMMARY.value)
        self.assertTrue(records[0].operator_confirmed)

    def test_onboarding_publication_adapter_normalization(self) -> None:
        self._write_onboarding_publication()
        records, warnings = onboarding_publication_evidence(data_root=self.data_root)
        self.assertFalse(warnings)
        kinds = {record.statement_kind_hint for record in records}
        self.assertIn(StatementKind.PROJECT_PURPOSE.value, kinds)
        self.assertIn(StatementKind.IDENTITY_CLAIM.value, kinds)
        self.assertIn(StatementKind.CAPABILITY.value, kinds)

    def test_malformed_canonical_source_hard_fails(self) -> None:
        ledger_path = live_root(self.data_root) / "DECISIONS" / "2026-03-24.yaml"
        ledger_path.write_text("entries: nope\n", encoding="utf-8")
        with self.assertRaises(TruthSourceError):
            decision_evidence(data_root=self.data_root)

    def test_malformed_external_receipt_warns_and_continues(self) -> None:
        receipt_dir = self.root / "truth_Workspace" / "Receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / "broken.md").write_text("no heading here\n", encoding="utf-8")
        records, warnings = workspace_receipt_evidence(data_root=self.data_root)
        self.assertEqual(records, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("skipped", warnings[0].message.lower())


class TruthCompilerBehaviorTests(TruthCompilerFixture):
    def test_implemented_precedence_over_intended_for_capability_claim(self) -> None:
        records = [
            EvidenceRecord(
                evidence_id="EVID-intended",
                source_type="onboarding_publication",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler writes current-state artifacts.",
                detail="Planned capability.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T09:00:00-04:00",
                topic_key_hint="compiler-artifacts",
                truth_layer_hint=TruthLayer.INTENDED.value,
                path_ref="/tmp/model.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=False,
                metadata={},
            ),
            EvidenceRecord(
                evidence_id="EVID-receipt",
                source_type="receipt",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler writes current-state artifacts.",
                detail="Completed and closed.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T10:00:00-04:00",
                topic_key_hint="compiler-artifacts",
                truth_layer_hint=TruthLayer.IMPLEMENTED.value,
                path_ref="/tmp/receipt.md",
                supersession_hint=None,
                implemented_hint=True,
                needs_expansion_hint=False,
                metadata={"completion_like": True},
            ),
        ]
        statements, statement_meta = _build_statements(data_root=self.data_root, records=records, compiled_at="2026-03-24T10:30:00-04:00")
        resolved = _apply_supersession_and_contradictions(statements, statement_meta=statement_meta)["statements"]
        self.assertEqual(resolved[0]["truth_layer"], TruthLayer.IMPLEMENTED.value)

    def test_supersession_writes_old_and_new_links(self) -> None:
        records = [
            EvidenceRecord(
                evidence_id="EVID-old",
                source_type="onboarding_publication",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler only writes markdown summaries.",
                detail="Older intent.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T08:00:00-04:00",
                topic_key_hint="compiler-surface",
                truth_layer_hint=TruthLayer.INTENDED.value,
                path_ref="/tmp/model.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=False,
                metadata={},
            ),
            EvidenceRecord(
                evidence_id="EVID-new",
                source_type="receipt",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler writes statements, reports, and publications.",
                detail="Completed receipt.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T10:00:00-04:00",
                topic_key_hint="compiler-surface",
                truth_layer_hint=TruthLayer.IMPLEMENTED.value,
                path_ref="/tmp/receipt.md",
                supersession_hint=None,
                implemented_hint=True,
                needs_expansion_hint=False,
                metadata={"completion_like": True},
            ),
        ]
        statements, statement_meta = _build_statements(data_root=self.data_root, records=records, compiled_at="2026-03-24T10:30:00-04:00")
        resolved = _apply_supersession_and_contradictions(statements, statement_meta=statement_meta)["statements"]
        old_statement = next(item for item in resolved if item["summary"].startswith("Compiler only writes markdown"))
        new_statement = next(item for item in resolved if item["summary"].startswith("Compiler writes statements"))
        self.assertEqual(old_statement["truth_layer"], TruthLayer.SUPERSEDED.value)
        self.assertFalse(old_statement["active"])
        self.assertEqual(old_statement["superseded_by"], [new_statement["statement_id"]])
        self.assertIn(old_statement["statement_id"], new_statement["supersedes"])

    def test_unresolved_contradiction_remains_active_and_counted(self) -> None:
        records = [
            EvidenceRecord(
                evidence_id="EVID-a",
                source_type="semantic_capture",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler should stay CLI-only.",
                detail="Idea A.",
                confidence_hint="medium",
                operator_confirmed=False,
                effective_time="2026-03-24T09:00:00-04:00",
                topic_key_hint="compiler-surface",
                truth_layer_hint=TruthLayer.INTENDED.value,
                path_ref="/tmp/a.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=True,
                metadata={},
            ),
            EvidenceRecord(
                evidence_id="EVID-b",
                source_type="semantic_capture",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Compiler should expose a service API.",
                detail="Idea B.",
                confidence_hint="medium",
                operator_confirmed=False,
                effective_time="2026-03-24T09:05:00-04:00",
                topic_key_hint="compiler-surface",
                truth_layer_hint=TruthLayer.INTENDED.value,
                path_ref="/tmp/b.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=True,
                metadata={},
            ),
        ]
        statements, statement_meta = _build_statements(data_root=self.data_root, records=records, compiled_at="2026-03-24T10:30:00-04:00")
        resolved = _apply_supersession_and_contradictions(statements, statement_meta=statement_meta)
        self.assertEqual(len(resolved["unresolved_contradictions"]), 1)
        for item in resolved["statements"]:
            self.assertTrue(item["active"])
            self.assertTrue(item["contradicted_by"])

    def test_speculative_and_intended_separation_is_preserved(self) -> None:
        records = [
            EvidenceRecord(
                evidence_id="EVID-intended",
                source_type="semantic_capture",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Add future codex generation.",
                detail="Intended feature.",
                confidence_hint="low",
                operator_confirmed=False,
                effective_time="2026-03-24T09:00:00-04:00",
                topic_key_hint="future-codex",
                truth_layer_hint=TruthLayer.INTENDED.value,
                path_ref="/tmp/intended.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=True,
                metadata={},
            ),
            EvidenceRecord(
                evidence_id="EVID-speculative",
                source_type="semantic_capture",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Maybe ship autonomous story synthesis.",
                detail="Speculative possibility.",
                confidence_hint="low",
                operator_confirmed=False,
                effective_time="2026-03-24T09:02:00-04:00",
                topic_key_hint="story-synthesis",
                truth_layer_hint=TruthLayer.SPECULATIVE.value,
                path_ref="/tmp/speculative.yaml",
                supersession_hint=None,
                implemented_hint=False,
                needs_expansion_hint=True,
                metadata={},
            ),
        ]
        statements, _ = _build_statements(data_root=self.data_root, records=records, compiled_at="2026-03-24T10:30:00-04:00")
        layers = {item["summary"]: item["truth_layer"] for item in statements}
        self.assertEqual(layers["Add future codex generation."], TruthLayer.INTENDED.value)
        self.assertEqual(layers["Maybe ship autonomous story synthesis."], TruthLayer.SPECULATIVE.value)

    def test_current_work_summary_derives_from_active_run_and_quest_state(self) -> None:
        active_run = {
            "run_id": "RUN-1",
            "title": "Truth work",
            "goal": "Compile truth",
            "result_summary": None,
            "plan": {"items": [{"id": "ITEM-1", "text": "Publish truth pack", "status": "todo"}]},
        }
        receipt_records = [
            EvidenceRecord(
                evidence_id="EVID-closure",
                source_type="receipt",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Closed old publication pack.",
                detail="Done.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T08:00:00-04:00",
                topic_key_hint="old-pack",
                truth_layer_hint=TruthLayer.IMPLEMENTED.value,
                path_ref="/tmp/closure.md",
                supersession_hint=None,
                implemented_hint=True,
                needs_expansion_hint=False,
                metadata={"completion_like": True},
            )
        ]
        summary = _current_work_summary(
            active_run=active_run,
            quest_state={"accepted": [{"quest_id": "QUEST_001", "title": "Truth compile quest"}], "completed": []},
            receipt_records=receipt_records,
            disclosure_records=[],
            statements=[],
            stale_active_run_detected=False,
        )
        self.assertEqual(summary["current_focus"], "Compile truth")
        self.assertEqual(summary["accepted_governed_work"], "Truth compile quest")
        self.assertEqual(summary["recently_completed"], ["Closed old publication pack."])
        self.assertEqual(summary["next_hint"], "Publish truth pack")

    def test_stale_active_run_detection_fires(self) -> None:
        active_run = {"run_id": "RUN-1", "updated_at": "2026-03-24T09:00:00-04:00"}
        completion_records = [
            EvidenceRecord(
                evidence_id="EVID-done",
                source_type="receipt",
                statement_kind_hint=StatementKind.CAPABILITY.value,
                summary="Completed compile.",
                detail="Done.",
                confidence_hint="high",
                operator_confirmed=True,
                effective_time="2026-03-24T10:00:00-04:00",
                topic_key_hint="compile",
                truth_layer_hint=TruthLayer.IMPLEMENTED.value,
                path_ref="/tmp/done.md",
                supersession_hint=None,
                implemented_hint=True,
                needs_expansion_hint=False,
                metadata={"completion_like": True},
            )
        ]
        self.assertTrue(_stale_active_run(active_run=active_run, completion_records=completion_records))


class TruthPublicationAndCliTests(TruthCompilerFixture):
    def test_publications_render_only_from_statement_store_and_report(self) -> None:
        statement_store = {
            "compile_cycle_id": "TRUTH-COMPILE-1",
            "compiled_at": "2026-03-24T10:00:00-04:00",
            "statements": [
                {
                    "statement_id": "STMT-capability-truth-aaaa1111",
                    "statement_kind": "capability",
                    "summary": "Compiled truth exists.",
                    "detail": "Rendered from store.",
                    "truth_layer": "implemented",
                    "confidence": "high",
                    "operator_confirmed": True,
                    "needs_expansion": False,
                    "topic_key": "truth",
                    "provenance_refs": [],
                    "derived_from_statement_ids": [],
                    "supersedes": [],
                    "superseded_by": [],
                    "contradicted_by": [],
                    "first_seen_at": "2026-03-24T10:00:00-04:00",
                    "last_reconciled_at": "2026-03-24T10:00:00-04:00",
                    "last_evidence_at": "2026-03-24T10:00:00-04:00",
                    "active": True,
                }
            ],
        }
        report = {
            "compile_cycle_id": "TRUTH-COMPILE-1",
            "compiled_at": "2026-03-24T10:00:00-04:00",
            "contradiction_count": 0,
            "truth_compile_stale": False,
            "stale_active_run_detected": False,
            "current_work_summary": {"current_focus": "Compile truth", "accepted_governed_work": None, "recently_completed": [], "blocked_state": None, "next_hint": "Publish truth pack"},
        }
        rendered = render_publication_set(statement_store=statement_store, compiler_report=report)
        self.assertIn("Compiled truth exists.", rendered[PUBLICATION_FILENAMES["current_state"]])
        self.assertNotIn("semantic_capture", rendered[PUBLICATION_FILENAMES["current_state"]])

    def test_cycle_id_is_consistent_across_report_and_publication_set(self) -> None:
        result = compile_current_state(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        report = load_compiler_report(self.data_root)
        self.assertEqual(result["compile_cycle_id"], report["compile_cycle_id"])
        for path_text in result["publication_paths"].values():
            metadata = read_publication_metadata(Path(path_text))
            self.assertEqual(metadata["compile_cycle_id"], report["compile_cycle_id"])

    def test_atomic_publication_replacement_works(self) -> None:
        pubs_dir = truth_publications_dir(self.data_root)
        pubs_dir.mkdir(parents=True, exist_ok=True)
        for filename in PUBLICATION_FILENAMES.values():
            (pubs_dir / filename).write_text("old\n", encoding="utf-8")
        rendered = {filename: f"new::{filename}\n" for filename in PUBLICATION_FILENAMES.values()}
        write_publication_set_atomic(publications_dir=pubs_dir, rendered=rendered)
        for filename in PUBLICATION_FILENAMES.values():
            self.assertEqual((pubs_dir / filename).read_text(encoding="utf-8"), f"new::{filename}\n")

    def test_publication_failure_after_statement_and_report_write_yields_partial_and_preserves_prior_set(self) -> None:
        pubs_dir = truth_publications_dir(self.data_root)
        pubs_dir.mkdir(parents=True, exist_ok=True)
        old_paths = {}
        for filename in PUBLICATION_FILENAMES.values():
            path = pubs_dir / filename
            path.write_text(f"old::{filename}\n", encoding="utf-8")
            old_paths[filename] = path.read_text(encoding="utf-8")
        with mock.patch("synapse_runtime.truth_compiler.write_publication_set_atomic", side_effect=RuntimeError("boom")):
            with self.assertRaises(TruthCompilerPartialError) as exc_info:
                compile_current_state(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        self.assertTrue(statements_path(self.data_root).exists())
        self.assertTrue(compiler_report_path(self.data_root).exists())
        for filename in PUBLICATION_FILENAMES.values():
            self.assertEqual((pubs_dir / filename).read_text(encoding="utf-8"), old_paths[filename])
        self.assertIn("statement_store_path", exc_info.exception.payload)

    def test_compile_current_state_writes_statement_store_report_and_publications(self) -> None:
        completed = run_synapse(["compile-current-state", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(Path(payload["statement_store_path"]).exists())
        self.assertTrue(Path(payload["compiler_report_path"]).exists())
        for path_text in payload["publication_paths"].values():
            self.assertTrue(Path(path_text).exists())

    def test_evidence_writing_command_marks_truth_stale_without_full_compile(self) -> None:
        compile_first = run_synapse(["compile-current-state", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(compile_first.returncode, 0, compile_first.stdout + compile_first.stderr)
        first_payload = json.loads(compile_first.stdout)
        cycle_id = first_payload["compile_cycle_id"]

        decision = run_synapse(
            [
                "log-decision",
                "--title",
                "Choose truth compiler",
                "--summary",
                "Compiler becomes canonical.",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(decision.returncode, 0, decision.stdout + decision.stderr)
        state = yaml.safe_load(self._state_path().read_text(encoding="utf-8"))
        self.assertTrue(state["truth_compile_stale"])
        self.assertIn("new_evidence_after_last_truth_compile", state["truth_stale_reasons"])
        self.assertEqual(state["last_truth_compile_cycle_id"], cycle_id)

    def test_onboarding_confirm_triggers_full_compile(self) -> None:
        draft, questions, session = self._ready_onboarding_draft()
        confirm_args = [
            "--subject",
            self.subject,
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
        ]
        self._write_active_run(run_id="RUN-READY")
        active_run = yaml.safe_load(self._active_run_path().read_text(encoding="utf-8"))
        active_run["run_id"] = "RUN-READY"
        active_run["session_id"] = "SID-READY"
        active_run["session_mode"] = "onboarding_existing_repo"
        active_run["session_mode_source"] = "explicit"
        active_run["session_mode_set_at"] = "2026-03-24T09:00:00-04:00"
        self._active_run_path().write_text(yaml.safe_dump(active_run, sort_keys=False), encoding="utf-8")
        save_onboarding_session(data_root=self.data_root, session=session)
        pointer = default_onboarding_pointer(self.subject)
        pointer["current_onboarding_id"] = session["onboarding_id"]
        save_onboarding_pointer(data_root=self.data_root, pointer=pointer)
        onboarding_draft_path(self.data_root, draft["revision_id"]).write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
        onboarding_question_set_path(self.data_root, questions["question_set_id"]).write_text(yaml.safe_dump(questions, sort_keys=False), encoding="utf-8")

        confirmed = run_synapse(["onboarding-confirm", "--yes-i-confirm", "--json", *confirm_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
        payload = json.loads(confirmed.stdout)
        self.assertIn("truth_compile", payload)
        self.assertTrue(payload["truth_compile"]["compile_cycle_id"].startswith("TRUTH-COMPILE-"))
        self.assertTrue(Path(payload["truth_compile"]["compiler_report_path"]).exists())

    def test_run_finalize_triggers_full_compile(self) -> None:
        started = run_synapse(["run-start", "--title", "Truth run", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        finalized = run_synapse(["run-finalize", "--summary", "done", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        payload = json.loads(finalized.stdout)
        self.assertIn("truth_compile", payload)
        self.assertTrue(payload["truth_compile"]["compile_cycle_id"].startswith("TRUTH-COMPILE-"))

    def test_doctor_warns_when_no_compile_exists(self) -> None:
        code, output = self._run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("WARN_NO_TRUTH_COMPILE", output)

    def test_doctor_warns_on_stale_compile_without_hard_fail(self) -> None:
        run_synapse(["compile-current-state", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        log_decision(
            subject=self.subject,
            data_root=self.data_root,
            title="Choose stale path",
            summary="New evidence after compile.",
            why=None,
            constraints=[],
            tradeoffs=[],
            related_runs=[],
            related_quests=[],
        )
        refresh_truth_status(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        code, output = self._run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("WARN_TRUTH_COMPILE_STALE", output)

    def test_doctor_fails_on_material_contradiction(self) -> None:
        self._write_truth_doctor_fixture(cycle_id="TRUTH-COMPILE-TEST-aaaa1111", report_overrides={"material_contradiction_count": 1})
        code, output = self._run_doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL_MATERIAL_TRUTH_CONTRADICTION", output)

    def test_doctor_fails_on_stale_active_run(self) -> None:
        self._write_truth_doctor_fixture(
            cycle_id="TRUTH-COMPILE-TEST-bbbb2222",
            report_overrides={"stale_active_run_detected": True},
            state_overrides={"truth_stale_active_run_detected": True},
        )
        code, output = self._run_doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL_STALE_ACTIVE_RUN_DETECTED", output)

    def test_doctor_fails_on_publication_report_cycle_mismatch(self) -> None:
        self._write_truth_doctor_fixture(
            cycle_id="TRUTH-COMPILE-TEST-cccc3333",
            publication_cycle_id="TRUTH-COMPILE-OTHER-dddd4444",
        )
        code, output = self._run_doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL_PUBLICATION_REPORT_CYCLE_MISMATCH", output)

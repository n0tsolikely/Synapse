import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.project_model import ProjectModelError, compute_revision_delta, validate_draft_revision, validate_question_set
from synapse_runtime.reducer import ReducerError, reduce_after_event
from synapse_runtime.repo_archaeology import ScanDepth, evidence_ref, run_repo_archaeology, stable_scan_item_id
from synapse_runtime.repo_onboarding import (
    RepoOnboardingError,
    canonical_codex_current_path,
    canonical_codex_future_path,
    current_onboarding_session,
    default_onboarding_session,
    default_onboarding_pointer,
    onboarding_confirm,
    onboarding_projection,
    onboarding_workplan_path,
    onboarding_session_path,
    reconstruct_onboarding_pointer,
    save_onboarding_pointer,
    save_onboarding_session,
    transition_onboarding_state,
)
from synapse_runtime.sidecar_store import ensure_live_scaffold

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


class RepoOnboardingSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine_root = self.root / "engine"
        self.data_root = self.root / "Subject_Data"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src").mkdir(parents=True, exist_ok=True)
        (self.engine_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (self.engine_root / "docs").mkdir(parents=True, exist_ok=True)
        (self.engine_root / "docs" / "README.md").write_text("# Engine\n", encoding="utf-8")
        (self.engine_root / "pyproject.toml").write_text("[project]\nname='engine'\n", encoding="utf-8")
        (self.engine_root / "TODO.md").write_text("TODO: tighten onboarding\n", encoding="utf-8")
        ensure_live_scaffold("Subject", self.data_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _base_draft(self) -> dict[str, object]:
        return {
            "onboarding_id": "ONBOARDING-1",
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": ["SCAN-1"],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Synapse runtime",
            "purpose_hypothesis": "Govern repo-local continuity.",
            "vision_hypothesis": "Durable machine-readable context.",
            "maturity_hypothesis": "Active development.",
            "user_or_stakeholder_hypotheses": [
                {
                    "id": "USER-1",
                    "summary": "Operators maintain governance and continuity.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="docs_inventory", item_id="abc")],
                    "answer_refs": [],
                }
            ],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "CLI manages continuity state.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="entrypoint_inventory", item_id="def")],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Runtime package contains reducer and sidecar flows.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="tree_inventory", item_id="ghi")],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "synapse.py is the primary CLI entrypoint.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="entrypoint_inventory", item_id="xyz")],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [
                {
                    "id": "CONS-1",
                    "summary": "Governance pack defines hard operating laws.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="docs_inventory", item_id="lmn")],
                    "answer_refs": [],
                }
            ],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML is used for artifact storage.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="manifest_inventory", item_id="123")],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo evolved through explicit phases.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="existing_continuity_inventory", item_id="phase")],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": ["Q-1"],
        }

    def _base_questions(self) -> dict[str, object]:
        return {
            "onboarding_id": "ONBOARDING-1",
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [
                {
                    "question_id": "Q-1",
                    "prompt": "What is the intended operator workflow?",
                    "category": "purpose",
                    "priority": "blocking",
                    "why_asked": "The code exposes multiple execution surfaces.",
                    "evidence_refs": [evidence_ref(scan_id="SCAN-1", section="docs_inventory", item_id="abc")],
                    "target_item_ids": ["CAP-1"],
                    "status": "open",
                    "answer_capture_batch_ids": [],
                }
            ],
        }

    def test_transition_validation_matches_phase3_graph(self) -> None:
        session = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-1",
            depth="deep",
            active_run_id="RUN-1",
            session_id="SID-1",
        )
        session = transition_onboarding_state(session, "needs_draft_submission")
        self.assertEqual(session["state"], "needs_draft_submission")
        session = transition_onboarding_state(session, "awaiting_user_clarification")
        self.assertEqual(session["state"], "awaiting_user_clarification")
        with self.assertRaises(RepoOnboardingError):
            transition_onboarding_state(session, "confirmed")

    def test_pointer_reconstruction_is_deterministic_and_rejects_ambiguity(self) -> None:
        first = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-1",
            depth="deep",
            active_run_id="RUN-1",
            session_id="SID-1",
        )
        first["state"] = "confirmed"
        first["confirmed_at"] = "2026-03-20T09:00:00-04:00"
        second = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-2",
            depth="deep",
            active_run_id="RUN-2",
            session_id="SID-2",
        )
        second["state"] = "needs_draft_submission"
        save_onboarding_session(data_root=self.data_root, session=first)
        save_onboarding_session(data_root=self.data_root, session=second)
        pointer = reconstruct_onboarding_pointer(subject="Subject", data_root=self.data_root)
        self.assertEqual(pointer["current_onboarding_id"], "ONBOARDING-2")
        self.assertEqual(pointer["latest_confirmed_onboarding_id"], "ONBOARDING-1")

        third = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-3",
            depth="deep",
            active_run_id="RUN-3",
            session_id="SID-3",
        )
        third["state"] = "needs_draft_submission"
        save_onboarding_session(data_root=self.data_root, session=third)
        with self.assertRaises(RepoOnboardingError):
            reconstruct_onboarding_pointer(subject="Subject", data_root=self.data_root)

    def test_draft_validation_rejects_missing_current_scan_and_unincorporated_answers(self) -> None:
        draft = self._base_draft()
        with self.assertRaises(ProjectModelError):
            validate_draft_revision(
                draft,
                onboarding_id="ONBOARDING-1",
                current_scan_id="SCAN-2",
                unincorporated_capture_batch_ids=[],
            )

        draft = self._base_draft()
        with self.assertRaises(ProjectModelError):
            validate_draft_revision(
                draft,
                onboarding_id="ONBOARDING-1",
                current_scan_id="SCAN-1",
                unincorporated_capture_batch_ids=["CAPTURE-1"],
            )

    def test_question_validation_requires_answer_capture_for_answered(self) -> None:
        draft = validate_draft_revision(
            self._base_draft(),
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
        )
        questions = self._base_questions()
        questions["questions"][0]["status"] = "answered"
        with self.assertRaises(ProjectModelError):
            validate_question_set(
                questions,
                onboarding_id="ONBOARDING-1",
                draft=draft,
                linked_capture_batch_ids=[],
            )

    def test_question_validation_allows_empty_question_set_for_confirmation_ready_revision(self) -> None:
        draft = validate_draft_revision(
            self._base_draft(),
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
        )
        questions = {
            "onboarding_id": "ONBOARDING-1",
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [],
        }
        normalized = validate_question_set(
            questions,
            onboarding_id="ONBOARDING-1",
            draft=draft,
            linked_capture_batch_ids=[],
        )
        self.assertEqual(normalized["questions"], [])

    def test_revision_delta_is_stable_by_item_id(self) -> None:
        prior = validate_draft_revision(
            self._base_draft(),
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
        )
        updated = self._base_draft()
        updated["revision_id"] = "REVISION-2"
        updated["supersedes_revision_id"] = "REVISION-1"
        updated["capability_hypotheses"][0]["summary"] = "CLI manages continuity and onboarding state."
        current = validate_draft_revision(
            updated,
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
            prior_draft=prior,
        )
        delta = compute_revision_delta(current, prior, reason_summary="Patched capability scope")
        self.assertEqual(delta["changed_item_ids"], ["CAP-1"])
        self.assertEqual(delta["new_item_ids"], [])

    def test_revision_delta_treats_full_snapshot_omission_as_removed(self) -> None:
        prior = validate_draft_revision(
            self._base_draft(),
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
        )
        updated = self._base_draft()
        updated["revision_id"] = "REVISION-2"
        updated["supersedes_revision_id"] = "REVISION-1"
        updated["interface_hypotheses"] = []
        current = validate_draft_revision(
            updated,
            onboarding_id="ONBOARDING-1",
            current_scan_id="SCAN-1",
            unincorporated_capture_batch_ids=[],
            prior_draft=prior,
        )
        delta = compute_revision_delta(current, prior, reason_summary="Dropped stale interface hypothesis")
        self.assertEqual(delta["removed_item_ids"], ["INT-1"])
        self.assertEqual(delta["new_item_ids"], [])

    def test_quick_and_deep_archaeology_write_bounded_artifacts_with_stable_ids(self) -> None:
        quick = run_repo_archaeology(
            onboarding_id="ONBOARDING-1",
            engine_root=self.engine_root,
            data_root=self.data_root,
            depth=ScanDepth.QUICK,
            scan_id="SCAN-QUICK",
            created_at="2026-03-20T10:00:00-04:00",
        )
        self.assertTrue(Path(quick["artifact_path"]).exists())
        self.assertIsNone(quick["scan"]["git_history_summary"])
        self.assertTrue(quick["scan"]["omissions"])

        deep_first = run_repo_archaeology(
            onboarding_id="ONBOARDING-1",
            engine_root=self.engine_root,
            data_root=self.data_root,
            depth=ScanDepth.DEEP,
            scan_id="SCAN-DEEP-1",
            created_at="2026-03-20T10:00:00-04:00",
        )
        deep_second = run_repo_archaeology(
            onboarding_id="ONBOARDING-1",
            engine_root=self.engine_root,
            data_root=self.data_root,
            depth=ScanDepth.DEEP,
            scan_id="SCAN-DEEP-2",
            created_at="2026-03-20T10:00:00-04:00",
        )
        first_ids = [item["item_id"] for item in deep_first["scan"]["docs_inventory"]]
        second_ids = [item["item_id"] for item in deep_second["scan"]["docs_inventory"]]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(
            stable_scan_item_id(section="docs_inventory", normalized_path="docs/README.md"),
            stable_scan_item_id(section="docs_inventory", normalized_path="docs/README.md"),
        )
        for section in (
            "subsystem_map",
            "capability_hypotheses",
            "history_signals",
            "contradiction_signals",
            "story_artifacts",
            "workspace_receipts",
            "spec_and_plan_artifacts",
            "unfinished_subsystems",
            "repo_scale_summary",
            "vision_signal_candidates",
        ):
            self.assertIn(section, deep_first["scan"])
        subsystem = deep_first["scan"]["subsystem_map"][0]
        self.assertIn("evidence_ref", subsystem)
        self.assertEqual(
            subsystem["evidence_ref"],
            evidence_ref(scan_id="SCAN-DEEP-1", section="subsystem_map", item_id=subsystem["item_id"]),
        )
        self.assertGreaterEqual(
            len(deep_first["scan"]["capability_hypotheses"]),
            len(deep_first["scan"]["entrypoint_inventory"]),
        )

    def test_projection_uses_confirmed_pointer_when_no_current_session_exists(self) -> None:
        session = default_onboarding_session(
            subject="Subject",
            engine_root=self.engine_root,
            data_root=self.data_root,
            onboarding_id="ONBOARDING-1",
            depth="deep",
            active_run_id="RUN-1",
            session_id="SID-1",
        )
        session["state"] = "confirmed"
        session["confirmed_at"] = "2026-03-20T11:00:00-04:00"
        save_onboarding_session(data_root=self.data_root, session=session)
        pointer = default_onboarding_pointer("Subject")
        pointer["latest_confirmed_onboarding_id"] = "ONBOARDING-1"
        save_onboarding_pointer(data_root=self.data_root, pointer=pointer)
        projection = onboarding_projection(subject="Subject", data_root=self.data_root)
        self.assertEqual(projection["latest_confirmed_onboarding_id"], "ONBOARDING-1")


class RepoOnboardingCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "project-onboard"
        self.home.mkdir(parents=True, exist_ok=True)
        self.repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=self.repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Synapse Tests"], cwd=self.repo, check=True, capture_output=True, text=True)
        (self.repo / "README.md").write_text("# Project Onboard\n", encoding="utf-8")
        (self.repo / "pyproject.toml").write_text("[project]\nname='project-onboard'\n", encoding="utf-8")
        (self.repo / "src").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (self.repo / "docs").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "ARCH.md").write_text("# Architecture\n", encoding="utf-8")
        self.extra_env = {"SYNAPSE_SESSION_ID": "sess-onboard"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _data_root(self) -> Path:
        return (self.repo.parent / f"{self.repo.name}_Data").resolve()

    def _onboarding_dir(self) -> Path:
        return self._data_root() / ".synapse" / "ONBOARDING"

    def _current_pointer(self) -> dict[str, Any]:
        return yaml.safe_load((self._onboarding_dir() / "CURRENT.yaml").read_text(encoding="utf-8"))

    def _session_payload(self, onboarding_id: str) -> dict[str, Any]:
        path = self._onboarding_dir() / "SESSIONS" / f"ONBOARDING__{onboarding_id}.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _workplan_payload(self, onboarding_id: str) -> dict[str, Any]:
        path = self._onboarding_dir() / "WORKPLANS" / f"ONBOARDING_WORKPLAN__{onboarding_id}.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _start_onboarding(self, *, extra_args: list[str] | None = None) -> dict[str, Any]:
        result = run_synapse(
            ["onboard-repo", "--json", *(extra_args or [])],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _confirmation_ready_draft(
        self,
        onboarding_id: str,
        scan_id: str,
        *,
        revision_id: str = "REVISION-1",
        supersedes_revision_id: str | None = None,
        based_on_capture_batch_ids: list[str] | None = None,
        answer_batch_id: str | None = None,
        purpose: str = "Exercise onboarding.",
    ) -> dict[str, Any]:
        answer_refs = [f"capture:{answer_batch_id}:CAPTURE-001"] if answer_batch_id else []
        capability = {
            "id": "CAP-1" if supersedes_revision_id is None else "CAP-2",
            "summary": "CLI can onboard an existing repo." if answer_batch_id is None else "CLI can onboard repos and preserve agent continuity.",
            "status": "partial",
            "confidence": "high",
            "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % scan_id],
            "answer_refs": answer_refs,
        }
        if supersedes_revision_id is not None:
            capability["supersedes"] = "CAP-1"
        return {
            "onboarding_id": onboarding_id,
            "revision_id": revision_id,
            "supersedes_revision_id": supersedes_revision_id,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": [scan_id],
            "based_on_capture_batch_ids": list(based_on_capture_batch_ids or []),
            "summary_hypothesis": "Project onboard",
            "purpose_hypothesis": purpose,
            "vision_hypothesis": "Track repo story.",
            "maturity_hypothesis": "Prototype.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [capability],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:tree_inventory:comp1" % scan_id],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:int1" % scan_id],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:manifest_inventory:dep1" % scan_id],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:existing_continuity_inventory:hist1" % scan_id],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": [],
        }

    def _question_set(
        self,
        onboarding_id: str,
        scan_id: str,
        *,
        draft_revision_id: str = "REVISION-1",
        question_set_id: str = "QUESTION_SET-1",
        status: str = "open",
        priority: str = "blocking",
        target_item_ids: list[str] | None = None,
        answer_capture_batch_ids: list[str] | None = None,
        include_question: bool = True,
    ) -> dict[str, Any]:
        questions: list[dict[str, Any]] = []
        if include_question:
            questions.append(
                {
                    "question_id": "Q-1",
                    "prompt": "What workflow matters most?",
                    "category": "purpose",
                    "priority": priority,
                    "why_asked": "Need explicit operator framing.",
                    "evidence_refs": ["scan:%s:docs_inventory:q1" % scan_id],
                    "target_item_ids": list(target_item_ids or ["CAP-1"]),
                    "status": status,
                    "answer_capture_batch_ids": list(answer_capture_batch_ids or []),
                }
            )
        return {
            "onboarding_id": onboarding_id,
            "question_set_id": question_set_id,
            "draft_revision_id": draft_revision_id,
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": questions,
        }

    def test_onboard_repo_creates_session_and_scan_then_resume_and_rescan_behave_deterministically(self) -> None:
        first = self._start_onboarding()
        self.assertTrue(Path(first["scan_artifact_path"]).exists())
        self.assertTrue(Path(first["analysis_brief_path"]).exists())
        self.assertTrue(Path(first["workplan_path"]).exists())
        pointer = self._current_pointer()
        self.assertEqual(pointer["current_onboarding_id"], first["onboarding_id"])
        session = self._session_payload(first["onboarding_id"])
        workplan = self._workplan_payload(first["onboarding_id"])
        self.assertEqual(session["current_workplan_id"], first["onboarding_id"])
        self.assertEqual(session["workplan_step_statuses"]["archaeology_complete"], "complete")
        self.assertEqual(workplan["workplan_id"], first["onboarding_id"])
        proposal_dir = self._data_root() / ".synapse" / "PROPOSALS"
        self.assertFalse(list(proposal_dir.glob("**/*.yaml")))

        resumed = self._start_onboarding()
        self.assertTrue(resumed["resumed_existing"])
        self.assertEqual(resumed["onboarding_id"], first["onboarding_id"])

        rescanned = self._start_onboarding(extra_args=["--rescan"])
        self.assertEqual(rescanned["onboarding_id"], first["onboarding_id"])
        self.assertNotEqual(rescanned["scan_id"], first["scan_id"])
        session = self._session_payload(first["onboarding_id"])
        self.assertEqual(session["state"], "needs_draft_submission")
        self.assertEqual(len(session["scan_ids"]), 2)

    def test_rehydrate_marks_draft_stale_after_rescan_even_without_new_clarifications(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        rescanned = self._start_onboarding(extra_args=["--rescan"])
        self.assertNotEqual(rescanned["scan_id"], first["scan_id"])

        status = run_synapse(
            ["onboarding-status", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        status_payload = json.loads(status.stdout)
        self.assertTrue(status_payload["draft_is_stale"])

        rehydrate = run_synapse(
            ["render-rehydrate", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(rehydrate.returncode, 0, rehydrate.stdout + rehydrate.stderr)
        manifold = yaml.safe_load((self._data_root() / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertTrue(manifold["draft_is_stale"])
        text = (self._data_root() / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("- Draft stale: YES", text)

    def test_deep_onboarding_scan_records_git_summary_when_repo_metadata_exists(self) -> None:
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=self.repo, check=True, capture_output=True, text=True)
        first = self._start_onboarding()
        scan = yaml.safe_load(Path(first["scan_artifact_path"]).read_text(encoding="utf-8"))
        self.assertIsInstance(scan["git_history_summary"], dict)
        self.assertTrue(scan["git_history_summary"]["current_branch"])
        self.assertTrue(scan["git_history_summary"]["recent_commits"])

    def test_onboard_repo_requires_allow_switch_when_active_run_is_not_onboarding(self) -> None:
        started = run_synapse(
            ["session-start", "--title", "Spec", "--session-mode", "brainstorm_spec", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        blocked = run_synapse(
            ["onboard-repo", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("onboarding_existing_repo", blocked.stdout + blocked.stderr)

    def test_onboard_repo_restart_abandons_current_nonterminal_session_and_starts_new_one(self) -> None:
        first = self._start_onboarding()
        restarted = self._start_onboarding(extra_args=["--restart"])
        self.assertNotEqual(restarted["onboarding_id"], first["onboarding_id"])
        pointer = self._current_pointer()
        self.assertEqual(pointer["current_onboarding_id"], restarted["onboarding_id"])
        prior_session = self._session_payload(first["onboarding_id"])
        self.assertEqual(prior_session["state"], "abandoned")
        self.assertEqual(prior_session["superseded_by_onboarding_id"], restarted["onboarding_id"])

    def test_onboard_repo_rescan_against_confirmed_session_without_restart_fails(self) -> None:
        self.test_onboarding_confirm_publishes_archived_and_canonical_artifacts_and_projects_state()
        blocked = run_synapse(
            ["onboard-repo", "--rescan", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("without --restart", blocked.stdout + blocked.stderr)

    def test_onboard_repo_returns_already_completed_and_status_targets_latest_confirmed(self) -> None:
        self.test_onboarding_confirm_publishes_archived_and_canonical_artifacts_and_projects_state()
        completed = run_synapse(
            ["onboard-repo", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        completed_payload = json.loads(completed.stdout)
        self.assertTrue(completed_payload["already_completed"])
        self.assertFalse(completed_payload["resumed_existing"])

        status = run_synapse(
            ["onboarding-status", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        status_payload = json.loads(status.stdout)
        self.assertEqual(status_payload["onboarding_id"], completed_payload["onboarding_id"])
        self.assertEqual(status_payload["latest_confirmed_onboarding_id"], completed_payload["onboarding_id"])
        self.assertEqual(status_payload["state"], "confirmed")

    def test_onboarding_update_and_respond_preserve_revision_loop(self) -> None:
        first = self._start_onboarding()
        draft = {
            "onboarding_id": first["onboarding_id"],
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": [first["scan_id"]],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Project onboard",
            "purpose_hypothesis": "Exercise onboarding.",
            "vision_hypothesis": "Track repo story.",
            "maturity_hypothesis": "Prototype.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "CLI can onboard an existing repo.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:tree_inventory:comp1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:int1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:manifest_inventory:dep1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:existing_continuity_inventory:hist1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": ["Q-1"],
        }
        questions = {
            "onboarding_id": first["onboarding_id"],
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [
                {
                    "question_id": "Q-1",
                    "prompt": "What workflow matters most?",
                    "category": "purpose",
                    "priority": "blocking",
                    "why_asked": "Need explicit operator framing.",
                    "evidence_refs": ["scan:%s:docs_inventory:q1" % first["scan_id"]],
                    "target_item_ids": ["CAP-1"],
                    "status": "open",
                    "answer_capture_batch_ids": [],
                }
            ],
        }
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        update_payload = json.loads(update.stdout)
        self.assertEqual(update_payload["onboarding_state"], "awaiting_user_clarification")

        respond = run_synapse(
            [
                "onboarding-respond",
                "--text",
                "Most of that is right, but this is also for agent continuity.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "repo_fact", "summary": "Also used for agent continuity"}]}),
                "--question-ids-json",
                json.dumps(["Q-1"]),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(respond.returncode, 0, respond.stdout + respond.stderr)
        respond_payload = json.loads(respond.stdout)
        self.assertEqual(respond_payload["onboarding_state"], "needs_draft_revision")
        self.assertEqual(respond_payload["linked_question_ids"], ["Q-1"])
        self.assertTrue(Path(respond_payload["capture_artifact_path"]).exists())
        session = self._session_payload(first["onboarding_id"])
        self.assertIn(respond_payload["capture_batch_id"], session["clarification_capture_batch_ids"])
        self.assertIn(respond_payload["capture_batch_id"], session["unincorporated_capture_batch_ids"])
        proposal_dir = self._data_root() / ".synapse" / "PROPOSALS"
        self.assertFalse(list(proposal_dir.glob("**/*.yaml")))

        revised_draft = {
            **draft,
            "revision_id": "REVISION-2",
            "supersedes_revision_id": "REVISION-1",
            "based_on_capture_batch_ids": [respond_payload["capture_batch_id"]],
            "capability_hypotheses": [
                {
                    "id": "CAP-2",
                    "summary": "CLI onboards repos and preserves agent continuity.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [f"capture:{respond_payload['capture_batch_id']}:CAPTURE-001"],
                    "supersedes": "CAP-1",
                }
            ],
            "next_question_ids": [],
        }
        revised_questions = {
            **questions,
            "question_set_id": "QUESTION_SET-2",
            "draft_revision_id": "REVISION-2",
            "questions": [
                {
                    **questions["questions"][0],
                    "target_item_ids": ["CAP-2"],
                    "status": "answered",
                    "priority": "blocking",
                    "answer_capture_batch_ids": [respond_payload["capture_batch_id"]],
                }
            ],
        }
        revised = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(revised_draft),
                "--questions-json",
                json.dumps(revised_questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        revised_payload = json.loads(revised.stdout)
        self.assertEqual(revised_payload["onboarding_state"], "awaiting_confirmation")
        self.assertEqual(revised_payload["revision_delta_id"], "REVISION-2")
        self.assertTrue(Path(revised_payload["draft_story_path"]).exists())
        self.assertTrue(Path(revised_payload["draft_vision_path"]).exists())
        self.assertTrue(Path(revised_payload["draft_codex_current_path"]).exists())
        self.assertTrue(Path(revised_payload["draft_codex_future_path"]).exists())
        workplan = self._workplan_payload(first["onboarding_id"])
        step_statuses = {item["step_id"]: item["status"] for item in workplan["steps"]}
        self.assertEqual(step_statuses["draft_story_written"], "complete")
        self.assertEqual(step_statuses["draft_current_codex_written"], "complete")
        self.assertEqual(step_statuses["clarification_incorporated"], "complete")
        self.assertEqual(step_statuses["confirmation_readiness_passed"], "complete")
        session = self._session_payload(first["onboarding_id"])
        self.assertEqual(session["unincorporated_capture_batch_ids"], [])

    def test_onboarding_response_batch_remains_unincorporated_until_revision_consumes_it(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        draft["next_question_ids"] = ["Q-1"]
        questions = self._question_set(first["onboarding_id"], first["scan_id"])
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        response = run_synapse(
            [
                "onboarding-respond",
                "--text",
                "Clarification to incorporate before publish.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "repo_fact", "summary": "Clarification to incorporate"}]}),
                "--question-ids-json",
                json.dumps(["Q-1"]),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
        response_payload = json.loads(response.stdout)

        session = self._session_payload(first["onboarding_id"])
        self.assertEqual(session["unincorporated_capture_batch_ids"], [response_payload["capture_batch_id"]])
        self.assertEqual(session["clarification_capture_batch_ids"], [response_payload["capture_batch_id"]])
        workplan = self._workplan_payload(first["onboarding_id"])
        step_statuses = {item["step_id"]: item["status"] for item in workplan["steps"]}
        self.assertEqual(step_statuses["clarification_incorporated"], "blocked")
        self.assertEqual(step_statuses["confirmation_readiness_passed"], "blocked")

        revised_draft = {
            **draft,
            "revision_id": "REVISION-2",
            "supersedes_revision_id": "REVISION-1",
            "based_on_capture_batch_ids": [response_payload["capture_batch_id"]],
            "capability_hypotheses": [
                {
                    "id": "CAP-2",
                    "summary": "CLI onboards repos with clarification-aware revision support.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [f"capture:{response_payload['capture_batch_id']}:CAPTURE-001"],
                    "supersedes": "CAP-1",
                }
            ],
            "next_question_ids": [],
        }
        revised_questions = {
            **questions,
            "question_set_id": "QUESTION_SET-2",
            "draft_revision_id": "REVISION-2",
            "questions": [
                {
                    **questions["questions"][0],
                    "target_item_ids": ["CAP-2"],
                    "status": "answered",
                    "answer_capture_batch_ids": [response_payload["capture_batch_id"]],
                }
            ],
        }
        revised = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(revised_draft),
                "--questions-json",
                json.dumps(revised_questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(revised.returncode, 0, revised.stdout + revised.stderr)
        session = self._session_payload(first["onboarding_id"])
        self.assertEqual(session["unincorporated_capture_batch_ids"], [])

    def test_onboarding_respond_from_awaiting_confirmation_moves_back_to_revision_needed(self) -> None:
        first = self._start_onboarding()
        draft = {
            "onboarding_id": first["onboarding_id"],
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": [first["scan_id"]],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Project onboard",
            "purpose_hypothesis": "Exercise onboarding.",
            "vision_hypothesis": "Track repo story.",
            "maturity_hypothesis": "Prototype.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "CLI can onboard an existing repo.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:tree_inventory:comp1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:int1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:manifest_inventory:dep1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:existing_continuity_inventory:hist1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": [],
        }
        questions = {
            "onboarding_id": first["onboarding_id"],
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [],
        }
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertEqual(json.loads(update.stdout)["onboarding_state"], "awaiting_confirmation")

        respond = run_synapse(
            [
                "onboarding-respond",
                "--text",
                "One more correction before publish.",
                "--captures-json",
                json.dumps({"captures": [{"kind": "repo_fact", "summary": "Clarification after ready state"}]}),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(respond.returncode, 0, respond.stdout + respond.stderr)
        self.assertEqual(json.loads(respond.stdout)["onboarding_state"], "needs_draft_revision")

    def test_onboarding_confirm_requires_explicit_confirmation_and_rejects_blocking_questions(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        draft["component_hypotheses"] = []
        draft["next_question_ids"] = ["Q-1"]
        questions = self._question_set(first["onboarding_id"], first["scan_id"])
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        missing_flag = run_synapse(
            ["onboarding-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(missing_flag.returncode, 2, missing_flag.stdout + missing_flag.stderr)
        blocked = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("blocking", (blocked.stdout + blocked.stderr).lower())

    def test_onboarding_confirm_rejects_tampered_draft_missing_required_field(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        draft_path = self._onboarding_dir() / "DRAFTS" / "PROJECT_MODEL_DRAFT__REVISION-1.yaml"
        draft_payload = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
        draft_payload["purpose_hypothesis"] = ""
        draft_path.write_text(yaml.safe_dump(draft_payload, sort_keys=False), encoding="utf-8")
        blocked = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("purpose_hypothesis", blocked.stdout + blocked.stderr)

    def test_onboarding_confirm_fails_when_current_draft_no_longer_includes_current_scan(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        draft_path = self._onboarding_dir() / "DRAFTS" / "PROJECT_MODEL_DRAFT__REVISION-1.yaml"
        draft_payload = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
        draft_payload["based_on_scan_ids"] = []
        draft_path.write_text(yaml.safe_dump(draft_payload, sort_keys=False), encoding="utf-8")
        blocked = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("current_scan_id", blocked.stdout + blocked.stderr)

    def test_onboarding_confirm_fails_when_unincorporated_capture_batches_remain(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        session_path = self._onboarding_dir() / "SESSIONS" / f"ONBOARDING__{first['onboarding_id']}.yaml"
        session = yaml.safe_load(session_path.read_text(encoding="utf-8"))
        session["unincorporated_capture_batch_ids"] = ["CAPTURE-LEFTOVER"]
        session_path.write_text(yaml.safe_dump(session, sort_keys=False), encoding="utf-8")
        blocked = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("clarification capture batches", blocked.stdout + blocked.stderr)

    def test_onboarding_abandon_marks_current_session_without_deleting_artifacts(self) -> None:
        first = self._start_onboarding()
        session_path = self._onboarding_dir() / "SESSIONS" / f"ONBOARDING__{first['onboarding_id']}.yaml"
        result = run_synapse(
            ["onboarding-abandon", "--reason", "Operator reset", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "abandoned")
        self.assertTrue(session_path.exists())
        pointer = self._current_pointer()
        self.assertIsNone(pointer["current_onboarding_id"])

    def test_onboarding_confirm_publishes_archived_and_canonical_artifacts_and_projects_state(self) -> None:
        first = self._start_onboarding()
        draft = {
            "onboarding_id": first["onboarding_id"],
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": [first["scan_id"]],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Project onboard",
            "purpose_hypothesis": "Exercise onboarding.",
            "vision_hypothesis": "Track repo story.",
            "maturity_hypothesis": "Prototype.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "CLI can onboard an existing repo.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:tree_inventory:comp1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:int1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:manifest_inventory:dep1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:existing_continuity_inventory:hist1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": [],
        }
        questions = {
            "onboarding_id": first["onboarding_id"],
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [
                {
                    "question_id": "Q-1",
                    "prompt": "What workflow matters most?",
                    "category": "purpose",
                    "priority": "important",
                    "why_asked": "Need explicit operator framing.",
                    "evidence_refs": ["scan:%s:docs_inventory:q1" % first["scan_id"]],
                    "target_item_ids": ["CAP-1"],
                    "status": "open",
                    "answer_capture_batch_ids": [],
                }
            ],
        }
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        update_payload = json.loads(update.stdout)
        self.assertEqual(update_payload["onboarding_state"], "awaiting_confirmation")

        confirm = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(confirm.returncode, 0, confirm.stdout + confirm.stderr)
        payload = json.loads(confirm.stdout)
        self.assertTrue(Path(payload["published_project_model_path"]).exists())
        self.assertTrue(Path(payload["published_project_story_path"]).exists())
        self.assertTrue(Path(payload["published_vision_path"]).exists())
        self.assertTrue(Path(payload["published_codex_current_path"]).exists())
        self.assertTrue(Path(payload["published_codex_future_path"]).exists())
        self.assertTrue(Path(payload["publication_receipt_path"]).exists())
        self.assertTrue(payload["proposal_paths"])
        self.assertEqual(payload["compile_status"], "ok")
        self.assertTrue(Path(payload["compiled_current_state_path"]).exists())

        pointer = self._current_pointer()
        self.assertIsNone(pointer["current_onboarding_id"])
        self.assertEqual(pointer["latest_confirmed_onboarding_id"], first["onboarding_id"])

        live = self._data_root() / ".synapse"
        state = yaml.safe_load((live / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((live / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["latest_confirmed_onboarding_id"], first["onboarding_id"])
        self.assertEqual(manifold["latest_confirmed_onboarding_id"], first["onboarding_id"])
        self.assertEqual(state["published_codex_current_path"], payload["published_codex_current_path"])
        self.assertEqual(state["published_codex_future_path"], payload["published_codex_future_path"])
        receipt = yaml.safe_load(Path(payload["publication_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["compile_status"], "ok")
        self.assertTrue(receipt["published_codex_current_path"])
        self.assertTrue(receipt["published_codex_future_path"])

        rehydrate = run_synapse(
            ["render-rehydrate", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(rehydrate.returncode, 0, rehydrate.stdout + rehydrate.stderr)
        text = (live / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Onboarding status", text)
        self.assertIn("## Published project model", text)
        self.assertIn("Current codex path:", text)
        self.assertIn("Future codex path:", text)

    def test_onboarding_confirm_partial_when_post_publication_compile_fails(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        from synapse_runtime.truth_compiler import TruthCompilerPartialError

        def explode_compile(*_: Any, **__: Any):
            raise TruthCompilerPartialError(
                "compile boom",
                payload={
                    "publication_paths": {
                        "current_state": str((self._data_root() / ".synapse" / "TRUTH" / "PUBLICATIONS" / "CURRENT_STATE.md").resolve())
                    }
                },
            )

        session = self._session_payload(first["onboarding_id"])
        active_run = yaml.safe_load((self._data_root() / ".synapse" / "ACTIVE_RUN.yaml").read_text(encoding="utf-8"))
        with mock.patch(
            "synapse_runtime.truth_compiler.compile_current_state",
            side_effect=explode_compile,
        ):
            payload = onboarding_confirm(
                subject="PROJECT-ONBOARD",
                data_root=self._data_root(),
                session=session,
                active_run=active_run,
            )
        self.assertEqual(payload["compile_status"], "partial")
        self.assertTrue(Path(payload["published_project_model_path"]).exists())
        receipt = yaml.safe_load(Path(payload["publication_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["compile_status"], "partial")
        self.assertTrue(receipt["published_codex_current_path"])
        self.assertTrue(receipt["published_codex_future_path"])

    def test_onboarding_confirm_bounds_long_proposal_filenames(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        draft["summary_hypothesis"] = (
            "OpenClaw in this repo is an upstream-derived multi-channel AI runtime that has been turned into the "
            "live local product state for Cinder by integrating the Wingman cognition sidecar, workspace identity "
            "overlays, and local governance/runtime conventions for a brutally long onboarding publication test."
        )
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        confirm = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(confirm.returncode, 0, confirm.stdout + confirm.stderr)
        payload = json.loads(confirm.stdout)
        self.assertTrue(payload["proposal_paths"])
        for raw_path in payload["proposal_paths"]:
            proposal_path = Path(raw_path)
            self.assertLess(len(proposal_path.name), 255)
            self.assertTrue(proposal_path.exists())

    def test_onboarding_confirm_writes_receipt_then_atomically_replaces_canonical_outputs_before_seeding_proposals(self) -> None:
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        session = self._session_payload(first["onboarding_id"])
        active_run = yaml.safe_load((self._data_root() / ".synapse" / "ACTIVE_RUN.yaml").read_text(encoding="utf-8"))
        events: list[str] = []
        real_replace = os.replace

        def record_receipt(path: Path, payload: dict[str, Any]) -> None:
            events.append("receipt")
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        def record_replace(src: Path, dest: Path) -> None:
            events.append(f"replace:{Path(dest).name}")
            real_replace(src, dest)

        def record_seed(**_: Any) -> list[str]:
            events.append("seed")
            return []

        with mock.patch("synapse_runtime.repo_onboarding._write_publication_receipt", side_effect=record_receipt), mock.patch(
            "synapse_runtime.repo_onboarding.os.replace",
            side_effect=record_replace,
        ), mock.patch("synapse_runtime.repo_onboarding.seed_onboarding_proposals", side_effect=record_seed):
            payload = onboarding_confirm(
                subject="PROJECT-ONBOARD",
                data_root=self._data_root(),
                session=session,
                active_run=active_run,
            )

        self.assertEqual(payload["proposal_paths"], [])
        self.assertGreaterEqual(events.count("receipt"), 2)
        self.assertEqual(events[0], "receipt")
        replace_events = [item for item in events if item.startswith("replace:")]
        self.assertEqual(
            replace_events[:5],
            [
                "replace:PROJECT_MODEL.yaml",
                "replace:PROJECT_STORY.md",
                "replace:VISION.md",
                "replace:CODEX_CURRENT.md",
                "replace:CODEX_FUTURE.md",
            ],
        )
        self.assertGreater(events.index("seed"), events.index("replace:CODEX_FUTURE.md"))

    def test_restart_after_confirmation_preserves_prior_archived_publication_and_current_canonical_until_replacement(self) -> None:
        self.test_onboarding_confirm_publishes_archived_and_canonical_artifacts_and_projects_state()
        live = self._data_root() / ".synapse"
        archived = list((live / "ONBOARDING" / "PUBLISHED").glob("PROJECT_MODEL__*.yaml"))
        self.assertEqual(len(archived), 1)
        canonical_text = (live / "PROJECT_MODEL.yaml").read_text(encoding="utf-8")

        restarted = run_synapse(
            ["onboard-repo", "--restart", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(restarted.returncode, 0, restarted.stdout + restarted.stderr)
        pointer = self._current_pointer()
        self.assertIsNotNone(pointer["current_onboarding_id"])
        self.assertEqual(len(list((live / "ONBOARDING" / "PUBLISHED").glob("PROJECT_MODEL__*.yaml"))), 1)
        self.assertEqual((live / "PROJECT_MODEL.yaml").read_text(encoding="utf-8"), canonical_text)

    def test_second_confirmed_onboarding_preserves_prior_archived_publications(self) -> None:
        self.test_onboarding_confirm_publishes_archived_and_canonical_artifacts_and_projects_state()
        restarted = self._start_onboarding(extra_args=["--restart"])
        draft = self._confirmation_ready_draft(
            restarted["onboarding_id"],
            restarted["scan_id"],
            revision_id="REVISION-SECOND",
            purpose="Refresh the published repo picture after restart.",
        )
        questions = self._question_set(
            restarted["onboarding_id"],
            restarted["scan_id"],
            draft_revision_id="REVISION-SECOND",
            question_set_id="QUESTION_SET-SECOND",
            include_question=False,
        )
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        confirm = run_synapse(
            ["onboarding-confirm", "--yes-i-confirm", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(confirm.returncode, 0, confirm.stdout + confirm.stderr)
        archived = list((self._data_root() / ".synapse" / "ONBOARDING" / "PUBLISHED").glob("PROJECT_MODEL__*.yaml"))
        self.assertEqual(len(archived), 2)

    def test_missing_onboarding_artifact_fails_reducer_refresh_explicitly(self) -> None:
        first = self._start_onboarding()
        draft = {
            "onboarding_id": first["onboarding_id"],
            "revision_id": "REVISION-1",
            "supersedes_revision_id": None,
            "created_at": "2026-03-20T10:00:00-04:00",
            "based_on_scan_ids": [first["scan_id"]],
            "based_on_capture_batch_ids": [],
            "summary_hypothesis": "Project onboard",
            "purpose_hypothesis": "Exercise onboarding.",
            "vision_hypothesis": "Track repo story.",
            "maturity_hypothesis": "Prototype.",
            "user_or_stakeholder_hypotheses": [],
            "capability_hypotheses": [
                {
                    "id": "CAP-1",
                    "summary": "CLI can onboard an existing repo.",
                    "status": "partial",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:cap1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "component_hypotheses": [
                {
                    "id": "COMP-1",
                    "summary": "Onboarding state lives in .synapse/ONBOARDING.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:tree_inventory:comp1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "interface_hypotheses": [
                {
                    "id": "INT-1",
                    "summary": "onboard-repo is the entry surface.",
                    "status": "implemented",
                    "confidence": "high",
                    "evidence_refs": ["scan:%s:entrypoint_inventory:int1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "constraint_hypotheses": [],
            "non_goal_hypotheses": [],
            "dependency_hypotheses": [
                {
                    "id": "DEP-1",
                    "summary": "PyYAML persists artifacts.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:manifest_inventory:dep1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "history_and_supersession_hypotheses": [
                {
                    "id": "HIST-1",
                    "summary": "Repo story is published only after confirmation.",
                    "status": "implemented",
                    "confidence": "medium",
                    "evidence_refs": ["scan:%s:existing_continuity_inventory:hist1" % first["scan_id"]],
                    "answer_refs": [],
                }
            ],
            "contradictions": [],
            "open_unknowns": [],
            "next_question_ids": [],
        }
        questions = {
            "onboarding_id": first["onboarding_id"],
            "question_set_id": "QUESTION_SET-1",
            "draft_revision_id": "REVISION-1",
            "generated_at": "2026-03-20T10:00:00-04:00",
            "questions": [],
        }
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        question_path = self._onboarding_dir() / "QUESTIONS" / "QUESTION_SET__QUESTION_SET-1.yaml"
        question_path.unlink()
        with self.assertRaises(ReducerError):
            reduce_after_event(
                subject="PROJECT-ONBOARD",
                data_root=self._data_root(),
                engine_root=self.repo,
                event=json.loads(update.stdout)["event"]["payload"],
                refresh_continuity=True,
            )

    def test_reducer_replay_rebuilds_onboarding_without_rerunning_archaeology(self) -> None:
        confirmed = run_synapse(
            ["session-start", "--title", "Onboard", "--session-mode", "onboarding_existing_repo", "--json"],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
        first = self._start_onboarding()
        draft = self._confirmation_ready_draft(first["onboarding_id"], first["scan_id"])
        questions = self._question_set(first["onboarding_id"], first["scan_id"], include_question=False)
        update = run_synapse(
            [
                "onboarding-update",
                "--draft-json",
                json.dumps(draft),
                "--questions-json",
                json.dumps(questions),
                "--json",
            ],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        event_payload = json.loads(update.stdout)["event"]["payload"]
        with mock.patch("synapse_runtime.repo_onboarding.run_repo_archaeology", side_effect=AssertionError("rescan not allowed")):
            replay = reduce_after_event(
                subject="PROJECT-ONBOARD",
                data_root=self._data_root(),
                engine_root=self.repo,
                event=event_payload,
                refresh_continuity=True,
            )
        self.assertEqual(replay["mode"], "active")


if __name__ == "__main__":
    unittest.main()

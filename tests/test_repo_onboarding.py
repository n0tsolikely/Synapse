import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.project_model import ProjectModelError, compute_revision_delta, validate_draft_revision, validate_question_set
from synapse_runtime.repo_archaeology import ScanDepth, evidence_ref, run_repo_archaeology, stable_scan_item_id
from synapse_runtime.repo_onboarding import (
    RepoOnboardingError,
    current_onboarding_session,
    default_onboarding_session,
    default_onboarding_pointer,
    onboarding_projection,
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

    def _start_onboarding(self, *, extra_args: list[str] | None = None) -> dict[str, Any]:
        result = run_synapse(
            ["onboard-repo", "--json", *(extra_args or [])],
            cwd=self.repo,
            home=self.home,
            extra_env=self.extra_env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_onboard_repo_creates_session_and_scan_then_resume_and_rescan_behave_deterministically(self) -> None:
        first = self._start_onboarding()
        self.assertTrue(Path(first["scan_artifact_path"]).exists())
        self.assertTrue(Path(first["analysis_brief_path"]).exists())
        pointer = self._current_pointer()
        self.assertEqual(pointer["current_onboarding_id"], first["onboarding_id"])

        resumed = self._start_onboarding()
        self.assertTrue(resumed["resumed_existing"])
        self.assertEqual(resumed["onboarding_id"], first["onboarding_id"])

        rescanned = self._start_onboarding(extra_args=["--rescan"])
        self.assertEqual(rescanned["onboarding_id"], first["onboarding_id"])
        self.assertNotEqual(rescanned["scan_id"], first["scan_id"])
        session = self._session_payload(first["onboarding_id"])
        self.assertEqual(session["state"], "needs_draft_submission")
        self.assertEqual(len(session["scan_ids"]), 2)

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
        self.assertTrue(Path(respond_payload["capture_artifact_path"]).exists())
        session = self._session_payload(first["onboarding_id"])
        self.assertIn(respond_payload["capture_batch_id"], session["clarification_capture_batch_ids"])
        self.assertIn(respond_payload["capture_batch_id"], session["unincorporated_capture_batch_ids"])

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
        self.assertTrue(Path(payload["publication_receipt_path"]).exists())
        self.assertTrue(payload["proposal_paths"])

        pointer = self._current_pointer()
        self.assertIsNone(pointer["current_onboarding_id"])
        self.assertEqual(pointer["latest_confirmed_onboarding_id"], first["onboarding_id"])

        live = self._data_root() / ".synapse"
        state = yaml.safe_load((live / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((live / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["latest_confirmed_onboarding_id"], first["onboarding_id"])
        self.assertEqual(manifold["latest_confirmed_onboarding_id"], first["onboarding_id"])

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


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.quest_acceptance import parse_quest_document
from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]
SNAPSHOT_WRITER = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_snapshot_writer.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def run_snapshot_writer(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SNAPSHOT_WRITER + args, cwd=cwd, env=env, capture_output=True, text=True)


class QuestRuntimeRefactorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "QuestRefactor"
        self.data_root = self.root / f"{self.subject}_Data"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
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

    def _write_codex_freeze(self) -> None:
        freeze = self.data_root / "Codex" / "CODEX_FREEZE.md"
        freeze.parent.mkdir(parents=True, exist_ok=True)
        freeze.write_text("# CODEX FREEZE\n\nBrains Approval: YES\nDate: 2026-03-31\n", encoding="utf-8")

    def _open_control_sync(self) -> None:
        result = run_snapshot_writer(
            [
                "--subject",
                self.subject,
                "--data-root",
                str(self.data_root),
                "--allow-switch",
                "control-open",
                "--participants",
                "Brains, Hands",
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _plan_quests(self, *extra_args: str) -> dict:
        base = [
            "plan-quests",
            "--json",
            "--anchor",
            "6.5",
            "--anchor",
            "9.2",
            "--constraint",
            "Keep quest ids and board layout stable.",
            "--change-class",
            "FEATURE",
            "--vision-delta",
            "ALIGNED",
            "--door-impact",
            "Runtime",
            "--testing-level",
            "TL2",
            *self.subject_args,
        ]
        result = run_synapse(base + list(extra_args), cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _accept(self, quest_path: str) -> dict:
        self._write_codex_freeze()
        self._open_control_sync()
        result = run_synapse(["accept-quest", quest_path, "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def _complete(self, quest_ref: str, *extra_args: str) -> dict:
        result = run_synapse(["complete-quest", quest_ref, "--json", *extra_args, *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_plan_quests_single_outcome_persists_plan_and_one_board_quest(self) -> None:
        payload = self._plan_quests(
            "--title",
            "Quest runtime refactor",
            "--goal",
            "Persist runtime execution plans and close quests with completion audits.",
            "--item",
            "Persist execution-ready plans under .synapse/PLANS.",
            "--item",
            "Close quests only through clean PASS completion audits.",
        )

        self.assertEqual(len(payload["quests"]), 1)
        plan_path = Path(payload["plan_artifact_path"])
        quest_path = Path(payload["quests"][0]["path"])
        self.assertTrue(plan_path.exists())
        self.assertTrue(quest_path.exists())

        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["revision_number"], 1)
        self.assertEqual(len(plan["milestones"]), 2)
        self.assertEqual(plan["quest_refs"], [str(quest_path.resolve())])

        doc = parse_quest_document(subject=self.subject, data_root=self.data_root, path=quest_path)
        self.assertEqual(doc.quest_state, "BOARD")
        self.assertIn(str(plan_path.resolve()), doc.plan_artifact_refs)
        self.assertIn("completion audit returns PASS", doc.closure_statement)

    def test_plan_quests_splits_multiple_independently_closable_outcomes(self) -> None:
        payload = self._plan_quests(
            "--title",
            "Quest runtime split",
            "--goal",
            "Separate MCP transport work from governed wrapper work.",
            "--separate-outcome",
            "MCP transport",
            "--separate-outcome",
            "Governed wrapper",
            "--item",
            "MCP transport :: Add complete_quest MCP tool.",
            "--item",
            "MCP transport :: Add plan_quests MCP tool.",
            "--item",
            "Governed wrapper :: Update the governed wrapper to call complete-quest.",
        )

        self.assertEqual(len(payload["quests"]), 2)
        self.assertEqual({entry["plan_id"] for entry in payload["quests"]}, {payload["plan_id"]})
        self.assertEqual({entry["plan_artifact_path"] for entry in payload["quests"]}, {payload["plan_artifact_path"]})

        plan = yaml.safe_load(Path(payload["plan_artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(plan["quest_refs"]), 2)
        self.assertEqual(plan["revision_number"], 1)

    def test_plan_quests_supports_full_dungeon_single_quest(self) -> None:
        payload = self._plan_quests(
            "--title",
            "Close the full dungeon",
            "--goal",
            "Finish the entire dungeon as one coherent bounded outcome.",
            "--dungeon-ref",
            "DUNGEON-001",
            "--dungeon-coverage",
            "FULL_DUNGEON",
            "--item",
            "Close the full dungeon and prove all milestones cleanly.",
        )

        self.assertEqual(len(payload["quests"]), 1)
        quest_path = Path(payload["quests"][0]["path"])
        doc = parse_quest_document(subject=self.subject, data_root=self.data_root, path=quest_path)
        self.assertEqual(doc.dungeon_ref, "DUNGEON-001")
        self.assertEqual(doc.dungeon_coverage, "FULL_DUNGEON")

    def test_complete_quest_failure_loop_and_pass_completion(self) -> None:
        draft = self._plan_quests(
            "--title",
            "Quest completion loop",
            "--goal",
            "Exercise fail then pass completion flow.",
            "--item",
            "Materialize the accepted quest bundle.",
            "--item",
            "Record a clean completion audit.",
        )
        accepted = self._accept(draft["quests"][0]["path"])
        accepted_path = Path(accepted["acceptance"]["accepted_path"])
        bundle_path = Path(accepted["acceptance"]["audit_bundle_path"])

        failed = self._complete(
            accepted_path.name,
            "--milestone-status",
            "MILESTONE-001:DONE:Bundle materialized.",
            "--milestone-status",
            "MILESTONE-002:PENDING:Completion audit still incomplete.",
            "--check",
            "UNIT_TESTS:PASS:Targeted quest tests passed.",
            "--receipt-ref",
            str(bundle_path / "06_TESTS.txt"),
            "--command-run",
            "python3 -m unittest tests.test_quest_runtime_refactor -v",
        )
        self.assertEqual(failed["completion"]["overall_verdict"], "FAIL")
        self.assertEqual(failed["completion"]["final_state_decision"], "ACTIVE")
        self.assertIn("/Accepted/", failed["completion"]["active_path"])
        self.assertTrue(Path(failed["completion"]["latest_completion_audit_path"]).exists())

        passed = self._complete(
            accepted_path.name,
            "--milestone-status",
            "MILESTONE-001:DONE:Bundle materialized.",
            "--milestone-status",
            "MILESTONE-002:DONE:Completion audit closed cleanly.",
            "--check",
            "UNIT_TESTS:PASS:Targeted quest tests passed.",
            "--check",
            "GOVERNANCE:PASS:Completion audit receipts are present.",
            "--receipt-ref",
            str(bundle_path / "06_TESTS.txt"),
            "--receipt-ref",
            str(bundle_path / "06_CHANGED_FILES.txt"),
            "--command-run",
            "python3 -m unittest tests.test_quest_runtime_refactor -v",
            "--changed-file",
            "runtime/synapse.py",
        )
        self.assertEqual(passed["completion"]["overall_verdict"], "PASS")
        self.assertEqual(passed["completion"]["final_state_decision"], "COMPLETED")
        self.assertIn("/Completed/", passed["completion"]["active_path"])
        self.assertTrue(Path(passed["completion"]["archived_completion_audit_path"]).exists())

    def test_complete_quest_can_reopen_completed_quest(self) -> None:
        draft = self._plan_quests(
            "--title",
            "Quest reopen path",
            "--goal",
            "Allow a completed quest to move back to accepted when later evidence breaks closure.",
            "--item",
            "Ship the original bounded outcome.",
        )
        accepted = self._accept(draft["quests"][0]["path"])
        accepted_path = Path(accepted["acceptance"]["accepted_path"])
        bundle_path = Path(accepted["acceptance"]["audit_bundle_path"])

        passed = self._complete(
            accepted_path.name,
            "--milestone-status",
            "MILESTONE-001:DONE:Original outcome shipped.",
            "--check",
            "UNIT_TESTS:PASS:Quest shipped cleanly.",
            "--receipt-ref",
            str(bundle_path / "06_TESTS.txt"),
            "--command-run",
            "python3 -m unittest tests.test_quest_runtime_refactor -v",
        )
        completed_name = Path(passed["completion"]["active_path"]).name
        self.assertIn("/Completed/", passed["completion"]["active_path"])

        reopened = self._complete(
            completed_name,
            "--milestone-status",
            "MILESTONE-001:BLOCKED:Later evidence proved the closure incomplete.",
            "--check",
            "REGRESSION:BLOCKED:Follow-up regression opened the quest again.",
            "--receipt-ref",
            str(bundle_path / "06_TESTS.txt"),
            "--blocker",
            "Regression reopened the bounded outcome.",
            "--command-run",
            "python3 -m unittest tests.test_quest_runtime_refactor -v",
        )
        self.assertEqual(reopened["completion"]["overall_verdict"], "BLOCKED")
        self.assertEqual(reopened["completion"]["final_state_decision"], "ACTIVE")
        self.assertIn("/Accepted/", reopened["completion"]["active_path"])
        self.assertTrue(Path(reopened["completion"]["archived_completion_audit_path"]).exists())


if __name__ == "__main__":
    unittest.main()

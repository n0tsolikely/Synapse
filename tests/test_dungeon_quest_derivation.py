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

from synapse_runtime.guild_orders_runtime import formalize_guild_orders_from_proposal
from synapse_runtime.quest_acceptance import parse_quest_document
from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class DungeonQuestDerivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "DungeonQuestDerivation"
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

    def _formalize_orders(self) -> str:
        evidence_path = self.data_root / "Docs" / "orders-evidence.md"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("# Ambient heading that should not matter\n", encoding="utf-8")
        result = formalize_guild_orders_from_proposal(
            subject=self.subject,
            data_root=self.data_root,
            proposal={
                "proposal_id": "GUILD_ORDERS__RUN_001__QUEST_DERIVATION",
                "title": "Derive quest work from canonical dungeon truth",
                "summary": "Turn canonical dungeon truth into BOARD quest planning inputs.",
                "reason": "Keep quest planning aligned to canonical Dungeon scope.",
                "objective": "Derive BOARD quests from canonical Dungeon truth without placeholder lineage.",
                "coherent_outcome": "Canonical dungeon-derived quest planning exists with honest coverage and lineage.",
                "closure_statement": "Close only when canonical dungeon-derived planning is deterministic and coverage-safe.",
                "verification_plan": "Run dungeon quest derivation tests plus quest regressions.",
                "evidence": [str(evidence_path.relative_to(self.data_root))],
            },
        )
        return str(result["artifact_path"])

    def _plan_quests(self, *extra_args: str) -> dict[str, object]:
        base = [
            "plan-quests",
            "--json",
            "--anchor",
            "6.5",
            "--anchor",
            "9.2",
            "--constraint",
            "Keep canonical lineage and quest coverage honest.",
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

    def test_plan_quests_derives_single_full_dungeon_from_canonical_orders(self) -> None:
        orders_path = self._formalize_orders()
        payload = self._plan_quests(
            "--guild-orders-artifact",
            orders_path,
            "--dungeon-id",
            "DUNGEON_01",
        )

        self.assertEqual(len(payload["quests"]), 1)
        plan = yaml.safe_load(Path(payload["plan_artifact_path"]).read_text(encoding="utf-8"))
        self.assertTrue(str(plan["guild_orders_ref"]).endswith(".txt"))
        self.assertTrue(str(plan["dungeon_ref"]).endswith("::DUNGEON_01"))
        self.assertEqual(plan["dungeon_coverage"], "FULL_DUNGEON")

        quest_path = Path(payload["quests"][0]["path"])
        doc = parse_quest_document(subject=self.subject, data_root=self.data_root, path=quest_path)
        self.assertNotEqual(doc.guild_orders_ref, "N/A")
        self.assertEqual(doc.dungeon_coverage, "FULL_DUNGEON")
        self.assertEqual(doc.dungeon_ref.split("::")[-1], "DUNGEON_01")

    def test_plan_quests_derives_partial_dungeon_when_split_outcomes_present(self) -> None:
        orders_path = self._formalize_orders()
        payload = self._plan_quests(
            "--guild-orders-artifact",
            orders_path,
            "--dungeon-id",
            "DUNGEON_01",
            "--separate-outcome",
            "Derivation adapter",
            "--separate-outcome",
            "Coverage enforcement",
        )

        self.assertEqual(len(payload["quests"]), 2)
        plan = yaml.safe_load(Path(payload["plan_artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(plan["dungeon_coverage"], "PARTIAL_DUNGEON")
        for entry in payload["quests"]:
            doc = parse_quest_document(subject=self.subject, data_root=self.data_root, path=Path(entry["path"]))
            self.assertEqual(doc.dungeon_coverage, "PARTIAL_DUNGEON")
            self.assertNotEqual(doc.guild_orders_ref, "N/A")

    def test_plan_quests_blocks_full_dungeon_when_split_outcomes_requested(self) -> None:
        orders_path = self._formalize_orders()
        result = run_synapse(
            [
                "plan-quests",
                "--json",
                "--guild-orders-artifact",
                orders_path,
                "--dungeon-id",
                "DUNGEON_01",
                "--dungeon-coverage",
                "FULL_DUNGEON",
                "--separate-outcome",
                "Adapter lane",
                "--separate-outcome",
                "Writer lane",
                "--anchor",
                "6.5",
                "--constraint",
                "Keep canonical lineage and quest coverage honest.",
                "--change-class",
                "FEATURE",
                "--vision-delta",
                "ALIGNED",
                "--door-impact",
                "Runtime",
                "--testing-level",
                "TL2",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("PARTIAL_DUNGEON", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

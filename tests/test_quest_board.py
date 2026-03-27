import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
import sys

if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.quest_acceptance import parse_quest_document
from synapse_runtime.quest_board import draft_quest_from_proposal, fill_quest_template, load_quest_template
from synapse_runtime.subject_bootstrap import initialize_subject_state


class QuestBoardGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "QuestSubject"
        self.data_root = self.root / f"{self.subject}_Data"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fill_quest_template_renders_compact_filled_artifact(self) -> None:
        template = load_quest_template()
        rendered = fill_quest_template(
            template,
            {
                "quest_id": "QUEST_001",
                "title": "Tighten meeting template generation",
                "subject": self.subject,
                "origin": "Ambient proposal WORK_CLUSTER__MEETING",
                "priority": "P1",
                "links": "None",
                "codex_anchors": "6.5, 9.2",
                "codex_constraints": "Keep quest generation deterministic.",
                "change_class": "FEATURE",
                "vision_delta": "ALIGNED",
                "system_context": "Stuart meeting and journal output should be generated from a compact quest contract.",
                "anti_dup": 'rg -n "meeting|journal|template" core Stuart_Data',
                "placement_intent": "Intended layer: runtime | Intended target path(s): runtime/synapse_runtime/quest_board.py.",
                "atomicity": "Atomic: yes - one independently verifiable quest generation fix.",
                "risk": "R0",
                "door_impact": "CLI",
                "testing_level": "TL2",
                "talent_awarded": "NO",
                "description": "Generate compact quest files instead of copying template instructions verbatim.",
                "objective": "Generated quest artifacts contain real filled fields and no template boilerplate.",
                "out_of_scope": "Changing quest validation rules.",
                "dependencies": "None",
                "verification_plan": "python3 -m unittest tests.test_quest_board -v",
                "audit_bundle_path": f"{self.subject}_Data/Audits/Execution/QUEST_001__2026-03-26__tighten-meeting-template-generation",
            },
        )

        self.assertIn("QUEST — SYNAPSE OS", rendered)
        self.assertIn("Quest ID: QUEST_001", rendered)
        self.assertIn("Title: Tighten meeting template generation", rendered)
        self.assertIn("Verification Plan: python3 -m unittest tests.test_quest_board -v", rendered)
        self.assertNotIn("QUEST TEMPLATE — SYNAPSE OS", rendered)
        self.assertNotIn("(duplicate this file for each new Quest)", rendered)
        self.assertNotIn("# REQUIRED.", rendered)
        self.assertNotIn("# OPTIONAL.", rendered)

    def test_draft_quest_from_proposal_writes_parseable_compact_file(self) -> None:
        result = draft_quest_from_proposal(
            subject=self.subject,
            data_root=self.data_root,
            proposal={
                "proposal_id": "WORK_CLUSTER__TIGHTEN-MEETING-JOURNAL",
                "kind": "quest",
                "title": "Tighten meeting and journal generation template behavior",
                "summary": "Generated quest files should be compact and readable.",
                "description": "Quest generation should instantiate a real quest artifact instead of copying raw template instructions.",
                "objective": "A generated quest file contains only filled quest content and parseable labels.",
                "reason": "Template comments leaked into a real quest.",
                "related_files": [
                    "/home/notsolikely/Stuart/core/meetings/transcript_versions.py",
                    "/home/notsolikely/Stuart/core/journal/generation.py",
                ],
            },
            prefix="QUEST",
        )

        artifact_path = Path(result["artifact_path"])
        text = artifact_path.read_text(encoding="utf-8")
        self.assertIn("Quest ID: QUEST_001", text)
        self.assertIn("Title: Tighten meeting and journal generation template behavior", text)
        self.assertIn("Status: Generated Quest Artifact", text)
        self.assertNotIn("QUEST TEMPLATE — SYNAPSE OS", text)
        self.assertNotIn("(duplicate this file for each new Quest)", text)
        self.assertNotIn("# REQUIRED.", text)

        parsed = parse_quest_document(subject=self.subject, data_root=self.data_root, path=artifact_path)
        self.assertEqual(parsed.quest_id, "QUEST_001")
        self.assertEqual(parsed.title, "Tighten meeting and journal generation template behavior")
        self.assertEqual(parsed.subject, self.subject)
        self.assertEqual(parsed.priority, "P1")
        self.assertEqual(parsed.risk, "R0")
        self.assertEqual(parsed.dependencies, "None")


if __name__ == "__main__":
    unittest.main()

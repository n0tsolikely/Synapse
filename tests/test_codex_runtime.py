import tempfile
from pathlib import Path
import sys
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.codex_runtime import codex_anchor_index_path, codex_build_state_path, formalize_codex_from_proposal


class CodexRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "CodexRuntimeSubject_Data"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _proposal(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "proposal_id": "CODEX__TEST__001",
            "title": "Track active plan truth",
            "summary": "Record the currently active runtime plan truth.",
            "reason": "Codex needs a durable active-plan section.",
            "evidence": ["Docs/evidence.md"],
            "codex_implications": ["Keep plan truth durable and section-aware."],
        }
        payload.update(overrides)
        return payload

    def test_formalize_codex_falls_back_to_candidate_only_without_section_target(self) -> None:
        result = formalize_codex_from_proposal(
            subject="CodexRuntimeSubject",
            data_root=self.data_root,
            proposal=self._proposal(),
        )

        artifact_path = Path(result["artifact_path"])
        receipt_path = Path(result["receipt_path"])
        self.assertTrue(artifact_path.exists())
        self.assertTrue(receipt_path.exists())
        self.assertEqual(artifact_path.parent, self.data_root / "Codex" / "Candidates")
        self.assertEqual(result["decision"]["write_posture"], "candidate_only")
        self.assertFalse(codex_build_state_path(self.data_root).exists())
        self.assertFalse(codex_anchor_index_path(self.data_root).exists())

    def test_formalize_codex_writes_draft_anchored_section_when_toc_draft_matches(self) -> None:
        toc_path = self.data_root / "Codex" / "TOC_DRAFT.md"
        toc_path.parent.mkdir(parents=True, exist_ok=True)
        toc_path.write_text("# TOC_DRAFT\n\nStatus: DRAFT\n\n## Sections\n1. Active Plan\n", encoding="utf-8")

        result = formalize_codex_from_proposal(
            subject="CodexRuntimeSubject",
            data_root=self.data_root,
            proposal=self._proposal(codex_section_key="ACTIVE_PLAN", codex_truth_layer="implemented"),
        )

        artifact_path = Path(result["artifact_path"])
        receipt_path = Path(result["receipt_path"])
        build_state = yaml.safe_load(codex_build_state_path(self.data_root).read_text(encoding="utf-8"))
        anchor_index = yaml.safe_load(codex_anchor_index_path(self.data_root).read_text(encoding="utf-8"))
        self.assertTrue(artifact_path.exists())
        self.assertTrue(receipt_path.exists())
        self.assertEqual(artifact_path.parent, self.data_root / "Codex" / "Sections")
        self.assertEqual(result["decision"]["write_posture"], "draft_anchor_only")
        self.assertEqual(result["decision"]["section_key"], "ACTIVE_PLAN")
        self.assertEqual(build_state["sections"][0]["section_key"], "ACTIVE_PLAN")
        self.assertTrue(anchor_index["section_receipts"])

    def test_formalize_codex_blocks_when_anchor_is_required_but_unresolved(self) -> None:
        result = formalize_codex_from_proposal(
            subject="CodexRuntimeSubject",
            data_root=self.data_root,
            proposal=self._proposal(codex_section_key="ACTIVE_PLAN", codex_target_required=True),
        )

        artifact_path = Path(result["artifact_path"])
        receipt_path = Path(result["receipt_path"])
        self.assertEqual(artifact_path, receipt_path)
        self.assertTrue(receipt_path.exists())
        self.assertEqual(result["decision"]["write_posture"], "blocked")
        self.assertFalse((self.data_root / "Codex" / "Sections" / "SECTION__ACTIVE_PLAN.md").exists())
        self.assertFalse(list((self.data_root / "Codex" / "Candidates").glob("CANDIDATE__*.md")))


if __name__ == "__main__":
    unittest.main()

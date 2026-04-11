import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.guild_orders_runtime import (
    GuildOrdersOperation,
    GuildOrdersRevisionClass,
    classify_guild_orders_revision,
    execute_guild_orders_operation,
    formalize_guild_orders_from_proposal,
    normalize_guild_orders_packet,
)
from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.subject_bootstrap import initialize_subject_state


class GuildOrdersRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.subject = "GuildOrdersRuntimeRepo"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_evidence(self, name: str, text: str) -> str:
        path = self.data_root / "Docs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.data_root))

    def _proposal(self, **overrides: object) -> dict[str, object]:
        evidence_ref = self._write_evidence(
            "ambient-scope.md",
            "# Wrong Heading From Evidence\n\n- Wrong Bullet Scope\n\nThe canonical runtime should ignore this heading scrape bait.\n",
        )
        proposal = {
            "proposal_id": "GUILD_ORDERS__RUN_001__CANONICAL_SCOPE",
            "title": "Canonical Guild Orders Scope",
            "summary": "Formalize the bounded engine scope into lawful Guild Orders.",
            "reason": "Keep Orders canonization inside one bounded runtime owner.",
            "objective": "Formalize lawful Guild Orders from proposal truth instead of ambient evidence headings.",
            "coherent_outcome": "A bounded Guild Orders artifact exists with deterministic Dungeon structure.",
            "closure_statement": "Close only when Guild Orders formalization is bounded, deterministic, and receipt-backed.",
            "verification_plan": "Run targeted Guild Orders runtime tests plus formalize regressions.",
            "evidence": [evidence_ref],
            "codex_implications": ["Keep Codex mutation out of the Guild Orders runtime."],
            "blockers": [],
        }
        proposal.update(overrides)
        return proposal

    def test_normalize_packet_requires_structured_fields(self) -> None:
        proposal = self._proposal()
        proposal["closure_statement"] = ""
        with self.assertRaises(LiveMemoryError):
            normalize_guild_orders_packet(
                subject=self.subject,
                data_root=self.data_root,
                proposal=proposal,
            )

    def test_formalize_from_proposal_uses_structured_fields_not_evidence_headings(self) -> None:
        proposal = self._proposal()
        result = formalize_guild_orders_from_proposal(
            subject=self.subject,
            data_root=self.data_root,
            proposal=proposal,
        )
        artifact_path = Path(result["artifact_path"])
        body = artifact_path.read_text(encoding="utf-8")
        self.assertTrue(artifact_path.exists())
        self.assertEqual(artifact_path.parent.name, "PAUSED")
        self.assertIn("Dungeon Title: Canonical Guild Orders Scope", body)
        self.assertIn("Dungeon Objective:", body)
        self.assertNotIn("Wrong Heading From Evidence", body)
        self.assertNotIn("Wrong Bullet Scope", body)

    def test_revision_classification_treats_verification_only_change_as_editorial(self) -> None:
        existing_packet = normalize_guild_orders_packet(
            subject=self.subject,
            data_root=self.data_root,
            proposal=self._proposal(),
        )
        incoming_packet = normalize_guild_orders_packet(
            subject=self.subject,
            data_root=self.data_root,
            proposal=self._proposal(
                verification_plan="Run the stronger verification pass and keep the same bounded scope.",
                evidence=[self._write_evidence("fresh-proof.md", "fresh proof")],
            ),
        )
        revision = classify_guild_orders_revision(
            existing_packet=existing_packet,
            incoming_packet=incoming_packet,
            operation=GuildOrdersOperation.REVISE_PAUSED,
        )
        self.assertEqual(revision, GuildOrdersRevisionClass.EDITORIAL)

    def test_material_revision_requires_control_sync_receipt(self) -> None:
        original_proposal = self._proposal()
        existing_packet = normalize_guild_orders_packet(
            subject=self.subject,
            data_root=self.data_root,
            proposal=original_proposal,
        )
        created = formalize_guild_orders_from_proposal(
            subject=self.subject,
            data_root=self.data_root,
            proposal=original_proposal,
        )
        revised_packet = normalize_guild_orders_packet(
            subject=self.subject,
            data_root=self.data_root,
            proposal=self._proposal(
                coherent_outcome="A bounded Guild Orders artifact exists with deterministic Dungeon structure and explicit revision gates."
            ),
        )

        blocked = execute_guild_orders_operation(
            data_root=self.data_root,
            packet=revised_packet,
            requested_operation=GuildOrdersOperation.REVISE_PAUSED,
            source_artifact_path=created["artifact_path"],
            existing_packet=existing_packet,
            supporting_receipt_refs=[],
        )
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.revision_class, GuildOrdersRevisionClass.MATERIAL_SCOPE_CHANGE)
        self.assertEqual(blocked.blocked_reason, "missing_control_sync_receipt_refs")

        receipt_rel = Path("Snapshots") / "Control Sync" / "CONTROL_SYNC__2026-04-10__test.txt"
        receipt_path = self.data_root / receipt_rel
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text("control sync receipt", encoding="utf-8")

        allowed = execute_guild_orders_operation(
            data_root=self.data_root,
            packet=revised_packet,
            requested_operation=GuildOrdersOperation.REVISE_PAUSED,
            source_artifact_path=created["artifact_path"],
            existing_packet=existing_packet,
            supporting_receipt_refs=[str(receipt_rel)],
        )
        self.assertTrue(allowed.ok)
        self.assertEqual(allowed.destination_artifact_path, created["artifact_path"])
        revised_body = Path(created["artifact_path"]).read_text(encoding="utf-8")
        self.assertIn("explicit revision gates", revised_body)

    def test_start_active_blocks_under_fog_of_war(self) -> None:
        proposal = self._proposal()
        packet = normalize_guild_orders_packet(
            subject=self.subject,
            data_root=self.data_root,
            proposal=proposal,
        )
        created = formalize_guild_orders_from_proposal(
            subject=self.subject,
            data_root=self.data_root,
            proposal=proposal,
        )
        receipt_rel = Path("Snapshots") / "Control Sync" / "CONTROL_SYNC__2026-04-10__test.txt"
        receipt_path = self.data_root / receipt_rel
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text("control sync receipt", encoding="utf-8")

        result = execute_guild_orders_operation(
            data_root=self.data_root,
            packet=packet,
            requested_operation=GuildOrdersOperation.START_ACTIVE,
            source_artifact_path=created["artifact_path"],
            supporting_receipt_refs=[str(receipt_rel)],
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.blocked_reason, "fog_of_war_blocks_active_transition")


if __name__ == "__main__":
    unittest.main()

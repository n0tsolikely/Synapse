import tempfile
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.codex_packets import (
    build_codex_packet,
    codex_packet_summary,
    load_codex_packets,
    packet_path,
    sync_codex_packets,
)


class CodexPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "PacketSubject_Data"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sync_persists_source_linked_noncanonical_packets(self) -> None:
        packet = build_codex_packet(
            subject="PacketSubject",
            section_key="ACTIVE_PLAN",
            refreshed_at="2026-04-01T12:00:00-04:00",
            summary="Ship the installable web app foundation.",
            detail_lines=[
                "Objective: support accounts and transcription.",
                "MILESTONE-001: account auth",
            ],
            source_refs=[
                {
                    "kind": "plan_revision",
                    "id": "PLAN-1::REVISION-001",
                    "path": "/tmp/PLAN__PLAN-1__REVISION-001__foundation.yaml",
                }
            ],
            metadata={"phase": "p3"},
        )

        receipt = sync_codex_packets(self.data_root, [packet])
        self.assertEqual(len(receipt["written_paths"]), 1)
        self.assertFalse(receipt["removed_paths"])
        self.assertTrue(packet_path(self.data_root, "ACTIVE_PLAN").exists())

        loaded = load_codex_packets(self.data_root)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["canonical_status"], "derived_noncanonical")
        self.assertEqual(loaded[0]["source_ref_count"], 1)
        self.assertTrue(loaded[0]["source_signature"])

        summary = codex_packet_summary(self.data_root)
        self.assertEqual(summary["codex_packet_count"], 1)
        self.assertEqual(summary["packet_section_keys"], ["ACTIVE_PLAN"])
        self.assertEqual(summary["recent_codex_packet_details"][0]["section_title"], "Active Plan")

    def test_sync_removes_stale_packets_when_current_set_changes(self) -> None:
        first = build_codex_packet(
            subject="PacketSubject",
            section_key="ACTIVE_PLAN",
            refreshed_at="2026-04-01T12:00:00-04:00",
            summary="Initial plan summary.",
            detail_lines=[],
            source_refs=[{"kind": "plan_revision", "id": "PLAN-A", "path": "/tmp/plan-a.yaml"}],
        )
        second = build_codex_packet(
            subject="PacketSubject",
            section_key="NARRATIVE_DELTA",
            refreshed_at="2026-04-01T12:10:00-04:00",
            summary="Narrative changed toward a reusable website system.",
            detail_lines=[],
            source_refs=[{"kind": "governed_working_record", "id": "REC-1", "path": "/tmp/rec-1.yaml"}],
        )

        sync_codex_packets(self.data_root, [first])
        receipt = sync_codex_packets(self.data_root, [second])

        self.assertEqual(len(receipt["written_paths"]), 1)
        self.assertEqual(len(receipt["removed_paths"]), 1)
        section_keys = [item["section_key"] for item in load_codex_packets(self.data_root)]
        self.assertEqual(section_keys, ["NARRATIVE_DELTA"])


if __name__ == "__main__":
    unittest.main()

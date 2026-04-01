import tempfile
import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.kernel_types import ConversationSegmentEnvelope, ExecutionSegmentEnvelope
from synapse_runtime.semantic_classifier import (
    classify_conversation_segment,
    classify_execution_segment,
    normalized_semantic_summary,
    persist_semantic_events,
)


class SemanticClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "Subject_Data"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_noise_text_is_classified_as_transient_noise(self) -> None:
        segment = ConversationSegmentEnvelope(
            segment_id="SEGCONV-1",
            schema_version=1,
            classifier_version="v1-phase1",
            recorded_at="2026-04-01T15:00:00-04:00",
            subject="Subject",
            segment_family="conversation",
            source_turn_id="TURN-1",
            source_surface="cli",
            session_id=None,
            run_id=None,
            role="user",
            segment_index=0,
            text_preview="okay",
            text_length=4,
            transient_noise=True,
            source_refs=[{"kind": "raw_conversation_turn", "id": "TURN-1", "path": "/tmp/turn.json", "sha256": "abc"}],
        )
        events = classify_conversation_segment(segment, text="okay")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].class_label, "transient_noise")
        self.assertEqual(events[0].topic_key, "transient.noise")

    def test_planning_text_emits_scope_and_build_plan_events(self) -> None:
        segment = ConversationSegmentEnvelope(
            segment_id="SEGCONV-2",
            schema_version=1,
            classifier_version="v1-phase1",
            recorded_at="2026-04-01T15:00:00-04:00",
            subject="Subject",
            segment_family="conversation",
            source_turn_id="TURN-2",
            source_surface="cli",
            session_id=None,
            run_id=None,
            role="user",
            segment_index=0,
            text_preview="Need accounts and a plan.",
            text_length=26,
            transient_noise=False,
            source_refs=[{"kind": "raw_conversation_turn", "id": "TURN-2", "path": "/tmp/turn.json", "sha256": "abc"}],
        )
        events = classify_conversation_segment(
            segment,
            text="We need to support separate user accounts and plan the transcription flow.",
        )
        self.assertTrue(any(item.topic_key == "project.scope" for item in events))
        self.assertTrue(any(item.topic_key == "build.plan" for item in events))

    def test_execution_failure_emits_verification_and_failure(self) -> None:
        segment = ExecutionSegmentEnvelope(
            segment_id="SEGEXEC-1",
            schema_version=1,
            classifier_version="v1-phase1",
            recorded_at="2026-04-01T15:00:00-04:00",
            subject="Subject",
            segment_family="execution",
            source_event_id="EXEC-1",
            source_surface="cli",
            session_id=None,
            run_id=None,
            event_family="TOOL_EVENTS",
            phase="post_tool_use",
            tool_name="exec_command",
            status="failed",
            changed_files=[],
            command_preview="pytest -q",
            transient_noise=False,
            source_refs=[{"kind": "raw_execution_event", "id": "EXEC-1", "path": "/tmp/exec.json", "sha256": "abc"}],
        )
        events = classify_execution_segment(segment)
        self.assertTrue(any(item.topic_key == "verification.command" for item in events))
        self.assertTrue(any(item.topic_key == "execution.failure" for item in events))

    def test_persist_semantic_events_dedupes_by_event_id(self) -> None:
        segment = ConversationSegmentEnvelope(
            segment_id="SEGCONV-3",
            schema_version=1,
            classifier_version="v1-phase1",
            recorded_at="2026-04-01T15:00:00-04:00",
            subject="Subject",
            segment_family="conversation",
            source_turn_id="TURN-3",
            source_surface="cli",
            session_id=None,
            run_id=None,
            role="user",
            segment_index=0,
            text_preview="Need a web app.",
            text_length=16,
            transient_noise=False,
            source_refs=[{"kind": "raw_conversation_turn", "id": "TURN-3", "path": "/tmp/turn.json", "sha256": "abc"}],
        )
        events = classify_conversation_segment(segment, text="I want this to become a web app.")
        receipts_first = persist_semantic_events(self.data_root, events)
        receipts_second = persist_semantic_events(self.data_root, events)
        self.assertTrue(all(item["written"] for item in receipts_first))
        self.assertTrue(all(not item["written"] for item in receipts_second))
        summary = normalized_semantic_summary(self.data_root)
        self.assertEqual(summary["semantic_event_count"], len(events))


if __name__ == "__main__":
    unittest.main()

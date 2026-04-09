from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.canonizer import (
    author_decision_body,
    author_discovery_body,
    compose_authored_sections,
    render_draftshot_body,
    render_snapshot_candidate_body,
    working_record_authoring_metadata,
)


class CanonizerTests(unittest.TestCase):
    def test_compose_authored_sections_keeps_truth_vision_unresolved_distinct(self) -> None:
        sections = compose_authored_sections(
            truths=["Implemented auth flow", "Implemented auth flow"],
            visions=["Expand to tenant-aware auth"],
            unresolved=["Need real SSO proof"],
            source_refs=[{"kind": "semantic_event", "id": "SEMEVT-1", "path": "/tmp/evt-1.json"}],
        )

        self.assertEqual(sections["implemented_truths"], ["Implemented auth flow"])
        self.assertEqual(sections["intended_directions"], ["Expand to tenant-aware auth"])
        self.assertEqual(sections["unresolved_items"], ["Need real SSO proof"])
        self.assertIn("[TRUTH] Implemented auth flow", sections["truth_state_lines"])
        self.assertIn("[VISION] Expand to tenant-aware auth", sections["truth_state_lines"])
        self.assertIn("[UNRESOLVED] Need real SSO proof", sections["truth_state_lines"])
        self.assertIn("[EVIDENCE] 1 source refs", sections["truth_state_lines"])

    def test_author_discovery_body_renders_authored_sections_and_refs(self) -> None:
        body, sections = author_discovery_body(
            subject="CanonizerSubject",
            logged_at="2026-04-09T12:00:00-04:00",
            title="Discovery A",
            summary="The runtime already persists continuity state.",
            truths=["Continuity state is on disk under .synapse."],
            visions=["Later compile that into stronger codex packets."],
            unresolved=["Need to prove import review behavior."],
            related_runs=["RUN-001"],
            related_quests=["QUEST-001"],
            source_refs=[{"kind": "conversation_segment", "id": "SEG-1", "path": "/tmp/seg-1.json"}],
        )

        self.assertIn("## Implemented Truths", body)
        self.assertIn("## Intended Direction", body)
        self.assertIn("## Unresolved / Review", body)
        self.assertIn("[conversation_segment] SEG-1", body)
        self.assertEqual(sections["source_ref_count"], 1)

    def test_render_draftshot_body_preserves_contract_and_truth_state_labels(self) -> None:
        body = render_draftshot_body(
            subject="CanonizerSubject",
            session_id="syn-can-001",
            run_id="RUN-001",
            revision_number=2,
            refreshed_at="2026-04-09T13:00:00-04:00",
            draftshot_context="GENERAL",
            capture_entries=[
                {"capture_id": "DECISION-1", "section": "DECISIONS", "summary": "Choose typed candidates.", "truth_state": "TRUTH"},
                {"capture_id": "VISION-1", "section": "FINDINGS", "summary": "Expand to richer codex packets.", "truth_state": "VISION"},
                {"capture_id": "QUESTION-1", "section": "OPEN_QUESTIONS", "summary": "Need real backend seam.", "truth_state": "UNRESOLVED"},
            ],
            sections={
                "DECISIONS": [{"capture_id": "DECISION-1", "summary": "Choose typed candidates.", "truth_state": "TRUTH"}],
                "FINDINGS": [{"capture_id": "VISION-1", "summary": "Expand to richer codex packets.", "truth_state": "VISION"}],
                "TODO": [],
                "RISKS": [],
                "OPEN_QUESTIONS": [{"capture_id": "QUESTION-1", "summary": "Need real backend seam.", "truth_state": "UNRESOLVED"}],
            },
            running_log=[{"revision_label": "REV2", "refreshed_at": "2026-04-09T13:00:00-04:00", "change_type": "updated", "summary": "Captured richer authored state.", "source_ref_count": 3}],
        )

        self.assertIn("B) Capture Index", body)
        self.assertIn("[TRUTH] Choose typed candidates.", body)
        self.assertIn("[VISION] Expand to richer codex packets.", body)
        self.assertIn("[UNRESOLVED] Need real backend seam.", body)
        self.assertIn("H) Running Log", body)

    def test_render_snapshot_candidate_body_separates_truth_direction_and_review(self) -> None:
        body, sections = render_snapshot_candidate_body(
            kind="CONTROL_SYNC",
            subject="CanonizerSubject",
            session_id="syn-can-002",
            target_day="2026-04-09",
            revision_number=1,
            refreshed_at="2026-04-09T14:00:00-04:00",
            summary="Scope and architecture are aligned around typed continuity candidates.",
            truths=["Scope: Keep typed candidates as the continuity lane."],
            visions=["Narrative: Grow toward richer codex packets."],
            unresolved=["Governance: Still need a production model backend seam."],
            draftshot={"revision_id": "DRAFTREV-1", "body_path": "/tmp/draftshot.txt"},
            source_refs=[{"kind": "draftshot_revision", "id": "DRAFTREV-1", "body_path": "/tmp/draftshot.txt"}],
        )

        self.assertIn("## Truths In Hand", body)
        self.assertIn("## Intended Direction", body)
        self.assertIn("## Unresolved / Review", body)
        self.assertIn("production model backend seam", body)
        self.assertEqual(sections["truth_state_counts"]["VISION"], 1)

    def test_working_record_authoring_metadata_marks_narrative_as_vision(self) -> None:
        metadata = working_record_authoring_metadata(
            family="NARRATIVE_CLAIMS",
            summary="The system becomes a reusable installable website baseline.",
            detail="The current direction is packaging the continuity kernel for repeated reuse.",
            source_refs=[{"kind": "semantic_event", "id": "SEMEVT-2", "path": "/tmp/evt-2.json"}],
        )

        canonizer = metadata["canonizer"]
        self.assertEqual(canonizer["implemented_truths"], [])
        self.assertTrue(canonizer["intended_directions"])
        self.assertIn("[VISION]", canonizer["truth_state_lines"][0])

    def test_author_decision_body_keeps_constraints_and_tradeoffs(self) -> None:
        body, sections = author_decision_body(
            subject="CanonizerSubject",
            logged_at="2026-04-09T15:00:00-04:00",
            title="Decision B",
            summary="Keep owner boundaries intact.",
            why="The current owners already handle persistence and gating.",
            constraints=["Do not bypass Draftshot owner."],
            tradeoffs=["Body rendering becomes another seam to maintain."],
            related_runs=["RUN-100"],
            related_quests=[],
            source_refs=[{"kind": "semantic_event", "id": "SEMEVT-3", "path": "/tmp/evt-3.json"}],
        )

        self.assertIn("## Constraints", body)
        self.assertIn("## Tradeoffs", body)
        self.assertIn("Keep owner boundaries intact.", sections["implemented_truths"])


if __name__ == "__main__":
    unittest.main()

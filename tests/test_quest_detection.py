import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_cmd(args):
    return subprocess.run(
        SYNAPSE + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class QuestDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name) / "QuestSubject_Data"
        self.engine_root = Path(self.tmp.name) / "QuestSubject_Engine"
        self.data_root.mkdir()
        self.engine_root.mkdir()
        self.subject_args = [
            "--subject",
            "QuestSubject",
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _run_start(self, title: str, plan_item: str):
        result = run_cmd(["run-start", "--title", title, "--plan-item", plan_item, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _quest_proposals(self, dirname: str = "quests"):
        return sorted((self.data_root / ".synapse" / "PROPOSALS" / dirname).glob("*.yaml"))

    def _read_yaml(self, path: Path):
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _write_current_accepted_quest(self, *, quest_id: str = "QUEST_001", title: str = "Core runtime hardening"):
        accepted_dir = self.data_root / "Quest Board" / "Accepted"
        bundle_dir = self.data_root / "Audits" / "Execution" / f"{quest_id}__2026-03-10__accepted"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "00_SUMMARY.md").write_text("# 00_SUMMARY.md\n\n- Audit State: pending_completion_audit\n", encoding="utf-8")
        quest_path = accepted_dir / f"{quest_id}__accepted__2026-03-10.txt"
        quest_path.write_text(
            "\n".join(
                [
                    f"Quest ID: {quest_id}",
                    "",
                    f"Title: {title}",
                    "",
                    "Subject: QuestSubject",
                    "",
                    "Coherent Outcome: Keep the current accepted runtime work bounded and honest.",
                    "",
                    "Closure Statement: Close only when the bounded runtime work is complete and the completion audit passes.",
                    "",
                    "Stretch Plan / Milestones:",
                    "- MILESTONE-001 :: Keep the governed runtime work coherent.",
                    "",
                    "Plan Artifact Refs: QuestSubject_Data/.synapse/PLANS/PLAN__PLAN-20260310T120000-0500__REVISION-001__accepted.yaml",
                    "",
                    "Audit State: pending_completion_audit",
                    "",
                    f"Audit Bundle Folder Path (required once ACCEPTED): {bundle_dir}",
                    "",
                    "Talent Point Awarded: NO",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return quest_path

    def test_creates_quest_candidate_from_deterministic_runtime_signals(self):
        self._run_start("Ambient runtime session", "Implement ambient quest clustering")
        result = run_cmd(
            [
                "run-update",
                "--command",
                "python3 runtime/synapse.py run-update",
                "--file",
                "runtime/synapse_runtime/live_memory.py",
                "--note",
                "Cluster repeated runtime work into one quest candidate.",
                "--summary",
                "Implement ambient quest clustering",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        proposals = self._quest_proposals()
        self.assertEqual(len(proposals), 1)
        proposal = self._read_yaml(proposals[0])
        self.assertEqual(proposal["kind"], "quest")
        self.assertEqual(proposal["cluster_id"], proposal["proposal_id"])
        self.assertEqual(proposal["scope_classification"], "unknown")
        self.assertGreaterEqual(proposal["signal_count"], 2)
        self.assertIn("plan", proposal["evidence_sources"])
        self.assertIn("file", proposal["evidence_sources"])
        self.assertIn("command", proposal["evidence_sources"])
        self.assertIn("note", proposal["evidence_sources"])

        manifold = self._read_yaml(self.data_root / ".synapse" / "MANIFOLD.yaml")
        self.assertTrue(manifold["quest_candidate_details"])
        self.assertEqual(manifold["quest_candidate_details"][0]["proposal_id"], proposal["proposal_id"])

        rehydrate = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Quest candidates", rehydrate)
        self.assertIn("Implement ambient quest clustering", rehydrate)

    def test_clusters_repeated_related_updates_into_one_candidate(self):
        self._run_start("Ambient runtime session", "Cluster ambient work")
        first = run_cmd(
            [
                "run-update",
                "--note",
                "Cluster ambient work around the runtime sidecar.",
                "--summary",
                "Cluster ambient work",
                *self.subject_args,
            ]
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run_cmd(
            [
                "run-update",
                "--note",
                "Cluster ambient work around the runtime sidecar with more detail.",
                "--summary",
                "Cluster ambient work",
                *self.subject_args,
            ]
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        proposals = self._quest_proposals()
        self.assertEqual(len(proposals), 1)
        proposal = self._read_yaml(proposals[0])
        self.assertGreaterEqual(proposal["signal_count"], 3)
        self.assertEqual(proposal["state"], "proposed")

    def test_repeated_noop_update_does_not_spawn_duplicate_or_increment_signal_count(self):
        self._run_start("Ambient runtime session", "Capture stable candidate")
        args = [
            "run-update",
            "--note",
            "Keep the candidate stable without new evidence.",
            "--summary",
            "Capture stable candidate",
            *self.subject_args,
        ]
        first = run_cmd(args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_proposal = self._read_yaml(self._quest_proposals()[0])
        second = run_cmd(args)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        proposals = self._quest_proposals()
        self.assertEqual(len(proposals), 1)
        proposal = self._read_yaml(proposals[0])
        self.assertEqual(proposal["signal_count"], first_proposal["signal_count"])

    def test_out_of_scope_work_becomes_sidequest_candidate(self):
        self._write_current_accepted_quest(title="Core runtime hardening")
        self._run_start("Unexpected docs work", "Patch docs router")
        result = run_cmd(
            [
                "run-update",
                "--file",
                "docs/PERSONAS.md",
                "--note",
                "Unexpected docs fix outside the accepted runtime hardening scope.",
                "--summary",
                "Patch docs router",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        quests = self._quest_proposals("quests")
        side_quests = self._quest_proposals("side_quests")
        self.assertFalse(quests)
        self.assertEqual(len(side_quests), 1)
        proposal = self._read_yaml(side_quests[0])
        self.assertEqual(proposal["kind"], "side_quest")
        self.assertEqual(proposal["scope_classification"], "out_of_scope")

    def test_ready_candidate_auto_formalizes_into_board_quest(self):
        self._run_start("Runtime quest promotion", "Formalize clustered runtime quest")
        first = run_cmd(
            [
                "run-update",
                "--command",
                "python3 runtime/synapse.py run-update",
                "--file",
                "runtime/synapse_runtime/live_memory.py",
                "--note",
                "Formalize clustered runtime quest through ambient evidence.",
                "--summary",
                "Formalize clustered runtime quest",
                *self.subject_args,
            ]
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run_cmd(
            [
                "run-update",
                "--command",
                "python3 -m unittest tests.test_live_memory",
                "--file",
                "runtime/synapse.py",
                "--verification",
                "tests passed",
                "--summary",
                "Formalize clustered runtime quest",
                *self.subject_args,
            ]
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        proposals = self._quest_proposals()
        self.assertEqual(len(proposals), 1)
        proposal = self._read_yaml(proposals[0])
        self.assertEqual(proposal["state"], "formalized")
        artifact_path = Path(proposal["formalized_artifact_path"])
        self.assertTrue(artifact_path.exists())
        self.assertIn("/Quest Board/", proposal["formalized_artifact_path"])
        self.assertTrue(list((self.data_root / "Quest Board").glob("QUEST_*.txt")))

        rehydrate = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("board_artifact=", rehydrate)
        self.assertIn(str(artifact_path), rehydrate)

    def test_insufficient_evidence_stays_noncanonical(self):
        self._run_start("Ambient notes session", "Investigate rough scope")
        result = run_cmd(
            [
                "run-update",
                "--note",
                "Investigate rough scope before touching files.",
                "--summary",
                "Investigate rough scope",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        proposals = self._quest_proposals()
        self.assertEqual(len(proposals), 1)
        proposal = self._read_yaml(proposals[0])
        self.assertIn(proposal["state"], {"draft", "proposed"})
        self.assertFalse(proposal.get("formalized_artifact_path"))
        self.assertFalse(list((self.data_root / "Quest Board").glob("QUEST_*.txt")))


if __name__ == "__main__":
    unittest.main()

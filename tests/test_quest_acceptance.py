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

from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]
SNAPSHOT_WRITER = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_snapshot_writer.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def run_snapshot_writer(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(SNAPSHOT_WRITER + args, cwd=cwd, env=env, capture_output=True, text=True)


class QuestAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "TestSubject"
        self.data_root = self.root / f"{self.subject}_Data"
        self.engine_root = self.root / f"{self.subject}_Engine"
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        (self.data_root / "Quest Board").mkdir(parents=True, exist_ok=True)
        self.subject_args = [
            "--subject",
            self.subject,
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _write_codex_freeze(self):
        freeze = self.data_root / "Codex" / "CODEX_FREEZE.md"
        freeze.parent.mkdir(parents=True, exist_ok=True)
        freeze.write_text(
            "\n".join(
                [
                    "# CODEX FREEZE",
                    "",
                    "Brains Approval: YES",
                    "Date: 2026-03-10",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _open_control_sync(self):
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

    def _write_board_quest(self, quest_id: str = "QUEST_001", **overrides: str) -> Path:
        slug = overrides.pop("slug", "runtime-governed-bridge")
        date = overrides.pop("date", "2026-03-10")
        filename = f"{quest_id}__{slug}__{date}.txt"
        bundle_path = overrides.pop(
            "audit_bundle",
            f"{self.subject}_Data/Audits/Execution/{quest_id}__{date}__{slug}",
        )
        fields = {
            "Quest ID": quest_id,
            "Title": "Runtime governed bridge",
            "Subject": self.subject,
            "Origin": "Control Sync 2026-03-10",
            "Priority": "P1",
            "Links": "None",
            "Codex Anchors (DRAFT)": "6.5, 9.2",
            "Codex Constraint Summary (DRAFT)": "Keep router thin; no proofless claims.",
            "Change Class": "FEATURE",
            "Vision Delta": "ALIGNED",
            "System Context Statement": (
                "Synapse runtime inside the existing governed CLI; acceptance extends the current quest flow "
                "instead of creating a parallel executor."
            ),
            "Anti-Duplication Plan": 'rg -n "accept-quest|Quest Board|Accepted" runtime tests governance',
            "Placement Intent": "Intended layer: runtime | Intended target path(s): runtime/synapse.py, runtime/synapse_runtime/",
            "Coherent Outcome": "Move the quest into governed execution as one bounded coherent runtime outcome.",
            "Closure Statement": "Close only when governed acceptance is complete and later completion audit PASS can honestly close it.",
            "Split Triggers": "- Split if acceptance work reveals more than one independently closable outcome.",
            "Risk": "R1",
            "R2 Confirmation Artifact (REQUIRED if Risk = R2)": "",
            "Description": "Accept a board quest into governed execution.",
            "Scope / Objective": (
                "Successful acceptance moves the quest into Accepted/ with a canonical audit bundle "
                "and explicit readiness."
            ),
            "Stretch Plan / Milestones": "- MILESTONE-001 :: Move the quest into Accepted/.\n- MILESTONE-002 :: Create the governed audit bundle.",
            "Out of Scope": "Completing the quest or writing execution receipts.",
            "Dependencies": "None",
            "Door Impact": "CLI",
            "Testing Level (TL)": "TL2",
            "Verification Plan": (
                "Verification Commands: python3 -m unittest tests.test_quest_acceptance "
                "| PASS when exit code is 0 | FAIL otherwise | Receipts: 01_COMPLETION_AUDIT.md + 06_TESTS.txt"
            ),
            "Talent Point Awarded": "NO",
            "Plan Artifact Refs": "",
            "Audit Bundle Folder Path (required once ACCEPTED)": bundle_path,
        }
        fields.update(overrides)
        lines = []
        for label, value in fields.items():
            if value == "":
                lines.extend([f"{label}:", ""])
            else:
                lines.extend([f"{label}: {value}", ""])
        path = self.data_root / "Quest Board" / filename
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_accept_quest_valid_path_moves_to_accepted_and_updates_sidecar(self):
        self._write_codex_freeze()
        self._open_control_sync()
        board_path = self._write_board_quest()

        result = run_synapse(["accept-quest", str(board_path), "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        payload = json.loads(result.stdout)
        accepted_path = Path(payload["acceptance"]["accepted_path"])
        bundle_path = Path(payload["acceptance"]["audit_bundle_path"])
        event_payload = payload["event"]["payload"]
        self.assertFalse(board_path.exists())
        self.assertTrue(accepted_path.exists())
        self.assertTrue(bundle_path.exists())
        self.assertTrue((bundle_path / "00_ACCEPTANCE_RECEIPT.txt").exists())
        self.assertTrue((bundle_path / "00_SUMMARY.md").exists())
        self.assertFalse((bundle_path / "01_PREQUEST.md").exists())
        receipt_text = (bundle_path / "00_ACCEPTANCE_RECEIPT.txt").read_text(encoding="utf-8")
        self.assertIn("ACCEPTANCE_STATUS: PASS", receipt_text)
        self.assertIn("CONTROL_SYNC_ACTIVE: YES", receipt_text)
        summary_text = (bundle_path / "00_SUMMARY.md").read_text(encoding="utf-8")
        self.assertIn("Audit State: pending_completion_audit", summary_text)
        self.assertIn("Completion requires a clean PASS in 01_COMPLETION_AUDIT.md", summary_text)
        self.assertIn("Verification Plan", summary_text)

        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifold.get("current_accepted_quest_id"), "QUEST_001")
        self.assertEqual(Path(manifold.get("current_accepted_quest_path")).resolve(), accepted_path.resolve())
        self.assertEqual(Path(manifold.get("current_accepted_audit_bundle_path")).resolve(), bundle_path.resolve())
        self.assertTrue(manifold.get("governed_execution_ready"))
        self.assertEqual(manifold.get("current_accepted_audit_state"), "pending_completion_audit")
        self.assertEqual(event_payload["action_name"], "accept-quest")
        self.assertEqual(event_payload["outputs"]["accepted_quest_id"], "QUEST_001")
        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state.get("last_event_id"), event_payload["event_id"])
        self.assertEqual(state.get("last_reduced_event_id"), event_payload["event_id"])
        self.assertTrue(list((self.data_root / ".synapse" / "EVENTS").glob("*.jsonl")))

        rehydrate = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Governed execution", rehydrate)
        self.assertIn("Current accepted quest: QUEST_001", rehydrate)
        self.assertIn(str(bundle_path.resolve()), rehydrate)

    def test_accept_quest_rejects_fog_of_war(self):
        self._open_control_sync()
        board_path = self._write_board_quest()

        result = run_synapse(["accept-quest", str(board_path), *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Fog of War is active", result.stdout + result.stderr)
        self.assertTrue(board_path.exists())

    def test_accept_quest_rejects_missing_required_fields(self):
        self._write_codex_freeze()
        self._open_control_sync()
        board_path = self._write_board_quest(Title="")

        result = run_synapse(["accept-quest", str(board_path), *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Title is required", result.stdout + result.stderr)
        self.assertTrue(board_path.exists())

    def test_accept_quest_rejects_missing_verification_plan(self):
        self._write_codex_freeze()
        self._open_control_sync()
        board_path = self._write_board_quest(**{"Verification Plan": "DEFERRED TO 01_PREQUEST.md"})

        result = run_synapse(["accept-quest", str(board_path), *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Verification Plan must be concrete", result.stdout + result.stderr)
        self.assertTrue(board_path.exists())

    def test_accept_quest_materializes_default_bundle_and_plan_refs_for_legacy_board_quest(self):
        self._write_codex_freeze()
        self._open_control_sync()
        board_path = self._write_board_quest(
            **{
                "Coherent Outcome": "",
                "Closure Statement": "",
                "Split Triggers": "",
                "Stretch Plan / Milestones": "",
                "Plan Artifact Refs": "",
                "Audit Bundle Folder Path (required once ACCEPTED)": "",
            }
        )

        result = run_synapse(["accept-quest", str(board_path), "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        acceptance = payload["acceptance"]
        accepted_path = Path(acceptance["accepted_path"])
        bundle_path = Path(acceptance["audit_bundle_path"])
        self.assertTrue(accepted_path.exists())
        self.assertTrue(bundle_path.exists())
        self.assertTrue(acceptance["plan_artifact_refs"])
        self.assertTrue(Path(acceptance["plan_artifact_refs"][0]).exists())

        accepted_text = accepted_path.read_text(encoding="utf-8")
        self.assertIn("Split Triggers:", accepted_text)
        self.assertIn("Stretch Plan / Milestones:", accepted_text)
        self.assertIn("Plan Artifact Refs:", accepted_text)
        self.assertIn(f"{self.subject}_Data/Audits/Execution/{bundle_path.name}", accepted_text)


if __name__ == "__main__":
    unittest.main()

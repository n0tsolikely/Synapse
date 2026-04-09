import json
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

from synapse_runtime.live_journal import record_quest_acceptance

SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_cmd(args):
    return subprocess.run(
        SYNAPSE + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class LiveMemoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name) / "TestSubject_Data"
        self.engine_root = Path(self.tmp.name) / "TestSubject_Engine"
        self.data_root.mkdir()
        self.engine_root.mkdir()
        self.subject_args = [
            "--subject",
            "TestSubject",
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _read_active_run(self):
        path = self.data_root / ".synapse" / "ACTIVE_RUN.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _run_start(self, title="Test run", plan_item="Do the thing"):
        result = run_cmd(["run-start", "--title", title, "--plan-item", plan_item, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_bootstrap_scaffold(self):
        result = run_cmd(["live-bootstrap", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        live_root = self.data_root / ".synapse"
        for name in ["VISION.md", "STATE.yaml", "MANIFOLD.yaml", "REHYDRATE.md", "ACTIVE_RUN.yaml"]:
            self.assertTrue((live_root / name).exists())
        self.assertTrue((live_root / "EVENTS").is_dir())
        self.assertTrue((live_root / "THREADS" / "open_questions.md").exists())
        self.assertTrue(list((live_root / "DECISIONS").glob("*.yaml")))
        self.assertTrue(list((live_root / "DISCOVERIES").glob("*.yaml")))
        self.assertTrue(list((live_root / "DISCLOSURES").glob("*.yaml")))
        for dirname in ["quests", "side_quests", "snapshots", "control_sync", "guild_orders", "codex", "build_manual", "talent", "disclosures"]:
            self.assertTrue((live_root / "PROPOSALS" / dirname).is_dir())

    def test_run_update_command_records(self):
        self._run_start()
        cmd = "python3 runtime/synapse.py live-bootstrap --subject TestSubject"
        result = run_cmd(
            [
                "run-update",
                "--command",
                cmd,
                "--file",
                "runtime/synapse.py",
                "--note",
                "Observed runtime change.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertIn(cmd, active.get("commands", []))
        ledgers = sorted((self.data_root / ".synapse" / "DISCOVERIES").glob("*.yaml"))
        self.assertTrue(ledgers)
        entries = yaml.safe_load(ledgers[-1].read_text(encoding="utf-8"))["entries"]
        self.assertTrue(any("Observed runtime change." in entry.get("summary", "") for entry in entries))

    def test_finalize_completed_requires_terminal_items(self):
        self._run_start()
        result = run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot finalize as completed", result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertTrue(active.get("run_id"))

    def test_finalize_completed_when_items_done(self):
        self._run_start()
        result = run_cmd(["run-update", "--set-item-status", "ITEM-001:DONE", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runs = list((self.data_root / ".synapse" / "RUNS").glob("RUN-*.yaml"))
        self.assertTrue(runs)
        snapshot_proposals = list((self.data_root / ".synapse" / "PROPOSALS" / "snapshots").glob("*.yaml"))
        self.assertTrue(snapshot_proposals)

    def test_log_decision_and_rehydrate(self):
        self._run_start()
        run_cmd(["run-update", "--set-item-status", "ITEM-001:DONE", *self.subject_args])
        run_cmd(["run-finalize", "--status", "completed", *self.subject_args])
        result = run_cmd(
            [
                "log-decision",
                "--title",
                "Decision A",
                "--summary",
                "Because it is necessary.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["render-rehydrate", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        content = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("Active run: none", content)
        self.assertIn("Last run:", content)
        self.assertIn("Last decision:", content)
        decisions = sorted((self.data_root / ".synapse" / "DECISIONS").glob("DECISION__*.md"))
        self.assertTrue(decisions)
        decision_text = decisions[-1].read_text(encoding="utf-8")
        self.assertIn("## Implemented Truths", decision_text)
        self.assertIn("## Source Refs", decision_text)
        ledgers = sorted((self.data_root / ".synapse" / "DECISIONS").glob("*.yaml"))
        self.assertTrue(ledgers)
        entries = yaml.safe_load(ledgers[-1].read_text(encoding="utf-8"))["entries"]
        self.assertTrue(any(entry.get("title") == "Decision A" for entry in entries))
        control_sync = list((self.data_root / ".synapse" / "PROPOSALS" / "control_sync").glob("*.yaml"))
        self.assertTrue(control_sync)

    def test_render_rehydrate_refreshes_active_pack_and_archives_superseded_files(self):
        self._run_start(title="Continuity refresh", plan_item="Seal current truth")
        pack_dir = self.data_root / "Latest Rehydration Pack"
        archive_dir = self.data_root / "Archive" / "Latest Rehydration Pack"
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / "TestSubject_BOOTSTRAP_PROMPT__2026-03-09.txt").write_text("old bootstrap\n", encoding="utf-8")
        (pack_dir / "TestSubject_CONTINUITY_LOCK__2026-03-09.txt").write_text("old continuity\n", encoding="utf-8")

        result = run_cmd(["render-rehydrate", "--json", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        active_bootstrap = sorted(pack_dir.glob("*BOOTSTRAP_PROMPT*"))
        active_continuity = sorted(pack_dir.glob("*CONTINUITY_LOCK*"))
        self.assertEqual(len(active_bootstrap), 1)
        self.assertEqual(len(active_continuity), 1)
        self.assertTrue(archive_dir.exists())
        self.assertTrue(any(item.name.endswith("__2026-03-09.txt") for item in archive_dir.iterdir()))

        subject_state = yaml.safe_load((self.data_root / "SUBJECT_STATE.yaml").read_text(encoding="utf-8"))
        latest_pack = subject_state["pointers"]["latest_rehydration_pack"]
        self.assertEqual(latest_pack["bootstrap_prompt"]["path"], f"Latest Rehydration Pack/{active_bootstrap[0].name}")
        self.assertEqual(latest_pack["continuity_lock"]["path"], f"Latest Rehydration Pack/{active_continuity[0].name}")
        self.assertEqual(payload["continuity"]["continuity_lock_path"], str(active_continuity[0].resolve()))

    def test_log_disclosure_writes_durable_ledger_and_rehydrate(self):
        self._run_start(title="Blocked runtime", plan_item="Investigate ambiguity")
        result = run_cmd(
            [
                "log-disclosure",
                "--trigger",
                "Canonical working tree cannot be proven",
                "--expected",
                "One canonical repo root with intact subject state.",
                "--provable",
                "Multiple possible roots and no deterministic proof yet.",
                "--status-label",
                "BLOCKED",
                "--status-label",
                "UNKNOWN",
                "--impact",
                "Any structural change risks writing into the wrong tree.",
                "--safe-option",
                "HALT and confirm canonical tree.",
                "--safe-option",
                "Re-run discovery with receipts only.",
                "--decision-needed",
                "Confirm which tree is canonical.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["render-rehydrate", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        content = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Recent disclosures", content)
        self.assertIn("Confirm which tree is canonical.", content)

        disclosures = sorted((self.data_root / ".synapse" / "DISCLOSURES").glob("DISCLOSURE__*.md"))
        self.assertTrue(disclosures)
        disclosure_text = disclosures[-1].read_text(encoding="utf-8")
        self.assertIn("## Truths In Hand", disclosure_text)
        self.assertIn("## Unresolved / Review", disclosure_text)
        ledger = sorted((self.data_root / ".synapse" / "DISCLOSURES").glob("*.yaml"))
        self.assertTrue(ledger)
        entries = yaml.safe_load(ledger[-1].read_text(encoding="utf-8"))["entries"]
        self.assertTrue(any(entry.get("decision_needed") == "Confirm which tree is canonical." for entry in entries))
        proposals = list((self.data_root / ".synapse" / "PROPOSALS" / "disclosures").glob("*.yaml"))
        self.assertTrue(proposals)

    def test_log_disclosure_updates_related_quest_audit_bundle(self):
        self._run_start(title="Quest-bound disclosure", plan_item="Track quest uncertainty")
        accepted_dir = self.data_root / "Quest Board" / "Accepted"
        bundle_dir = self.data_root / "Audits" / "Execution" / "QUEST_001__2026-03-10__runtime-proof"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        quest_path = accepted_dir / "QUEST_001__runtime-proof__2026-03-10.txt"
        quest_path.write_text(
            "\n".join(
                [
                    "Quest ID:",
                    "QUEST_001",
                    "",
                    "Audit Bundle Folder Path (required once ACCEPTED):",
                    str(bundle_dir),
                    "",
                    "Talent Point Awarded: (YES / NO)",
                    "NO",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        for name in ["00_SUMMARY.md", "01_COMPLETION_AUDIT.md"]:
            (bundle_dir / name).write_text(f"# {name}\n", encoding="utf-8")

        result = run_cmd(
            [
                "log-disclosure",
                "--trigger",
                "Verification proof missing for QUEST_001",
                "--expected",
                "A PASS receipt for the accepted quest.",
                "--provable",
                "The implementation exists but proof is still incomplete.",
                "--status-label",
                "UNVERIFIED",
                "--impact",
                "Quest completion cannot be claimed safely.",
                "--safe-option",
                "Keep the quest open and gather proof.",
                "--decision-needed",
                "Confirm whether to re-run verification now.",
                "--related-quest",
                "QUEST_001",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        summary_text = (bundle_dir / "00_SUMMARY.md").read_text(encoding="utf-8")
        verify_text = (bundle_dir / "01_COMPLETION_AUDIT.md").read_text(encoding="utf-8")
        disclosure_text = (bundle_dir / "05_DISCLOSURE.md").read_text(encoding="utf-8")
        self.assertIn("Disclosure Gate Event", summary_text)
        self.assertIn("QUEST_001", summary_text)
        self.assertIn("Verification proof missing for QUEST_001", verify_text)
        self.assertIn("Decision Needed From Brains", disclosure_text)

    def test_record_quest_acceptance_writes_authored_discovery_artifact(self):
        self._run_start(title="Quest acceptance discovery", plan_item="Accept the governed quest")
        accepted_dir = self.data_root / "Quest Board" / "Accepted"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        accepted_path = accepted_dir / "QUEST_002__author-discovery__2026-04-09.txt"
        accepted_path.write_text("accepted quest\n", encoding="utf-8")
        audit_bundle_path = self.data_root / "Audits" / "Execution" / "QUEST_002__2026-04-09__author-discovery"
        audit_bundle_path.mkdir(parents=True, exist_ok=True)
        control_sync_state_path = self.data_root / ".synapse" / "STATE.yaml"
        result = record_quest_acceptance(
            subject="TestSubject",
            data_root=self.data_root,
            quest_id="QUEST_002",
            quest_title="Author discovery",
            accepted_path=accepted_path,
            audit_bundle_path=audit_bundle_path,
            control_sync_state_path=control_sync_state_path,
        )

        discovery_path = Path(result["discovery_path"])
        self.assertTrue(discovery_path.exists())
        discovery_text = discovery_path.read_text(encoding="utf-8")
        self.assertIn("## Implemented Truths", discovery_text)
        self.assertIn("Accepted quest artifact exists", discovery_text)

        ledgers = sorted((self.data_root / ".synapse" / "DISCOVERIES").glob("*.yaml"))
        self.assertTrue(ledgers)
        entries = yaml.safe_load(ledgers[-1].read_text(encoding="utf-8"))["entries"]
        entry = next(item for item in entries if item.get("kind") == "governed_execution_readiness")
        self.assertEqual(entry["artifact_path"], str(discovery_path))
        self.assertIn("authored_sections", entry)

    def test_session_tick_creates_run_and_promotion_backlog(self):
        result = run_cmd(
            [
                "session-tick",
                "--title",
                "Ambient scope shift",
                "--summary",
                "runtime scope shift for ambient governance",
                "--command",
                "python3 -m unittest",
                "--file",
                "runtime/synapse.py",
                "--verification",
                "unit tests passed",
                "--decision-title",
                "Ambient runtime direction",
                "--decision-summary",
                "Promote ambient sidecar as primary runtime.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertTrue(active.get("run_id"))

        proposals_root = self.data_root / ".synapse" / "PROPOSALS"
        self.assertTrue(list((proposals_root / "control_sync").glob("*.yaml")))
        self.assertTrue(list((proposals_root / "quests").glob("*.yaml")))
        self.assertTrue(list((proposals_root / "codex").glob("*.yaml")))
        self.assertTrue(list((proposals_root / "guild_orders").glob("*.yaml")))
        self.assertFalse(list((proposals_root / "talent").glob("*.yaml")))
        codex_payload = yaml.safe_load(sorted((proposals_root / "codex").glob("*.yaml"))[-1].read_text(encoding="utf-8"))
        guild_orders_payload = yaml.safe_load(sorted((proposals_root / "guild_orders").glob("*.yaml"))[-1].read_text(encoding="utf-8"))
        self.assertEqual(codex_payload["canonizer_schema_version"], 1)
        self.assertIn("canonizer_sections", codex_payload)
        self.assertTrue(codex_payload["evidence_sources"])
        self.assertTrue(codex_payload["confidence_reason"])
        self.assertEqual(guild_orders_payload["canonizer_schema_version"], 1)
        self.assertIn("canonizer_sections", guild_orders_payload)
        self.assertTrue(guild_orders_payload["coherent_outcome"])
        self.assertTrue(guild_orders_payload["closure_statement"])
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertTrue(manifold.get("quest_candidate_details"))
        self.assertTrue(manifold.get("codex_candidate_details"))
        self.assertTrue(manifold.get("guild_order_candidate_details"))
        self.assertEqual(manifold.get("current_verification_status"), "PASS")
        rehydrate = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Quest candidates", rehydrate)
        self.assertIn("## Recent verification", rehydrate)
        self.assertIn("unit tests passed", rehydrate)

    def test_formalize_snapshot_codex_and_guild_orders_candidates(self):
        self._run_start(title="Capability work", plan_item="Ship runtime")
        result = run_cmd(
            [
                "run-update",
                "--set-item-status",
                "ITEM-001:DONE",
                "--command",
                "python3 -m unittest",
                "--file",
                "runtime/synapse.py",
                "--verification",
                "tests passed",
                "--summary",
                "scope phase runtime capability shift",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["run-finalize", "--status", "completed", "--summary", "close session", *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        snapshots = sorted((self.data_root / ".synapse" / "PROPOSALS" / "snapshots").glob("*.yaml"))
        codex = sorted((self.data_root / ".synapse" / "PROPOSALS" / "codex").glob("*.yaml"))
        guild_orders = sorted((self.data_root / ".synapse" / "PROPOSALS" / "guild_orders").glob("*.yaml"))
        self.assertTrue(snapshots)
        self.assertTrue(codex)
        self.assertTrue(guild_orders)

        snapshot_id = yaml.safe_load(snapshots[-1].read_text(encoding="utf-8"))["proposal_id"]
        codex_id = yaml.safe_load(codex[-1].read_text(encoding="utf-8"))["proposal_id"]
        guild_orders_id = yaml.safe_load(guild_orders[-1].read_text(encoding="utf-8"))["proposal_id"]

        result = run_cmd(["formalize", "--proposal-id", snapshot_id, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["formalize", "--proposal-id", codex_id, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["formalize", "--proposal-id", guild_orders_id, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertTrue(list((self.data_root / "Snapshots" / "End of Day").glob("*.txt")))
        self.assertTrue(list((self.data_root / "Codex" / "Sections").glob("CANDIDATE__*.md")))
        self.assertTrue(list((self.data_root / "Guild Orders" / "PAUSED").glob("GO-*.txt")))

    def test_formalize_build_manual_and_disclosure_candidates(self):
        self._run_start(title="Runtime build manual", plan_item="Shape runtime HOW guidance")
        result = run_cmd(
            [
                "run-update",
                "--set-item-status",
                "ITEM-001:DONE",
                "--command",
                "python3 -m unittest",
                "--file",
                "runtime/synapse.py",
                "--verification",
                "tests passed",
                "--summary",
                "runtime build manual scaffolding wiring and verification expectations changed",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        build_manual = sorted((self.data_root / ".synapse" / "PROPOSALS" / "build_manual").glob("*.yaml"))
        self.assertTrue(build_manual)
        build_manual_id = yaml.safe_load(build_manual[-1].read_text(encoding="utf-8"))["proposal_id"]

        result = run_cmd(
            [
                "log-disclosure",
                "--trigger",
                "Build path proof missing",
                "--expected",
                "A stable verification path for the new runtime slice.",
                "--provable",
                "Implementation changed, but final proof path still needs Brains confirmation.",
                "--status-label",
                "UNVERIFIED",
                "--impact",
                "Cannot safely claim the governed build path is complete.",
                "--safe-option",
                "Formalize a disclosure snapshot and hold claims.",
                "--decision-needed",
                "Approve the verification path or redirect it.",
                *self.subject_args,
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        disclosures = sorted((self.data_root / ".synapse" / "PROPOSALS" / "disclosures").glob("*.yaml"))
        self.assertTrue(disclosures)
        disclosure_id = yaml.safe_load(disclosures[-1].read_text(encoding="utf-8"))["proposal_id"]

        result = run_cmd(["formalize", "--proposal-id", build_manual_id, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_cmd(["formalize", "--proposal-id", disclosure_id, *self.subject_args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        manual_path = self.data_root / "Build_Manual" / "BUILD_MANUAL.md"
        self.assertTrue(manual_path.exists())
        manual_text = manual_path.read_text(encoding="utf-8")
        self.assertIn("Runtime build manual", manual_text)
        self.assertIn("Execution changed scaffolding, sequencing, or verification expectations enough to warrant Build Manual guidance.", manual_text)
        self.assertTrue(list((self.data_root / "Build_Manual" / "Updates").glob("UPDATE__*.md")))
        self.assertTrue(list((self.data_root / "Snapshots" / "General").glob("*.txt")))


if __name__ == "__main__":
    unittest.main()

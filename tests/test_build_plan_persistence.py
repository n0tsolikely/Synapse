import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.quest_plans import list_plan_artifacts, load_execution_plan
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock
from synapse_runtime.truth_sources import collect_evidence

SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path, extra_env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True, input=stdin)


class BuildPlanPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "PlanPersistenceRepo"
        self.engine_root = self.root / self.subject
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
        self.data_root = self.root / f"{self.subject}_Data"
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        write_focus_lock(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            cwt=self.engine_root,
            home=self.home,
            selection_method="test",
            source_detail="test_build_plan_persistence",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_record_raw_turn_creates_and_revises_plan_artifacts(self) -> None:
        first = run_synapse(
            [
                "record-raw-turn",
                "--role",
                "user",
                "--source-surface",
                "cli-test",
                "--text",
                "Okay, that's the plan: we need to build an installable web app with separate user accounts and audio transcription support.",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_payload = json.loads(first.stdout)
        first_plan = first_payload["reducer"]["sidecar"]["governed_promotion"]["plan_revisions"]
        self.assertEqual(len(first_plan), 1)

        second = run_synapse(
            [
                "record-raw-turn",
                "--role",
                "user",
                "--source-surface",
                "cli-test",
                "--text",
                "Okay, that's the plan: we need to build an installable web app with separate user accounts and audio transcription support.",
                "--json",
            ],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_payload = json.loads(second.stdout)
        second_plan = second_payload["reducer"]["sidecar"]["governed_promotion"]["plan_revisions"]
        self.assertEqual(len(second_plan), 1)

        artifacts = list_plan_artifacts(self.data_root)
        self.assertEqual(len(artifacts), 2)
        latest = load_execution_plan(artifacts[-1])
        self.assertEqual(latest["revision_number"], 2)
        self.assertTrue(latest["source_segment_ids"])
        self.assertTrue(latest["source_semantic_event_ids"])
        self.assertTrue(latest["lineage_family_id"])
        self.assertIn("build.plan", latest["semantic_topics"])

        evidence = collect_evidence(subject=self.subject, data_root=self.data_root, engine_root=self.engine_root)
        source_types = {item.source_type for item in evidence["evidence_records"]}
        self.assertIn("plan_revision", source_types)
        self.assertIn("governed_working_record", source_types)

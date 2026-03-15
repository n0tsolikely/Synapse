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

from synapse_runtime.event_log import append_event, build_event, validate_event_stream
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import home_focus_lock_path, repo_focus_lock_path, write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class EventSpineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "EventSubject"
        self.data_root = (self.root / f"{self.subject}_Data").resolve()
        self.engine_root = (self.root / f"{self.subject}_Engine").resolve()
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        self.subject_args = [
            "--subject",
            self.subject,
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self) -> None:
        repo_lock = repo_focus_lock_path(REPO_ROOT)
        if repo_lock.exists():
            repo_lock.unlink()
        home_lock = home_focus_lock_path(self.home)
        if home_lock.exists():
            home_lock.unlink()
        self.tmp.cleanup()

    def _events_root(self) -> Path:
        return self.data_root / ".synapse" / "EVENTS"

    def _load_state(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))

    def _engage(self) -> None:
        write_focus_lock(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            cwt=REPO_ROOT,
            home=self.home,
            selection_method="test",
            source_detail="test_event_spine",
        )

    def test_append_event_uses_required_envelope_shape_and_rotates_by_day(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        first = build_event(
            subject=self.subject,
            action_name="run-update",
            summary="Track event contract",
            status="ok",
            timestamp="2026-03-14T23:55:00-04:00",
            signals={
                "commands": ["python3 -m unittest tests.test_event_spine"],
                "changed_files": ["runtime/synapse.py"],
                "verification_entries": ["tests passed"],
                "related_quest_ids": ["QUEST_001"],
                "accepted_context": {
                    "current_accepted_quest_id": "QUEST_001",
                    "governed_execution_ready": True,
                    "active_order_ids": ["ORDER_001"],
                },
            },
            truth_flags={"governed": True, "derived_state_changed": True},
            outputs={"written_artifacts": ["runtime/synapse.py"]},
        )
        second = build_event(
            subject=self.subject,
            action_name="log-decision",
            summary="Roll into next day",
            status="ok",
            timestamp="2026-03-15T00:05:00-04:00",
            signals={"decisions": ["Decision B"]},
            truth_flags={"derived_state_changed": True},
            outputs={"written_artifacts": ["Decision.md"]},
        )

        first_receipt = append_event(data_root=self.data_root, event=first)
        second_receipt = append_event(data_root=self.data_root, event=second)

        self.assertTrue(Path(first_receipt["path"]).exists())
        self.assertTrue(Path(second_receipt["path"]).exists())
        self.assertNotEqual(first_receipt["path"], second_receipt["path"])
        self.assertEqual(Path(first_receipt["path"]).name, "2026-03-14.jsonl")
        self.assertEqual(Path(second_receipt["path"]).name, "2026-03-15.jsonl")
        self.assertEqual(validate_event_stream(self.data_root), [])

        payload = json.loads(Path(first_receipt["path"]).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(payload["action_name"], "run-update")
        self.assertEqual(payload["signals"]["commands"], ["python3 -m unittest tests.test_event_spine"])
        self.assertEqual(payload["signals"]["plan_items"], [])
        self.assertEqual(payload["signals"]["decisions"], [])
        self.assertEqual(payload["signals"]["accepted_context"]["current_accepted_quest_id"], "QUEST_001")
        self.assertTrue(payload["truth_flags"]["governed"])
        self.assertIn("canon_mutated", payload["truth_flags"])
        self.assertIn("written_artifacts", payload["outputs"])
        self.assertIn("accepted_quest_id", payload["outputs"])
        self.assertEqual(len(payload["semantic_fingerprint"]), 64)

    def test_run_start_emits_event_and_reducer_metadata(self) -> None:
        result = run_synapse(
            ["run-start", "--title", "Evented run", "--plan-item", "Do the thing", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        payload = json.loads(result.stdout)
        event_payload = payload["event"]["payload"]
        receipt = payload["event"]["receipt"]
        self.assertEqual(event_payload["action_name"], "run-start")
        self.assertEqual(event_payload["signals"]["run_title"], "Evented run")
        self.assertEqual(event_payload["signals"]["plan_items"], ["Do the thing"])
        self.assertEqual(payload["reducer"]["mode"], "active")
        self.assertIsNotNone(payload["reducer"]["sidecar"])
        self.assertTrue(Path(receipt["path"]).exists())

        state = self._load_state()
        self.assertEqual(state.get("last_event_id"), event_payload["event_id"])
        self.assertEqual(state.get("last_reduced_event_id"), event_payload["event_id"])
        self.assertEqual(state.get("reducer_version"), payload["reducer"]["reducer_version"])
        self.assertTrue((self.data_root / ".synapse" / "REHYDRATE.md").exists())

    def test_doctor_accepts_live_subject_without_event_spine_until_upgraded(self) -> None:
        ensure_live_scaffold(self.subject, self.data_root)
        events_root = self._events_root()
        self.assertTrue(events_root.exists())
        events_root.rmdir()
        self._engage()

        doctor = run_synapse(
            ["doctor", "--governance-root", str(REPO_ROOT / "governance")],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("MISSING (UPGRADEABLE EVENT SPINE)", doctor.stdout + doctor.stderr)

        run_start = run_synapse(
            ["run-start", "--title", "Upgrade legacy", "--plan-item", "Emit first event", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(run_start.returncode, 0, run_start.stdout + run_start.stderr)
        self.assertTrue(self._events_root().is_dir())
        self.assertTrue(list(self._events_root().glob("*.jsonl")))

    def test_doctor_fails_on_malformed_event_stream(self) -> None:
        ensure_live_scaffold(self.subject, self.data_root)
        bad_log = self._events_root() / "2026-03-15.jsonl"
        bad_log.write_text("{bad json\n", encoding="utf-8")
        self._engage()

        doctor = run_synapse(
            ["doctor", "--governance-root", str(REPO_ROOT / "governance")],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertNotEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertIn("FAIL_INVALID_EVENTS:1", doctor.stdout + doctor.stderr)

    def test_legacy_reducer_mode_bypasses_reducer_but_keeps_event_append(self) -> None:
        result = run_synapse(
            ["run-start", "--title", "Legacy reducer", "--plan-item", "Fallback path", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
            extra_env={"SYNAPSE_REDUCER_MODE": "legacy"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload["reducer"]["mode"], "legacy")
        self.assertTrue(list(self._events_root().glob("*.jsonl")))
        state = self._load_state()
        self.assertIsNone(state.get("last_event_id"))
        self.assertIsNone(state.get("last_reduced_event_id"))
        self.assertIsNone(state.get("reducer_version"))


if __name__ == "__main__":
    unittest.main()

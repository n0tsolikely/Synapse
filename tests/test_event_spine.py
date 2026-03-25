import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.event_log import EventLogError, append_event, build_event, validate_event_stream
from synapse_runtime.reducer import ReducerError
from synapse_runtime.sidecar_store import ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import home_focus_lock_path, repo_focus_lock_path, write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]
_SYNAPSE_SPEC = importlib.util.spec_from_file_location("synapse_cli_test_module", REPO_ROOT / "runtime" / "synapse.py")
assert _SYNAPSE_SPEC and _SYNAPSE_SPEC.loader
synapse_cli = importlib.util.module_from_spec(_SYNAPSE_SPEC)
_SYNAPSE_SPEC.loader.exec_module(synapse_cli)


def run_synapse(args: list[str], *, cwd: Path, home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("SYNAPSE_SESSION_ID", None)
    env.pop("SUBJECT", None)
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

    def _event_entries(self) -> list[dict]:
        entries: list[dict] = []
        for path in sorted(self._events_root().glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def _engage(self) -> None:
        with mock.patch.dict(os.environ, {"SYNAPSE_SESSION_ID": "", "SUBJECT": ""}, clear=False):
            write_focus_lock(
                subject=self.subject,
                data_root=self.data_root,
                engine_root=self.engine_root,
                cwt=REPO_ROOT,
                home=self.home,
                selection_method="test",
                source_detail="test_event_spine",
            )

    def _run_start_namespace(self, *, json_mode: bool) -> argparse.Namespace:
        return argparse.Namespace(
            title="Evented run",
            goal=None,
            plan_item=["Do the thing"],
            items_file=None,
            subject=self.subject,
            data_root=str(self.data_root),
            engine_root=str(self.engine_root),
            allow_switch=True,
            session_id=None,
            json=json_mode,
        )

    def _session_mode_namespace(self, *, json_mode: bool) -> argparse.Namespace:
        return argparse.Namespace(
            target_session_mode="scope_planning",
            reason="Move from ideation into scoped planning",
            subject=self.subject,
            data_root=str(self.data_root),
            engine_root=str(self.engine_root),
            allow_switch=True,
            session_id=None,
            json=json_mode,
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

    def test_follow_up_event_uses_persisted_active_run_session_id(self) -> None:
        start = run_synapse(
            [
                "run-start",
                "--title",
                "Evented run",
                "--plan-item",
                "Do the thing",
                "--session-id",
                "sid-event",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        update = run_synapse(
            ["run-update", "--summary", "follow-up", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        payload = json.loads(update.stdout)
        persisted_event = self._event_entries()[-1]
        self.assertEqual(payload["event"]["payload"]["session_id"], "sid-event")
        self.assertEqual(persisted_event["session_id"], "sid-event")

    def test_run_update_records_automation_metadata_and_side_effect_outputs(self) -> None:
        start = run_synapse(
            [
                "session-start",
                "--title",
                "Automation event run",
                "--session-mode",
                "control_sync",
                "--session-id",
                "sid-auto",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        update = run_synapse(
            [
                "run-update",
                "--summary",
                "Risk surfaced in runtime bridge",
                "--note",
                "risk: event replay may miss automation capture context",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        payload = json.loads(update.stdout)
        event_payload = payload["event"]["payload"]
        self.assertTrue(event_payload["signals"]["automation_triggered"])
        self.assertIn("semantic_capture", event_payload["signals"]["automation_action_kinds"])
        self.assertIn("disclosure_log", event_payload["signals"]["automation_action_kinds"])
        self.assertIn("continuity_refresh", event_payload["signals"]["automation_action_kinds"])
        self.assertEqual(event_payload["signals"]["automation_context"]["activity_kind"], "run-update")
        self.assertIsNotNone(event_payload["outputs"]["capture_artifact_path"])
        self.assertIsNotNone(event_payload["outputs"]["disclosures_ledger_path"])

        persisted_event = self._event_entries()[-1]
        self.assertEqual(
            persisted_event["signals"]["automation_action_kinds"],
            event_payload["signals"]["automation_action_kinds"],
        )
        self.assertEqual(
            persisted_event["outputs"]["capture_artifact_path"],
            event_payload["outputs"]["capture_artifact_path"],
        )

    def test_session_mode_set_uses_persisted_active_run_session_id(self) -> None:
        start = run_synapse(
            [
                "session-start",
                "--title",
                "Evented session",
                "--session-id",
                "sid-mode",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        transition = run_synapse(
            [
                "session-mode",
                "--set",
                "scope_planning",
                "--reason",
                "Need a scoped planning posture",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(transition.returncode, 0, transition.stdout + transition.stderr)

        payload = json.loads(transition.stdout)
        persisted_event = self._event_entries()[-1]
        self.assertEqual(payload["event"]["payload"]["session_id"], "sid-mode")
        self.assertEqual(persisted_event["session_id"], "sid-mode")

    def test_run_finalize_event_preserves_prior_session_posture_signals(self) -> None:
        start = run_synapse(
            ["run-start", "--title", "Evented run", "--plan-item", "Do the thing", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        update = run_synapse(
            ["run-update", "--set-item-status", "ITEM-001:DONE", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)

        finalize = run_synapse(
            ["run-finalize", "--status", "completed", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(finalize.returncode, 0, finalize.stdout + finalize.stderr)

        payload = json.loads(finalize.stdout)
        event_payload = payload["event"]["payload"]
        persisted_events = self._event_entries()
        run_finalize_event = next(
            event for event in reversed(persisted_events) if event.get("action_name") == "run-finalize"
        )
        compile_event = persisted_events[-1]

        self.assertEqual(payload["session_mode"], "execution")
        self.assertEqual(payload["session_mode_source"], "command_default")
        self.assertEqual(payload["session_mode_policy_version"], 1)
        self.assertEqual(event_payload["action_name"], "run-finalize")
        self.assertEqual(event_payload["signals"]["session_mode"], "execution")
        self.assertEqual(event_payload["signals"]["session_mode_source"], "command_default")
        self.assertEqual(event_payload["signals"]["session_mode_policy_version"], 1)
        self.assertEqual(run_finalize_event["action_name"], "run-finalize")
        self.assertEqual(run_finalize_event["signals"]["session_mode"], "execution")
        self.assertEqual(run_finalize_event["signals"]["session_mode_source"], "command_default")
        self.assertEqual(run_finalize_event["signals"]["session_mode_policy_version"], 1)
        self.assertEqual(compile_event["action_name"], "compile-current-state")

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

    def test_reducer_failure_after_event_append_returns_partial_runtime_status(self) -> None:
        args = self._run_start_namespace(json_mode=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with mock.patch.object(synapse_cli, "reduce_after_event", side_effect=ReducerError("boom")):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = synapse_cli.cmd_run_start(args)

        self.assertEqual(exit_code, 3, stdout.getvalue() + stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        runtime_status = payload["runtime_status"]
        self.assertEqual(runtime_status["operation_status"], "partial")
        self.assertTrue(runtime_status["primary_mutation_committed"])
        self.assertTrue(runtime_status["event_recorded"])
        self.assertFalse(runtime_status["derived_state_current"])
        self.assertEqual(runtime_status["error_code"], "REDUCER_REFRESH_FAILED")
        self.assertTrue(runtime_status["event_id"])
        self.assertTrue(list(self._events_root().glob("*.jsonl")))

    def test_event_append_failure_after_primary_mutation_returns_partial_runtime_status(self) -> None:
        args = self._run_start_namespace(json_mode=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with mock.patch.object(synapse_cli, "append_event", side_effect=EventLogError("append blew up")):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = synapse_cli.cmd_run_start(args)

        self.assertEqual(exit_code, 3, stdout.getvalue() + stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        runtime_status = payload["runtime_status"]
        self.assertEqual(runtime_status["operation_status"], "partial")
        self.assertTrue(runtime_status["primary_mutation_committed"])
        self.assertFalse(runtime_status["event_recorded"])
        self.assertFalse(runtime_status["derived_state_current"])
        self.assertEqual(runtime_status["error_code"], "EVENT_APPEND_FAILED")
        self.assertIsNone(runtime_status["event_id"])
        self.assertFalse(list(self._events_root().glob("*.jsonl")))

    def test_pre_mutation_failure_stays_hard_failure(self) -> None:
        args = self._run_start_namespace(json_mode=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with mock.patch.object(synapse_cli, "run_start", side_effect=synapse_cli.LiveMemoryError("no write")):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = synapse_cli.cmd_run_start(args)

        combined = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(exit_code, 2, combined)
        self.assertIn("FAIL: no write", combined)
        self.assertNotIn("runtime_status", combined)

    def test_text_mode_partial_receipt_includes_event_id_and_recovery_hint(self) -> None:
        args = self._run_start_namespace(json_mode=False)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with mock.patch.object(synapse_cli, "reduce_after_event", side_effect=ReducerError("boom")):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = synapse_cli.cmd_run_start(args)

        combined = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(exit_code, 3, combined)
        self.assertIn("PARTIAL:", combined)
        self.assertIn("event_id:", combined)
        self.assertIn("recovery_hint:", combined)

    def test_session_mode_set_uses_partial_runtime_status_when_reducer_refresh_fails(self) -> None:
        start = run_synapse(
            ["session-start", "--title", "Evented session", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        args = self._session_mode_namespace(json_mode=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}, clear=False):
            with mock.patch.object(synapse_cli, "reduce_after_event", side_effect=ReducerError("boom")):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = synapse_cli.cmd_session_mode(args)

        self.assertEqual(exit_code, 3, stdout.getvalue() + stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        runtime_status = payload["runtime_status"]
        self.assertEqual(runtime_status["operation_status"], "partial")
        self.assertTrue(runtime_status["primary_mutation_committed"])
        self.assertTrue(runtime_status["event_recorded"])
        self.assertFalse(runtime_status["derived_state_current"])
        self.assertEqual(runtime_status["error_code"], "REDUCER_REFRESH_FAILED")
        self.assertEqual(payload["from_session_mode"], "brainstorm_spec")
        self.assertEqual(payload["to_session_mode"], "scope_planning")

    def test_all_event_pipeline_call_sites_route_through_shared_result_handler(self) -> None:
        source = (REPO_ROOT / "runtime" / "synapse.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("event_info = _event_pipeline("), 23)
        inline_event_commands = (
            "cmd_attach_or_init",
            "cmd_live_bootstrap",
            "cmd_run_start",
            "cmd_session_start",
            "cmd_run_update",
            "cmd_session_tick",
            "cmd_capture_chunk",
            "cmd_onboarding_update",
            "cmd_onboarding_respond",
            "cmd_onboarding_confirm",
            "cmd_onboarding_abandon",
            "cmd_run_finalize",
            "cmd_session_mode",
            "cmd_install_hooks",
            "cmd_verify_hooks",
            "cmd_log_decision",
            "cmd_log_disclosure",
        )
        helper_event_commands = {
            "cmd_onboard_repo": "_run_onboarding_bootstrap(",
            "cmd_accept_quest": "_accept_quest_mutation(",
            "cmd_formalize": "_formalize_candidate_mutation(",
            "cmd_compile_current_state": "_run_truth_compile(",
        }
        for fn_name in inline_event_commands:
            marker = f"def {fn_name}("
            start = source.index(marker)
            end = source.find("\ndef ", start + 1)
            block = source[start:end if end != -1 else None]
            self.assertIn("_event_pipeline(", block, fn_name)
            self.assertIn("_finalize_mutation_result(", block, fn_name)
        watch_marker = "def cmd_watch("
        watch_start = source.index(watch_marker)
        watch_end = source.find("\ndef ", watch_start + 1)
        watch_block = source[watch_start:watch_end if watch_end != -1 else None]
        self.assertIn("_event_pipeline(", watch_block)
        for fn_name, helper_call in helper_event_commands.items():
            marker = f"def {fn_name}("
            start = source.index(marker)
            end = source.find("\ndef ", start + 1)
            block = source[start:end if end != -1 else None]
            self.assertIn(helper_call, block, fn_name)
            self.assertIn("_finalize_mutation_result(", block, fn_name)
        for helper_name in (
            "_run_onboarding_bootstrap",
            "_accept_quest_mutation",
            "_formalize_candidate_mutation",
            "_run_truth_compile",
        ):
            marker = f"def {helper_name}("
            start = source.index(marker)
            end = source.find("\ndef ", start + 1)
            block = source[start:end if end != -1 else None]
            self.assertIn("_event_pipeline(", block, helper_name)


if __name__ == "__main__":
    unittest.main()

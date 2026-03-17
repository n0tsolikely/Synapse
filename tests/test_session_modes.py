import unittest
import tempfile
import json
import os
import subprocess

from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime.governance_model import ProposalKind
from synapse_runtime.session_modes import (
    SESSION_MODE_POLICY_VERSION,
    SessionMode,
    backfill_mode_from_active_run,
    default_mode_for_command,
    policy_for,
    policy_summary,
    session_mode_signal_fields,
    validate_transition,
)
from synapse_runtime.sidecar_store import _default_active_run, _load_active_run


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class SessionModePolicyTests(unittest.TestCase):
    def test_canonical_registry_contains_all_six_modes(self) -> None:
        expected = {
            "onboarding_existing_repo",
            "brainstorm_spec",
            "control_sync",
            "scope_planning",
            "execution",
            "closeout",
        }
        self.assertEqual({mode.value for mode in SessionMode}, expected)

    def test_each_policy_exposes_required_fields(self) -> None:
        for mode in SessionMode:
            policy = policy_for(mode)
            summary = policy_summary(mode)
            self.assertEqual(policy.mode, mode)
            self.assertTrue(policy.description)
            self.assertIsInstance(policy.allowed_proposal_kinds, tuple)
            self.assertIn("description", summary)
            self.assertIn("blocked_mutation_commands", summary)
            self.assertIn("allowed_next_modes", summary)
            self.assertIn("auto_formalize_ready_quests", summary)
            self.assertIn("manual_formalize_allowed", summary)
            self.assertIn("quest_acceptance_allowed", summary)
            self.assertIn("allowed_proposal_kinds", summary)

    def test_default_mode_resolution_is_deterministic(self) -> None:
        self.assertEqual(default_mode_for_command("session-start"), SessionMode.BRAINSTORM_SPEC)
        self.assertEqual(default_mode_for_command("session-tick"), SessionMode.BRAINSTORM_SPEC)
        self.assertEqual(default_mode_for_command("run-start"), SessionMode.EXECUTION)

    def test_execution_policy_allows_talent_and_closeout_blocks_quest_like_outputs(self) -> None:
        self.assertIn(ProposalKind.TALENT, policy_for(SessionMode.EXECUTION).allowed_proposal_kinds)
        closeout_kinds = set(policy_for(SessionMode.CLOSEOUT).allowed_proposal_kinds)
        self.assertNotIn(ProposalKind.QUEST, closeout_kinds)
        self.assertNotIn(ProposalKind.SIDE_QUEST, closeout_kinds)
        self.assertNotIn(ProposalKind.GUILD_ORDERS, closeout_kinds)

    def test_transition_validation_matches_graph(self) -> None:
        allowed, next_modes = validate_transition(SessionMode.BRAINSTORM_SPEC, SessionMode.SCOPE_PLANNING)
        self.assertTrue(allowed)
        self.assertIn(SessionMode.SCOPE_PLANNING, next_modes)

        blocked, next_modes = validate_transition(SessionMode.BRAINSTORM_SPEC, SessionMode.EXECUTION)
        self.assertFalse(blocked)
        self.assertNotIn(SessionMode.EXECUTION, next_modes)

        blocked, next_modes = validate_transition(SessionMode.CLOSEOUT, SessionMode.EXECUTION)
        self.assertFalse(blocked)
        self.assertNotIn(SessionMode.EXECUTION, next_modes)

    def test_backfill_maps_decision_to_control_sync(self) -> None:
        run_data, changed = backfill_mode_from_active_run(
            {"interaction_mode": "decision", "run_id": "RUN-LEGACY", "active": True},
            "2026-03-16T12:00:00-04:00",
        )
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.CONTROL_SYNC.value)
        self.assertEqual(run_data["session_mode_source"], "legacy_backfill")
        self.assertEqual(run_data["session_mode_policy_version"], SESSION_MODE_POLICY_VERSION)

    def test_backfill_maps_missing_or_maintenance_to_brainstorm_spec(self) -> None:
        run_data, changed = backfill_mode_from_active_run(
            {"interaction_mode": "maintenance", "run_id": "RUN-LEGACY", "active": True},
            "2026-03-16T12:00:00-04:00",
        )
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

        run_data, changed = backfill_mode_from_active_run(
            {"run_id": "RUN-LEGACY", "active": True},
            "2026-03-16T12:00:00-04:00",
        )
        self.assertTrue(changed)
        self.assertEqual(run_data["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

    def test_backfill_is_noop_when_session_mode_already_exists(self) -> None:
        run_data = {
            "session_mode": SessionMode.EXECUTION.value,
            "session_mode_source": "explicit",
            "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
        }
        normalized, changed = backfill_mode_from_active_run(run_data, "2026-03-16T12:00:00-04:00")
        self.assertFalse(changed)
        self.assertEqual(normalized, run_data)

    def test_backfill_does_not_invent_posture_for_idle_default_run(self) -> None:
        run_data = {
            "active": False,
            "run_id": None,
            "interaction_mode": "maintenance",
        }
        normalized, changed = backfill_mode_from_active_run(run_data, "2026-03-16T12:00:00-04:00")
        self.assertFalse(changed)
        self.assertNotIn("session_mode", normalized)

    def test_signal_fields_return_only_posture_context(self) -> None:
        self.assertEqual(session_mode_signal_fields(None), {})
        self.assertEqual(session_mode_signal_fields({}), {})
        self.assertEqual(
            session_mode_signal_fields(
                {
                    "session_mode": SessionMode.SCOPE_PLANNING.value,
                    "session_mode_source": "explicit",
                    "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
                    "session_mode_reason": "ignored here",
                }
            ),
            {
                "session_mode": "scope_planning",
                "session_mode_source": "explicit",
                "session_mode_policy_version": SESSION_MODE_POLICY_VERSION,
            },
        )


class ActiveRunNormalizationTests(unittest.TestCase):
    def test_load_active_run_backfills_decision_to_control_sync_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ACTIVE_RUN.yaml"
            payload = _default_active_run("Subject")
            payload["active"] = True
            payload["run_id"] = "RUN-1"
            payload["interaction_mode"] = "decision"
            for key in (
                "session_mode",
                "session_mode_source",
                "session_mode_set_at",
                "session_mode_reason",
                "session_mode_policy_version",
            ):
                payload.pop(key, None)
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

            run_data = _load_active_run(path, "Subject")

            self.assertEqual(run_data["session_mode"], SessionMode.CONTROL_SYNC.value)
            self.assertEqual(run_data["session_mode_source"], "legacy_backfill")
            persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["session_mode"], SessionMode.CONTROL_SYNC.value)
            self.assertEqual(persisted["session_mode_policy_version"], SESSION_MODE_POLICY_VERSION)

    def test_load_active_run_backfills_maintenance_to_brainstorm_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ACTIVE_RUN.yaml"
            payload = _default_active_run("Subject")
            payload["active"] = True
            payload["run_id"] = "RUN-2"
            payload["interaction_mode"] = "maintenance"
            for key in (
                "session_mode",
                "session_mode_source",
                "session_mode_set_at",
                "session_mode_reason",
                "session_mode_policy_version",
            ):
                payload.pop(key, None)
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

            run_data = _load_active_run(path, "Subject")

            self.assertEqual(run_data["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

    def test_repeated_loads_do_not_remutate_already_backfilled_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ACTIVE_RUN.yaml"
            payload = _default_active_run("Subject")
            payload["active"] = True
            payload["run_id"] = "RUN-3"
            payload["interaction_mode"] = "decision"
            for key in (
                "session_mode",
                "session_mode_source",
                "session_mode_set_at",
                "session_mode_reason",
                "session_mode_policy_version",
            ):
                payload.pop(key, None)
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

            _load_active_run(path, "Subject")
            first_text = path.read_text(encoding="utf-8")
            _load_active_run(path, "Subject")
            second_text = path.read_text(encoding="utf-8")

            self.assertEqual(first_text, second_text)


class SessionModeLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / "ModeSubject_Data"
        self.engine_root = self.root / "ModeSubject_Engine"
        self.data_root.mkdir()
        self.engine_root.mkdir()
        self.subject_args = [
            "--subject",
            "ModeSubject",
            "--data-root",
            str(self.data_root),
            "--engine-root",
            str(self.engine_root),
            "--allow-switch",
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _read_active_run(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "ACTIVE_RUN.yaml").read_text(encoding="utf-8"))

    def _read_state(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))

    def _read_manifold(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))

    def _read_rehydrate(self) -> str:
        return (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")

    def _start_brainstorm_session(self) -> None:
        result = run_synapse(["session-start", "--title", "Spec pass", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_session_start_new_run_defaults_to_brainstorm_spec(self) -> None:
        result = run_synapse(["session-start", "--title", "Spec pass", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        active = self._read_active_run()
        self.assertEqual(active["session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertEqual(active["session_mode_source"], "command_default")
        self.assertEqual(payload["run"]["event"]["payload"]["signals"]["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

    def test_session_tick_create_defaults_to_brainstorm_spec(self) -> None:
        result = run_synapse(
            ["session-tick", "--summary", "Capture idea drift", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertEqual(active["session_mode"], SessionMode.BRAINSTORM_SPEC.value)

    def test_run_start_defaults_to_execution(self) -> None:
        result = run_synapse(["run-start", "--title", "Build path", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = self._read_active_run()
        self.assertEqual(active["session_mode"], SessionMode.EXECUTION.value)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["session_mode"], SessionMode.EXECUTION.value)
        self.assertEqual(payload["event"]["payload"]["signals"]["session_mode"], SessionMode.EXECUTION.value)

    def test_finalize_clears_active_posture_and_preserves_last_posture_in_archive(self) -> None:
        result = run_synapse(["run-start", "--title", "Build path", "--plan-item", "Ship it", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_synapse(["run-update", "--set-item-status", "ITEM-001:DONE", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_synapse(["run-finalize", "--status", "completed", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        active = self._read_active_run()
        self.assertIsNone(active["session_mode"])
        payload = json.loads(result.stdout)
        archive_path = Path(payload["archive_path"])
        archived = yaml.safe_load(archive_path.read_text(encoding="utf-8"))
        self.assertEqual(archived["session_mode"], SessionMode.EXECUTION.value)
        self.assertEqual(archived["last_session_mode"], SessionMode.EXECUTION.value)
        self.assertTrue(archived["last_session_mode_ended_at"])

    def test_session_mode_inspect_returns_active_posture(self) -> None:
        self._start_brainstorm_session()
        result = run_synapse(["session-mode", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["active_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertIn("scope_planning", payload["allowed_next_modes"])

    def test_active_posture_projects_into_state_manifold_and_rehydrate(self) -> None:
        self._start_brainstorm_session()

        state = self._read_state()
        manifold = self._read_manifold()
        rehydrate = self._read_rehydrate()

        self.assertEqual(state["active_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertNotIn(SessionMode.BRAINSTORM_SPEC.value, state["active_modes"])
        self.assertEqual(manifold["active_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertEqual(manifold["active_session_mode_source"], "command_default")
        self.assertEqual(
            manifold["active_session_mode_policy"]["blocked_mutation_commands"],
            ["formalize", "accept-quest"],
        )
        self.assertIn("scope_planning", manifold["active_session_mode_policy"]["allowed_next_modes"])
        self.assertIn("## Session posture", rehydrate)
        self.assertIn("Current session mode: brainstorm_spec", rehydrate)
        self.assertIn("Blocked mutation commands: formalize, accept-quest", rehydrate)
        self.assertIn("Allowed next modes: control_sync, scope_planning, closeout", rehydrate)

    def test_valid_session_mode_transition_emits_event_and_updates_active_run(self) -> None:
        self._start_brainstorm_session()
        result = run_synapse(
            [
                "session-mode",
                "--set",
                "scope_planning",
                "--reason",
                "Moving from ideation into scoped planning",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["from_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertEqual(payload["to_session_mode"], SessionMode.SCOPE_PLANNING.value)
        self.assertEqual(payload["event"]["payload"]["signals"]["from_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertEqual(payload["event"]["payload"]["signals"]["to_session_mode"], SessionMode.SCOPE_PLANNING.value)
        self.assertEqual(
            payload["event"]["payload"]["signals"]["session_mode_reason"],
            "Moving from ideation into scoped planning",
        )
        self.assertEqual(payload["event"]["payload"]["signals"]["session_mode"], SessionMode.SCOPE_PLANNING.value)
        active = self._read_active_run()
        self.assertEqual(active["session_mode"], SessionMode.SCOPE_PLANNING.value)

    def test_invalid_transition_fails_before_mutation(self) -> None:
        self._start_brainstorm_session()
        before = self._read_active_run()
        result = run_synapse(
            [
                "session-mode",
                "--set",
                "execution",
                "--reason",
                "skip ahead",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["active_session_mode"], SessionMode.BRAINSTORM_SPEC.value)
        self.assertEqual(payload["target_session_mode"], SessionMode.EXECUTION.value)
        self.assertIn("scope_planning", payload["allowed_next_modes"])
        self.assertIn("Invalid session-mode transition", payload["error"])
        after = self._read_active_run()
        self.assertEqual(after["session_mode"], before["session_mode"])
        self.assertEqual(after["session_mode_set_at"], before["session_mode_set_at"])

    def test_same_mode_set_is_noop_without_event(self) -> None:
        self._start_brainstorm_session()
        before = self._read_active_run()
        result = run_synapse(
            ["session-mode", "--set", "brainstorm_spec", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["changed"])
        self.assertNotIn("event", payload)
        after = self._read_active_run()
        self.assertEqual(after["session_mode_set_at"], before["session_mode_set_at"])

    def test_session_mode_set_without_active_run_fails(self) -> None:
        result = run_synapse(
            [
                "session-mode",
                "--set",
                "scope_planning",
                "--reason",
                "need a run first",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["active_session_mode"])
        self.assertIn("No active run exists", payload["error"])

    def test_session_start_existing_run_rejects_different_requested_mode(self) -> None:
        self._start_brainstorm_session()
        result = run_synapse(
            ["session-start", "--session-mode", "scope_planning", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("session-mode --set", result.stdout + result.stderr)

    def test_session_tick_existing_run_rejects_different_requested_mode(self) -> None:
        self._start_brainstorm_session()
        result = run_synapse(
            ["session-tick", "--session-mode", "scope_planning", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("session-mode --set", result.stdout + result.stderr)

    def test_finalize_projects_last_posture_and_clears_active_posture(self) -> None:
        result = run_synapse(
            ["run-start", "--title", "Build path", "--plan-item", "Ship it", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_synapse(
            [
                "session-mode",
                "--set",
                "scope_planning",
                "--reason",
                "Moving from implementation to scoped closeout planning",
                "--json",
                *self.subject_args,
            ],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_synapse(
            ["run-update", "--set-item-status", "ITEM-001:DONE", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_synapse(
            ["run-finalize", "--status", "completed", "--json", *self.subject_args],
            cwd=REPO_ROOT,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        state = self._read_state()
        manifold = self._read_manifold()
        rehydrate = self._read_rehydrate()

        self.assertIsNone(state["active_session_mode"])
        self.assertEqual(state["last_session_mode"], SessionMode.SCOPE_PLANNING.value)
        self.assertTrue(state["last_session_mode_ended_at"])
        self.assertIsNone(manifold["active_session_mode"])
        self.assertIsNone(manifold["active_session_mode_policy"])
        self.assertEqual(manifold["last_session_mode"], SessionMode.SCOPE_PLANNING.value)
        self.assertTrue(manifold["last_session_mode_ended_at"])
        self.assertIn("Current session mode: none", rehydrate)
        self.assertIn("Last session mode: scope_planning", rehydrate)


if __name__ == "__main__":
    unittest.main()

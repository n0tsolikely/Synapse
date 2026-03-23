import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from synapse_runtime import provenance as prov
from synapse_runtime import wrapper_proof
from synapse_runtime.sidecar_store import authoritative_coordination_paths, ensure_live_scaffold
from synapse_runtime.subject_bootstrap import initialize_subject_state


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]
_GUARD_SPEC = importlib.util.spec_from_file_location(
    "synapse_governance_guard",
    REPO_ROOT / "runtime" / "tools" / "synapse_governance_guard.py",
)
assert _GUARD_SPEC and _GUARD_SPEC.loader
synapse_governance_guard = importlib.util.module_from_spec(_GUARD_SPEC)
_GUARD_SPEC.loader.exec_module(synapse_governance_guard)


def run_synapse(args: list[str], *, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SYNAPSE_ROOT"] = str(REPO_ROOT)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


class ProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "ProvSubject"
        self.data_root = (self.root / f"{self.subject}_Data").resolve()
        self.engine_root = (self.root / self.subject).resolve()
        self.engine_root.mkdir(parents=True, exist_ok=True)
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
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
        self.tmp.cleanup()

    def _git_init(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
        subprocess.run(["git", "config", "user.email", "prov@example.com"], cwd=self.engine_root, check=True)
        subprocess.run(["git", "config", "user.name", "Prov Test"], cwd=self.engine_root, check=True)
        (self.engine_root / "README.md").write_text("# provenance\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.engine_root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.engine_root, check=True)

    def _event_entries(self) -> list[dict]:
        root = self.data_root / ".synapse" / "EVENTS"
        entries: list[dict] = []
        if not root.exists():
            return entries
        for path in sorted(root.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries

    def _provenance_root(self) -> Path:
        return self.data_root / ".synapse" / "PROVENANCE"

    def _baseline_path(self) -> Path:
        return self._provenance_root() / "WATCH_BASELINE.yaml"

    def _hooks_path(self) -> Path:
        return self._provenance_root() / "HOOKS.yaml"

    def _anomaly_ledger(self) -> Path:
        return self._provenance_root() / "ANOMALIES" / f"{prov._now().date().isoformat()}.yaml"

    def _write_accepted_quest(self, *, bundle_path: Path | None) -> Path:
        accepted_dir = self.data_root / "Quest Board" / "Accepted"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        path = accepted_dir / "QUEST_001__phase5-proof-check__2026-03-23.txt"
        lines = [
            "Quest ID: QUEST_001",
            "",
            "Title: Phase 5 proof check",
            "",
            f"Subject: {self.subject}",
            "",
            "Origin: Control Sync 2026-03-23",
            "",
            "Priority: P1",
            "",
            "Codex Anchors (DRAFT): 6.5, 9.2",
            "",
            "Codex Constraint Summary (DRAFT): Trust is explicit.",
            "",
            "Change Class: FEATURE",
            "",
            "Vision Delta: ALIGNED",
            "",
            "System Context Statement: Phase 5 provenance.",
            "",
            "Anti-Duplication Plan: rg -n \"provenance\" runtime tests",
            "",
            "Placement Intent: Intended layer: runtime",
            "",
            "Atomicity Statement: Atomic: yes",
            "",
            "Risk: R1",
            "",
            "R2 Confirmation Artifact (REQUIRED if Risk = R2):",
            "",
            "Description: Validate wrapper proof provenance.",
            "",
            "Scope / Objective: Surface trust blockers honestly.",
            "",
            "Out of Scope: universal mediation.",
            "",
            "Dependencies: None",
            "",
            "Door Impact: Runtime",
            "",
            "Testing Level (TL): TL2",
            "",
            "Verification Plan: run targeted tests.",
            "",
            "Talent Point Awarded: NO",
            "",
            f"Audit Bundle Folder Path (required once ACCEPTED): {bundle_path if bundle_path else ''}",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_wrapper_proof(self, bundle: Path, *, commands_count: int = 1, sha_override: str | None = None) -> Path:
        proof_path = bundle / "06_WRAPPER_PROOF.json"
        wrapper_path = REPO_ROOT / "runtime" / "tools" / "synapse_quest_run.sh"
        payload = {
            "schema_version": 1,
            "wrapper": "synapse_quest_run.sh",
            "wrapper_path": str(wrapper_path.resolve()),
            "wrapper_sha256": sha_override or hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
            "commands_count": commands_count,
            "bundle_path": str(bundle.resolve()),
        }
        proof_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return proof_path

    def test_wrapper_proof_validation_and_fingerprint_are_shared(self) -> None:
        bundle = self.data_root / "Audits" / "Execution" / "QUEST_001__proof"
        bundle.mkdir(parents=True, exist_ok=True)
        proof_path = self._write_wrapper_proof(bundle)

        validation = wrapper_proof.validate_wrapper_proof_file(proof_path)
        self.assertTrue(validation["ok"], validation)
        ok, why = synapse_governance_guard._wrapper_proof_ok(bundle)
        self.assertTrue(ok, why)

        fingerprint_1 = wrapper_proof.wrapper_proof_fingerprint(proof_path)
        fingerprint_2 = wrapper_proof.wrapper_proof_fingerprint(proof_path)
        self.assertEqual(fingerprint_1, fingerprint_2)

        bad = self._write_wrapper_proof(bundle, sha_override="0" * 64)
        validation = wrapper_proof.validate_wrapper_proof_file(bad)
        self.assertFalse(validation["ok"])
        self.assertIn("wrapper_sha256", validation["error"])

    def test_authoritative_coordination_paths_exclude_derived_outputs(self) -> None:
        paths = {path.resolve() for path in authoritative_coordination_paths(self.data_root)}
        self.assertIn((self.data_root / ".synapse" / "ACTIVE_RUN.yaml").resolve(), paths)
        self.assertIn((self.data_root / ".synapse" / "ONBOARDING" / "CURRENT.yaml").resolve(), paths)
        self.assertNotIn((self.data_root / ".synapse" / "STATE.yaml").resolve(), paths)
        self.assertNotIn((self.data_root / ".synapse" / "MANIFOLD.yaml").resolve(), paths)
        self.assertNotIn((self.data_root / ".synapse" / "REHYDRATE.md").resolve(), paths)

    def test_install_and_verify_hooks_write_receipts_and_events(self) -> None:
        self._git_init()
        install = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        install_payload = json.loads(install.stdout)
        self.assertEqual(install_payload["git_hooks_status"], "installed")
        self.assertTrue((self.engine_root / ".git" / "hooks" / "pre-commit").exists())
        self.assertTrue((self.engine_root / ".git" / "hooks" / "pre-push").exists())
        self.assertTrue(self._hooks_path().exists())

        verify = run_synapse(["verify-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        verify_payload = json.loads(verify.stdout)
        self.assertEqual(verify_payload["git_hooks_status"], "installed")

        actions = [entry.get("action_name") for entry in self._event_entries()]
        self.assertIn("install-hooks", actions)
        self.assertIn("verify-hooks", actions)

    def test_install_hooks_non_git_is_not_applicable_and_emits_no_event(self) -> None:
        install = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        payload = json.loads(install.stdout)
        self.assertEqual(payload["git_hooks_status"], "not_applicable")
        self.assertFalse(self._hooks_path().exists())
        self.assertEqual([entry.get("action_name") for entry in self._event_entries()], [])

        verify = run_synapse(["verify-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        payload = json.loads(verify.stdout)
        self.assertEqual(payload["git_hooks_status"], "not_applicable")
        self.assertEqual([entry.get("action_name") for entry in self._event_entries()], [])

    def test_install_hooks_force_backs_up_unmanaged_hook(self) -> None:
        self._git_init()
        hooks_dir = self.engine_root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "pre-commit").write_text("#!/usr/bin/env bash\necho custom\n", encoding="utf-8")
        fail = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(fail.returncode, 2, fail.stdout + fail.stderr)

        ok = run_synapse(["install-hooks", "--json", "--force", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        payload = json.loads(ok.stdout)
        self.assertTrue(payload["backups"])
        self.assertTrue(any(path.endswith(".synapse.bak") for path in payload["backups"]))

    def test_verify_hooks_classifies_outdated_managed_hook(self) -> None:
        self._git_init()
        install = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        hook_path = self.engine_root / ".git" / "hooks" / "pre-commit"
        hook_path.write_text(hook_path.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8")

        verify = run_synapse(["verify-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        payload = json.loads(verify.stdout)
        self.assertEqual(payload["git_hooks_status"], "outdated")

    def test_append_provenance_anomalies_dedupes_same_day(self) -> None:
        anomaly = {
            "anomaly_id": "ANOM-1",
            "fingerprint": "fp-1",
            "detected_at": "2026-03-23T00:00:00-04:00",
            "kind": prov.ProvenanceAnomalyKind.GIT_HOOKS_MISSING.value,
            "severity": prov.ProvenanceSeverity.WARNING.value,
            "subject": self.subject,
            "run_id": None,
            "session_id": None,
            "accepted_quest_id": None,
            "message": "hooks missing",
            "evidence": {},
        }
        path1 = prov.append_provenance_anomalies(self.data_root, [anomaly])
        path2 = prov.append_provenance_anomalies(self.data_root, [anomaly])
        self.assertIsNotNone(path1)
        self.assertIsNone(path2)
        ledger = yaml.safe_load(self._anomaly_ledger().read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["entries"]), 1)

    def test_classify_absolute_and_delta_anomalies(self) -> None:
        absolute = prov.classify_absolute_provenance_anomalies(
            {
                "subject": self.subject,
                "run_id": "RUN-1",
                "session_id": "sid-1",
                "accepted_quest_id": "QUEST_001",
                "accepted_audit_bundle_path": None,
                "wrapper_proof_status": prov.WrapperProofStatus.MISSING.value,
                "wrapper_proof_path": None,
                "engine_is_git_repo": True,
                "git_hooks_status": prov.GitHooksStatus.OUTDATED.value,
                "engine_git_head": "abc",
            }
        )
        kinds = {item["kind"] for item in absolute}
        self.assertIn(prov.ProvenanceAnomalyKind.ACCEPTED_QUEST_BUNDLE_MISSING.value, kinds)
        self.assertIn(prov.ProvenanceAnomalyKind.GIT_HOOKS_OUTDATED.value, kinds)

        previous = {
            "subject": self.subject,
            "run_id": "RUN-1",
            "session_id": "sid-1",
            "accepted_quest_id": "QUEST_001",
            "engine_is_git_repo": True,
            "engine_git_head": "abc",
            "engine_dirty_fingerprint": None,
            "wrapper_proof_fingerprint": "proof-1",
            "coordination_fingerprints": {"a": "1"},
            "event_progress": {"latest_event_file_path": "e1", "latest_event_file_fingerprint": "f1", "latest_event_count": 1},
        }
        current = {
            **previous,
            "engine_git_head": "def",
            "coordination_fingerprints": {"a": "2"},
        }
        delta = prov.classify_delta_provenance_anomalies(previous, current)
        delta_kinds = {item["kind"] for item in delta}
        self.assertIn(prov.ProvenanceAnomalyKind.ENGINE_MUTATION_WITHOUT_WRAPPER_RECEIPT.value, delta_kinds)
        self.assertIn(prov.ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS.value, delta_kinds)
        severities = {item["kind"]: item["severity"] for item in delta}
        self.assertEqual(severities[prov.ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS.value], prov.ProvenanceSeverity.BLOCKER.value)

        no_run_current = dict(current)
        no_run_current["run_id"] = None
        no_run_delta = prov.classify_delta_provenance_anomalies(previous, no_run_current)
        severity = next(item["severity"] for item in no_run_delta if item["kind"] == prov.ProvenanceAnomalyKind.COORDINATION_STATE_CHANGED_WITHOUT_EVENT_PROGRESS.value)
        self.assertEqual(severity, prov.ProvenanceSeverity.WARNING.value)

    def test_provenance_status_read_only_and_strict_blocked(self) -> None:
        self._git_init()
        self._write_accepted_quest(bundle_path=self.data_root / "Audits" / "Execution" / "QUEST_001__missing")
        before = self._baseline_path().exists(), self._hooks_path().exists(), self._anomaly_ledger().exists()
        result = run_synapse(["provenance-status", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["provenance_status"], "blocked")
        self.assertFalse(self._baseline_path().exists())
        self.assertFalse(self._hooks_path().exists())
        self.assertFalse(self._anomaly_ledger().exists())
        strict = run_synapse(["provenance-status", "--strict", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(strict.returncode, 2, strict.stdout + strict.stderr)
        self.assertEqual(before, (False, False, False))

    def test_first_watch_creates_baseline_and_second_no_change_emits_no_new_provenance_event(self) -> None:
        self._git_init()
        hooks = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(hooks.returncode, 0, hooks.stdout + hooks.stderr)

        first = run_synapse(["watch", "--json", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue(self._baseline_path().exists())
        first_payload = json.loads(first.stdout)
        self.assertEqual(first_payload["ticks"][0]["provenance"]["provenance_status"], "clear")
        actions_after_first = [entry.get("action_name") for entry in self._event_entries()]
        self.assertEqual(actions_after_first.count("provenance-watch-cycle"), 1)

        second = run_synapse(["watch", "--json", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        actions_after_second = [entry.get("action_name") for entry in self._event_entries()]
        self.assertEqual(actions_after_second.count("provenance-watch-cycle"), 1)

    def test_watch_status_change_emits_new_provenance_event(self) -> None:
        self._git_init()
        hooks = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(hooks.returncode, 0, hooks.stdout + hooks.stderr)
        first = run_synapse(["watch", "--json", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

        missing_bundle = self.data_root / "Audits" / "Execution" / "QUEST_001__missing"
        self._write_accepted_quest(bundle_path=missing_bundle)

        second = run_synapse(["watch", "--json", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        payload = json.loads(second.stdout)
        self.assertEqual(payload["ticks"][0]["provenance"]["provenance_status"], "blocked")

        actions = [entry.get("action_name") for entry in self._event_entries()]
        self.assertEqual(actions.count("provenance-watch-cycle"), 2)

    def test_watch_no_provenance_preserves_non_provenance_behavior(self) -> None:
        self._git_init()
        result = run_synapse(["watch", "--json", "--no-provenance", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self._baseline_path().exists())
        self.assertFalse(self._hooks_path().exists())
        self.assertFalse(self._anomaly_ledger().exists())

    def test_render_and_refresh_project_trust_without_raw_store_writes(self) -> None:
        self._git_init()
        install = run_synapse(["install-hooks", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        watch = run_synapse(["watch", "--json", "--iterations", "1", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(watch.returncode, 0, watch.stdout + watch.stderr)
        baseline_before = self._baseline_path().read_text(encoding="utf-8")
        anomaly_before = self._anomaly_ledger().read_text(encoding="utf-8") if self._anomaly_ledger().exists() else None

        rendered = run_synapse(["render-rehydrate", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        refresh = run_synapse(["refresh-continuity", "--json", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(refresh.returncode, 0, refresh.stdout + refresh.stderr)

        self.assertEqual(self._baseline_path().read_text(encoding="utf-8"), baseline_before)
        anomaly_after = self._anomaly_ledger().read_text(encoding="utf-8") if self._anomaly_ledger().exists() else None
        self.assertEqual(anomaly_after, anomaly_before)

        state = yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))
        manifold = yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))
        self.assertIn("provenance_status", state)
        self.assertIn("provenance_blockers", manifold)
        rehydrate_text = (self.data_root / ".synapse" / "REHYDRATE.md").read_text(encoding="utf-8")
        self.assertIn("## Provenance / Trust", rehydrate_text)
        self.assertIn("clear means no current warnings or blockers under Phase 5 checks", rehydrate_text)

    def test_provenance_text_output_preserves_honesty_note(self) -> None:
        self._git_init()
        result = run_synapse(["provenance-status", *self.subject_args], cwd=REPO_ROOT, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("honesty_note:", result.stdout)
        self.assertIn("does not prove universal mediation", result.stdout)

    def test_unresolved_subject_watch_does_not_write_provenance_raw_stores(self) -> None:
        result = run_synapse(["watch", "--json", "--iterations", "1"], cwd=REPO_ROOT, home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(self.home.glob("*_Data/.synapse/PROVENANCE/WATCH_BASELINE.yaml")))


if __name__ == "__main__":
    unittest.main()

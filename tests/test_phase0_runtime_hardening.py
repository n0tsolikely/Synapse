import datetime as dt
import json
import os
import shlex
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

from synapse_runtime.quest_candidates import _proposal_dir
from synapse_runtime.governance_model import ProposalKind
from synapse_runtime.repo_state import load_state, save_state
from synapse_runtime.sidecar_projection import refresh_quest_lifecycle_projection
from synapse_runtime.sidecar_store import _now_iso, ensure_live_scaffold, live_root
from synapse_runtime.subject_bootstrap import initialize_subject_state
from synapse_runtime.subject_resolver import write_focus_lock


SYNAPSE = [sys.executable, str(REPO_ROOT / "runtime" / "synapse.py")]
CODEX_GATE = [sys.executable, str(REPO_ROOT / "runtime" / "tools" / "synapse_codex_gate.py")]


def run_synapse(
    args: list[str],
    *,
    cwd: Path,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(SYNAPSE + args, cwd=cwd, env=env, capture_output=True, text=True)


def run_codex_gate(
    args: list[str],
    *,
    cwd: Path,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("SYNAPSE_ROOT", str(REPO_ROOT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(CODEX_GATE + args, cwd=cwd, env=env, capture_output=True, text=True)


class Phase0RuntimeHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.subject = "AdoptedRepo"
        self.engine_root = (self.root / self.subject).resolve()
        self.engine_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=self.engine_root, check=True)
        self.data_root = (self.root / f"{self.subject}_Data").resolve()
        initialize_subject_state(self.subject, self.data_root, self.engine_root)
        ensure_live_scaffold(self.subject, self.data_root)
        write_focus_lock(
            subject=self.subject,
            data_root=self.data_root,
            engine_root=self.engine_root,
            cwt=self.engine_root,
            home=self.home,
            selection_method="test",
            source_detail="test_phase0_runtime_hardening",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _proposal_path(self, proposal_id: str, kind: ProposalKind) -> Path:
        return _proposal_dir(live_root(self.data_root), kind) / f"{proposal_id}.yaml"

    def _write_proposal(self, *, proposal_id: str, kind: ProposalKind, title: str, summary: str, reason: str) -> Path:
        payload = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "subject": self.subject,
            "kind": kind.value,
            "state": "proposed",
            "interaction_mode": "ambient",
            "source_id": "PHASE0",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "title": title,
            "summary": summary,
            "reason": reason,
            "blockers": [],
            "evidence": ["runtime/synapse.py"],
            "codex_implications": [],
        }
        path = self._proposal_path(proposal_id, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def _completed_path(self, quest_id: str, slug: str) -> Path:
        return self.data_root / "Quest Board" / "Completed" / f"{quest_id}__{slug}__2026-03-10.txt"

    def _write_completed_quest(self, quest_id: str, *, title: str, slug: str) -> Path:
        bundle = self.data_root / "Audits" / "Execution" / f"{quest_id}__2026-03-10__{slug}"
        bundle.mkdir(parents=True, exist_ok=True)
        path = self._completed_path(quest_id, slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    f"Quest ID: {quest_id}",
                    "",
                    f"Title: {title}",
                    "",
                    f"Subject: {self.subject}",
                    "",
                    "Origin: Test completion projection",
                    "",
                    f"Audit Bundle Folder Path (required once ACCEPTED): {self.subject}_Data/Audits/Execution/{bundle.name}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _load_sidecar_state(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "STATE.yaml").read_text(encoding="utf-8"))

    def _load_sidecar_manifold(self) -> dict:
        return yaml.safe_load((self.data_root / ".synapse" / "MANIFOLD.yaml").read_text(encoding="utf-8"))

    def _write_toc(self) -> None:
        toc_path = self.data_root / "Codex" / "TOC_DRAFT.md"
        toc_path.parent.mkdir(parents=True, exist_ok=True)
        toc_path.write_text("# TOC_DRAFT\n\n1. Core System\n", encoding="utf-8")

    def _legacy_open_questions_path(self) -> Path:
        return self.data_root / "Incubation" / "OPEN_QUESTIONS.md"

    def _legacy_discoveries_path(self) -> Path:
        return self.data_root / "Incubation" / "DISCOVERIES.md"

    def test_formalize_from_adopted_repo_cwd_uses_synapse_governance_template(self) -> None:
        proposal_id = "QUEST__PHASE0__ROOT_RESOLUTION"
        self._write_proposal(
            proposal_id=proposal_id,
            kind=ProposalKind.QUEST,
            title="Root resolution hardening",
            summary="Formalize a quest while running from the adopted repo cwd.",
            reason="Governance assets must resolve from the Synapse install root, not the subject cwd.",
        )

        result = run_synapse(["formalize", "--proposal-id", proposal_id, "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        payload = json.loads(result.stdout)
        artifact_path = Path(payload["result"]["artifact_path"])
        self.assertTrue(artifact_path.exists())
        self.assertEqual(artifact_path.parent.resolve(), (self.data_root / "Quest Board").resolve())
        self.assertIn("Quest ID:", artifact_path.read_text(encoding="utf-8"))

    def test_doctor_relative_governance_root_resolves_against_synapse_root(self) -> None:
        result = run_synapse(["doctor", "--governance-root", "governance"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Governance root: {(REPO_ROOT / 'governance').resolve()}", result.stdout)
        self.assertNotIn(str((self.engine_root / "governance").resolve()), result.stdout)

    def test_doctor_accepts_governance_root_from_env_without_cli_arg(self) -> None:
        result = run_synapse(
            ["doctor", "--no-subject"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_GOVERNANCE_ROOT": str((REPO_ROOT / "governance").resolve())},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Governance root: {(REPO_ROOT / 'governance').resolve()}", result.stdout)

    def test_governance_map_relative_governance_root_keeps_output_cwd_relative(self) -> None:
        output_path = self.engine_root / "out.json"
        result = run_synapse(
            ["governance-map", "--governance-root", "governance", "--output", "out.json"],
            cwd=self.engine_root,
            home=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output_path.exists())
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["governance_root"], str((REPO_ROOT / "governance").resolve()))

    def test_mode_writes_state_under_install_root_not_subject_repo(self) -> None:
        temp_synapse_root = self.root / "install-root"
        (temp_synapse_root / "runtime").mkdir(parents=True, exist_ok=True)
        (temp_synapse_root / "governance").mkdir(parents=True, exist_ok=True)

        result = run_synapse(
            ["mode", "--set", "PLAN"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_ROOT": str(temp_synapse_root)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((temp_synapse_root / ".synapse" / "STATE.json").exists())
        self.assertFalse((self.engine_root / ".synapse" / "STATE.json").exists())

    def test_legacy_drift_state_falls_back_once_then_writes_install_root(self) -> None:
        temp_synapse_root = self.root / "install-root"
        (temp_synapse_root / "runtime").mkdir(parents=True, exist_ok=True)
        (temp_synapse_root / "governance").mkdir(parents=True, exist_ok=True)
        legacy_path = self.engine_root / ".synapse" / "STATE.json"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps({"mode": "PLAN", "last_ack_commit": "legacy-ack", "drift_warned_sessions": {}}, indent=2),
            encoding="utf-8",
        )

        state = load_state(synapse_root=temp_synapse_root, cwt=self.engine_root)
        self.assertEqual(state["mode"], "PLAN")
        self.assertEqual(state["last_ack_commit"], "legacy-ack")

        state["mode"] = "INCUBATION"
        save_state(state, synapse_root=temp_synapse_root)

        install_path = temp_synapse_root / ".synapse" / "STATE.json"
        self.assertTrue(install_path.exists())
        install_state = json.loads(install_path.read_text(encoding="utf-8"))
        self.assertEqual(install_state["mode"], "INCUBATION")
        legacy_state = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(legacy_state["mode"], "PLAN")

    def test_install_root_state_wins_over_legacy_workspace_state(self) -> None:
        temp_synapse_root = self.root / "install-root"
        (temp_synapse_root / "runtime").mkdir(parents=True, exist_ok=True)
        (temp_synapse_root / "governance").mkdir(parents=True, exist_ok=True)
        install_path = temp_synapse_root / ".synapse" / "STATE.json"
        install_path.parent.mkdir(parents=True, exist_ok=True)
        install_path.write_text(
            json.dumps({"mode": "EXECUTE", "last_ack_commit": "install-ack", "drift_warned_sessions": {}}, indent=2),
            encoding="utf-8",
        )
        legacy_path = self.engine_root / ".synapse" / "STATE.json"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps({"mode": "PLAN", "last_ack_commit": "legacy-ack", "drift_warned_sessions": {}}, indent=2),
            encoding="utf-8",
        )

        state = load_state(synapse_root=temp_synapse_root, cwt=self.engine_root)
        self.assertEqual(state["mode"], "EXECUTE")
        self.assertEqual(state["last_ack_commit"], "install-ack")

    def test_drift_reports_commands_with_explicit_install_root_target(self) -> None:
        temp_synapse_root = self.root / "install-root"
        (temp_synapse_root / "runtime" / "synapse_runtime").mkdir(parents=True, exist_ok=True)
        (temp_synapse_root / "governance").mkdir(parents=True, exist_ok=True)
        (temp_synapse_root / "AGENTS.md").write_text("test\n", encoding="utf-8")
        (temp_synapse_root / "governance" / "README.txt").write_text("baseline\n", encoding="utf-8")
        (temp_synapse_root / "runtime" / "synapse.py").write_text("# smoke\n", encoding="utf-8")
        (temp_synapse_root / "runtime" / "synapse_runtime" / "__init__.py").write_text("", encoding="utf-8")

        subprocess.run(["git", "init", "-q"], cwd=temp_synapse_root, check=True)
        subprocess.run(["git", "add", "AGENTS.md", "governance/README.txt", "runtime/synapse.py", "runtime/synapse_runtime/__init__.py"], cwd=temp_synapse_root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Smoke", "-c", "user.email=smoke@example.com", "commit", "-q", "-m", "baseline"],
            cwd=temp_synapse_root,
            check=True,
        )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_synapse_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        save_state(
            {"mode": "EXECUTE", "last_ack_commit": head, "drift_warned_sessions": {}},
            synapse_root=temp_synapse_root,
        )

        (temp_synapse_root / "governance" / "README.txt").write_text("baseline\nchanged\n", encoding="utf-8")
        subprocess.run(["git", "add", "governance/README.txt"], cwd=temp_synapse_root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Smoke", "-c", "user.email=smoke@example.com", "commit", "-q", "-m", "change governance"],
            cwd=temp_synapse_root,
            check=True,
        )

        result = run_synapse(
            ["drift", "--json"],
            cwd=self.engine_root,
            home=self.home,
            extra_env={"SYNAPSE_ROOT": str(temp_synapse_root)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state_path"], str((temp_synapse_root / ".synapse" / "STATE.json").resolve()))
        self.assertTrue(payload["governance_changed"])
        self.assertEqual(payload["changed_files"], ["governance/README.txt"])
        prefix = f"git -C {shlex.quote(str(temp_synapse_root.resolve()))}"
        self.assertTrue(all(str(cmd).startswith(prefix) for cmd in payload["commands"]))

    def test_completed_quest_projection_refresh_stamps_state_and_manifold(self) -> None:
        completed = self._write_completed_quest("QUEST_007", title="Ship Phase 0", slug="ship-phase-0")

        refresh_quest_lifecycle_projection(subject=self.subject, data_root=self.data_root)

        state = self._load_sidecar_state()
        manifold = self._load_sidecar_manifold()
        self.assertEqual(state["last_completed_quest_id"], "QUEST_007")
        self.assertEqual(Path(state["last_completed_quest_path"]).resolve(), completed.resolve())
        self.assertEqual(manifold["completed_quest_ids"], ["QUEST_007"])
        detail = manifold["completed_quest_details"][0]
        self.assertEqual(detail["quest_id"], "QUEST_007")
        self.assertEqual(detail["state"], "completed")
        self.assertTrue(detail["audit_bundle_path"])

    def test_render_rehydrate_surfaces_completed_quests_from_projection_state(self) -> None:
        self._write_completed_quest("QUEST_003", title="Complete continuity refresh", slug="continuity-refresh")

        result = run_synapse(["render-rehydrate", "--json"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        rehydrate_path = self.data_root / ".synapse" / "REHYDRATE.md"
        text = rehydrate_path.read_text(encoding="utf-8")
        self.assertIn("## Completed quests", text)
        self.assertIn("QUEST_003", text)
        self.assertIn("Complete continuity refresh", text)

    def test_completed_quest_ordering_uses_quest_number_not_mtime(self) -> None:
        older = self._write_completed_quest("QUEST_010", title="Tenth quest", slug="tenth")
        newer = self._write_completed_quest("QUEST_002", title="Second quest", slug="second")
        base = dt.datetime(2026, 3, 16, 12, 0, 0).timestamp()
        os.utime(older, (base - 3600, base - 3600))
        os.utime(newer, (base, base))

        refresh_quest_lifecycle_projection(subject=self.subject, data_root=self.data_root)

        manifold = self._load_sidecar_manifold()
        self.assertEqual(manifold["completed_quest_ids"][:2], ["QUEST_010", "QUEST_002"])
        self.assertEqual(manifold["last_completed_quest_id"], "QUEST_010")

    def test_codex_gate_prefers_canonical_sidecar_over_legacy_incubation(self) -> None:
        self._write_toc()
        self._legacy_open_questions_path().write_text(
            "# OPEN QUESTIONS\n\n- Q-001 | Status: BLOCKING | Question: Legacy blocker\n",
            encoding="utf-8",
        )
        self._legacy_discoveries_path().write_text(
            "# DISCOVERIES\n\nCONTRADICTION: legacy contradiction that should be ignored\n",
            encoding="utf-8",
        )

        result = run_codex_gate(["spec"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("status: READY", result.stdout)
        self.assertIn("blocking_questions: 0", result.stdout)
        self.assertIn(f"data_root: {self.data_root}", result.stdout)

    def test_codex_gate_placeholder_blocker_is_not_counted(self) -> None:
        self._write_toc()
        result = run_codex_gate(["spec"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("blocking_questions: 0", result.stdout)

    def test_codex_gate_real_blocker_is_counted(self) -> None:
        self._write_toc()
        (self.data_root / ".synapse" / "THREADS" / "open_questions.md").write_text(
            "# Open Questions\n\n## Blocking\n- Need a real answer.\n\n## Nonblocking\n- None yet.\n",
            encoding="utf-8",
        )
        result = run_codex_gate(["spec"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("status: NEEDS_DECISIONS", result.stdout)
        self.assertIn("blocking_questions: 1", result.stdout)

    def test_codex_gate_canonical_parse_failure_fails_closed(self) -> None:
        self._write_toc()
        (self.data_root / ".synapse" / "THREADS" / "open_questions.md").write_text(
            "# Open Questions\n\n- broken canonical shape\n",
            encoding="utf-8",
        )
        result = run_codex_gate(["spec"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Malformed canonical sidecar open questions", result.stdout + result.stderr)

    def test_codex_gate_legacy_fallback_only_when_sidecar_absent(self) -> None:
        self._write_toc()
        (self.data_root / ".synapse" / "THREADS" / "open_questions.md").unlink()
        self._legacy_open_questions_path().write_text(
            "# OPEN QUESTIONS\n\n- Q-001 | Status: BLOCKING | Question: fallback blocker\n",
            encoding="utf-8",
        )
        result = run_codex_gate(["spec"], cwd=self.engine_root, home=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("status: NEEDS_DECISIONS", result.stdout)
        self.assertIn("blocking_questions: 1", result.stdout)


if __name__ == "__main__":
    unittest.main()

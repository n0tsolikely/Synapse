import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = REPO_ROOT / "runtime" / "tools" / "synapse_governance_guard.py"

_SPEC = importlib.util.spec_from_file_location("synapse_governance_guard", GUARD_PATH)
assert _SPEC and _SPEC.loader
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)


class GovernanceGuardWrapperProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.tmp.name) / "bundle"
        self.bundle.mkdir(parents=True, exist_ok=True)
        self.tests_path = self.bundle / "06_TESTS.txt"
        self.changed_path = self.bundle / "06_CHANGED_FILES.txt"
        self.proof_path = self.bundle / "06_WRAPPER_PROOF.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_receipts(self, *, marker: bool) -> None:
        lines = [
            "## Command Receipt Log",
            "CMD: echo ok",
            "RC: 0",
        ]
        if marker:
            lines.append("WRAPPER_VALIDATE_MARKER: YES")
        self.tests_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.changed_path.write_text("NONE\n", encoding="utf-8")

    def _write_wrapper_proof(self, *, commands_count: int = 1, bundle_path: Path | None = None, sha_override: str | None = None) -> None:
        wrapper_path = REPO_ROOT / "runtime" / "tools" / "synapse_quest_run.sh"
        wrapper_sha = sha_override or hashlib.sha256(wrapper_path.read_bytes()).hexdigest()
        payload = {
            "schema_version": 1,
            "wrapper": "synapse_quest_run.sh",
            "wrapper_path": str(wrapper_path.resolve()),
            "wrapper_sha256": wrapper_sha,
            "commands_count": commands_count,
            "bundle_path": str((bundle_path or self.bundle).resolve()),
        }
        self.proof_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_proof_receipts_require_wrapper_marker(self):
        self._write_receipts(marker=False)
        ok, why = guard._proof_receipts_ok(self.bundle)
        self.assertFalse(ok)
        self.assertIn("WRAPPER_VALIDATE_MARKER", why)

        self._write_receipts(marker=True)
        ok, why = guard._proof_receipts_ok(self.bundle)
        self.assertTrue(ok, why)

    def test_wrapper_proof_validates_sha_count_and_bundle_path(self):
        self._write_receipts(marker=True)
        self._write_wrapper_proof()
        ok, why = guard._wrapper_proof_ok(self.bundle)
        self.assertTrue(ok, why)

        self._write_wrapper_proof(commands_count=0)
        ok, why = guard._wrapper_proof_ok(self.bundle)
        self.assertFalse(ok)
        self.assertIn("commands_count", why)

        self._write_wrapper_proof(commands_count=1, bundle_path=Path(self.tmp.name) / "wrong_bundle")
        ok, why = guard._wrapper_proof_ok(self.bundle)
        self.assertFalse(ok)
        self.assertIn("bundle_path", why)

        self._write_wrapper_proof(commands_count=1, sha_override=("0" * 64))
        ok, why = guard._wrapper_proof_ok(self.bundle)
        self.assertFalse(ok)
        self.assertIn("wrapper_sha256", why)


if __name__ == "__main__":
    unittest.main()

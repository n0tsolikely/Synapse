"""Shared wrapper-proof inspection and validation helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from synapse_runtime.accepted_execution_view import load_accepted_quest_details, select_current_accepted_quest


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
SYNAPSE_ROOT = RUNTIME_ROOT.parent
WRAPPER_SCRIPT_PATH = SYNAPSE_ROOT / "runtime" / "tools" / "synapse_quest_run.sh"
WRAPPER_PROOF_FILENAME = "06_WRAPPER_PROOF.json"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _wrapper_script_sha256() -> str:
    return _sha256_bytes(WRAPPER_SCRIPT_PATH.read_bytes())


def _accepted_execution_context(subject: str, data_root: Path) -> dict[str, Any]:
    details = load_accepted_quest_details(subject, data_root)
    current = select_current_accepted_quest(details)
    bundle_path = None
    if current and current.get("audit_bundle_path"):
        bundle_path = Path(str(current["audit_bundle_path"])).expanduser().resolve()
    return {
        "accepted_quest_id": current.get("quest_id") if current else None,
        "accepted_audit_bundle_path": str(bundle_path) if bundle_path else None,
        "accepted_execution_view": current,
    }


def locate_wrapper_proof(subject: str, data_root: Path) -> dict[str, Any]:
    context = _accepted_execution_context(subject, data_root)
    bundle_path_text = context.get("accepted_audit_bundle_path")
    bundle_path = Path(str(bundle_path_text)).resolve() if bundle_path_text else None
    proof_path = bundle_path / WRAPPER_PROOF_FILENAME if bundle_path else None
    return {
        **context,
        "wrapper_proof_path": str(proof_path.resolve()) if proof_path else None,
        "bundle_exists": bool(bundle_path and bundle_path.is_dir()),
        "proof_exists": bool(proof_path and proof_path.is_file()),
    }


def validate_wrapper_proof_file(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return {
            "ok": False,
            "error": f"missing required wrapper proof: {WRAPPER_PROOF_FILENAME}",
            "path": str(path),
            "payload": None,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"invalid wrapper proof JSON: {exc}",
            "path": str(path),
            "payload": None,
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "wrapper proof payload must be a JSON object",
            "path": str(path),
            "payload": payload,
        }

    expected_bundle_path = str(path.parent.resolve())
    actual_wrapper_path = str(WRAPPER_SCRIPT_PATH.resolve())
    expected_wrapper_sha = _wrapper_script_sha256()

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        return {
            "ok": False,
            "error": f"wrapper proof schema_version must be 1 (got {schema_version!r})",
            "path": str(path),
            "payload": payload,
        }
    if str(payload.get("wrapper") or "").strip() != "synapse_quest_run.sh":
        return {
            "ok": False,
            "error": "wrapper proof wrapper field must equal 'synapse_quest_run.sh'",
            "path": str(path),
            "payload": payload,
        }
    if str(payload.get("wrapper_path") or "").strip() != actual_wrapper_path:
        return {
            "ok": False,
            "error": f"wrapper_path mismatch: expected {actual_wrapper_path}",
            "path": str(path),
            "payload": payload,
        }
    if str(payload.get("wrapper_sha256") or "").strip() != expected_wrapper_sha:
        return {
            "ok": False,
            "error": "wrapper_sha256 does not match current synapse_quest_run.sh",
            "path": str(path),
            "payload": payload,
        }
    try:
        commands_count = int(payload.get("commands_count"))
    except Exception:
        commands_count = -1
    if commands_count <= 0:
        return {
            "ok": False,
            "error": "commands_count must be a positive integer",
            "path": str(path),
            "payload": payload,
        }
    if str(payload.get("bundle_path") or "").strip() != expected_bundle_path:
        return {
            "ok": False,
            "error": f"bundle_path mismatch: expected {expected_bundle_path}",
            "path": str(path),
            "payload": payload,
        }
    return {
        "ok": True,
        "error": None,
        "path": str(path),
        "payload": payload,
        "wrapper_path": actual_wrapper_path,
        "wrapper_sha256": expected_wrapper_sha,
        "commands_count": commands_count,
        "bundle_path": expected_bundle_path,
    }


def wrapper_proof_fingerprint(path: Path) -> str | None:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return None
    try:
        return _sha256_bytes(path.read_bytes())
    except Exception:
        return None


def current_wrapper_proof_receipt(subject: str, data_root: Path) -> dict[str, Any]:
    located = locate_wrapper_proof(subject, data_root)
    accepted_quest_id = located.get("accepted_quest_id")
    bundle_path = located.get("accepted_audit_bundle_path")
    proof_path = located.get("wrapper_proof_path")
    if not accepted_quest_id:
        return {
            **located,
            "wrapper_proof_status": "not_applicable",
            "wrapper_proof_valid": None,
            "wrapper_proof_error": None,
            "wrapper_proof_fingerprint": None,
        }
    if not bundle_path or not located.get("bundle_exists"):
        return {
            **located,
            "wrapper_proof_status": "missing",
            "wrapper_proof_valid": False,
            "wrapper_proof_error": "accepted audit bundle is missing or unreadable",
            "wrapper_proof_fingerprint": None,
        }
    if not proof_path or not located.get("proof_exists"):
        return {
            **located,
            "wrapper_proof_status": "missing",
            "wrapper_proof_valid": False,
            "wrapper_proof_error": f"missing required wrapper proof: {WRAPPER_PROOF_FILENAME}",
            "wrapper_proof_fingerprint": None,
        }
    validation = validate_wrapper_proof_file(Path(proof_path))
    if not validation.get("ok"):
        return {
            **located,
            "wrapper_proof_status": "invalid",
            "wrapper_proof_valid": False,
            "wrapper_proof_error": validation.get("error"),
            "wrapper_proof_validation": validation,
            "wrapper_proof_fingerprint": wrapper_proof_fingerprint(Path(proof_path)),
        }
    return {
        **located,
        "wrapper_proof_status": "valid",
        "wrapper_proof_valid": True,
        "wrapper_proof_error": None,
        "wrapper_proof_validation": validation,
        "wrapper_proof_fingerprint": wrapper_proof_fingerprint(Path(proof_path)),
    }

"""Append-only raw evidence helpers for the engaged-kernel scaffold."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from synapse_runtime.kernel_types import RawStoreFamily


RAW_DIRNAME = "RAW"
RECORD_FAMILIES = (
    RawStoreFamily.CONVERSATION_TURNS,
    RawStoreFamily.EXECUTION_EVENTS,
    RawStoreFamily.TOOL_EVENTS,
    RawStoreFamily.IMPORT_EVENTS,
)


class RawStoreError(RuntimeError):
    """Raised when raw evidence cannot be written safely."""


_MIME_EXTENSIONS = {
    "application/json": ".json",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


def raw_root(data_root: Path) -> Path:
    return data_root / ".synapse" / RAW_DIRNAME



def raw_family_dir(data_root: Path, family: RawStoreFamily) -> Path:
    return raw_root(data_root) / family.value



def ensure_raw_scaffold(data_root: Path) -> dict[str, Any]:
    root = raw_root(data_root)
    created: list[str] = []
    existing: list[str] = []
    root.mkdir(parents=True, exist_ok=True)
    for family in (*RECORD_FAMILIES, RawStoreFamily.BLOBS):
        path = raw_family_dir(data_root, family)
        if path.exists():
            existing.append(str(path))
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))
    return {
        "raw_root": str(root.resolve()),
        "created": created,
        "existing": existing,
        "required_paths": {
            family.value.lower(): str(raw_family_dir(data_root, family).resolve())
            for family in (*RECORD_FAMILIES, RawStoreFamily.BLOBS)
        },
    }



def inspect_raw_scaffold(data_root: Path) -> dict[str, Any]:
    root = raw_root(data_root)
    families: dict[str, str] = {}
    missing: list[str] = []
    for family in (*RECORD_FAMILIES, RawStoreFamily.BLOBS):
        path = raw_family_dir(data_root, family)
        status = "exists" if path.exists() and path.is_dir() else "missing"
        families[family.value.lower()] = status
        if status != "exists":
            missing.append(family.value.lower())
    if missing:
        scaffold_status = "missing" if len(missing) == len(families) else "partial"
    else:
        scaffold_status = "healthy"
    return {
        "raw_root": str(root.resolve()),
        "scaffold_status": scaffold_status,
        "families": families,
        "missing_families": missing,
    }



def _day_bucket(recorded_at: str) -> str:
    return str(recorded_at).split("T", 1)[0]



def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")



def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()



def _blob_extension(mime_type: str) -> str:
    return _MIME_EXTENSIONS.get(str(mime_type or "").strip().lower(), ".blob")



def write_blob(*, data_root: Path, payload: bytes | str | dict[str, Any] | list[Any], mime_type: str) -> dict[str, Any]:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = _json_bytes(payload)
    sha256 = _sha256_bytes(raw)
    extension = _blob_extension(mime_type)
    blob_dir = raw_family_dir(data_root, RawStoreFamily.BLOBS) / sha256[:2]
    blob_dir.mkdir(parents=True, exist_ok=True)
    path = blob_dir / f"{sha256}{extension}"
    if not path.exists():
        path.write_bytes(raw)
    return {
        "sha256": sha256,
        "path": str(path.resolve()),
        "mime_type": mime_type,
        "size_bytes": len(raw),
    }



def write_raw_record(*, data_root: Path, family: RawStoreFamily, record_id: str, recorded_at: str, payload: dict[str, Any]) -> dict[str, Any]:
    if family not in RECORD_FAMILIES:
        raise RawStoreError(f"Unsupported raw record family: {family}")
    bucket_dir = raw_family_dir(data_root, family) / _day_bucket(recorded_at)
    bucket_dir.mkdir(parents=True, exist_ok=True)
    path = bucket_dir / f"{record_id}.json"
    if path.exists():
        raise RawStoreError(f"Raw record already exists and will not be rewritten: {path}")
    path.write_bytes(_json_bytes(payload))
    return {
        "record_id": record_id,
        "path": str(path.resolve()),
        "sha256": _sha256_bytes(path.read_bytes()),
        "family": family.value,
    }

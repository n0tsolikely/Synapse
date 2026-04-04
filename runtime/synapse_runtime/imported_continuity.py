"""Transcript, note, and PDF import envelopes for noncanonical continuity parsing."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from synapse_runtime.kernel_types import (
    ConversationSegmentEnvelope,
    ImportedContinuityEnvelope,
    ImportedContinuityKind,
    ImportedContinuityParseStatus,
    KERNEL_SCHEMA_VERSION,
    SEMANTIC_CLASSIFIER_VERSION,
    SegmentFamily,
    stable_kernel_id,
)
from synapse_runtime.semantic_classifier import conversation_blocks


class ImportedContinuityError(RuntimeError):
    """Raised when imported continuity sources cannot be parsed honestly."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _preview(text: str, *, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def normalize_import_kind(value: str | None, *, source_path: Path) -> ImportedContinuityKind:
    text = str(value or "").strip().lower()
    if text in {"", "auto"}:
        if source_path.suffix.lower() == ".pdf":
            return ImportedContinuityKind.PDF
        return ImportedContinuityKind.NOTE
    try:
        return ImportedContinuityKind(text)
    except ValueError as exc:
        raise ImportedContinuityError(f"Unsupported imported continuity kind: {value}") from exc


def parse_imported_continuity_source(*, source_path: Path, source_kind: str | None = None) -> dict[str, Any]:
    path = source_path.expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ImportedContinuityError(f"Imported continuity source does not exist: {path}")

    raw = path.read_bytes()
    kind = normalize_import_kind(source_kind, source_path=path)
    warnings: list[str] = []
    parser_name = "builtin-text"
    parser_status = ImportedContinuityParseStatus.PARSED.value
    confidence_band = "medium"
    extracted_text = ""

    if kind == ImportedContinuityKind.PDF:
        parser_name = "unavailable-pdf-extractor"
        parser_status = ImportedContinuityParseStatus.UNSUPPORTED.value
        confidence_band = "low"
        warnings.append("PDF extraction is unavailable in this runtime; provenance was preserved without pretending text certainty.")
    else:
        try:
            extracted_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            extracted_text = raw.decode("utf-8", errors="replace")
            parser_status = ImportedContinuityParseStatus.LIMITED.value
            confidence_band = "low"
            warnings.append("Source required replacement decoding; extracted text confidence was reduced.")

    envelope = ImportedContinuityEnvelope(
        import_id=stable_kernel_id("IMPORT", path, _sha256_bytes(raw)),
        schema_version=KERNEL_SCHEMA_VERSION,
        recorded_at="",
        source_path=str(path),
        source_kind=kind.value,
        source_sha256=_sha256_bytes(raw),
        size_bytes=len(raw),
        parser_status=parser_status,
        parser_name=parser_name,
        confidence_band=confidence_band,
        text_preview=_preview(extracted_text),
        extracted_text=extracted_text,
        warnings=warnings,
    )
    return envelope.to_dict()


def imported_confidence_profile(envelope: dict[str, Any]) -> dict[str, Any]:
    parser_status = str(envelope.get("parser_status") or ImportedContinuityParseStatus.UNSUPPORTED.value).strip().lower()
    confidence_band = str(envelope.get("confidence_band") or "low").strip().lower()
    extracted_text = str(envelope.get("extracted_text") or "").strip()
    requires_review = parser_status in {
        ImportedContinuityParseStatus.LIMITED.value,
        ImportedContinuityParseStatus.UNSUPPORTED.value,
    } or confidence_band == "low"
    has_text = bool(extracted_text)
    publication_candidate_eligible = (
        parser_status == ImportedContinuityParseStatus.PARSED.value
        and confidence_band in {"medium", "high"}
        and has_text
    )
    snapshot_candidate_eligible = publication_candidate_eligible
    draftshot_eligible = has_text and parser_status != ImportedContinuityParseStatus.UNSUPPORTED.value
    return {
        "parser_status": parser_status,
        "confidence_band": confidence_band,
        "requires_review": requires_review,
        "draftshot_eligible": draftshot_eligible,
        "snapshot_candidate_eligible": snapshot_candidate_eligible,
        "publication_candidate_eligible": publication_candidate_eligible,
        "warning_count": len(list(envelope.get("warnings") or [])),
    }


def imported_segments_from_envelope(
    envelope: dict[str, Any],
    *,
    subject: str,
    recorded_at: str,
    source_refs: list[dict[str, Any]],
    session_id: str | None = None,
    run_id: str | None = None,
    source_surface: str = "import",
) -> list[ConversationSegmentEnvelope]:
    text = str(envelope.get("extracted_text") or "").strip()
    if not text:
        return []

    blocks = conversation_blocks(text)

    import_id = str(envelope.get("import_id") or "").strip() or stable_kernel_id("IMPORT", text[:80])
    return [
        ConversationSegmentEnvelope(
            segment_id=stable_kernel_id("SEGCONV", import_id, index),
            schema_version=KERNEL_SCHEMA_VERSION,
            classifier_version=SEMANTIC_CLASSIFIER_VERSION,
            recorded_at=recorded_at,
            subject=subject,
            segment_family=SegmentFamily.CONVERSATION.value,
            source_turn_id=import_id,
            source_surface=source_surface,
            session_id=session_id,
            run_id=run_id,
            role="imported",
            segment_index=index,
            text_preview=_preview(block),
            text_length=len(block),
            transient_noise=False,
            source_refs=list(source_refs),
        )
        for index, block in enumerate(blocks)
    ]

"""Governance corpus ingestion and machine-readable inventory for Synapse."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.governance_model import (
    AuthorityClass,
    GovernanceCategory,
    KNOWN_CONTRADICTIONS,
    authority_precedence,
    implementation_status_from_capabilities,
    matched_concepts,
    now_iso,
)


@dataclass(frozen=True)
class GovernanceDoc:
    path: str
    title: str
    governance_category: str
    authority_class: str
    concepts_defined: tuple[str, ...]
    concepts_referenced: tuple[str, ...]
    runtime_obligations_implied: tuple[str, ...]
    artifact_obligations_implied: tuple[str, ...]
    blockers_or_gates_implied: tuple[str, ...]
    implementation_status: str
    capability_keys: tuple[str, ...]
    contradiction_note: str | None = None


TITLE_STOPWORDS = {
    "version:",
    "last updated:",
    "status:",
    "purpose:",
    "audience:",
}

OBLIGATION_RX = re.compile(r"\b(MUST(?: NOT)?|REQUIRED|forbidden|illegal|blocked|invalid)\b", re.IGNORECASE)
ARTIFACT_HINT_RX = re.compile(r"(<Subject>_Data|<Subject>_Engine|\.yaml\b|\.md\b|\.txt\b|/|\\)", re.IGNORECASE)
BLOCKER_RX = re.compile(r"\b(Disclosure Gate|BLOCKED|FAIL|forbidden|illegal|MUST NOT proceed|invalid)\b", re.IGNORECASE)


def _clean_line(raw: str) -> str:
    line = raw.strip()
    line = re.sub(r"^[#>*\-\s]+", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def _first_title(text: str, fallback: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(line.lower().startswith(prefix) for prefix in TITLE_STOPWORDS):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        return line
    return fallback


def _classify_category(path: str) -> GovernanceCategory:
    if path in {"README.txt", "INDEX.txt", "SYNAPSE_STATE.yaml", "FILE_TREE.txt", "GOV_INDEX.yaml", "CONVERSION_QUEUE.yaml"}:
        return GovernanceCategory.ROUTING
    if path.startswith("Continuity/"):
        return GovernanceCategory.CONTINUITY
    if path.startswith("Processes/"):
        return GovernanceCategory.PROCESS
    if path.startswith("Guild Docs/"):
        if "SNAPSHOT" in path.upper():
            return GovernanceCategory.SNAPSHOT
        return GovernanceCategory.CANONICAL
    if path.startswith("Quest Board/"):
        return GovernanceCategory.QUEST_SYSTEM
    if path.startswith("Talent Tree/"):
        return GovernanceCategory.TALENT_TREE
    if path.startswith("The Guild/Terminology/Locks/"):
        return GovernanceCategory.TERMINOLOGY_LOCK
    if path.startswith("The Guild/Terminology/Terms/") or path == "The Guild/Terminology/README.md":
        return GovernanceCategory.TERMINOLOGY_TERM
    if path.startswith("Schemas/") or path == "GOV_IR_SCHEMA.json":
        return GovernanceCategory.SCHEMA
    if path.startswith("The Guild/"):
        return GovernanceCategory.CANONICAL
    return GovernanceCategory.SUPPORT


def _classify_authority(path: str, title: str) -> AuthorityClass:
    if path.startswith("The Guild/Terminology/Locks/"):
        return AuthorityClass.LOCK_AUTHORITY
    if path in {"README.txt", "INDEX.txt", "SYNAPSE_STATE.yaml", "FILE_TREE.txt", "GOV_INDEX.yaml", "CONVERSION_QUEUE.yaml"}:
        return AuthorityClass.ROUTING_INDEXING
    if path.startswith("Schemas/") or path == "GOV_IR_SCHEMA.json":
        return AuthorityClass.SCHEMA_CONTRACT
    if "TEMPLATE" in path.upper():
        return AuthorityClass.TEMPLATE_SPEC
    if path.startswith("The Guild/Terminology/Terms/") or path == "The Guild/Terminology/README.md":
        return AuthorityClass.TERMINOLOGY_REFERENCE
    if path.startswith("Processes/"):
        return AuthorityClass.PROCESS_PROCEDURE
    if path.startswith("The Guild/") or path.startswith("Continuity/") or path.startswith("Guild Docs/") or path.startswith("Quest Board/") or path.startswith("Talent Tree/"):
        return AuthorityClass.DEFINITIONAL_LAW
    if "template" in title.lower():
        return AuthorityClass.TEMPLATE_SPEC
    return AuthorityClass.SUPPORTING_DOC


def _extract_obligation_lines(text: str, *, artifact_only: bool = False, blocker_only: bool = False) -> list[str]:
    results: list[str] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        if blocker_only:
            if not BLOCKER_RX.search(line):
                continue
        elif not OBLIGATION_RX.search(line):
            continue
        if artifact_only and not ARTIFACT_HINT_RX.search(line):
            continue
        if len(line) > 280:
            line = line[:277].rstrip() + "..."
        if line not in results:
            results.append(line)
    return results[:16]


def _extract_defined_concepts(path: str, title: str, text: str) -> list[str]:
    defined: list[str] = []
    combined = "\n".join([title, text[:1200]])
    for spec in matched_concepts(combined):
        if spec.display_name not in defined:
            defined.append(spec.display_name)
    return defined


def _extract_referenced_concepts(text: str, defined: list[str]) -> list[str]:
    refs: list[str] = []
    for spec in matched_concepts(text):
        if spec.display_name in defined:
            continue
        if spec.display_name not in refs:
            refs.append(spec.display_name)
    return refs


def _capabilities_for_doc(path: str, text: str) -> list[str]:
    keys: list[str] = []
    for spec in matched_concepts(text):
        for key in spec.capabilities:
            if key not in keys:
                keys.append(key)

    if path.startswith("The Guild/Terminology/Locks/"):
        for key in ("governance_inventory", "truth_gate_receipts"):
            if key not in keys:
                keys.append(key)
    if path.startswith("Processes/") and "DRAFTSHOT" in path.upper():
        for key in ("draftshot_bridge", "snapshot_runtime"):
            if key not in keys:
                keys.append(key)
    if path.startswith("Processes/") and "SCHEMA_VALIDATION" in path.upper():
        for key in ("schema_validation",):
            if key not in keys:
                keys.append(key)
    if path == "SYNAPSE_STATE.yaml":
        for key in ("schema_validation", "subject_resolution", "governance_inventory"):
            if key not in keys:
                keys.append(key)
    return keys


def _doc_records(governance_root: Path) -> list[GovernanceDoc]:
    docs: list[GovernanceDoc] = []
    for path in sorted(governance_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(governance_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        title = _first_title(text, rel)
        category = _classify_category(rel)
        authority = _classify_authority(rel, title)
        defined = _extract_defined_concepts(rel, title, text)
        referenced = _extract_referenced_concepts(text, defined)
        capabilities = _capabilities_for_doc(rel, "\n".join([title, text]))
        docs.append(
            GovernanceDoc(
                path=rel,
                title=title,
                governance_category=category.value,
                authority_class=authority.value,
                concepts_defined=tuple(defined),
                concepts_referenced=tuple(referenced),
                runtime_obligations_implied=tuple(_extract_obligation_lines(text)),
                artifact_obligations_implied=tuple(_extract_obligation_lines(text, artifact_only=True)),
                blockers_or_gates_implied=tuple(_extract_obligation_lines(text, blocker_only=True)),
                implementation_status=implementation_status_from_capabilities(capabilities, path=rel).value,
                capability_keys=tuple(capabilities),
                contradiction_note=KNOWN_CONTRADICTIONS.get(f"governance/{rel}") or KNOWN_CONTRADICTIONS.get(rel),
            )
        )
    return docs


def build_governance_inventory(governance_root: Path) -> dict[str, Any]:
    docs = _doc_records(governance_root)
    category_counts: dict[str, int] = {}
    for doc in docs:
        category_counts[doc.governance_category] = category_counts.get(doc.governance_category, 0) + 1

    contradictions = [
        {
            "path": path,
            "note": note,
        }
        for path, note in sorted(KNOWN_CONTRADICTIONS.items())
    ]

    return {
        "generated_at": now_iso(),
        "governance_root": str(governance_root.resolve()),
        "authority_model": {
            "precedence": authority_precedence(),
            "notes": [
                "Locks override all non-lock documents.",
                "Conversation is non-authoritative compared with filesystem artifacts.",
                "Continuity Lock and Buffs constrain subject runtime behavior but do not override governance law.",
            ],
        },
        "summary": {
            "doc_count": len(docs),
            "category_counts": category_counts,
            "contradiction_count": len(contradictions),
        },
        "docs": [asdict(doc) for doc in docs],
        "contradictions": contradictions,
    }


def write_governance_inventory(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    yaml_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    path.write_text(yaml_text, encoding="utf-8")
    return path


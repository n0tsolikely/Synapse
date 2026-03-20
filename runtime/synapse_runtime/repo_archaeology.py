"""Deterministic repo archaeology for existing-repo onboarding."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from synapse_runtime.live_memory_common import LiveMemoryError
from synapse_runtime.sidecar_store import _now_iso, live_root


class RepoArchaeologyError(LiveMemoryError):
    """Raised when deterministic repo archaeology cannot complete safely."""


class ScanDepth(str, Enum):
    QUICK = "quick"
    DEEP = "deep"


_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".cs",
    ".csproj",
    ".sln",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".sh",
    ".ps1",
    ".sql",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".lock",
}
_MANIFEST_FILENAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "composer.json",
    "composer.lock",
    "Gemfile",
    "Gemfile.lock",
    "mix.exs",
    "mix.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
_ENTRYPOINT_FILENAMES = {
    "main.py",
    "app.py",
    "manage.py",
    "Program.cs",
    "Startup.cs",
    "server.js",
    "server.ts",
    "index.js",
    "index.ts",
    "main.ts",
    "main.js",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.mjs",
    "nuxt.config.ts",
    "nuxt.config.js",
    "astro.config.mjs",
    "astro.config.ts",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env",
    ".env.example",
}
_DOC_DIR_MARKERS = {"docs", "doc", "documentation"}
_IGNORE_DIR_NAMES = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "coverage", "bin", "obj"}
_UNFINISHED_MARKERS = ("TODO", "FIXME", "HACK", "XXX", "WIP")
_CONTINUITY_NAMES = {
    ".synapse",
    "EXECUTOR.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/PERSONAS.md",
    "docs/INTEGRATIONS.md",
    "Latest Rehydration Pack",
    "Buffs",
}


def scan_limits(depth: ScanDepth) -> dict[str, int | None]:
    if depth == ScanDepth.QUICK:
        return {
            "max_text_files": 200,
            "max_bytes_per_text_file": 256 * 1024,
            "max_recent_commits": 0,
            "max_local_branches": 0,
            "max_tags": 0,
        }
    return {
        "max_text_files": 400,
        "max_bytes_per_text_file": 512 * 1024,
        "max_recent_commits": 200,
        "max_local_branches": 20,
        "max_tags": 20,
    }


def scan_artifact_path(data_root: Path, scan_id: str) -> Path:
    return (live_root(data_root) / "ONBOARDING" / "SCANS" / f"SCAN__{scan_id}.yaml").resolve()


def stable_scan_item_id(*, section: str, normalized_path: str | None = None, key: str | None = None) -> str:
    payload = json.dumps(
        {
            "section": section,
            "path": normalized_path or "",
            "key": key or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def evidence_ref(*, scan_id: str, section: str, item_id: str) -> str:
    return f"scan:{scan_id}:{section}:{item_id}"


def write_scan_artifact(*, data_root: Path, scan: dict[str, Any]) -> str:
    path = scan_artifact_path(data_root, str(scan["scan_id"]))
    path.write_text(yaml.safe_dump(scan, sort_keys=False), encoding="utf-8")
    return str(path)


def run_repo_archaeology(
    *,
    onboarding_id: str,
    engine_root: Path,
    data_root: Path,
    depth: str | ScanDepth = ScanDepth.DEEP,
    scan_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    depth_value = depth if isinstance(depth, ScanDepth) else ScanDepth(str(depth))
    engine = engine_root.resolve()
    if not engine.exists() or not engine.is_dir():
        raise RepoArchaeologyError(f"Engine root does not exist for archaeology scan: {engine}")

    limits = scan_limits(depth_value)
    omissions: list[dict[str, Any]] = []
    text_budget = int(limits["max_text_files"] or 0)
    byte_budget = int(limits["max_bytes_per_text_file"] or 0)

    candidates = list(_iter_repo_files(engine))
    text_candidates = [path for path in candidates if _is_text_candidate(path)]
    if len(text_candidates) > text_budget:
        omissions.append(
            {
                "section": "text_inspection",
                "reason": "max_text_files_reached",
                "limit": text_budget,
                "actual": len(text_candidates),
            }
        )
        text_candidates = text_candidates[:text_budget]

    text_samples: dict[str, str] = {}
    for path in text_candidates:
        rel = _relpath(path, engine)
        text, truncated = _read_text_sample(path, byte_budget)
        text_samples[rel] = text
        if truncated:
            omissions.append(
                {
                    "section": "text_inspection",
                    "reason": "max_bytes_per_text_file_reached",
                    "path": rel,
                    "limit": byte_budget,
                }
            )

    tree_inventory = _tree_inventory(engine)
    docs_inventory = _docs_inventory(engine, candidates, text_samples)
    manifest_inventory = _manifest_inventory(engine, candidates, text_samples)
    entrypoint_inventory = _entrypoint_inventory(engine, candidates, text_samples)
    test_inventory = _test_inventory(engine, candidates, text_samples)
    unfinishedness_inventory = _unfinishedness_inventory(engine, text_samples)
    existing_continuity_inventory = _existing_continuity_inventory(engine)
    git_history_summary = _git_history_summary(engine, depth_value, limits, omissions)

    scan = {
        "onboarding_id": onboarding_id,
        "scan_id": scan_id,
        "depth": depth_value.value,
        "created_at": created_at or _now_iso(),
        "engine_root": str(engine),
        "data_root": str(data_root.resolve()),
        "repo_identity": _repo_identity(engine),
        "limits": limits,
        "omissions": omissions,
        "tree_inventory": tree_inventory,
        "docs_inventory": docs_inventory,
        "manifest_inventory": manifest_inventory,
        "entrypoint_inventory": entrypoint_inventory,
        "test_inventory": test_inventory,
        "unfinishedness_inventory": unfinishedness_inventory,
        "existing_continuity_inventory": existing_continuity_inventory,
        "git_history_summary": git_history_summary,
    }
    artifact_path = write_scan_artifact(data_root=data_root, scan=scan)
    return {"scan": scan, "artifact_path": artifact_path}


def load_scan_artifact(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RepoArchaeologyError(f"Unable to read scan artifact: {path}") from exc
    if not isinstance(payload, dict) or not payload.get("scan_id"):
        raise RepoArchaeologyError(f"Malformed scan artifact: {path}")
    return payload


def _iter_repo_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in sorted(dirnames) if name not in _IGNORE_DIR_NAMES]
        current = Path(current_root)
        for filename in sorted(filenames):
            paths.append(current / filename)
    return paths


def _is_text_candidate(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return True
    name = path.name
    return name in _MANIFEST_FILENAMES or name in _ENTRYPOINT_FILENAMES


def _relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_text_sample(path: Path, limit: int) -> tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except Exception:
        return "", False
    truncated = len(raw) > limit
    raw = raw[:limit]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return "", truncated
    return text, truncated


def _tree_inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        rel = child.name
        entries.append(
            {
                "item_id": stable_scan_item_id(section="tree_inventory", normalized_path=rel, key="root"),
                "path": rel,
                "kind": "directory" if child.is_dir() else "file",
            }
        )
        if child.is_dir() and child.name not in _IGNORE_DIR_NAMES:
            for grandchild in sorted(child.iterdir(), key=lambda item: item.name.lower())[:20]:
                grand_rel = grandchild.relative_to(root).as_posix()
                entries.append(
                    {
                        "item_id": stable_scan_item_id(section="tree_inventory", normalized_path=grand_rel, key="nested"),
                        "path": grand_rel,
                        "kind": "directory" if grandchild.is_dir() else "file",
                    }
                )
    return entries


def _docs_inventory(root: Path, files: list[Path], text_samples: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in files:
        rel = _relpath(path, root)
        parts = {part.lower() for part in path.parts}
        if path.suffix.lower() not in {".md", ".txt", ".rst"} and not (_DOC_DIR_MARKERS & parts):
            continue
        snippet = _headline_from_text(text_samples.get(rel, ""))
        results.append(
            {
                "item_id": stable_scan_item_id(section="docs_inventory", normalized_path=rel),
                "path": rel,
                "headline": snippet,
            }
        )
    return results


def _manifest_inventory(root: Path, files: list[Path], text_samples: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in files:
        rel = _relpath(path, root)
        if path.name not in _MANIFEST_FILENAMES and path.suffix.lower() not in {".csproj", ".sln"}:
            continue
        results.append(
            {
                "item_id": stable_scan_item_id(section="manifest_inventory", normalized_path=rel),
                "path": rel,
                "headline": _headline_from_text(text_samples.get(rel, "")),
            }
        )
    return results


def _entrypoint_inventory(root: Path, files: list[Path], text_samples: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in files:
        rel = _relpath(path, root)
        if path.name not in _ENTRYPOINT_FILENAMES and "/config/" not in f"/{rel.lower()}/":
            continue
        results.append(
            {
                "item_id": stable_scan_item_id(section="entrypoint_inventory", normalized_path=rel),
                "path": rel,
                "headline": _headline_from_text(text_samples.get(rel, "")),
            }
        )
    return results


def _test_inventory(root: Path, files: list[Path], text_samples: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in files:
        rel = _relpath(path, root)
        lower = rel.lower()
        if "/tests/" not in f"/{lower}" and not path.name.startswith("test_") and not path.name.endswith("_test.py") and not path.name.endswith(".spec.ts") and not path.name.endswith(".spec.js"):
            continue
        results.append(
            {
                "item_id": stable_scan_item_id(section="test_inventory", normalized_path=rel),
                "path": rel,
                "headline": _headline_from_text(text_samples.get(rel, "")),
            }
        )
    return results


def _unfinishedness_inventory(root: Path, text_samples: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for rel, text in text_samples.items():
        for marker in _UNFINISHED_MARKERS:
            if marker not in text:
                continue
            line = next((line.strip() for line in text.splitlines() if marker in line), marker)
            results.append(
                {
                    "item_id": stable_scan_item_id(section="unfinishedness_inventory", normalized_path=rel, key=marker),
                    "path": rel,
                    "marker": marker,
                    "summary": line[:240],
                }
            )
    return results


def _existing_continuity_inventory(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in sorted(_CONTINUITY_NAMES):
        path = root / name
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        results.append(
            {
                "item_id": stable_scan_item_id(section="existing_continuity_inventory", normalized_path=rel),
                "path": rel,
                "kind": "directory" if path.is_dir() else "file",
            }
        )
    return results


def _repo_identity(root: Path) -> dict[str, Any]:
    return {
        "repo_name": root.name,
        "engine_root": str(root),
        "git": _git_repo_identity(root),
    }


def _git_repo_identity(root: Path) -> dict[str, Any] | None:
    if not (root / ".git").exists():
        return None
    branch = _git_lines(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    head = _git_lines(root, ["rev-parse", "HEAD"])
    return {
        "current_branch": branch[0] if branch else None,
        "head_commit": head[0] if head else None,
    }


def _git_history_summary(root: Path, depth: ScanDepth, limits: dict[str, int | None], omissions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if depth != ScanDepth.DEEP:
        omissions.append({"section": "git_history_summary", "reason": "disabled_for_quick_depth"})
        return None
    if not (root / ".git").exists():
        omissions.append({"section": "git_history_summary", "reason": "git_metadata_unavailable"})
        return None

    max_commits = int(limits["max_recent_commits"] or 0)
    max_branches = int(limits["max_local_branches"] or 0)
    max_tags = int(limits["max_tags"] or 0)

    branch = _git_lines(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    branches = _git_lines(root, ["branch", "--format=%(refname:short)"])
    tags = _git_lines(root, ["tag", "--sort=-creatordate"])
    commits = _git_lines(root, ["log", f"--max-count={max_commits}", "--pretty=format:%H%x09%ad%x09%s", "--date=iso-strict"])
    churn = _git_lines(root, ["log", f"--max-count={max_commits}", "--name-only", "--pretty=format:"])

    branch_list = branches[:max_branches]
    if len(branches) > max_branches:
        omissions.append({"section": "git_history_summary.local_branches", "reason": "max_local_branches_reached", "limit": max_branches})
    tag_list = tags[:max_tags]
    if len(tags) > max_tags:
        omissions.append({"section": "git_history_summary.tags", "reason": "max_tags_reached", "limit": max_tags})

    churn_counts: dict[str, int] = {}
    for line in churn:
        rel = line.strip()
        if rel:
            churn_counts[rel] = churn_counts.get(rel, 0) + 1

    return {
        "current_branch": branch[0] if branch else None,
        "local_branches": branch_list,
        "tags": tag_list,
        "recent_commits": [
            {
                "item_id": stable_scan_item_id(section="git_history_summary.recent_commits", key=line),
                "raw": line,
            }
            for line in commits
        ],
        "top_churn_files": [
            {
                "item_id": stable_scan_item_id(section="git_history_summary.top_churn_files", normalized_path=path),
                "path": path,
                "touch_count": count,
            }
            for path, count in sorted(churn_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
    }


def _git_lines(root: Path, args: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _headline_from_text(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:200]
    return None

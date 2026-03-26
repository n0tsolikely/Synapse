"""Repo-local bridge files that point subject repos back to the Synapse contract."""

from __future__ import annotations

from pathlib import Path

from synapse_runtime.governance_pack import resolve_synapse_root


BRIDGE_START = "<!-- SYNAPSE SUBJECT BRIDGE: START -->"
BRIDGE_END = "<!-- SYNAPSE SUBJECT BRIDGE: END -->"
SHIM_FILENAMES = ("AGENTS.md", "CLAUDE.md")


def _managed_bridge_block(*, subject: str, data_root: Path, synapse_root: Path, shim_filename: str) -> str:
    executor_path = (synapse_root / "EXECUTOR.md").resolve()
    runtime_path = (synapse_root / "runtime" / "synapse.py").resolve()
    lines = [
        BRIDGE_START,
        f"# Synapse Subject Bridge ({shim_filename})",
        "",
        "This repository is governed through an external Synapse engine.",
        "",
        "Synapse root:",
        f"- `{synapse_root}`",
        "",
        "Subject repo:",
        "- this repository",
        "",
        "Subject data root:",
        f"- `{data_root}`",
        "",
        "Do not treat the absence of a local `EXECUTOR.md` as absence of Synapse governance.",
        "The canonical execution contract lives in the Synapse engine repo:",
        "",
        f"- `{executor_path}`",
        "",
        "Required behavior:",
        "1. Use the Synapse runtime for subject resolution, onboarding, continuity, doctor, and governed execution.",
        f"2. Treat this repository as the subject repo for `{subject}`.",
        "3. If continuity state already exists, reload it and continue under Synapse law rather than reinitializing from scratch.",
        "4. If the target repo or subject is genuinely ambiguous, ask the user which repo Synapse should engage against before proceeding.",
        "5. If onboarding or readiness gates fail, do not bypass them.",
        "",
        "Bootstrap:",
        f"- `python3 {runtime_path} engage --adopt-current-repo --shell`",
        "",
        f"Canonical contract: now open `{executor_path}` and follow it exactly.",
        BRIDGE_END,
        "",
    ]
    return "\n".join(lines)


def _merge_bridge(existing: str, block: str) -> tuple[str, str]:
    if not existing.strip():
        return block, "written"
    if BRIDGE_START in existing and BRIDGE_END in existing:
        start = existing.index(BRIDGE_START)
        end = existing.index(BRIDGE_END) + len(BRIDGE_END)
        before = existing[:start].rstrip()
        after = existing[end:].lstrip("\n")
        merged_parts: list[str] = []
        if before:
            merged_parts.append(before)
        merged_parts.append(block.rstrip())
        if after:
            merged_parts.append(after.rstrip())
        return "\n\n".join(part for part in merged_parts if part).rstrip() + "\n", "updated"
    return block.rstrip() + "\n\n" + existing.lstrip(), "prepended"


def _resolve_git_dir(repo_root: Path) -> Path | None:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if dot_git.is_file():
        first_line = dot_git.read_text(encoding="utf-8").splitlines()[0].strip()
        if first_line.lower().startswith("gitdir:"):
            git_dir_raw = first_line.split(":", 1)[1].strip()
            git_dir = Path(git_dir_raw)
            if not git_dir.is_absolute():
                git_dir = (repo_root / git_dir).resolve()
            return git_dir.resolve()
    return None


def ensure_subject_repo_bridge(
    *,
    subject: str,
    repo_root: Path,
    data_root: Path,
    shim_filename: str = "AGENTS.md",
    synapse_root: Path | None = None,
) -> dict[str, str]:
    synapse_root = (synapse_root or resolve_synapse_root()).resolve()
    repo_root = repo_root.resolve()
    data_root = data_root.resolve()
    bridge_path = repo_root / shim_filename
    block = _managed_bridge_block(
        subject=subject,
        data_root=data_root,
        synapse_root=synapse_root,
        shim_filename=shim_filename,
    )
    existing = bridge_path.read_text(encoding="utf-8") if bridge_path.exists() else ""
    merged, bridge_status = _merge_bridge(existing, block)

    if bridge_path.exists() and existing == merged:
        bridge_status = "noop"
    else:
        bridge_path.write_text(merged, encoding="utf-8")

    exclude_status = ensure_subject_bridge_git_exclude(repo_root, shim_filename=shim_filename)
    return {
        "shim_filename": shim_filename,
        "bridge_path": str(bridge_path.resolve()),
        "bridge_status": bridge_status,
        "exclude_status": exclude_status,
        "synapse_root": str(synapse_root),
    }


def ensure_subject_repo_bridges(
    *,
    subject: str,
    repo_root: Path,
    data_root: Path,
    synapse_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    bridges: dict[str, dict[str, str]] = {}
    for shim_filename in SHIM_FILENAMES:
        bridges[shim_filename] = ensure_subject_repo_bridge(
            subject=subject,
            repo_root=repo_root,
            data_root=data_root,
            shim_filename=shim_filename,
            synapse_root=synapse_root,
        )
    return bridges


def ensure_subject_bridge_git_exclude(repo_root: Path, *, shim_filename: str) -> str:
    git_dir = _resolve_git_dir(repo_root.resolve())
    if git_dir is None:
        return "no_git_dir"

    exclude_path = git_dir / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    exclude_entry = f"/{shim_filename}"
    if exclude_entry in {line.strip() for line in existing.splitlines()}:
        return "noop"
    with exclude_path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(f"{exclude_entry}\n")
    return "updated"

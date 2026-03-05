# Synapse

Synapse is a governance-first execution system for continuity across AI sessions.

## Purpose

- Preserve project continuity with deterministic artifacts, not chat memory.
- Enforce proof-backed execution (truth gate, audits, snapshots).
- Let any compliant operator rehydrate and continue work safely.

## 60-Second Quickstart (Local)

### 1) Clone
```bash
git clone https://github.com/n0tsolikely/Synapse.git
cd Synapse
```

### 2) Set subject focus
```bash
python3 runtime/synapse.py focus
```

### 3) Run governance check
```bash
python3 runtime/synapse.py doctor --governance-root governance
```

## Executor Contract and Compatibility Shims

Canonical executor rules are defined in `EXECUTOR.md`.
Compatibility shim files are provided for common tools and should point to `EXECUTOR.md` as single source of truth.

Shim surfaces in this repo:
- `AGENTS.md` (shim)
- `CLAUDE.md` (shim)
- `.github/copilot-instructions.md`
- `.cursor/rules/*`
- `.clinerules/*`
- `.continue/rules/*`
- `.roorules` and `.roo/rules/*`
- `.windsurf/rules/*`
- `.aiassistant/rules/*`

If you prefer a different tool convention, copy/rename as needed, but keep one canonical source: `EXECUTOR.md`.

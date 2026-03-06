# Synapse + Codex

Keep `~/.codex/AGENTS.md` thin.

The global Codex file should set working style only.
Do not put the full Synapse law into the global file.

For governed repo work:

- repo `AGENTS.md` stays tiny
- repo `AGENTS.md` points to `EXECUTOR.md`
- `EXECUTOR.md` is the canonical contract

If you want Synapse-managed persona overlays, use:

- `SYNAPSE_PERSONA`
- `$HOME/.synapse/PERSONA_ACTIVE.txt`
- `<repo>/.synapse/PERSONA_ACTIVE.txt`

Recommended session start:

```bash
cd /path/to/Synapse
python3 runtime/synapse.py engage
```

Do not run the full Synapse boot ritual globally outside a Synapse repo.

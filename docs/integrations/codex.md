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

For local MCP integration, use the dedicated stdio server:

```bash
python3 /path/to/Synapse/runtime/synapse_mcp/server.py
```

Run that process with:
- `cwd` set to the target governed workspace
- `SYNAPSE_ROOT` set to the Synapse install root

See [docs/integrations/mcp.md](/home/notsolikely/Synapse/docs/integrations/mcp.md) for the tool/resource inventory and example MCP client config.

Do not run the full Synapse boot ritual globally outside a Synapse repo.

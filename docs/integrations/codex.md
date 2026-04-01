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
cd /path/to/subject-repo
python3 /path/to/Synapse/runtime/synapse.py engage --adopt-current-repo
```

Optional local integration install/refresh:

```bash
cd /path/to/subject-repo
python3 /path/to/Synapse/runtime/synapse.py install-local-integration
```

For local MCP integration, use the dedicated stdio server:

```bash
python3 /path/to/Synapse/runtime/synapse_mcp/server.py
```

Run that process with:
- `cwd` set to the target governed workspace
- `SYNAPSE_ROOT` set to the Synapse install root

See [docs/integrations/mcp.md](/home/notsolikely/Synapse/docs/integrations/mcp.md) for the tool/resource inventory and example MCP client config.

Phase 0 truth:

- raw boundary capture is available through:
  - `record-raw-turn`
  - `record-raw-execution`
  - the optional local hook entrypoints installed by `install-local-integration`
- repo-local `.codex` assets are optional and explicitly installed
- repos surface `hooked` vs `degraded` posture through doctor/current-context instead of pretending hook mediation always exists

Do not run the full Synapse boot ritual globally outside a Synapse repo.

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
/path/to/Synapse/.venv/bin/python /path/to/Synapse/runtime/synapse.py engage --adopt-current-repo
```

Optional local integration install/refresh:

```bash
cd /path/to/subject-repo
/path/to/Synapse/.venv/bin/python /path/to/Synapse/runtime/synapse.py install-local-integration
```

If you want to pin a specific continuity observer backend explicitly:

```bash
/path/to/Synapse/.venv/bin/python /path/to/Synapse/runtime/synapse.py install-local-integration --observer-backend openai_responses
```

If the Synapse engine env does not exist yet, bootstrap it first:

```bash
python3 -m venv /path/to/Synapse/.venv
/path/to/Synapse/.venv/bin/python -m pip install -r /path/to/Synapse/runtime/requirements.txt
```

What this does now:

- verifies or bootstraps the Synapse engine runtime under `SYNAPSE_ROOT/.venv`
- installs `runtime/requirements.txt` there when required
- writes repo-local `.codex` assets pinned to that exact Synapse interpreter
- persists the selected continuity observer backend when one is chosen or auto-selected, and keeps using it until you explicitly change it
- can require an explicit observer-backend choice when multiple provider keys are available
- uses profile-aware launch wrappers so keys exported in bash login profiles remain available to the repo-local Synapse integration
- leaves the subject repo's own app/test/build environment alone

For local MCP integration, use the dedicated stdio server:

```bash
/path/to/Synapse/.venv/bin/python /path/to/Synapse/runtime/synapse_mcp/server.py
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

Current Codex client shape:

- repo-local project overrides live in `.codex/config.toml`
- lifecycle hooks are loaded from `.codex/hooks.json`
- wrapper scripts still live under `.codex/hooks/`
- legacy `.codex/mcp.json` may be kept as a compatibility hint, but current Codex integration should not rely on it

Interpreter rule:

- Synapse runtime / MCP should run from the Synapse engine interpreter
- subject repos keep their own separate environments for app/test/build work
- local integration should not rely on a random `python3` on PATH

That means a healthy local install should include at least:

- `.codex/config.toml`
- `.codex/hooks.json`
- `.codex/hooks/user_prompt_submit.sh`
- `.codex/hooks/pre_tool.sh`
- `.codex/hooks/post_tool.sh`
- `.codex/hooks/stop.sh`
- `.codex/synapse_local_integration.json`

Practical consequence:

- if those assets exist and the client trusts the project, Codex can invoke Synapse automatically at prompt/tool/stop boundaries
- if the client does not load them, Synapse must report degraded posture honestly instead of pretending chat capture happened

Phase 4 truth:

- the optional `Stop` hook can run `close-turn` validation automatically when the local integration assets are installed and the Codex client actually invokes that boundary
- managed `pre-commit` / `pre-push` hooks can fail closed on blocker-class continuity obligations through `provenance-status --strict`
- degraded posture is still supported and must be stated explicitly; it means those turn-bound checks are not guaranteed to have run
- Synapse does not claim universal interception, rollback of already-run commands, or guaranteed chat capture outside honest boundaries

Do not run the full Synapse boot ritual globally outside a Synapse repo.

# Synapse MCP

Synapse Phase 4 exposes the existing runtime through a local STDIO MCP server.

This is a transport layer over the current runtime. It is not:
- a shell wrapper
- a code-edit tool
- a second continuity store
- a replacement for runtime governance

## Entry Point

Run the server with:

```bash
/absolute/path/to/Synapse/.venv/bin/python /absolute/path/to/Synapse/runtime/synapse_mcp/server.py
```

The working directory should be the governed repo workspace you want Synapse to attach to or resume from.

## Install

Install runtime dependencies, including the official MCP SDK:

```bash
python3 -m venv /absolute/path/to/Synapse/.venv
/absolute/path/to/Synapse/.venv/bin/python -m pip install -r /absolute/path/to/Synapse/runtime/requirements.txt
```

Practical rule:

- the Synapse MCP server should run from the Synapse engine environment
- target repos keep their own separate environments for product code, tests, and builds
- do not rely on whatever `python3` happens to be first on PATH if you want predictable local integration behavior

## Environment

Supported environment variables:

- `SYNAPSE_ROOT`
- `SYNAPSE_GOVERNANCE_ROOT`
- `SYNAPSE_SESSION_ID` as a legacy fallback only

`SYNAPSE_ROOT` should point at the Synapse install root. If omitted, Synapse uses the Phase 0 install-root resolution contract.

## Working Directory

The server process `cwd` is expected to be the target repo workspace for local Codex/ChatGPT use.

That matters for:
- `bootstrap_session`
- `run_repo_onboarding`

Those tools may adopt or attach the current workspace repo into Synapse subject context when allowed.

## Connection Model

The server keeps connection-local convenience defaults for:
- workspace root
- subject
- engine root
- data root
- session id

Those defaults are not canonical truth. Canonical truth remains in the runtime:
- active run
- sidecar state
- semantic captures
- onboarding artifacts
- published project model/story/vision

## Tool Inventory

Phase 4 exposes exactly these tools:

1. `bootstrap_session`
2. `get_current_context`
3. `get_session_digest`
4. `transition_session_mode`
5. `record_activity`
6. `record_decision`
7. `record_disclosure`
8. `capture_chunk`
9. `run_repo_onboarding`
10. `submit_onboarding_draft`
11. `submit_onboarding_responses`
12. `confirm_onboarding`
13. `abandon_onboarding`
14. `list_formalization_candidates`
15. `formalize_candidate`
16. `accept_quest`
17. `refresh_continuity`
18. `finalize_run`

No shell, patch, file-edit, or arbitrary filesystem tools are exposed in Phase 4.

## Resource Inventory

Always listed:

- `synapse://current/context.json`
- `synapse://current/state.json`
- `synapse://current/manifold.json`
- `synapse://current/active-run.json`
- `synapse://current/rehydrate.md`
- `synapse://current/open-questions.md`
- `synapse://current/onboarding/status.json`

Conditionally listed when the underlying artifact exists:

- `synapse://current/onboarding/scan.json`
- `synapse://current/onboarding/brief.md`
- `synapse://current/onboarding/draft.json`
- `synapse://current/onboarding/questions.json`
- `synapse://current/project-model.json`
- `synapse://current/project-story.md`
- `synapse://current/vision.md`

Resources are read-only. They do not refresh continuity or mutate runtime state.

## Result Envelope

All tools return a structured envelope:

```json
{
  "ok": true,
  "status": "ok",
  "subject_context": {
    "subject": "Example",
    "engine_root": "/path/to/Example",
    "data_root": "/path/to/Example_Data",
    "session_id": "mcp-abc123"
  },
  "runtime_status": null,
  "data": {},
  "warnings": [],
  "error": null
}
```

Status values:
- `ok`
- `noop`
- `partial`
- `blocked`
- `failed`

Business-logic failures are returned inside the envelope. They are not surfaced as protocol crashes.

## Example MCP Config

Codex/ChatGPT-style local stdio config:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "/absolute/path/to/Synapse/.venv/bin/python",
      "args": [
        "/absolute/path/to/Synapse/runtime/synapse_mcp/server.py"
      ],
      "cwd": "/absolute/path/to/target-workspace",
      "env": {
        "SYNAPSE_ROOT": "/absolute/path/to/Synapse",
        "SYNAPSE_PYTHON": "/absolute/path/to/Synapse/.venv/bin/python"
      }
    }
  }
}
```

Optional governance override:

```json
{
  "SYNAPSE_ROOT": "/absolute/path/to/Synapse",
  "SYNAPSE_GOVERNANCE_ROOT": "/absolute/path/to/Synapse/governance"
}
```

## Expected Client Flow

Typical local flow:

1. call `bootstrap_session`
2. read `synapse://current/context.json` or call `get_current_context`
3. use mutation tools for continuity, semantic intake, onboarding, formalization, and quest acceptance
4. use `refresh_continuity` when you want an explicit rehydrate/pack sync
5. use `finalize_run` when ending the active run

The client should not shell out to `python runtime/synapse.py ...` for normal Synapse operations once MCP is configured.

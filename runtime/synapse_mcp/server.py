"""STDIO MCP server for Synapse."""

from __future__ import annotations

import sys
import os
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP

from synapse_mcp.connection_state import ConnectionState
from synapse_mcp.resources import register_resources
from synapse_mcp.tools import register_tools


SERVER_NAME = "Synapse"
SERVER_INSTRUCTIONS = (
    "Synapse MCP is a stdio transport over the existing runtime. "
    "Use bootstrap_session once, then operate through the fixed Phase 4 tool and resource surface."
)


def build_server() -> FastMCP:
    state = ConnectionState(workspace_root=os.getcwd())
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    register_tools(mcp, state)
    register_resources(mcp, state)
    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()

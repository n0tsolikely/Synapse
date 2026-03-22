"""Resource registration for the Synapse MCP server."""

from __future__ import annotations

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.helper_types import ReadResourceContents

from synapse_mcp.connection_state import ConnectionState
from synapse_mcp.runtime_bridge import map_runtime_exception, read_resource, resource_catalog


def register_resources(mcp: FastMCP, state: ConnectionState) -> None:
    server = mcp._mcp_server

    @server.list_resources()
    async def _list_resources() -> list[types.Resource]:
        catalog = resource_catalog(state=state)
        return [
            types.Resource(
                uri=item["uri"],
                name=item["uri"].split("synapse://current/", 1)[-1],
                title=item["uri"],
                description=f"Synapse resource for {item['uri']}",
                mimeType=item["mime_type"],
            )
            for item in catalog
        ]

    @server.list_resource_templates()
    async def _list_templates() -> list[types.ResourceTemplate]:
        return []

    @server.read_resource()
    async def _read_resource(uri):
        try:
            _, content, mime_type = read_resource(state=state, uri=str(uri))
        except Exception as exc:  # pragma: no cover - surfaced to client in tests
            raise map_runtime_exception(exc)
        return [ReadResourceContents(content=content, mime_type=mime_type)]

"""Public STARS MCP tool registration."""

from mcp.server import MCPServer

from .tools import academic, rooms

INSTRUCTIONS = " ".join((academic.INSTRUCTIONS, rooms.INSTRUCTIONS))


def register_tools(mcp: MCPServer) -> None:
    academic.register_tools(mcp)
    rooms.register_tools(mcp)

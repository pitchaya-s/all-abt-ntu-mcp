"""Public tool registration shared by local stdio and hosted HTTP servers."""

from mcp.server import MCPServer

from drntu import mcp_server as drntu
from faculty import mcp_server as faculty
from library import mcp_server as library
from mazemap import mcp_server as mazemap
from news import mcp_server as news
from omnibus import mcp_server as omnibus
from service import mcp_server as service
from stars import mcp_server as stars, room_tools


PUBLIC_MODULES = (stars, room_tools, mazemap, drntu, library, faculty, news, service, omnibus)
INSTRUCTIONS = " ".join(module.INSTRUCTIONS for module in PUBLIC_MODULES)


def register_tools(mcp: MCPServer) -> None:
    for module in PUBLIC_MODULES:
        module.register_tools(mcp)

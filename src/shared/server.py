"""Local stdio server with public tools and optional personal services."""

import asyncio

from mcp.server import MCPServer

from careeraxis import mcp_server as careeraxis_personal
from ntulearn import mcp_server
from library import personal_tools as library_personal
from onestop import mcp_server as onestop
from stars import personal_tools as stars_personal
from . import public_server


mcp = MCPServer(
    "all-abt-ntu-mcp",
    version="0.1.0-beta.2",
    instructions=(
        public_server.INSTRUCTIONS
        + " Optional personal tools use an opt-in native OS keyring entry; personal records are cached only in memory. "
        "Never request passwords through chat or tool arguments. Users manage credentials in their own terminal "
        "with all-abt-ntu auth save/status/delete. Deleting credentials blocks personal calls. "
        "When credential_error is present, credentials_configured is null: storage could not be read. "
        "Do not infer that credentials were never saved or tell users to replace them without checking access. "
        "Personal tables omit rows only when headers and records reconstruct them exactly. "
        "stars_save_stars_plan replaces a saved plan's entire course/index list and verifies it by reloading; "
        "it does not register, drop, or swap registered courses. "
        + mcp_server.INSTRUCTIONS + " " + library_personal.INSTRUCTIONS + " " + onestop.INSTRUCTIONS + " " + careeraxis_personal.INSTRUCTIONS
    ),
)


public_server.register_tools(mcp)
mcp_server.register_tools(mcp)
stars_personal.register_tools(mcp)
library_personal.register_tools(mcp)
onestop.register_tools(mcp)
careeraxis_personal.register_tools(mcp)


def main() -> None:
    from stars.wish.session import wish_session

    async def serve() -> None:
        try:
            await mcp.run_stdio_async()
        finally:
            await mcp_server.session.close()

    try:
        asyncio.run(serve())
    finally:
        try:
            wish_session.close()
        finally:
            try:
                library_personal.session.close()
            finally:
                try:
                    onestop.session.close()
                finally:
                    careeraxis_personal.client.session.close()

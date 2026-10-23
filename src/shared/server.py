"""Local stdio server with public tools and optional personal services."""

from mcp.server import MCPServer

from ntulearn import mcp_server
from library import personal_tools as library_personal
from stars import personal_tools as stars_personal
from . import public_server


mcp = MCPServer(
    "all-abt-ntu-mcp",
    version="0.1.0-beta.1",
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
        + mcp_server.INSTRUCTIONS + " " + library_personal.INSTRUCTIONS
    ),
)


public_server.register_tools(mcp)
mcp_server.register_tools(mcp)
stars_personal.register_tools(mcp)
library_personal.register_tools(mcp)


def main() -> None:
    from stars.wish.session import wish_session
    try:
        mcp.run(transport="stdio")
    finally:
        try:
            wish_session.close()
        finally:
            try:
                mcp_server.session.close()
            finally:
                library_personal.session.close()

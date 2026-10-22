"""The single MCP server and lifecycle shared by all NTU tool sets."""

from importlib import import_module

from mcp.server import MCPServer

from ntulearn_mcp import mcp_server


mcp = MCPServer(
    "all-abt-ntu-mcp",
    version="0.1.0",
    instructions=(
        "NTU timetable tools. Undergraduate tools use the official public Class Schedule; "
        "stars_search_courses finds undergraduate courses by partial code or title in a published term. "
        "graduate lookup uses GSLink/PGR and reports the currently published term as class groups, "
        "not indexes. Undergraduate exam lookup uses General Access and returns published exam times, "
        "not exam-seat assignments. Academic year is the first year printed by NTU (2026 means AY2026/27); "
        "undergraduate semester is 1, 2, or S. stars_get_course_indexes and stars_get_index include public "
        "STARS vacancy snapshots only when the published vacancy term matches the requested term. Unknown "
        "undergraduate timetable details are preserved and marked uncertain. Optional personal tools "
        "use NTU_USERNAME and NTU_PASSWORD; personal records are cached only in memory. "
        "Session identifiers are inherited from their enclosing course/index; common_sessions apply to "
        "every indexes_compared entry. Personal tables omit rows only when headers and records reconstruct "
        "them exactly. Unknown raw values and timetable details are preserved. "
        "stars_save_stars_plan replaces a saved plan's entire course/index list and verifies it by reloading; "
        "it does not register, drop, or swap registered courses. "
        + mcp_server.INSTRUCTIONS
    ),
)


mcp_server.register_tools(mcp)


def main() -> None:
    import_module("ntu_stars_mcp.mcp_server")
    from ntu_stars_mcp.wish.session import wish_session
    try:
        mcp.run(transport="stdio")
    finally:
        try:
            wish_session.close()
        finally:
            mcp_server.session.close()

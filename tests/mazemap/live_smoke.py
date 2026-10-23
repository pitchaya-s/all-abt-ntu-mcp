"""Opt-in public MazeMap requests through a real stdio MCP client."""

import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"])
    async with Client(params) as client:
        first_page_ids = set()
        for name, arguments in [
            ("mazemap_list_campuses", {}),
            ("mazemap_list_buildings", {"query": "North Spine"}),
            ("mazemap_search_places", {"query": "TR+7", "limit": 2}),
            ("mazemap_search_places", {"query": "TR+7", "limit": 2, "offset": 2}),
            ("mazemap_search_places", {"query": "TR+7", "campus_id": 2123, "limit": 2}),
            ("mazemap_get_place", {"poi_id": 1002362545}),
            ("mazemap_get_directions", {"from_poi_id": 1002362545, "to_poi_id": 1002362569}),
            ("mazemap_get_directions", {"from_poi_id": 1002362545, "to_poi_id": 1002362569, "constraint": "REQUIRE_ACCESSIBLE"}),
        ]:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, (name, result)
            data = result.structured_content
            assert data["retrieved_at"] and data["source_url"]
            if name == "mazemap_search_places":
                ids = {p["poi_id"] for p in data["places"]}
                assert ids
                if arguments.get("offset"):
                    assert not first_page_ids.intersection(ids), "Search pagination repeated a place"
                elif "campus_id" not in arguments:
                    first_page_ids = ids
            if name == "mazemap_get_directions":
                assert data["routes"][0]["distance_metres"] > 0
                assert data["routes"][0]["duration_seconds"] > 0
                assert data["routes"][0]["instructions"]
            print(name + ": OK")


if __name__ == "__main__":
    asyncio.run(main())

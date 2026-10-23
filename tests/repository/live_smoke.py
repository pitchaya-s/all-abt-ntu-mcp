"""Opt-in public repository lookups through stdio; no file bodies are downloaded."""

import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"])
    async with Client(params) as client:
        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, (name, result)
            data = result.structured_content
            assert data["source_url"] and data["retrieved_at"]
            print(name + ": OK", flush=True)
            return data

        first = await call("drntu_search", query="machine learning", page_size=2)
        assert first["items"] and all(v["entity_type"] == "Publication" for v in first["items"])
        second = await call("drntu_search", query="machine learning", page=first["pagination"]["next_page"], page_size=2)
        assert not {v["item_id"] for v in first["items"]}.intersection(v["item_id"] for v in second["items"])
        empty = await call("drntu_search", query="zzzz9999unfindablef42", page_size=1)
        assert empty["pagination"]["total_elements"] == 0 and empty["items"] == []
        detail = await call("drntu_get_item", item_id="d977355f-7b9d-4d60-ad60-6cec0cd01952")
        assert detail["metadata"].get("dc.description.abstract")
        for kind in ("communities", "collections"):
            browse = await call("drntu_browse", kind=kind, page_size=2)
            assert browse["containers"]
        await call("drntu_browse", kind="collections", community_id="012b8d30-2a60-4836-ad3b-1c79773dcfe9", page_size=2)
        await call("drntu_get_facets", query="machine learning")
        facets = await call("drntu_get_facets", facet="dateIssued", query="machine learning", page_size=2)
        suggested = facets["values"][0]["filter"]
        assert suggested and suggested["value"] != facets["values"][0]["label"]
        filtered = await call("drntu_search", query="machine learning", filters=[suggested], page_size=1)
        assert filtered["pagination"]["total_elements"] == facets["values"][0]["count"]
        bundles = await call("drntu_list_bundles", item_id="d977355f-7b9d-4d60-ad60-6cec0cd01952")
        original = next(b for b in bundles["bundles"] if b["name"] == "ORIGINAL")
        files = await call("drntu_list_files", bundle_id=original["bundle_id"])
        assert files["files"] and files["files"][0]["size_bytes"] > 0
        dataset = await call("drntu_get_dataset", persistent_id="doi:10.21979/N9/UD1IM9", limit=2)
        version = await call("drntu_get_dataset", persistent_id="doi:10.21979/N9/UD1IM9", version=dataset["version"], limit=2)
        assert dataset["version_state"] == "RELEASED" and version["title"] == dataset["title"]


if __name__ == "__main__":
    asyncio.run(main())

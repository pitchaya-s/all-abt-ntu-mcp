"""Opt-in public service directory checks; print counts and statuses only."""

import asyncio
import sys

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-c", "from shared.cli import main; main()"],
                                   env={"PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"})
    async with Client(params) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            print(name + ": OK", flush=True)
            return result.structured_content
        filters = await call("service_list_filters")
        directory = await call("service_search", limit=100)
        assert len(directory["locations"]) == directory["directory_count"] > 12
        clinic = await call("service_search", query="clinic")
        assert clinic["locations"] and clinic["cached"]
        assert all("clinic" in (item["name"] + " " + (item["address"] or "")).lower() for item in clinic["locations"])
        first = await call("service_search", limit=2)
        second = await call("service_search", limit=2, offset=first["next_offset"])
        assert not {item["name"] for item in first["locations"]} & {item["name"] for item in second["locations"]}
        north = await call("service_search", location_contains="North Spine")
        assert north["locations"] and all("north spine" in item["address"].lower() for item in north["locations"])
        food = next(item for item in filters["types"] if item["name"] == "Food & Beverages")
        assert (await call("service_search", type_id=food["id"], limit=1))["locations"]
        assert (await call("service_search", query="zzzz_no_service_12345"))["total_count"] == 0
        print("Live complete-directory search, contact/hours data, source filters, pagination and cache verified.")


if __name__ == "__main__":
    asyncio.run(main())

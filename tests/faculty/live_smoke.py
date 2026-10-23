"""Opt-in public directory checks; print counts/statuses without saving profiles."""

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
        first = await call("faculty_search")
        assert first["profiles"] and first["next_page"]
        second = await call("faculty_search", page=first["next_page"])
        assert not {p["profile_url"] for p in first["profiles"]} & {p["profile_url"] for p in second["profiles"]}
        named = await call("faculty_search", query=first["profiles"][0]["name"])
        assert first["profiles"][0]["profile_url"] in {p["profile_url"] for p in named["profiles"]}
        assert (await call("faculty_search", query="zzzz_no_faculty_12345"))["total_count"] == 0
        interests = await call("faculty_list_interests", query="Artificial and Augmented Intelligence")
        assert interests["interests"]
        interest = interests["interests"][0]
        filtered = await call("faculty_search", interest_id=interest["interest_id"])
        assert filtered["profiles"] and all(interest["name"] in p["interests"] for p in filtered["profiles"])
        assert (await call("faculty_search", interest_id=interest["interest_id"]))["cached"]
        print("Public faculty pagination, name search, empty results, interest filter and cache verified.")


if __name__ == "__main__":
    asyncio.run(main())

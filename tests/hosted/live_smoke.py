"""Opt-in HTTP checks against a local or deployed public MCP endpoint."""

import argparse
import asyncio

from jsonschema import Draft202012Validator
from mcp import Client


async def main(url):
    async with Client(url) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert len(tools) == 39 and all(tool.annotations.read_only_hint for tool in tools.values())
        for name, arguments in [
            ("faculty_list_interests", {"query": "intelligence", "limit": 1}),
            ("news_list_categories", {}),
        ]:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            print(name + ": OK", flush=True)
        print("Public HTTP MCP discovery and live reads passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Public MCP URL, including /mcp")
    asyncio.run(main(parser.parse_args().url))

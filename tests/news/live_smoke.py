"""Opt-in public news checks; no article bodies are printed or saved."""

import asyncio
from datetime import datetime
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
        first = await call("news_search", query="quantum")
        assert first["stories"] and first["next_page"]
        second = await call("news_search", query="quantum", page=first["next_page"])
        assert not {item["url"] for item in first["stories"]} & {item["url"] for item in second["stories"]}
        oldest = await call("news_search", sort="oldest")
        assert oldest["stories"]
        dates = [datetime.strptime(item["published_date"], "%d %b %Y") for item in oldest["stories"]]
        assert dates == sorted(dates)
        assert (await call("news_search", query="zzzz_no_story_12345"))["total_count"] == 0
        categories = await call("news_list_categories")
        category = next(item for item in categories["categories"] if item["name"] == "Research")
        assert (await call("news_search", category_id=category["id"]))["stories"]
        for story in [first["stories"][0], oldest["stories"][0]]:
            article = await call("news_get_article", url=story["url"], max_chars=100)
            assert article["title"] == story["title"] and article["total_characters"] > 100
            continuation = await call("news_get_article", url=story["url"], offset=article["next_offset"])
            assert continuation["text"] and continuation["cached"]
        assert (await call("news_search", query="quantum"))["cached"]
        print("Live news pagination, sorting, categories, article reading and caching verified.")


if __name__ == "__main__":
    asyncio.run(main())

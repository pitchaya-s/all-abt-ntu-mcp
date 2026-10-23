import os
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .fixtures import ARTICLE_URL, CATEGORY_ID


ROOT = Path(__file__).resolve().parents[2]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_calls_schemas_errors_and_resources(self):
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("protocol_server.py"))],
                                       env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])})
        async with Client(params) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("news_")}
            self.assertEqual(len(tools), 3)
            for name, args in [("news_search", {}), ("news_search", {"page": 2, "sort": "oldest"}),
                               ("news_search", {"category_id": CATEGORY_ID}), ("news_list_categories", {}),
                               ("news_get_article", {"url": ARTICLE_URL, "max_chars": 20})]:
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error, result)
                self.assertTrue(tools[name].annotations.read_only_hint)
                Draft202012Validator.check_schema(tools[name].output_schema)
                Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            for name, args in [("news_search", {"page": 0}), ("news_search", {"page": 3}),
                               ("news_search", {"sort": "random"}), ("news_search", {"query": "bad\nquery"}),
                               ("news_get_article", {"url": "https://example.org"}),
                               ("news_get_article", {"url": ARTICLE_URL, "max_chars": 50001})]:
                result = await client.call_tool(name, args)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
            self.assertEqual((await client.list_resources()).resources, [])

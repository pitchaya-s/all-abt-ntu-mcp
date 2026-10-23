import os
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .fixtures import CATEGORY_ID, TYPE_ID


ROOT = Path(__file__).resolve().parents[2]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_calls_schemas_errors_and_resources(self):
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("protocol_server.py"))],
                                       env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])})
        async with Client(params) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("service_")}
            self.assertEqual(len(tools), 2)
            for name, args in [("service_list_filters", {}), ("service_search", {"query": "clinic"}),
                               ("service_search", {"type_id": TYPE_ID}), ("service_search", {"category_id": CATEGORY_ID}),
                               ("service_search", {"location_contains": "south", "limit": 1})]:
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error, result)
                self.assertTrue(tools[name].annotations.read_only_hint)
                Draft202012Validator.check_schema(tools[name].output_schema)
                Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            for args in [{"limit": 101}, {"offset": -1}, {"query": "bad\nquery"}, {"type_id": "Food"},
                         {"type_id": "33333333-3333-4333-8333-333333333333"}]:
                result = await client.call_tool("service_search", args)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
            self.assertEqual((await client.list_resources()).resources, [])

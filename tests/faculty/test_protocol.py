import os
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .fixtures import INTEREST_ID


ROOT = Path(__file__).resolve().parents[2]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_schemas_calls_errors_and_resources(self):
        params = StdioServerParameters(
            command=sys.executable, args=[str(Path(__file__).with_name("protocol_server.py"))],
            env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
                 "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"},
        )
        async with Client(params) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools if tool.name.startswith("faculty_")}
            self.assertEqual(len(tools), 2)
            for name, args in [
                ("faculty_search", {}), ("faculty_search", {"query": "Example", "page": 2}),
                ("faculty_search", {"interest_id": INTEREST_ID}),
                ("faculty_search", {"query": "no matches"}),
                ("faculty_list_interests", {}), ("faculty_list_interests", {"query": "intelligence", "limit": 1}),
            ]:
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error, result)
                tool = tools[name]
                self.assertTrue(tool.annotations.read_only_hint)
                Draft202012Validator.check_schema(tool.output_schema)
                Draft202012Validator(tool.output_schema).validate(result.structured_content)
            for name, args in [
                ("faculty_search", {"page": 0}), ("faculty_search", {"page": True}),
                ("faculty_search", {"page": 3}), ("faculty_search", {"query": "bad\nquery"}),
                ("faculty_search", {"interest_id": "Artificial Intelligence"}),
                ("faculty_search", {"interest_id": "33333333-3333-4333-8333-333333333333"}),
                ("faculty_list_interests", {"limit": 101}), ("faculty_list_interests", {"offset": -1}),
            ]:
                result = await client.call_tool(name, args)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
            self.assertEqual((await client.list_resources()).resources, [])
            self.assertEqual((await client.list_resource_templates()).resource_templates, [])

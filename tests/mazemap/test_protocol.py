from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from mazemap import mcp_server
from shared.server import mcp


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("protocol_server.py")


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_provider_formats_are_sanitized(self):
        async with Client(mcp) as client:
            with patch.object(mcp_server.client, "get_place", side_effect=KeyError("raw-response-detail")):
                result = await client.call_tool("mazemap_get_place", {"poi_id": 1001})
                self.assertTrue(result.is_error)
                self.assertIn("unexpected data format", result.content[0].text)
                self.assertNotIn("raw-response-detail", result.content[0].text)
                self.assertIsNone(result.structured_content)
    async def test_stdio_tools_schemas_calls_errors_and_resources(self):
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                       env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
                                            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"})
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            maps = {tool.name: tool for tool in tools if tool.name.startswith("mazemap_")}
            self.assertEqual(len(maps), 5)
            calls = [("mazemap_list_campuses", {}), ("mazemap_list_buildings", {"query": "Example"}),
                     ("mazemap_search_places", {"query": "TR+7", "limit": 1}),
                     ("mazemap_get_place", {"poi_id": 1001}),
                     ("mazemap_get_directions", {"from_poi_id": 1001, "to_poi_id": 1002, "constraint": "REQUIRE_ACCESSIBLE"})]
            for name, arguments in calls:
                tool = maps[name]
                self.assertTrue(tool.annotations.read_only_hint)
                Draft202012Validator.check_schema(tool.output_schema)
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                Draft202012Validator(tool.output_schema).validate(result.structured_content)
            for name, arguments in [("mazemap_get_place", {"poi_id": "../escape"}),
                                     ("mazemap_get_place", {"poi_id": True}),
                                     ("mazemap_search_places", {"query": " "}),
                                     ("mazemap_search_places", {"query": "TR", "limit": 51}),
                                     ("mazemap_list_buildings", {"campus_id": 999}),
                                     ("mazemap_get_directions", {"from_poi_id": 1001, "to_poi_id": 1002, "constraint": "unknown"})]:
                result = await client.call_tool(name, arguments)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
            self.assertEqual((await client.list_resources()).resources, [])
            self.assertEqual((await client.list_resource_templates()).resource_templates, [])

import os
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters


ROOT = Path(__file__).resolve().parents[2]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_library_stdio_tools_schemas_calls_and_errors(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("protocol_server.py"))],
            env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])},
        )
        async with Client(params) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("library_")}
            self.assertEqual(len(tools), 6)
            for name, arguments in [
                ("library_search", {"query": "algorithms"}),
                ("library_get_record", {"record_id": "almaExample001"}),
                ("library_get_record", {"record_id": "cdi_example_article", "context": "PC"}),
                ("library_get_availability", {"record_id": "almaExample001"}),
                ("library_list_facilities", {}),
                (
                    "library_get_map_availability",
                    {"map_slug": "abcdef123456", "date": "2026-10-24", "time": "14:00"},
                ),
                ("library_get_facility_schedule", {"date": "2026-10-24", "space_id": 100}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                self.assertTrue(tools[name].annotations.read_only_hint)
                Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
            for name, arguments in [
                ("library_search", {"query": " "}),
                ("library_search", {"query": "x", "limit": 51}),
                ("library_get_record", {"record_id": "../escape"}),
                ("library_get_record", {"record_id": "missing"}),
                (
                    "library_get_map_availability",
                    {"map_slug": "abcdef123456", "date": "2026-02-30", "time": "14:00"},
                ),
                ("library_get_facility_schedule", {"date": "2026-10-24", "space_id": 100, "group_id": 20}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)

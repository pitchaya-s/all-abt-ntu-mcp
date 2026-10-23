import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from drntu import mcp_server
from shared.server import mcp
from .fixtures import BUNDLE_ID, CONTAINER_ID, DOI, ITEM_ID


ROOT = Path(__file__).resolve().parents[2]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_output_schemas_calls_and_errors(self):
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("protocol_server.py"))],
                                       env={"PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
                                            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"})
        async with Client(params) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("drntu_")}
            self.assertEqual(len(tools), 7)
            for name, arguments in [
                ("drntu_search", {"query": "learning", "filters": [{"field": "dateIssued", "value": "[2020 TO 2026]"}]}),
                ("drntu_get_item", {"item_id": ITEM_ID}), ("drntu_browse", {}),
                ("drntu_browse", {"kind": "collections", "community_id": CONTAINER_ID}),
                ("drntu_get_facets", {}), ("drntu_get_facets", {"facet": "dateIssued"}),
                ("drntu_list_bundles", {"item_id": ITEM_ID}), ("drntu_list_files", {"bundle_id": BUNDLE_ID}),
                ("drntu_get_dataset", {"persistent_id": DOI}),
                ("drntu_get_dataset", {"persistent_id": DOI, "version": "1.0"}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                tool = tools[name]
                self.assertTrue(tool.annotations.read_only_hint)
                Draft202012Validator.check_schema(tool.output_schema)
                Draft202012Validator(tool.output_schema).validate(result.structured_content)
            for name, arguments in [
                ("drntu_search", {"query": " "}), ("drntu_search", {"query": "x", "page_size": 51}),
                ("drntu_get_item", {"item_id": "../../etc/passwd"}),
                ("drntu_get_facets", {"facet": "../authn"}),
                ("drntu_get_dataset", {"persistent_id": DOI, "version": ":draft"}),
                ("drntu_get_dataset", {"persistent_id": "https://example.org/"}),
                ("drntu_search", {"query": "x", "filters": [{"field": "../x", "value": "y"}]}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)
            self.assertEqual((await client.list_resources()).resources, [])
            self.assertEqual((await client.list_resource_templates()).resource_templates, [])

    async def test_unexpected_provider_metadata_is_sanitized(self):
        with patch.object(mcp_server.client, "get", return_value=({"type": "item", "untrusted": "provider detail"}, {})):
            async with Client(mcp) as client:
                result = await client.call_tool("drntu_get_item", {"item_id": ITEM_ID})
                self.assertTrue(result.is_error)
                self.assertIn("unexpected data format", result.content[0].text)
                self.assertNotIn("provider detail", result.content[0].text)

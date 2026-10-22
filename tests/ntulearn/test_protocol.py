import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ntulearn_mcp import tools
from ntu_stars_mcp.mcp_server import mcp
from ntulearn_mcp.models import LearnError
from .fixtures import CONTENT, COURSE, SECRET


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("protocol_server.py")


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_schemas_calls_and_errors(self):
        with tempfile.TemporaryDirectory() as cwd:
            params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=cwd,
                                           env={"PYTHONPATH": str(ROOT / "src"), "NTU_USERNAME": "", "NTU_PASSWORD": ""})
            async with Client(params) as client:
                listing = await client.list_tools()
                self.assertEqual(len(listing.tools), 20)
                by_name = {tool.name: tool for tool in listing.tools}
                self.assertNotIn("register_courses", by_name)
                for tool in listing.tools:
                    Draft202012Validator.check_schema(tool.output_schema)
                    self.assertEqual(tool.annotations.read_only_hint, tool.name not in {"download_file", "save_stars_plan"})
                for name, arguments in [
                    ("ntulearn_auth_status", {}), ("list_courses", {"limit": 1}),
                    ("get_course_contents", {"course_id": COURSE}),
                    ("get_course_contents", {"course_id": COURSE, "parent_id": CONTENT}),
                    ("get_announcements", {"course_id": COURSE}),
                    ("get_calendar", {"since": "2026-10-22T00:00:00Z", "until": "2026-11-01T00:00:00Z"}),
                    ("get_gradebook", {"course_id": COURSE}),
                    ("get_content_attachments", {"course_id": COURSE, "content_id": "_202_1"}),
                ]:
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, name)
                    Draft202012Validator(by_name[name].output_schema).validate(result.structured_content)
                    self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                    self.assertNotIn(SECRET, json.dumps(result.structured_content))
                for name, arguments in [("list_courses", {"limit": 0}), ("get_course_contents", {"course_id": "../../escape"}),
                                        ("get_calendar", {"since": "2026-01-01T00:00:00", "until": "2026-01-02T00:00:00"}),
                                        ("unknown_tool", {})]:
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error)
                    self.assertIsNone(result.structured_content)
                self.assertEqual((await client.list_resources()).resources, [])
                self.assertEqual((await client.list_resource_templates()).resource_templates, [])

    async def test_backend_errors_are_sanitized_in_tool_results(self):
        async with Client(mcp) as client:
            for error in [RuntimeError(SECRET), LearnError("NTULearn denied access (HTTP 403).")]:
                with patch.object(tools.client, "list_courses", side_effect=error):
                    result = await client.call_tool("list_courses", {})
                    self.assertTrue(result.is_error)
                    self.assertNotIn(SECRET, result.content[0].text)

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ntulearn import mcp_server
from shared.server import mcp
from ntulearn.models import LearnError
from .fixtures import CONTENT, COURSE, SECRET


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("protocol_server.py")


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_schemas_calls_and_errors(self):
        with tempfile.TemporaryDirectory() as cwd:
            params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=cwd,
                                           env={"PYTHONPATH": str(ROOT / "src"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"})
            async with Client(params) as client:
                listing = await client.list_tools()
                self.assertEqual(len([t for t in listing.tools if t.name.startswith("ntulearn_")]), 20)
                by_name = {tool.name: tool for tool in listing.tools}
                self.assertNotIn("register_courses", by_name)
                from onestop.workflow_tools import WRITE_TOOLS
                writes = {"ntulearn_download_file", "ntulearn_download_course", "stars_save_stars_plan"}
                writes.update("onestop_" + name for name in WRITE_TOOLS)
                for tool in listing.tools:
                    Draft202012Validator.check_schema(tool.output_schema)
                    self.assertEqual(tool.annotations.read_only_hint, tool.name not in writes)
                for name, arguments in [
                    ("ntulearn_auth_status", {}), ("ntulearn_list_courses", {"limit": 1}),
                    ("ntulearn_get_course_contents", {"course_id": COURSE}),
                    ("ntulearn_get_course_contents", {"course_id": COURSE, "parent_id": CONTENT}),
                    ("ntulearn_get_announcements", {"course_id": COURSE}),
                    ("ntulearn_get_calendar", {"since": "2026-10-22T00:00:00Z", "until": "2026-11-01T00:00:00Z"}),
                    ("ntulearn_get_gradebook", {"course_id": COURSE}),
                    ("ntulearn_get_content_attachments", {"course_id": COURSE, "content_id": "_202_1"}),
                    ('ntulearn_get_upcoming', {'since': '2026-10-22T00:00:00Z', 'until': '2026-11-01T00:00:00Z'}),
                    ('ntulearn_read_file_content', {'course_id': COURSE, 'content_id': '_202_1', 'attachment_id': '_500_1'}),
                    ('ntulearn_list_messages', {}),
                    ('ntulearn_read_message', {'message_id': '_801_1', 'course_id': COURSE, 'conversation_id': '_800_1'}),
                    ('ntulearn_list_course_users', {'course_id': COURSE}),
                    ('ntulearn_list_course_groups', {'course_id': COURSE}),
                    ('ntulearn_get_group_members', {'course_id': COURSE, 'group_id': '_600_1'}),
                    ('ntulearn_search_course_content', {'course_id': COURSE, 'query': 'slides'}),
                    ('ntulearn_search_all_courses', {'query': 'slides'}),
                    ('ntulearn_get_content_tree', {'course_id': COURSE}),
                    ('ntulearn_download_file', {'course_id': COURSE, 'content_id': '_202_1', 'attachment_id': '_500_1', 'destination': str(Path(cwd) / 'single.txt')}),
                    ('ntulearn_download_course', {'course_id': COURSE, 'destination': str(Path(cwd) / 'course')}),
                    ('ntulearn_whats_new', {'course_ids': [COURSE]}),
                ]:
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, name)
                    Draft202012Validator(by_name[name].output_schema).validate(result.structured_content)
                    self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                    self.assertNotIn(SECRET, json.dumps(result.structured_content))
                for name, arguments in [("ntulearn_list_courses", {"limit": 0}), ("ntulearn_get_course_contents", {"course_id": "../../escape"}),
                                        ("ntulearn_get_calendar", {"since": "2026-01-01T00:00:00", "until": "2026-01-02T00:00:00"}),
                                        ('ntulearn_search_course_content', {'course_id': COURSE, 'query': ' '}),
                                        ('ntulearn_get_content_tree', {'course_id': COURSE, 'max_depth': 11}),
                                        ('ntulearn_list_messages', {'folder': 'trash'}),
                                        ('ntulearn_read_message', {'message_id': '_801_1', 'course_id': COURSE}),
                                        ('ntulearn_read_file_content', {'course_id': COURSE, 'content_id': '_202_1', 'attachment_id': '_missing_1'}),
                                        ("unknown_tool", {})]:
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error)
                    self.assertIsNone(result.structured_content)
                self.assertEqual((await client.list_resources()).resources, [])
                self.assertEqual((await client.list_resource_templates()).resource_templates, [])

    async def test_backend_errors_are_sanitized_in_tool_results(self):
        async with Client(mcp) as client:
            for error in [RuntimeError(SECRET), LearnError("NTULearn denied access (HTTP 403).")]:
                with patch.object(mcp_server.client, "list_courses", side_effect=error):
                    result = await client.call_tool("ntulearn_list_courses", {})
                    self.assertTrue(result.is_error)
                    self.assertNotIn(SECRET, result.content[0].text)

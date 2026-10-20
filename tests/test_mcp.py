from pathlib import Path
import unittest
from unittest.mock import patch

from mcp import Client

from ntu_course_index.mcp_server import mcp
from ntu_course_index.parser import parse_course_page


FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-2026-1.html"
HTML = FIXTURE.read_bytes().decode("windows-1252")
COURSE = parse_course_page(HTML, "SC2001").with_request_metadata(
    academic_year=2026,
    semester="1",
    retrieved_at="2026-10-21T00:00:00+00:00",
    source_url="https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE.main_display1",
)


class MCPClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_discover_and_call_over_mcp_client(self) -> None:
        with patch("ntu_course_index.mcp_server.fetch_course", return_value=COURSE) as fetch:
            async with Client(mcp) as client:
                listing = await client.list_tools()
                names = {tool.name for tool in listing.tools}
                self.assertEqual(
                    names,
                    {
                        "get_course",
                        "get_course_indexes",
                        "get_index_schedule",
                        "compare_indexes",
                        "find_matching_indexes",
                    },
                )
                result = await client.call_tool(
                    "get_index_schedule",
                    {"course_code": "SC2001", "index": "10143", "academic_year": 2026, "semester": 1},
                )
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["index"], "10143")
                self.assertEqual(len(result.structured_content["sessions"]), 4)

                course_result = await client.call_tool(
                    "get_course",
                    {"course_code": "SC2001", "academic_year": 2026, "semester": 1},
                )
                self.assertFalse(course_result.is_error)
                self.assertEqual(course_result.structured_content["index_count"], 36)

                comparison = await client.call_tool(
                    "compare_indexes",
                    {
                        "course_code": "SC2001",
                        "indexes": ["10143", "10144"],
                        "academic_year": 2026,
                        "semester": 1,
                        "against_sessions": [
                            {"day": "MON", "start_time": "12:30", "end_time": "13:20", "teaching_weeks": [2]}
                        ],
                    },
                )
                self.assertFalse(comparison.is_error)
                self.assertEqual(len(comparison.structured_content["common_sessions"]), 2)
                self.assertGreater(len(comparison.structured_content["clash_check"]["clashes_by_index"]["10143"]), 0)

                filtered = await client.call_tool(
                    "find_matching_indexes",
                    {
                        "course_code": "SC2001",
                        "academic_year": 2026,
                        "semester": 1,
                        "constraints": {"avoid_days": ["FRI"]},
                    },
                )
                self.assertFalse(filtered.is_error)
                self.assertGreater(filtered.structured_content["match_count"], 0)

                fetch.reset_mock()
                invalid = await client.call_tool(
                    "compare_indexes",
                    {"course_code": "SC2001", "indexes": ["10143"], "academic_year": 2026, "semester": 1},
                )
                self.assertTrue(invalid.is_error)
                fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

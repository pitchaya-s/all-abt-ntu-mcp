from pathlib import Path
import unittest
from unittest.mock import patch

from mcp import Client

from ntu_course_index.parser.exam import parse_undergraduate_exam_schedule
from ntu_course_index.mcp_server import mcp
from ntu_course_index.parser import parse_course_description, parse_course_page, parse_graduate_course_page


FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-2026-1.html"
HTML = FIXTURE.read_bytes().decode("windows-1252")
COURSE = parse_course_page(HTML, "SC2001").with_request_metadata(
    academic_year=2026,
    semester="1",
    retrieved_at="2026-10-21T00:00:00+00:00",
    source_url="https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1",
).with_course_description(
    description=parse_course_description(
        (Path(__file__).parent / "fixtures" / "sc2001-content-2026-1.html").read_bytes().decode("windows-1252"),
        "SC2001",
    ),
    status="available",
    source_url="https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1",
)
GRADUATE_HTML = (Path(__file__).parent / "fixtures" / "ee6102-graduate-2026-1.html").read_bytes().decode("windows-1252")
GRADUATE_COURSE = {
    **parse_graduate_course_page(GRADUATE_HTML, "EE6102"),
    "source_url": "https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable?bOption=Next&choiceSubj=EE6102",
}
EXAM_COURSE = parse_undergraduate_exam_schedule(
    (Path(__file__).parent / "fixtures" / "undergrad-exam-sc2001-2026-1.html").read_bytes().decode("windows-1252"),
    "SC2001",
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
                        "get_graduate_course_schedule",
                        "get_undergraduate_exam_schedule",
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
                self.assertEqual(course_result.structured_content["course_description_status"], "available")
                self.assertIn("algorithm design and analysis", course_result.structured_content["course_description"])

                with patch(
                    "ntu_course_index.mcp_server.fetch_graduate_course_schedule",
                    return_value=GRADUATE_COURSE,
                ):
                    graduate_result = await client.call_tool(
                        "get_graduate_course_schedule", {"course_code": "EE6102"}
                    )
                self.assertFalse(graduate_result.is_error)
                self.assertEqual(graduate_result.structured_content["academic_year"], 2026)
                self.assertEqual(
                    [group["class_group"] for group in graduate_result.structured_content["class_groups"]],
                    ["A", "B"],
                )

                with patch(
                    "ntu_course_index.mcp_server.fetch_undergraduate_exam_schedule",
                    return_value=EXAM_COURSE,
                ):
                    exam_result = await client.call_tool(
                        "get_undergraduate_exam_schedule", {"course_code": "SC2001"}
                    )
                self.assertFalse(exam_result.is_error)
                self.assertEqual(exam_result.structured_content["exams"][0]["date"], "2026-11-23")
                self.assertEqual(exam_result.structured_content["exams"][0]["start_time"], "13:00")

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

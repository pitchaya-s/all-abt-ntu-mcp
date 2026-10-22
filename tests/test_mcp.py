import unittest
from unittest.mock import patch

from mcp import Client

from ntu_stars_mcp.mcp_server import mcp
from mcp_fixtures import COURSE, EXAM_COURSE, GRADUATE_COURSE


class MCPClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_discover_and_call_over_mcp_client(self) -> None:
        with (
            patch("ntu_stars_mcp.mcp_server.fetch_course", return_value=COURSE) as fetch,
            patch("ntu_stars_mcp.mcp_server.fetch_course_vacancies", return_value={
                "status": "term_mismatch", "academic_year": 2026, "semester": "2",
                "retrieved_at": "2026-10-21T00:00:00+00:00", "indexes": {},
            }),
        ):
            async with Client(mcp) as client:
                listing = await client.list_tools()
                names = {tool.name for tool in listing.tools}
                self.assertEqual(
                    names,
                    {
                        "search_courses",
                        "get_course_metadata",
                        "get_course_indexes",
                        "get_graduate_course_schedule",
                        "get_undergraduate_exam_schedule",
                        "ntu_auth_status",
                        "get_stars_planner",
                        "save_stars_plan",
                        "get_degree_audit",
                        "get_index",
                        "compare_indexes",
                        "find_matching_indexes",
                    },
                )
                result = await client.call_tool(
                    "get_index",
                    {"course_code": "SC2001", "index": "10143", "academic_year": 2026, "semester": 1},
                )
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["course_code"], "SC2001")
                self.assertEqual(result.structured_content["index"], "10143")
                self.assertNotIn("course_name", result.structured_content)
                self.assertEqual(len(result.structured_content["sessions"]), 4)
                self.assertEqual(result.structured_content["vacancy_status"], "term_mismatch")
                self.assertIsNone(result.structured_content["vacancies_available"])

                metadata_result = await client.call_tool(
                    "get_course_metadata",
                    {"course_code": "SC2001", "academic_year": 2026, "semester": 1},
                )
                self.assertFalse(metadata_result.is_error)
                self.assertEqual(metadata_result.structured_content["course_description_status"], "available")
                self.assertIn("algorithm design and analysis", metadata_result.structured_content["course_description"])
                self.assertNotIn("indexes", metadata_result.structured_content)

                indexes_result = await client.call_tool(
                    "get_course_indexes",
                    {"course_code": "SC2001", "academic_year": 2026, "semester": 1},
                )
                self.assertFalse(indexes_result.is_error)
                self.assertEqual(indexes_result.structured_content["index_count"], 36)
                self.assertEqual(indexes_result.structured_content["indexes"][0]["index"], "10143")
                self.assertNotIn("course_description", indexes_result.structured_content)
                self.assertIsNone(indexes_result.structured_content["indexes"][0]["waitlist_length"])

                with patch(
                    "ntu_stars_mcp.mcp_server.fetch_graduate_course_schedule",
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
                    "ntu_stars_mcp.mcp_server.fetch_undergraduate_exam_schedule",
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
                            {"day": "TUE", "start_time": "16:30", "end_time": "17:20", "teaching_weeks": [2]}
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

                status = await client.call_tool("ntu_auth_status", {})
                self.assertFalse(status.is_error)
                self.assertIn("credentials_configured", status.structured_content)

                with patch(
                    "ntu_stars_mcp.mcp_server.fetch_stars_planner",
                    return_value={
                        "service": "stars_planner",
                        "page_title": "STARS Planner",
                        "academic_year": 2026,
                        "semester": 2,
                        "registration_notice": None,
                        "registered_courses": [],
                        "registered_courses_status": "not_present",
                        "planner_tables": [],
                        "timetable_tables": [],
                        "timetable_status": "not_present",
                        "saved_plans": [],
                        "source_url": "https://wish.wis.ntu.edu.sg/pls/webexe/aus_stars_planner.main",
                        "retrieved_at": "2026-10-21T00:00:00+00:00",
                        "from_cache": False,
                        "cache_age_seconds": 0,
                    },
                ):
                    planner = await client.call_tool("get_stars_planner", {})
                self.assertFalse(planner.is_error)
                self.assertEqual(planner.structured_content["service"], "stars_planner")

                with patch(
                    "ntu_stars_mcp.mcp_server.fetch_degree_audit",
                    return_value={
                        "service": "degree_audit",
                        "page_title": "Degree Audit",
                        "requirements": [],
                        "requirements_status": "empty",
                        "examination_results": [],
                        "examination_results_status": "not_present",
                        "courses_registered": [],
                        "courses_registered_status": "not_present",
                        "source_url": "https://wish.wis.ntu.edu.sg/pls/webexe/DARS_RESULT_RO.main_display",
                        "retrieved_at": "2026-10-21T00:00:00+00:00",
                        "from_cache": False,
                        "cache_age_seconds": 0,
                    },
                ):
                    audit = await client.call_tool("get_degree_audit", {})
                self.assertFalse(audit.is_error)
                self.assertEqual(audit.structured_content["service"], "degree_audit")

                fetch.reset_mock()
                invalid = await client.call_tool(
                    "compare_indexes",
                    {"course_code": "SC2001", "indexes": ["10143"], "academic_year": 2026, "semester": 1},
                )
                self.assertTrue(invalid.is_error)
                fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

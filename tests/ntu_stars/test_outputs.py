from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from mcp import Client

from .mcp_fixtures import COURSE, EXAM_COURSE, GRADUATE_COURSE
from ntu_stars_mcp import compact
from ntu_stars_mcp.mcp_server import get_course_indexes, get_index, mcp
from ntu_stars_mcp.ntu_client import NTURequestError
from ntu_stars_mcp.parser import parse_course_page


class CompactOutputTests(unittest.TestCase):
    def test_all_timetable_information_can_be_reconstructed(self):
        fixtures = Path(__file__).parent / "fixtures"
        for code in ("ZZ0001", "ZY0001", "ZX0001"):
            course = parse_course_page((fixtures / f"{code.lower()}-2026-1.html").read_bytes().decode("windows-1252"), code)
            course = replace(course, academic_year=2026, semester="1")
            with patch("ntu_stars_mcp.mcp_server.fetch_course", return_value=course), patch(
                "ntu_stars_mcp.mcp_server.fetch_course_vacancies", side_effect=NTURequestError("offline")
            ):
                result = get_course_indexes(code, 2026, 1)
                for index in result["indexes"]:
                    individual = get_index(code, index["index"], 2026, 1)
                    self.assertEqual(individual["sessions"], index["sessions"])
                    for raw, reduced in zip(course.indexes[index["index"]], index["sessions"]):
                        self.assertEqual({"course_code": code, "index": index["index"], "raw_day": None, "raw_time": None, **reduced}, raw.to_dict())

    def test_unknown_values_remain_explicit_and_course_index_result_is_smaller(self):
        raw = COURSE.indexes["00001"][0].to_dict()
        unknown = {**raw, "day": None, "start_time": None, "end_time": None, "raw_day": "ARRANGED", "raw_time": "TBA", "remarks": "Consult school"}
        reduced = compact.session_fields(unknown)
        self.assertEqual(reduced["raw_day"], "ARRANGED")
        self.assertEqual(reduced["raw_time"], "TBA")
        self.assertIsNone(reduced["day"])
        original = [session.to_dict() for sessions in COURSE.indexes.values() for session in sessions]
        reduced = [compact.session_fields(session) for session in original]
        self.assertLess(len(json.dumps(reduced)), len(json.dumps(original)))
        self.assertNotIn("course_code", reduced[0])
        self.assertNotIn("raw_time", reduced[0])

    def test_graduate_raw_schedule_stays_when_parsing_is_incomplete(self):
        before = deepcopy(GRADUATE_COURSE)
        result = compact.graduate_fields(GRADUATE_COURSE)
        self.assertNotIn("schedule_text", result["class_groups"][0])
        unusual = deepcopy(GRADUATE_COURSE)
        unusual["class_groups"][0]["sessions"][0]["start_time"] = None
        self.assertIn("schedule_text", compact.graduate_fields(unusual)["class_groups"][0])
        self.assertEqual(GRADUATE_COURSE, before)

    def test_exam_original_duration_stays_if_unknown_or_rounded(self):
        before = deepcopy(EXAM_COURSE)
        self.assertNotIn("duration_text", compact.exam_fields(EXAM_COURSE)["exams"][0])
        for text, minutes in (("By arrangement", None), ("1.333 hr", 80)):
            example = {**EXAM_COURSE, "exams": [{**EXAM_COURSE["exams"][0], "duration_text": text, "duration_minutes": minutes}]}
            self.assertEqual(compact.exam_fields(example)["exams"][0]["duration_text"], text)
        self.assertEqual(EXAM_COURSE, before)

    def test_only_losslessly_reconstructible_table_rows_are_removed(self):
        table = {"section": "Requirements", "headers": ["Type", "AU"], "rows": [["Core", "3"]], "records": [{"Type": "Core", "AU": "3"}]}
        result = compact.table_fields(table)
        self.assertNotIn("rows", result)
        self.assertEqual([[record[h] for h in result["headers"]] for record in result["records"]], table["rows"])
        for ambiguous in (
            {**table, "headers": []}, {**table, "headers": ["Type", "Type"]},
            {**table, "headers": ["Type", ""]}, {**table, "rows": [["Core", "3", "extra"]]},
            {**table, "records": [{"Type": "Core", "AU": "4"}]},
        ):
            self.assertIn("rows", compact.table_fields(ambiguous))
        self.assertIn("rows", table)

    def test_saved_plan_keeps_course_identity_and_conflicting_indexes(self):
        plan = {"courses": [{"course_code": "ZZ0001", "index": "00001"}],
                "sessions": [{"course_code": "ZZ0001", "index": "00001", "raw_time": None, "teaching_weeks": [1, 3]}]}
        result = compact.saved_plan_fields(plan)
        self.assertNotIn("index", result["sessions"][0])
        self.assertEqual(result["sessions"][0]["course_code"], "ZZ0001")
        conflicting = {**plan, "sessions": [{**plan["sessions"][0], "index": "00002", "raw_time": "TBA"}]}
        self.assertEqual(compact.saved_plan_fields(conflicting)["sessions"][0]["index"], "00002")
        self.assertEqual(compact.saved_plan_fields(conflicting)["sessions"][0]["raw_time"], "TBA")


class OutputSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_compact_optional_keys_stay_absent_and_common_sessions_inherit_indexes(self):
        with patch("ntu_stars_mcp.mcp_server.fetch_course", return_value=COURSE), patch("ntu_stars_mcp.mcp_server.fetch_course_vacancies", return_value={
            "status": "closed", "retrieved_at": None, "indexes": {},
        }):
            async with Client(mcp) as client:
                args = {"course_code": "ZZ0001", "academic_year": 2026, "semester": 1}
                result = await client.call_tool("stars_compare_indexes", {**args, "indexes": ["00001", "00002"]})
                self.assertFalse(result.is_error)
                data = result.structured_content
                self.assertEqual(len(data["common_sessions"]), 2)
                self.assertNotIn("shared_by", data["common_sessions"][0])
                self.assertNotIn("course_description", data)
                result = await client.call_tool("stars_find_matching_indexes", args)
                self.assertEqual(result.structured_content["constraints"], {})
                self.assertNotIn("raw_time", result.structured_content["matches"][0]["sessions"][0])

    async def test_malformed_tool_results_fail_schema_validation(self):
        broken = {**GRADUATE_COURSE, "academic_year": "not-a-year"}
        with patch("ntu_stars_mcp.mcp_server.fetch_graduate_course_schedule", return_value=broken):
            async with Client(mcp) as client:
                with self.assertLogs("mcp.server", level="ERROR"):
                    result = await client.call_tool("stars_get_graduate_course_schedule", {"course_code": "EE6102"})
                self.assertTrue(result.is_error)
                self.assertIsNone(result.structured_content)

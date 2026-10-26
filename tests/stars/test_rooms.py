import unittest
from threading import Barrier
from unittest.mock import patch

from mcp import Client
from pydantic import ValidationError

from shared.server import mcp
from stars.client import teaching
from stars.domain.models import Course, Session
from stars.domain.rooms import (
    available_rooms,
    build_catalogue,
    normalize_venue,
    room_schedule,
    room_type,
)
from stars.parser import NTUPageError, parse_course_page
from stars.parser.schedule import parse_teaching_schedule
from stars.parser.search import parse_course_search
from stars.room_schemas import RoomFilters, RoomWindow

from .room_fixtures import FULL_TIME, PART_TIME, block, page, snapshot


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = build_catalogue(snapshot().courses)
        self.window = RoomWindow(day="MON", start_time="14:00", end_time="15:00", teaching_weeks=[2])

    def test_full_time_and_part_time_indexes_block_rooms_and_unknowns_are_excluded(self):
        result = available_rooms(self.catalogue, self.window, RoomFilters(), 100, 0)
        self.assertEqual([r.venue for r in result["rooms"]], ["LT1"])
        self.assertEqual(result["excluded_busy_count"], 3)
        self.assertEqual(result["excluded_uncertain_count"], 2)
        self.assertEqual(self.catalogue.coverage.course_count, 4)
        self.assertEqual(self.catalogue.coverage.index_count, 5)
        self.assertEqual(self.catalogue.coverage.observed_room_count, 6)
        self.assertGreater(self.catalogue.coverage.unplaced_lesson_count, 0)
        self.assertNotIn("ONLINE", self.catalogue.rooms)

    def test_week_sets_and_all_term_semantics(self):
        w = self.window.model_copy(update={"start_time": "10:00", "end_time": "11:00"})
        second = available_rooms(self.catalogue, w, RoomFilters(room_types=["lecture_theatre"]), 100, 0)
        self.assertEqual(second["match_count"], 1)
        for weeks in ([1], [1, 2], None):
            broad = w.model_copy(update={"teaching_weeks": weeks})
            self.assertEqual(
                available_rooms(self.catalogue, broad, RoomFilters(room_types=["lecture_theatre"]), 100, 0)[
                    "match_count"
                ],
                0,
            )

    def test_shared_lectures_group_every_index_and_aliases_share_occupancy(self):
        result = room_schedule(self.catalogue, '"LT1"', None, None, None, None, 100, 0)
        self.assertEqual(result["session_count"], 1)
        self.assertEqual(result["sessions"][0].indexes, ["00001", "00002"])
        self.assertEqual(normalize_venue("//LHN-TR-01"), "LHN-TR+1")
        alias = room_schedule(self.catalogue, "LHN-TR-01", None, None, None, None, 100, 0)
        self.assertEqual(alias["session_count"], 2)
        self.assertEqual(alias["room"].room_type, "tutorial_room")
        self.assertEqual(alias["room"].aliases, ["LHN-TR+01", "LHN-TR-1"])

    def test_candidate_lesson_filter_never_removes_other_teaching_conflicts(self):
        result = available_rooms(
            self.catalogue,
            self.window,
            RoomFilters(venue_prefixes=["TR+"], used_for_lesson_types=["TUT"]),
            100,
            0,
        )
        self.assertEqual(result["match_count"], 0)
        self.assertGreater(result["excluded_busy_count"], 0)
        self.assertIsNone(room_type("SEE-HY3010"))
        self.assertIsNone(room_type("11-AUG"))
        self.assertIsNone(room_type("LAB"))
        self.assertIsNone(room_type("TR+1/TR+2"))

    def test_buffers_back_to_back_boundaries_and_pagination(self):
        w = RoomWindow(day="MON", start_time="13:00", end_time="14:00", teaching_weeks=[2])
        filters = RoomFilters(venue_contains="TR+1")
        result = available_rooms(self.catalogue, w, filters, 10, 0)
        self.assertEqual({r.venue for r in result["rooms"]}, {"LHN-TR+1", "TR+1"})
        self.assertTrue(all(r.free_until == "14:00" for r in result["rooms"]))
        self.assertEqual(
            available_rooms(self.catalogue, w.model_copy(update={"buffer_minutes": 1}), filters, 10, 0)[
                "match_count"
            ],
            0,
        )
        first = available_rooms(self.catalogue, w, filters, 1, 0)
        second = available_rooms(self.catalogue, w, filters, 1, 1)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertNotEqual(first["rooms"][0].venue, second["rooms"][0].venue)
        self.assertEqual(
            available_rooms(
                self.catalogue, w, RoomFilters(exclude_venues=["TR+1"], venue_prefixes=["TR+1"]), 10, 0
            )["match_count"],
            0,
        )

    def test_compound_venues_block_observed_component_rooms(self):
        extra = Session("ZQ0001", "00006", "LEC", "A", "TUE", "14:00", "15:00", "TR+1 / TR+2", (2,), None)
        course = Course("ZQ0001", "Fictional", 1, {}, {"00006": (extra,)})
        catalogue = build_catalogue((*snapshot().courses, course))
        self.assertEqual(catalogue.coverage.observed_room_count, self.catalogue.coverage.observed_room_count)
        self.assertIn(
            "TR+1 / TR+2",
            room_schedule(catalogue, "TR+1", "TUE", [2], None, None, 100, 0)["sessions"][
                0
            ].source_venue_labels,
        )
        w = self.window.model_copy(update={"day": "TUE"})
        self.assertEqual(
            available_rooms(catalogue, w, RoomFilters(venue_prefixes=["TR+1", "TR+2"]), 10, 0)["match_count"],
            0,
        )

    def test_room_schedule_filters_keep_unknowns(self):
        result = room_schedule(self.catalogue, "S4-CL1", "MON", [2], "14:00", "15:00", 100, 0)
        self.assertEqual(result["session_count"], 1)
        self.assertIsNone(result["sessions"][0].teaching_weeks)
        self.assertEqual(
            room_schedule(self.catalogue, "LT1", "TUE", None, None, None, 100, 0)["session_count"], 0
        )

    def test_invalid_windows_and_filters(self):
        for changes in [
            {"start_time": "15:00"},
            {"teaching_weeks": []},
            {"teaching_weeks": [0]},
            {"start_time": "00:00", "buffer_minutes": 1},
        ]:
            with self.assertRaises(ValidationError):
                RoomWindow(**{**self.window.model_dump(), **changes})
        with self.assertRaises(ValidationError):
            RoomFilters(venue_contains=" ")


class BulkParserTests(unittest.TestCase):
    def test_published_course_with_an_empty_index_table_stays_unknown_in_coverage(self):
        courses = parse_teaching_schedule(page([block("ZZ0001", [])]), 2030, "1")
        self.assertEqual(courses[0].indexes, {})
        catalogue = build_catalogue(courses)
        self.assertEqual(catalogue.coverage.courses_without_published_indexes, 1)
        self.assertEqual(catalogue.coverage.observed_room_count, 0)

    def test_complete_course_blocks_all_indexes_and_leading_decimal_aus(self):
        courses = parse_teaching_schedule(FULL_TIME, 2030, "1")
        self.assertEqual(len(courses), 3)
        self.assertEqual(courses[0].indexes.keys(), {"00001", "00002"})
        self.assertEqual(courses[2].au, 0.5)
        self.assertEqual(parse_course_search(FULL_TIME, 2030, "1")[2]["au"], 0.5)
        self.assertEqual(
            parse_course_page(
                page([block("ZZ0001", [["00001", "TUT", "A", "MON", "1000-1100", "TR+1", ""]], ".0 AU")]),
                "ZZ0001",
            ).au,
            0.0,
        )

    def test_truncated_mismatched_duplicate_and_malformed_bulk_responses_fail(self):
        for html in [
            FULL_TIME.replace("</html>", ""),
            FULL_TIME.replace("2030", "2031"),
            page([block("ZZ0001", [["00001", "TUT"]])]),
            page([block("ZZ0001", [["00001", "TUT", "A", "MON", "1000-1100", "TR+1", ""]])] * 2),
        ]:
            with self.assertRaises(NTUPageError):
                parse_teaching_schedule(html, 2030, "1")


class TeachingClientTests(unittest.TestCase):
    def setUp(self):
        teaching._cache.clear()
        self.addCleanup(teaching._cache.clear)

    def test_both_study_modes_cached_together_and_refresh(self):
        with patch.object(
            teaching,
            "_fetch_html",
            side_effect=lambda term, query, study_mode: (
                FULL_TIME if study_mode == "F" else PART_TIME,
                "https://example.invalid",
            ),
        ) as fetch:
            first = teaching.get_teaching_snapshot(2030, 1)
            self.assertEqual(len(first.courses), 4)
            self.assertTrue(teaching.get_teaching_snapshot(2030, 1).cached)
            self.assertFalse(teaching.get_teaching_snapshot(2030, 1, True).cached)
            self.assertEqual(fetch.call_count, 4)
            self.assertEqual(sorted(c.kwargs["study_mode"] for c in fetch.call_args_list), ["F", "F", "P", "P"])
            self.assertTrue(all(c.args[1] == "" for c in fetch.call_args_list))

    def test_study_mode_pages_are_fetched_concurrently(self):
        both_started = Barrier(2)

        def fetch(term, query, study_mode):
            both_started.wait(timeout=2)
            return (FULL_TIME if study_mode == "F" else PART_TIME, "https://example.invalid")

        with patch.object(teaching, "_fetch_html", side_effect=fetch):
            snapshot = teaching.get_teaching_snapshot(2030, 1)

        self.assertEqual(len(snapshot.courses), 4)

    def test_incomplete_mode_is_not_cached_and_errors_are_actionable(self):
        with patch.object(teaching, "_fetch_html", side_effect=[(FULL_TIME, "x"), ("<html>bad</html>", "x")]):
            with self.assertRaises(teaching.NTURequestError):
                teaching.get_teaching_snapshot(2030, 1)
        self.assertFalse(teaching._cache)


class RoomMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_structured_results_and_validation_before_fetch(self):
        with patch("stars.room_tools.get_teaching_snapshot", side_effect=snapshot) as fetch:
            async with Client(mcp) as client:
                args = {
                    "academic_year": 2030,
                    "semester": 1,
                    "window": {
                        "day": "MON",
                        "start_time": "14:00",
                        "end_time": "15:00",
                        "teaching_weeks": [2],
                    },
                }
                result = await client.call_tool("stars_find_available_rooms", args)
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.structured_content["rooms"][0]["venue"], "LT1")
                room = await client.call_tool(
                    "stars_get_room_schedule", {"venue": "LT1", "academic_year": 2030, "semester": 1}
                )
                self.assertFalse(room.is_error, room)
                self.assertEqual(room.structured_content["sessions"][0]["indexes"], ["00001", "00002"])
                fetch.reset_mock()
                for name, arguments in [
                    (
                        "stars_find_available_rooms",
                        {**args, "window": {"day": "MON", "start_time": "16:00", "end_time": "15:00"}},
                    ),
                    (
                        "stars_get_room_schedule",
                        {"venue": "LT1", "academic_year": 2030, "semester": 1, "start_time": "14:00"},
                    ),
                ]:
                    error = await client.call_tool(name, arguments)
                    self.assertTrue(error.is_error)
                fetch.assert_not_called()

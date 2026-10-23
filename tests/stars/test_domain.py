from pathlib import Path
import unittest

from stars.domain import Course, Session, clash_status, compare_indexes, find_matching_indexes
from stars.parser import parse_course_page


FIXTURES = Path(__file__).parent / "fixtures"


def zz0001() -> Course:
    html = (FIXTURES / "zz0001-2026-1.html").read_bytes().decode("windows-1252")
    return parse_course_page(html, "ZZ0001")


def session(index: str, day: str, start: str, end: str, weeks: tuple[int, ...] | None) -> Session:
    return Session("TEST1000", index, "LEC", None, day, start, end, None, weeks, None)


class ClashTests(unittest.TestCase):
    def test_week_disjointness_and_touching_times_do_not_clash(self) -> None:
        first = session("1", "MON", "10:00", "11:00", (2, 4, 6))
        other_weeks = session("2", "MON", "10:30", "11:30", (3, 5, 7))
        self.assertFalse(clash_status(first, other_weeks))
        same_weeks = session("3", "MON", "10:30", "11:30", (4, 8))
        self.assertTrue(clash_status(first, same_weeks))
        back_to_back = session("4", "MON", "11:00", "12:00", (4,))
        self.assertFalse(clash_status(first, back_to_back))

    def test_unknown_schedule_is_not_claimed_as_clear_or_clashing(self) -> None:
        unknown = session("5", "MON", "10:00", "11:00", None)
        no_day = Session("TEST1000", "6", "TUT", None, None, None, None, None, None, "TBA", "TBA", "ARRANGED")
        self.assertIsNone(clash_status(unknown, no_day))

    def test_overlapping_times_with_unknown_weeks_are_uncertain(self) -> None:
        unknown = session("1", "MON", "10:00", "11:00", None)
        known = session("2", "MON", "10:30", "11:30", (2, 4))
        self.assertIsNone(clash_status(unknown, known))
        self.assertFalse(clash_status(unknown, session("3", "MON", "11:00", "12:00", (2,))))


class IndexLogicTests(unittest.TestCase):
    def test_comparison_separates_common_and_index_specific_sessions(self) -> None:
        result = compare_indexes(zz0001(), ["00001", "00002"])
        self.assertEqual({item["lesson_type"] for item in result["common_sessions"]}, {"LEC/STUDIO"})
        self.assertEqual(result["common_sessions"][0]["shared_by"], ["00001", "00002"])
        self.assertEqual({item["lesson_type"] for item in result["unique_sessions_by_index"]["00001"]}, {"TUT", "LAB"})

    def test_filter_rules_and_week_scoped_clashes(self) -> None:
        result = find_matching_indexes(
            zz0001(),
            {
                "avoid_days": ["FRI"],
                "require_sessions": [
                    {"lesson_type": "TUT", "day": "TUE", "starts_at_or_after": "16:00"}
                ],
            },
            [],
        )
        self.assertIn("00001", {item["index"] for item in result["matches"]})
        self.assertTrue(all(item["status"] == "confirmed" for item in result["matches"]))
        self.assertTrue(
            all(session["day"] != "FRI" for item in result["matches"] for session in item["sessions"])
        )

        existing = [{"day": "TUE", "start_time": "16:30", "end_time": "17:20", "teaching_weeks": [3]}]
        scoped = find_matching_indexes(
            zz0001(), {"teaching_weeks": [2]}, existing
        )
        self.assertIn("00001", {item["index"] for item in scoped["matches"]})

    def test_unknown_sessions_are_marked_uncertain(self) -> None:
        course = Course(
            "TEST1000",
            "Unknown",
            None,
            {},
            {"1": (Session("TEST1000", "1", None, None, None, None, None, None, None, "TBA", "TBA", "ARRANGED"),)},
        )
        result = find_matching_indexes(course, {}, [])
        self.assertEqual(result["matches"][0]["status"], "uncertain")

    def test_clashes_outside_the_requested_weeks_do_not_reject_an_index(self) -> None:
        course = Course("TEST1000", "Scoped", None, {}, {"1": (session("1", "MON", "10:00", "11:00", (1, 2)),)})
        existing = [{"day": "MON", "start_time": "10:30", "end_time": "11:30", "teaching_weeks": [2, 3]}]
        result = find_matching_indexes(course, {"teaching_weeks": [1, 3]}, existing)
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["matches"][0]["status"], "confirmed")
        self.assertEqual(find_matching_indexes(course, {"teaching_weeks": [2]}, existing)["match_count"], 0)


if __name__ == "__main__":
    unittest.main()

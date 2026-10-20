from pathlib import Path
import unittest

from ntu_course_index.domain import Course, Session, clash_status, compare_indexes, find_matching_indexes
from ntu_course_index.parser import parse_course_page


FIXTURES = Path(__file__).parent / "fixtures"


def sc2001() -> Course:
    html = (FIXTURES / "sc2001-2026-1.html").read_bytes().decode("windows-1252")
    return parse_course_page(html, "SC2001")


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


class IndexLogicTests(unittest.TestCase):
    def test_comparison_separates_common_and_index_specific_sessions(self) -> None:
        result = compare_indexes(sc2001(), ["10143", "10144"])
        self.assertEqual({item["lesson_type"] for item in result["common_sessions"]}, {"LEC/STUDIO"})
        self.assertEqual(result["common_sessions"][0]["shared_by"], ["10143", "10144"])
        self.assertEqual({item["lesson_type"] for item in result["unique_sessions_by_index"]["10143"]}, {"TUT", "LAB"})

    def test_filter_rules_and_week_scoped_clashes(self) -> None:
        result = find_matching_indexes(
            sc2001(),
            {
                "avoid_days": ["FRI"],
                "require_sessions": [
                    {"lesson_type": "TUT", "day": "TUE", "starts_at_or_after": "16:00"}
                ],
            },
            [],
        )
        self.assertIn("10143", {item["index"] for item in result["matches"]})
        self.assertTrue(all(item["status"] == "confirmed" for item in result["matches"]))
        self.assertTrue(
            all(session["day"] != "FRI" for item in result["matches"] for session in item["sessions"])
        )

        existing = [{"day": "TUE", "start_time": "16:30", "end_time": "17:20", "teaching_weeks": [3]}]
        scoped = find_matching_indexes(
            sc2001(), {"teaching_weeks": [2]}, existing
        )
        self.assertIn("10143", {item["index"] for item in scoped["matches"]})

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


if __name__ == "__main__":
    unittest.main()

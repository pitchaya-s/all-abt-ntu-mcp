import unittest
from pathlib import Path

from stars.domain import session_signature
from stars.parser import (
    CourseUnavailable,
    NTUPageError,
    parse_course_description,
    parse_course_page,
    parse_graduate_course_page,
    parse_teaching_weeks,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("windows-1252")


class CoursePageTests(unittest.TestCase):
    def test_public_graduate_course_timetable(self) -> None:
        graduate_html = load_fixture("ee6102-graduate-2026-1.html")
        course = parse_graduate_course_page(graduate_html, "EE6102")
        self.assertEqual((course["course_code"], course["course_name"], course["au"]),
                         ("EE6102", "Cyber Security & Blockchain Technology", 3.0))
        self.assertEqual((course["academic_year"], course["term"]), (2026, "1"))
        groups = course["class_groups"]
        self.assertEqual([group["class_group"] for group in groups], ["A", "B"])
        self.assertEqual(groups[0]["sessions"][0]["day"], "FRI")
        self.assertEqual(groups[0]["sessions"][0]["start_time"], "18:30")
        self.assertEqual(groups[0]["sessions"][0]["venue"], "LKC-LT")
        self.assertTrue(course["schedule_complete"])
        self.assertEqual(
            set(course),
            {"course_code", "course_name", "au", "academic_year", "term", "schedule_complete", "class_groups"},
        )

    def test_graduate_page_with_no_matching_course(self) -> None:
        graduate_html = load_fixture("ee6102-graduate-2026-1.html")
        with self.assertRaises(CourseUnavailable):
            parse_graduate_course_page(graduate_html, "ZZ9999")
        with self.assertRaises(NTUPageError):
            parse_graduate_course_page("<html><body>maintenance</body></html>", "EE6102")

    def test_official_course_description(self) -> None:
        description = parse_course_description(load_fixture("zz0001-content-2026-1.html"), "ZZ0001")
        self.assertIsNotNone(description)
        self.assertIn("example course one", description)

    def test_course_description_missing_result_and_unrecognized_page(self) -> None:
        content = load_fixture("zz0001-content-2026-1.html")
        self.assertIsNone(parse_course_description(content, "ZZ9999"))
        with self.assertRaises(NTUPageError):
            parse_course_description("<html><body>maintenance</body></html>", "ZZ0001")

    def test_zz0001_2026_semester_one(self) -> None:
        course = parse_course_page(load_fixture("zz0001-2026-1.html"), "ZZ0001")
        self.assertEqual(course.course_name, "EXAMPLE COURSE ONE~")
        self.assertEqual(course.au, 3.0)
        self.assertEqual(course.details["prerequisite"], "MH1812 & SC1007 OR SC1007 & SC1124")
        self.assertEqual(len(course.indexes), 36)
        self.assertEqual((next(iter(course.indexes)), list(course.indexes)[-1]), ("00001", "00036"))

        sessions = course.indexes["00001"]
        tutorial = next(session for session in sessions if session.lesson_type == "TUT")
        lab = next(session for session in sessions if session.lesson_type == "LAB")
        self.assertEqual((tutorial.group, tutorial.day, tutorial.start_time, tutorial.end_time), ("SCEA", "TUE", "16:30", "17:20"))
        self.assertEqual(tutorial.teaching_weeks, tuple(range(2, 14)))
        self.assertEqual(lab.teaching_weeks, (1, 3, 5, 7, 9, 11, 13))
        self.assertEqual(lab.venue, "HWLAB2")

    def test_zy0001_has_shared_lectures_and_labs(self) -> None:
        course = parse_course_page(load_fixture("zy0001-2026-1.html"), "ZY0001")
        self.assertEqual(len(course.indexes), 13)
        self.assertEqual(len(course.indexes["00050"]), 4)
        first_lecture = course.indexes["00050"][0]
        second_lecture = course.indexes["00051"][0]
        self.assertEqual(first_lecture.lesson_type, "LEC/STUDIO")
        self.assertEqual(first_lecture.day, "THU")
        self.assertEqual(session_signature(first_lecture), session_signature(second_lecture))
        lab = next(session for session in course.indexes["00050"] if session.lesson_type == "LAB")
        self.assertEqual(lab.teaching_weeks, (2, 4, 6, 8, 10, 12))

    def test_zx0001_remark_is_not_misreported_as_prerequisite(self) -> None:
        course = parse_course_page(load_fixture("zx0001-2026-1.html"), "ZX0001")
        self.assertEqual(len(course.indexes), 12)
        self.assertIsNone(course.details.get("prerequisite"))
        self.assertEqual(course.details.get("remark"), "H2 Maths or equivalent")
        self.assertTrue(all(session.lesson_type in {"LEC/STUDIO", "TUT"} for rows in course.indexes.values() for session in rows))

    def test_a_second_semester_response(self) -> None:
        course = parse_course_page(load_fixture("zz0001-2025-2.html"), "ZZ0001")
        self.assertEqual(course.course_name, "EXAMPLE COURSE ONE~")
        self.assertIn("00044", course.indexes)
        self.assertEqual(course.indexes["00044"][0].day, "TUE")

    def test_explicit_weeks_and_unrecognized_remarks(self) -> None:
        self.assertEqual(parse_teaching_weeks("Teaching Wk2-13"), tuple(range(2, 14)))
        self.assertEqual(parse_teaching_weeks("Teaching Wk1,3,5,7,9,11,13"), (1, 3, 5, 7, 9, 11, 13))
        self.assertIsNone(parse_teaching_weeks("Teaching Wk2-13 except recess"))

    def test_teaching_week_ranges_are_bounded_before_expansion(self) -> None:
        for remark in ("Wk1-1000000000", "Wk0-13", "Wk21", "Wk13-2"):
            with self.subTest(remark=remark):
                self.assertIsNone(parse_teaching_weeks(remark))

    def test_reversed_graduate_time_ranges_are_not_complete_schedules(self) -> None:
        html = load_fixture("ee6102-graduate-2026-1.html").replace("9:20pm", "6:00pm")
        course = parse_graduate_course_page(html, "EE6102")
        self.assertFalse(course["schedule_complete"])
        self.assertIn("6:00pm", course["class_groups"][0]["schedule_text"])

    def test_unknown_time_day_and_remarks_are_preserved(self) -> None:
        page = """
        <table>
          <tr><td>TEST1000</td><td>Title &amp; Course</td><td>3.0 AU</td></tr>
        </table>
        <table border>
          <tr><th>INDEX</th><th>TYPE</th><th>GROUP</th><th>DAY</th><th>TIME</th><th>VENUE</th><th>REMARK</th></tr>
          <tr><td>00017</td><td>SEM</td><td>G1</td><td>ARRANGED</td><td>TBA</td><td>Online</td><td>Odd schedule weeks 2 and 4</td></tr>
        </table>
        """
        course = parse_course_page(page, "TEST1000")
        session = course.indexes["00017"][0]
        self.assertEqual(course.course_name, "Title & Course")
        self.assertIsNone(session.day)
        self.assertEqual(session.raw_day, "ARRANGED")
        self.assertEqual(session.raw_time, "TBA")
        self.assertEqual(session.remarks, "Odd schedule weeks 2 and 4")
        self.assertIsNone(session.teaching_weeks)

    def test_no_result_and_changed_html_fail_clearly(self) -> None:
        missing = "<html><body>Class schedule is not available.</body></html>"
        with self.assertRaises(CourseUnavailable):
            parse_course_page(missing, "ZZ9999")
        with self.assertRaises(NTUPageError):
            parse_course_page("<html><body>maintenance</body></html>", "ZZ0001")


if __name__ == "__main__":
    unittest.main()

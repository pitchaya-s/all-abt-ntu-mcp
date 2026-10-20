from pathlib import Path
import unittest

from ntu_course_index.domain import session_signature
from ntu_course_index.parser import CourseUnavailable, NTUPageError, parse_course_page, parse_teaching_weeks


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("windows-1252")


class CoursePageTests(unittest.TestCase):
    def test_sc2001_2026_semester_one(self) -> None:
        course = parse_course_page(load_fixture("sc2001-2026-1.html"), "SC2001")
        self.assertEqual(course.course_name, "ALGORITHM DESIGN & ANALYSIS~")
        self.assertEqual(course.au, 3.0)
        self.assertEqual(course.details["prerequisite"], "MH1812 & SC1007 OR SC1007 & SC1124")
        self.assertEqual(len(course.indexes), 36)
        self.assertEqual((next(iter(course.indexes)), list(course.indexes)[-1]), ("10143", "10183"))

        sessions = course.indexes["10143"]
        tutorial = next(session for session in sessions if session.lesson_type == "TUT")
        lab = next(session for session in sessions if session.lesson_type == "LAB")
        self.assertEqual((tutorial.group, tutorial.day, tutorial.start_time, tutorial.end_time), ("SCEA", "TUE", "16:30", "17:20"))
        self.assertEqual(tutorial.teaching_weeks, tuple(range(2, 14)))
        self.assertEqual(lab.teaching_weeks, (1, 3, 5, 7, 9, 11, 13))
        self.assertEqual(lab.venue, "HWLAB2")

    def test_sc2207_has_shared_lectures_and_labs(self) -> None:
        course = parse_course_page(load_fixture("sc2207-2026-1.html"), "SC2207")
        self.assertEqual(len(course.indexes), 13)
        self.assertEqual(len(course.indexes["10308"]), 4)
        first_lecture = course.indexes["10308"][0]
        second_lecture = course.indexes["10309"][0]
        self.assertEqual(first_lecture.lesson_type, "LEC/STUDIO")
        self.assertEqual(first_lecture.day, "THU")
        self.assertEqual(session_signature(first_lecture), session_signature(second_lecture))
        lab = next(session for session in course.indexes["10308"] if session.lesson_type == "LAB")
        self.assertEqual(lab.teaching_weeks, (2, 4, 6, 8, 10, 12))

    def test_mh2802_remark_is_not_misreported_as_prerequisite(self) -> None:
        course = parse_course_page(load_fixture("mh2802-2026-1.html"), "MH2802")
        self.assertEqual(len(course.indexes), 12)
        self.assertIsNone(course.details.get("prerequisite"))
        self.assertEqual(course.details.get("remark"), "H2 Maths or equivalent")
        self.assertTrue(all(session.lesson_type in {"LEC/STUDIO", "TUT"} for rows in course.indexes.values() for session in rows))

    def test_a_second_semester_response(self) -> None:
        course = parse_course_page(load_fixture("sc2001-2025-2.html"), "SC2001")
        self.assertEqual(course.course_name, "ALGORITHM DESIGN & ANALYSIS~")
        self.assertIn("10253", course.indexes)
        self.assertEqual(course.indexes["10253"][0].day, "TUE")

    def test_explicit_weeks_and_unrecognized_remarks(self) -> None:
        self.assertEqual(parse_teaching_weeks("Teaching Wk2-13"), tuple(range(2, 14)))
        self.assertEqual(parse_teaching_weeks("Teaching Wk1,3,5,7,9,11,13"), (1, 3, 5, 7, 9, 11, 13))
        self.assertIsNone(parse_teaching_weeks("Teaching Wk2-13 except recess"))

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
            parse_course_page("<html><body>maintenance</body></html>", "SC2001")


if __name__ == "__main__":
    unittest.main()

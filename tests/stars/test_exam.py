import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

from stars.client import NTURequestError, exams, get_undergraduate_exam_schedule
from stars.parser import CourseUnavailable, NTUPageError
from stars.parser.exam import (
    parse_undergraduate_exam_plan,
    parse_undergraduate_exam_schedule,
)

FIXTURE = Path(__file__).parent / "fixtures" / "undergrad-exam-zz0001-2026-1.html"
EXAM_HTML = FIXTURE.read_bytes().decode("windows-1252")
LANDING_HTML = "<h2>For Undergraduate Programmes</h2><input>General Access"
PLAN_HTML = '<input type="radio" name="p_plan_no" value="115">AY2026-27 SEM 1<br>'
FILTER_HTML = '<select name="p_subj"><option>ZZ0001</option></select>'


class UndergraduateExamParserTests(unittest.TestCase):
    def test_parses_published_course_exam_and_notice(self) -> None:
        result = parse_undergraduate_exam_schedule(EXAM_HTML, "zz0001")
        self.assertEqual((result["course_code"], result["course_name"]), ("ZZ0001", "EXAMPLE COURSE ONE"))
        self.assertEqual((result["academic_year"], result["semester"]), (2026, "1"))
        self.assertEqual(result["exam_status"], "available")
        self.assertEqual(
            result["exams"],
            [
                {
                    "date": "2026-11-23",
                    "day": "MON",
                    "start_time": "13:00",
                    "end_time": "15:00",
                    "duration_minutes": 120,
                    "duration_text": "2 hr",
                }
            ],
        )
        self.assertIn("subject to changes", result["notice"].lower())

    def test_preserves_unrecognized_exam_times(self) -> None:
        html = EXAM_HTML.replace("23 November 2026", "Date to be announced").replace("1.00 pm", "Time TBA")
        exam = parse_undergraduate_exam_schedule(html, "ZZ0001")["exams"][0]
        self.assertIsNone(exam["date"])
        self.assertEqual(exam["raw_date"], "Date to be announced")
        self.assertIsNone(exam["start_time"])
        self.assertEqual(exam["raw_time"], "Time TBA")

    def test_distinguishes_course_not_listed_from_unrecognized_page(self) -> None:
        html = EXAM_HTML.replace("ZZ0001", "ZZ0002")
        result = parse_undergraduate_exam_schedule(html, "ZZ0001")
        self.assertEqual(result["exam_status"], "not_listed")
        self.assertEqual(result["exam_count"], 0)
        with self.assertRaisesRegex(NTUPageError, "no exam table"):
            parse_undergraduate_exam_schedule("<html>service unavailable</html>", "ZZ0001")

    def test_selects_latest_or_requested_published_term(self) -> None:
        html = (
            '<input type="radio" name="p_plan_no" value="105">AY2025-26 SEM 2<br>'
            '<input type="radio" name="p_plan_no" value="115">AY2026-27 SEM 1<br>'
        )
        latest = parse_undergraduate_exam_plan(html)
        requested = parse_undergraduate_exam_plan(html, 2025, "2")
        self.assertEqual((latest["plan_number"], latest["academic_year"], latest["semester"]), ("115", 2026, "1"))
        self.assertEqual((requested["plan_number"], requested["academic_year"], requested["semester"]), ("105", 2025, "2"))
        with self.assertRaises(CourseUnavailable):
            parse_undergraduate_exam_plan(html, 2024, "1")


class UndergraduateExamClientTests(unittest.TestCase):
    def setUp(self) -> None:
        with exams._cache_lock:
            exams._exam_cache.clear()

    def test_public_general_access_flow_and_cache(self) -> None:
        with patch(
            "stars.client.exams._fetch_html_request",
            side_effect=[LANDING_HTML, PLAN_HTML, FILTER_HTML, EXAM_HTML],
        ) as fetch:
            result = get_undergraduate_exam_schedule("zz0001")
            cached = get_undergraduate_exam_schedule("ZZ0001")

        self.assertEqual(result["exam_count"], 1)
        self.assertEqual(cached, result)
        self.assertEqual(fetch.call_count, 4)
        requests = [call.args[0] for call in fetch.call_args_list]
        clients = [call.args[2] for call in fetch.call_args_list]
        self.assertTrue(all(isinstance(client, httpx.Client) for client in clients))
        self.assertTrue(all(client is clients[0] for client in clients))
        self.assertEqual(requests[0].full_url, exams.UNDERGRAD_EXAM_FORM_URL)
        self.assertEqual(
            parse_qs(requests[1].data.decode()),
            {"p_opt": ["1"], "p_type": ["UE"], "bOption": ["Next"]},
        )
        detail = parse_qs(requests[-1].data.decode(), keep_blank_values=True)
        self.assertEqual(detail["p_subj"], ["ZZ0001"])
        self.assertEqual(detail["p_matric"], [""])
        self.assertEqual(detail["academic_session"], ["Semester 1 Academic Year 2026-2027"])

    def test_validates_term_and_reports_ntus_network_errors(self) -> None:
        with patch("stars.client.exams._fetch_html_request") as fetch:
            with self.assertRaisesRegex(ValueError, "both academic_year and semester"):
                get_undergraduate_exam_schedule("ZZ0001", 2026)
            with self.assertRaisesRegex(ValueError, "not Special Term"):
                get_undergraduate_exam_schedule("ZZ0001", 2026, "S")
            with self.assertRaisesRegex(ValueError, "Course code"):
                get_undergraduate_exam_schedule("ZZ0001?x=1")
            fetch.assert_not_called()

        with patch(
            "stars.client.exams._fetch_html_request",
            side_effect=NTURequestError("offline"),
        ):
            with self.assertRaisesRegex(NTURequestError, "offline"):
                get_undergraduate_exam_schedule("ZZ0001")


if __name__ == "__main__":
    unittest.main()

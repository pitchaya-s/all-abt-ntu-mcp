from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from ntu_stars_mcp.parser import NTUPageError, parse_stars_planner_page
from ntu_stars_mcp.parser.planner import parse_saved_plan_timetable
from ntu_stars_mcp.ntu_client import NTURequestError
from ntu_stars_mcp.wish.models import NTUPersonalDataError
from ntu_stars_mcp.wish.planner import PLANNER_VIEW_URL, read_stars_planner

FIXTURES = Path(__file__).parent / "fixtures"
CALENDAR = (FIXTURES / "personal-planner-calendar-sanitized.html").read_text()
LOAD = '''<html><body onload="xyz.target='_parent';xyz.submit()">
<form action="AUS_STARS_PLANNER.planner" method="post" id="xyz">
<input type="hidden" name="p1" value="private-session-token">
<input type="hidden" name="acad" value="2026"><input type="hidden" name="semester" value="2">
<input type="hidden" name="plan_no" value="1">
<input type="hidden" name="subj_code" value="ZZ0001"><input type="hidden" name="index_nmbr" value="00001"><input type="hidden" name="subj_type" value="C">
<input type="hidden" name="subj_code" value=""><input type="hidden" name="index_nmbr" value=""><input type="hidden" name="subj_type" value="">
</form></body></html>'''
COURSES = [{"course_code": "ZZ0001", "index": "00001", "course_type": "C"}]


class _Response:
    def __init__(self, html: str, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=Windows-1252"}
        self.html = html
        self.disposed = False

    def body(self):
        return self.html.encode("windows-1252")

    def dispose(self):
        self.disposed = True


class _Page:
    def __init__(self, flags=None, responses=None, selection=False) -> None:
        self.url = PLANNER_VIEW_URL if not selection else PLANNER_VIEW_URL.replace(".planner", ".time_table")
        self.context = SimpleNamespace(request=self)
        self.responses = responses if responses is not None else [_Response(LOAD), _Response(CALENDAR)]
        self.calls = []
        self.flags = flags or {"plan1_exists": "Y", "plan2_exists": "N", "plan3_exists": "N"}
        self.action = PLANNER_VIEW_URL
        self.selection_action = self.url
        self.submitted = False

    def content(self):
        return CALENDAR

    def evaluate(self, *_args):
        if self.url != PLANNER_VIEW_URL:
            raise AssertionError("Calendar was not opened before loading plans")
        return {"flags": self.flags, "action": self.action, "fields": [["p1", "private-session-token"], ["acad", "2026"], ["semester", "2"], ["subj_code", ""], ["subj_code", ""], ["plan_no", "1"]]}

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def locator(self, _selector):
        page = self

        class Form:
            def locator(self, _selector):
                return self

            def get_attribute(self, name):
                return "post" if name == "method" else page.selection_action

            def evaluate(self, _script, destination):
                page.submitted = True
                page.url = destination

        return Form()

    def expect_navigation(self, **_kwargs):
        class Navigation:
            value = SimpleNamespace(status=200)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        return Navigation()


class PlannerParserTests(unittest.TestCase):
    def test_live_empty_registration_is_distinct_from_a_saved_calendar(self):
        result = parse_stars_planner_page(CALENDAR)
        self.assertEqual((result["academic_year"], result["semester"]), (2026, 2))
        self.assertEqual(result["registered_courses_status"], "empty")
        self.assertEqual(result["registered_courses"], [])
        self.assertEqual(result["timetable_status"], "empty")
        self.assertIn("no course registration", result["registration_notice"])

    def test_calendar_rowspans_preserve_days_times_and_irregular_weeks(self):
        result = parse_saved_plan_timetable(CALENDAR, COURSES)
        self.assertEqual(result["timetable_status"], "parsed")
        self.assertEqual(result["unparsed_sessions"], [])
        self.assertEqual(len(result["sessions"]), 4)
        sessions = {s["day"]: s for s in result["sessions"]}
        self.assertEqual(set(sessions), {"MON", "TUE", "WED", "THU"})
        self.assertEqual(sessions["TUE"]["lesson_type"], "LAB")
        self.assertEqual(sessions["TUE"]["end_time"], "16:20")
        self.assertEqual(sessions["TUE"]["teaching_weeks"], [1, 3, 5, 7, 9, 11, 13])
        self.assertEqual(sessions["THU"]["start_time"], "15:30")
        self.assertEqual(sessions["WED"]["start_time"], "16:30")
        self.assertNotIn(10, sessions["WED"]["teaching_weeks"])
        self.assertEqual(sessions["WED"]["index"], "00001")

    def test_unusual_schedule_content_is_preserved(self):
        result = parse_saved_plan_timetable(CALENDAR.replace("1430to1520", "TBA"), COURSES)
        self.assertEqual(result["timetable_status"], "unparsed")
        self.assertTrue(any("TBA" in row["text"] for row in result["unparsed_sessions"]))
        unknown_weeks = parse_saved_plan_timetable(CALENDAR.replace("Wk1-9,11-13", "By arrangement"), COURSES)
        lecture = next(s for s in unknown_weeks["sessions"] if s["day"] == "MON")
        self.assertIsNone(lecture["teaching_weeks"])
        self.assertEqual(lecture["remarks"], "By arrangement")

    def test_landing_page_and_malformed_calendar_are_not_successful_empty_results(self):
        with self.assertRaises(NTUPageError):
            parse_stars_planner_page("<title>STARS Planner</title><p>Timetable</p>")
        with self.assertRaises(NTUPageError):
            parse_saved_plan_timetable("<p>Changed HTML</p>", COURSES)
        with self.assertRaisesRegex(NTUPageError, "cell span"):
            parse_saved_plan_timetable(CALENDAR.replace('rowspan="2"', 'rowspan="999999"'), COURSES)


@patch("ntu_stars_mcp.wish.planner._wait_for_request_slot")
class PlannerNavigationTests(unittest.TestCase):
    def test_only_read_only_display_endpoints_are_requested(self, _pace):
        page = _Page(selection=True)
        result = read_stars_planner(page)
        self.assertTrue(page.submitted)
        plan = result["saved_plans"][0]
        self.assertEqual(plan["courses"], COURSES)
        self.assertEqual(len(plan["sessions"]), 4)
        self.assertEqual(result["saved_plans"][1]["status"], "not_saved")
        self.assertEqual(len(page.calls), 2)
        self.assertTrue(page.calls[0][0].endswith(".load_time_table"))
        self.assertEqual(page.calls[1][0], PLANNER_VIEW_URL)
        self.assertEqual(parse_qs(page.calls[1][1]["data"], keep_blank_values=True)["subj_code"], ["ZZ0001", ""])
        self.assertTrue(all(call[1]["max_redirects"] == 0 for call in page.calls))
        self.assertNotIn("private-session-token", repr(result))

    def test_all_three_plans_are_loaded_independently(self, _pace):
        responses = [r for i in (1, 2, 3) for r in (_Response(LOAD.replace('name="plan_no" value="1"', f'name="plan_no" value="{i}"')), _Response(CALENDAR))]
        page = _Page(flags={f"plan{i}_exists": "Y" for i in (1, 2, 3)}, responses=responses)
        result = read_stars_planner(page)
        self.assertEqual([p["plan_number"] for p in result["saved_plans"]], [1, 2, 3])
        self.assertEqual([parse_qs(page.calls[i][1]["data"])["plan_no"] for i in (0, 2, 4)], [["1"], ["2"], ["3"]])

    def test_unsaved_and_unknown_plans_do_not_trigger_loads(self, _pace):
        page = _Page(flags={"plan1_exists": "N", "plan2_exists": "N"})
        result = read_stars_planner(page)
        self.assertEqual([p["status"] for p in result["saved_plans"]], ["not_saved", "not_saved", "unknown"])
        self.assertEqual(page.calls, [])

    def test_changed_forms_are_not_submitted(self, _pace):
        page = _Page(selection=True)
        page.selection_action = "https://other.example/register"
        with self.assertRaisesRegex(NTUPageError, "no form was submitted"):
            read_stars_planner(page)
        self.assertFalse(page.submitted)
        page = _Page()
        page.action = "https://other.example/save"
        with self.assertRaisesRegex(NTUPageError, "no request was submitted"):
            read_stars_planner(page)
        self.assertEqual(page.calls, [])

    def test_expired_sessions_and_external_redirects_are_detected(self, _pace):
        login = _Response('<form><input name="UID"></form>')
        self.assertIsNone(read_stars_planner(_Page(responses=[login])))
        self.assertTrue(login.disposed)
        expired = _Response('', status=302, headers={"location": "/pls/webexe/ldap_login.login"})
        self.assertIsNone(read_stars_planner(_Page(responses=[expired])))
        external = _Response('', status=302, headers={"location": "https://other.example"})
        with self.assertRaisesRegex(NTUPersonalDataError, "no redirect was followed"):
            read_stars_planner(_Page(responses=[external]))

    def test_service_failures_and_changed_load_responses_fail_clearly(self, _pace):
        with self.assertRaisesRegex(NTURequestError, "HTTP 503"):
            read_stars_planner(_Page(responses=[_Response('', status=503)]))
        with self.assertRaisesRegex(NTUPageError, "Load response"):
            read_stars_planner(_Page(responses=[_Response('<p>Unexpected</p>')]))
        with self.assertRaisesRegex(NTUPageError, "inconsistent"):
            read_stars_planner(_Page(responses=[_Response(LOAD.replace('name="index_nmbr"', 'name="changed"'))]))

    def test_saved_plan_identity_and_term_must_match_the_request(self, _pace):
        for name, value in (("plan_no", "2"), ("acad", "2025"), ("semester", "1")):
            with self.subTest(field=name):
                wrong = re.sub(f'name="{name}" value="[^"]*"', f'name="{name}" value="{value}"', LOAD)
                page = _Page(responses=[_Response(wrong)])
                with self.assertRaisesRegex(NTUPageError, "different plan or academic term"):
                    read_stars_planner(page)
                self.assertEqual(len(page.calls), 1)

    def test_duplicate_courses_do_not_get_ambiguous_index_assignments(self, _pace):
        duplicate = LOAD.replace('name="subj_code" value=""', 'name="subj_code" value="ZZ0001"')
        with self.assertRaisesRegex(NTUPageError, "duplicate courses"):
            read_stars_planner(_Page(responses=[_Response(duplicate)]))


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from mcp import Client

from stars.mcp_server import mcp
from stars.client import NTURequestError, search, search_courses
from stars.client.courses import _fetch_html
from stars.parser import NTUPageError, parse_course_search


FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "search-zz00-2026-1.html").read_text()
TITLE_HTML = (FIXTURES / "search-data-structures-2026-1.html").read_text()
EMPTY_HTML = (FIXTURES / "search-empty-2026-1.html").read_text()
PART_TIME_HTML = (FIXTURES / "search-zz00-part-time-2026-1.html").read_text()
SOURCE = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1"


class SearchParserTests(unittest.TestCase):
    def test_official_partial_code_and_title_results(self):
        courses = parse_course_search(HTML, 2026, "1")
        self.assertEqual([course["course_code"] for course in courses], ["ZZ0000", "ZZ0001", "ZZ0002", "ZZ0005", "ZZ0006", "ZZ0008"])
        self.assertEqual(courses[1], {"course_code": "ZZ0001", "course_name": "EXAMPLE COURSE ONE~", "au": 3.0})
        titles = parse_course_search(TITLE_HTML, 2026, "1")
        self.assertEqual([course["course_code"] for course in titles], ["IE2108", "SC1007", "SC1303"])
        self.assertEqual(titles[2]["au"], 4.0)

    def test_part_time_and_recognized_empty_results(self):
        self.assertEqual(len(parse_course_search(PART_TIME_HTML, 2026, "1")), 4)
        self.assertEqual(parse_course_search(EMPTY_HTML, 2026, "1"), [])

    def test_unexpected_pages_and_wrong_terms_are_rejected(self):
        for html, year, semester in [
            ("<h1>Service unavailable</h1>", 2026, "1"),
            ("<p>No records found</p>", 2026, "1"),
            (HTML, 2025, "1"), (HTML, 2026, "2"),
            (HTML.replace("3.0 AU", "3 credits"), 2026, "1"),
            (HTML.replace("<th><b>INDEX</b></th>", "<th>CHANGED</th>", 1), 2026, "1"),
        ]:
            with self.subTest(year=year, semester=semester, html=html[:30]):
                with self.assertRaises(NTUPageError):
                    parse_course_search(html, year, semester)

    def test_duplicate_courses_are_deduplicated_but_conflicts_rejected(self):
        self.assertEqual(len(parse_course_search(HTML + HTML, 2026, "1")), 6)
        with self.assertRaisesRegex(NTUPageError, "conflicting"):
            parse_course_search(HTML + HTML.replace("3.0 AU", "4.0 AU"), 2026, "1")


class SearchClientTests(unittest.TestCase):
    def setUp(self):
        with search._cache_lock:
            search._cache.clear()

    def test_request_reuses_official_post_form_and_study_mode(self):
        with patch("stars.client.courses._fetch_html_request", return_value=HTML) as fetch:
            _fetch_html("2026;1", "DATA STRUCTURES", study_mode="P")
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, SOURCE)
        fields = parse_qs(request.data.decode())
        self.assertEqual(fields["r_subj_code"], ["DATA STRUCTURES"])
        self.assertEqual(fields["r_search_type"], ["P"])
        self.assertEqual(fields["acadsem"], ["2026;1"])

    def test_pages_share_cache_and_mutations_do_not_corrupt_it(self):
        with patch.object(search, "_fetch_html", return_value=(HTML, SOURCE)) as fetch:
            first = search_courses(" zz00 ", 2026, 1, limit=2)
            second = search_courses("ZZ00", 2026, 1, limit=2, offset=2)
            self.assertEqual(first["query"], "ZZ00")
            self.assertEqual(first["total_count"], 6)
            self.assertTrue(first["has_more"])
            self.assertEqual(second["courses"][0]["course_code"], "ZZ0002")
            self.assertEqual(first["retrieved_at"], second["retrieved_at"])
            first["courses"][0]["course_name"] = "modified"
            self.assertNotEqual(search_courses("ZZ00", 2026, 1)["courses"][0]["course_name"], "modified")
            self.assertFalse(search_courses("ZZ00", 2026, 1, offset=5)["has_more"])
            self.assertEqual(search_courses("ZZ00", 2026, 1, offset=99)["courses"], [])
        fetch.assert_called_once_with("2026;1", "ZZ00", study_mode="F")

    def test_part_time_uses_a_separate_cache_key(self):
        with patch.object(search, "_fetch_html", side_effect=[(HTML, SOURCE), (PART_TIME_HTML, SOURCE)]) as fetch:
            self.assertEqual(search_courses("ZZ00", 2026, 1)["total_count"], 6)
            self.assertEqual(search_courses("ZZ00", 2026, 1, "part_time")["total_count"], 4)
            self.assertEqual(fetch.call_args.kwargs, {"study_mode": "P"})
        self.assertEqual(fetch.call_count, 2)

    def test_invalid_inputs_are_rejected_before_network(self):
        with patch.object(search, "_fetch_html") as fetch:
            for query in ["", " ", "S", "SC%", "SC_", "<script>", "A" * 81, "AB\x00CD"]:
                with self.subTest(query=query), self.assertRaises(ValueError):
                    search_courses(query, 2026, 1)
            for kwargs in [dict(study_mode="unknown"), dict(limit=0), dict(limit=101), dict(offset=-1), dict(limit=True), dict(offset=False)]:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    search_courses("ZZ00", 2026, 1, **kwargs)
            for year, semester in [(True, 1), (1999, 1), (2026, 3)]:
                with self.assertRaises(ValueError):
                    search_courses("ZZ00", year, semester)
            fetch.assert_not_called()

    def test_errors_are_not_cached_and_empty_results_are_cached(self):
        with patch.object(search, "_fetch_html", side_effect=[NTURequestError("offline"), ("unexpected", SOURCE), (EMPTY_HTML, SOURCE)]) as fetch:
            with self.assertRaisesRegex(NTURequestError, "offline"):
                search_courses("ZZZXQ99999", 2026, 1)
            with self.assertRaisesRegex(NTURequestError, "safely parse"):
                search_courses("ZZZXQ99999", 2026, 1)
            self.assertEqual(search_courses("ZZZXQ99999", 2026, 1)["total_count"], 0)
            self.assertEqual(search_courses("ZZZXQ99999", 2026, 1)["courses"], [])
            self.assertEqual(fetch.call_count, 3)

    def test_cache_expiry_disabled_cache_and_eviction(self):
        with patch.object(search, "_fetch_html", return_value=(HTML, SOURCE)) as fetch:
            search_courses("ZZ00", 2026, 1)
            with search._cache_lock:
                key = next(iter(search._cache))
                search._cache[key] = (0, search._cache[key][1])
            search_courses("ZZ00", 2026, 1)
            self.assertEqual(fetch.call_count, 2)
            with patch.object(search, "CACHE_TTL_SECONDS", 0):
                search_courses("ZZ00", 2026, 1)
                search_courses("ZZ00", 2026, 1)
            self.assertEqual(fetch.call_count, 4)
            with patch.object(search, "MAX_CACHE_ENTRIES", 1):
                search_courses("ZZ0001", 2026, 1)
                self.assertEqual(len(search._cache), 1)
                self.assertEqual(next(iter(search._cache))[2], "ZZ0001")


class SearchMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_returns_typed_results_and_actionable_errors(self):
        with patch("stars.mcp_server.fetch_course_search", wraps=search_courses), patch.object(search, "_fetch_html", return_value=(TITLE_HTML, SOURCE)):
            async with Client(mcp) as client:
                args = {"query": "DATA STRUCTURES", "academic_year": 2026, "semester": 1}
                reply = await client.call_tool("stars_search_courses", args)
                self.assertFalse(reply.is_error)
                self.assertEqual(reply.structured_content["total_count"], 3)
                for changes in [{"query": "%"}, {"study_mode": "graduate"}, {"limit": 0}, {"semester": 3}]:
                    error = await client.call_tool("stars_search_courses", {**args, **changes})
                    self.assertTrue(error.is_error)
                with patch("stars.mcp_server.fetch_course_search", side_effect=NTURequestError("NTU unavailable")):
                    error = await client.call_tool("stars_search_courses", args)
                    self.assertTrue(error.is_error)
                    self.assertIn("NTU unavailable", error.content[0].text)

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

from mcp import Client

from shared.server import mcp
from stars.client import NTURequestError, vacancy
from stars.parser import NTUPageError, parse_course_page, parse_course_vacancies

FIXTURES = Path(__file__).parent / "fixtures"
HTML = (FIXTURES / "zz0001-vacancy-2026-2.html").read_text()
SGT = timezone(timedelta(hours=8))


class VacancyParserTests(unittest.TestCase):
    def test_official_course_responses(self) -> None:
        for code, count in [("ZZ0001", 7), ("ZY0001", 23)]:
            html = (FIXTURES / f"{code.lower()}-vacancy-2026-2.html").read_text()
            result = parse_course_vacancies(html, code)
            self.assertEqual((result["academic_year"], result["semester"]), (2026, "2"))
            self.assertEqual(len(result["indexes"]), count)
        result = parse_course_vacancies(HTML, "ZZ0001")
        self.assertEqual(result["indexes"]["00037"], {"vacancies_available": 28, "waitlist_length": 0})
        self.assertEqual(result["indexes"]["00043"]["vacancies_available"], 35)

    def test_unknown_counts_are_not_zero(self) -> None:
        result = parse_course_vacancies(HTML.replace("\n28\n", "\nN/A\n", 1), "ZZ0001")
        self.assertIsNone(result["indexes"]["00037"]["vacancies_available"])
        self.assertEqual(result["indexes"]["00037"]["waitlist_length"], 0)

    def test_unexpected_or_inconsistent_pages_are_rejected(self) -> None:
        for html in (
            "", "<html>Service unavailable</html>", "<html>Please log in</html>",
            HTML.replace("ZZ0001", "ZY0001"),
            HTML.replace("Check Vacancies, 2026 2", "Check Vacancies"),
            HTML.replace("Vacancies<BR>Available", "New Header"),
            HTML.replace("\n28\n", "\n-1\n", 1),
            HTML.replace("\n28\n", "\nERROR\n", 1),
            HTML.replace("\n00038\n", "\n00037\n", 1),
            HTML.replace("\n00037\n", "\n\n", 1),
            HTML.replace("\n00037\n</TD>", "\n00037\n</TD><TD>extra</TD>", 1),
        ):
            with self.subTest(html=html[:40]):
                with self.assertRaises(NTUPageError):
                    parse_course_vacancies(html, "ZZ0001")


class VacancyClientTests(unittest.TestCase):
    def setUp(self) -> None:
        vacancy._cache.clear()
        clock = patch.object(vacancy, "datetime", wraps=datetime)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = datetime(2026, 10, 21, 12, tzinfo=SGT)

    def test_post_request_and_shared_short_cache(self) -> None:
        with patch.object(vacancy, "_fetch_html_request", return_value=HTML) as fetch:
            first = vacancy.get_course_vacancies("zz0001", 2026, 2)
            first["indexes"]["00037"]["vacancies_available"] = 999
            second = vacancy.get_course_vacancies("ZZ0001", 2026, 2)
        fetch.assert_called_once()
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, vacancy.VACANCY_URL)
        self.assertEqual(parse_qs(request.data.decode()), {"subj": ["ZZ0001"]})
        self.assertFalse(first["from_cache"])
        self.assertTrue(second["from_cache"])
        self.assertEqual(second["indexes"]["00037"]["vacancies_available"], 28)
        self.assertLessEqual(vacancy.VACANCY_CACHE_TTL_SECONDS, 60)

    def test_other_term_does_not_leak_counts_or_modify_snapshot(self) -> None:
        with patch.object(vacancy, "_fetch_html_request", return_value=HTML) as fetch:
            for year, semester in [(2026, 1), (2025, 2), (2026, "S")]:
                result = vacancy.get_course_vacancies("ZZ0001", year, semester)
                self.assertEqual(result["status"], "term_mismatch")
                self.assertEqual(result["indexes"], {})
            current = vacancy.get_course_vacancies("ZZ0001", 2026, 2)
        fetch.assert_called_once()
        self.assertEqual(current["status"], "available")
        self.assertEqual(len(current["indexes"]), 7)

    def test_closing_hours_never_request_or_return_cached_counts(self) -> None:
        with patch.object(vacancy, "_fetch_html_request", return_value=HTML) as fetch:
            vacancy.get_course_vacancies("ZZ0001", 2026, 2)
            fetch.reset_mock()
            for hour, minute in [(0, 0), (8, 59), (22, 0), (23, 59)]:
                self.clock.now.return_value = datetime(2026, 10, 21, hour, minute, tzinfo=SGT)
                result = vacancy.get_course_vacancies("ZZ0001", 2026, 2)
                self.assertEqual(result["status"], "closed")
                self.assertEqual(result["indexes"], {})
                self.assertIsNone(result["retrieved_at"])
            fetch.assert_not_called()

    def test_opening_boundaries(self) -> None:
        with patch.object(vacancy, "_fetch_html_request", return_value=HTML) as fetch:
            for hour, minute in [(9, 0), (21, 59)]:
                self.clock.now.return_value = datetime(2026, 10, 21, hour, minute, tzinfo=SGT)
                self.assertEqual(vacancy.get_course_vacancies("ZZ0001", 2026, 2)["status"], "available")
            fetch.assert_called_once()

    def test_expired_and_disabled_cache_refetch(self) -> None:
        with patch.object(vacancy, "_fetch_html_request", return_value=HTML) as fetch:
            vacancy.get_course_vacancies("ZZ0001", 2026, 2)
            created, result = vacancy._cache["ZZ0001"]
            vacancy._cache["ZZ0001"] = (created - 61, result)
            self.assertFalse(vacancy.get_course_vacancies("ZZ0001", 2026, 2)["from_cache"])
            with patch.object(vacancy, "VACANCY_CACHE_TTL_SECONDS", 0):
                self.assertFalse(vacancy.get_course_vacancies("ZZ0001", 2026, 2)["from_cache"])
            self.assertEqual(fetch.call_count, 3)

    def test_failures_are_not_cached_and_validation_precedes_network(self) -> None:
        for response in [NTURequestError("HTTP 503"), "<html>Service closed</html>"]:
            with patch.object(vacancy, "_fetch_html_request", **(
                {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
            )):
                with self.assertRaises(NTURequestError):
                    vacancy.get_course_vacancies("ZZ0001", 2026, 2)
                self.assertEqual(vacancy._cache, {})
        with patch.object(vacancy, "_fetch_html_request") as fetch:
            with self.assertRaises(ValueError):
                vacancy.get_course_vacancies("ZZ0001?bad", 2026, 2)
            with self.assertRaises(ValueError):
                vacancy.get_course_vacancies("ZZ0001", 2026, 3)
            fetch.assert_not_called()

    def test_cache_has_a_size_limit(self) -> None:
        with (
            patch.object(vacancy, "MAX_CACHE_ENTRIES", 1),
            patch.object(vacancy, "_fetch_html_request", side_effect=[HTML, HTML.replace("ZZ0001", "ZZ0002")]),
        ):
            vacancy.get_course_vacancies("ZZ0001", 2026, 2)
            vacancy.get_course_vacancies("ZZ0002", 2026, 2)
        self.assertEqual(set(vacancy._cache), {"ZZ0002"})


class VacancyMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_and_degraded_responses_for_both_tools(self) -> None:
        course = parse_course_page((FIXTURES / "zz0001-2026-1.html").read_bytes().decode("windows-1252"), "ZZ0001")
        course = replace(course, academic_year=2026, semester="2", indexes={
            "00037": tuple(replace(session, index="00037") for session in course.indexes["00001"]),
            "00000": (),
        })
        snapshot = {**parse_course_vacancies(HTML, "ZZ0001"), "status": "available", "retrieved_at": "2026-10-21T04:00:00+00:00"}
        with patch("stars.mcp_server.fetch_course", return_value=course):
            async with Client(mcp) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertIn("stars_get_index", names)
                self.assertNotIn("get_index_schedule", names)
                for tool in ["stars_get_index", "stars_get_course_indexes"]:
                    args = {"course_code": "ZZ0001", "academic_year": 2026, "semester": 2}
                    if tool == "stars_get_index":
                        args["index"] = "00037"
                    with patch("stars.mcp_server.fetch_course_vacancies", return_value=snapshot):
                        result = await client.call_tool(tool, args)
                    self.assertFalse(result.is_error)
                    data = result.structured_content
                    index = data if tool == "stars_get_index" else data["indexes"][0]
                    self.assertEqual(index["vacancy_status"], "available")
                    self.assertEqual(index["vacancies_available"], 28)
                    self.assertEqual(index["waitlist_length"], 0)
                    self.assertEqual(len(index["sessions"]), 4)
                    self.assertNotIn("indexes", data["vacancy_metadata"])
                    if tool == "stars_get_course_indexes":
                        self.assertEqual(data["indexes"][1]["vacancy_status"], "not_listed")
                        self.assertIsNone(data["indexes"][1]["vacancies_available"])
                    for status in ["closed", "term_mismatch"]:
                        with patch("stars.mcp_server.fetch_course_vacancies", return_value={**snapshot, "status": status, "indexes": {}}):
                            result = await client.call_tool(tool, args)
                        self.assertFalse(result.is_error)
                        data = result.structured_content
                        index = data if tool == "stars_get_index" else data["indexes"][0]
                        self.assertEqual(index["vacancy_status"], status)
                        self.assertIsNone(index["vacancies_available"])
                    with patch("stars.mcp_server.fetch_course_vacancies", side_effect=NTURequestError("unavailable")):
                        result = await client.call_tool(tool, args)
                    self.assertFalse(result.is_error)
                    data = result.structured_content
                    index = data if tool == "stars_get_index" else data["indexes"][0]
                    self.assertEqual(index["vacancy_status"], "unavailable")
                    self.assertIsNone(index["waitlist_length"])
                    self.assertEqual(len(index["sessions"]), 4)

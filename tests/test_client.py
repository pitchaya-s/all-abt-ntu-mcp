from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ntu_course_index import ntu_client
from ntu_course_index.ntu_client import NTURequestError, get_course, get_graduate_course_schedule


FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-2026-1.html"
HTML = FIXTURE.read_bytes().decode("windows-1252")
CONTENT_FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-content-2026-1.html"
CONTENT_HTML = CONTENT_FIXTURE.read_bytes().decode("windows-1252")
GRADUATE_FIXTURE = Path(__file__).parent / "fixtures" / "ee6102-graduate-2026-1.html"
GRADUATE_HTML = GRADUATE_FIXTURE.read_bytes().decode("windows-1252")


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        with ntu_client._cache_lock:
            ntu_client._cache.clear()
            ntu_client._graduate_cache.clear()

    def test_invalid_course_code_is_rejected_before_network(self) -> None:
        with patch("ntu_course_index.ntu_client.urlopen") as open_url:
            with self.assertRaisesRegex(ValueError, "Course code"):
                get_course("SC2001?x=1", 2026, 1)
            with self.assertRaisesRegex(ValueError, "Semester"):
                get_course("SC2001", 2026, 3)
            open_url.assert_not_called()

    def test_undergraduate_fetch_uses_public_schedule_form(self) -> None:
        with patch("ntu_course_index.ntu_client._fetch_html_request", return_value="page") as fetch:
            html, source_url = ntu_client._fetch_html("2026;1", "SC2001")
        request = fetch.call_args.args[0]
        fields = dict(part.split("=", 1) for part in request.data.decode().split("&"))
        self.assertEqual(html, "page")
        self.assertEqual(source_url, ntu_client.BASE_URL)
        self.assertEqual(request.full_url, ntu_client.BASE_URL)
        self.assertEqual(fields["acadsem"], "2026%3B1")
        self.assertEqual(fields["r_subj_code"], "SC2001")
        self.assertEqual(fields["r_search_type"], "F")
        self.assertEqual(fields["boption"], "Search")
        self.assertEqual(fields["staff_access"], "true")

    def test_network_failure_is_reported_and_not_cached(self) -> None:
        with patch.object(ntu_client, "MAX_RETRIES", 0), patch(
            "ntu_course_index.ntu_client.urlopen", side_effect=URLError("offline")
        ):
            with self.assertRaisesRegex(NTURequestError, "after 1 attempt"):
                get_course("SC2001", 2026, 1)

    def test_graduate_schedule_is_cached_and_normalized(self) -> None:
        with patch(
            "ntu_course_index.ntu_client._fetch_html_request",
            return_value=GRADUATE_HTML,
        ) as fetch:
            course = get_graduate_course_schedule("ee6102")
            cached = get_graduate_course_schedule("EE6102")
        fetch.assert_called_once()
        self.assertEqual(course["course_code"], "EE6102")
        self.assertEqual(len(course["class_groups"]), 2)
        self.assertIn("choiceSubj=EE6102", course["source_url"])
        self.assertEqual(cached, course)

    def test_graduate_schedule_invalid_code_and_network_error(self) -> None:
        with patch("ntu_course_index.ntu_client._fetch_html_request") as fetch:
            with self.assertRaisesRegex(ValueError, "Course code"):
                get_graduate_course_schedule("EE6102?x=1")
            fetch.assert_not_called()

        with patch(
            "ntu_course_index.ntu_client._fetch_html_request",
            side_effect=NTURequestError("offline"),
        ):
            with self.assertRaisesRegex(NTURequestError, "offline"):
                get_graduate_course_schedule("EE6102")

    def test_successful_parses_are_cached(self) -> None:
        with (
            patch("ntu_course_index.ntu_client._fetch_html", return_value=(HTML, "https://ntu.example/course")) as fetch,
            patch(
                "ntu_course_index.ntu_client._fetch_course_content_html",
                return_value=(CONTENT_HTML, "https://ntu.example/content"),
            ) as fetch_content,
        ):
            first = get_course("SC2001", 2026, 1)
            second = get_course("SC2001", 2026, 1)
        fetch.assert_called_once()
        fetch_content.assert_called_once()
        self.assertEqual(first.retrieved_at, second.retrieved_at)
        self.assertEqual(first.source_url, "https://ntu.example/course")
        self.assertEqual(first.course_description_status, "available")
        self.assertIn("algorithm design and analysis", first.course_description)

    def test_description_request_failure_does_not_hide_schedule(self) -> None:
        with (
            patch("ntu_course_index.ntu_client._fetch_html", return_value=(HTML, "https://ntu.example/course")),
            patch(
                "ntu_course_index.ntu_client._fetch_course_content_html",
                side_effect=NTURequestError("content page unavailable"),
            ),
        ):
            course = get_course("SC2001", 2026, 1)
        self.assertEqual(len(course.indexes), 36)
        self.assertIsNone(course.course_description)
        self.assertEqual(course.course_description_status, "unavailable")

    def test_cache_evicts_oldest_entry_at_its_limit(self) -> None:
        def html_for(code: str) -> tuple[str, str]:
            return HTML.replace("SC2001", code), f"https://ntu.example/{code}"

        with (
            patch.object(ntu_client, "MAX_CACHE_ENTRIES", 2),
            patch("ntu_course_index.ntu_client._fetch_html", side_effect=lambda _term, code: html_for(code)),
            patch(
                "ntu_course_index.ntu_client._fetch_course_content_html",
                return_value=(CONTENT_HTML, "https://ntu.example/content"),
            ),
        ):
            get_course("SC2001", 2026, 1)
            get_course("SC2002", 2026, 1)
            get_course("SC2003", 2026, 1)

        self.assertEqual(set(ntu_client._cache), {(2026, "1", "SC2002"), (2026, "1", "SC2003")})


if __name__ == "__main__":
    unittest.main()

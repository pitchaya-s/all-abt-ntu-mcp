from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ntu_course_index import ntu_client
from ntu_course_index.ntu_client import NTURequestError, get_course


FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-2026-1.html"
HTML = FIXTURE.read_bytes().decode("windows-1252")


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        with ntu_client._cache_lock:
            ntu_client._cache.clear()

    def test_invalid_course_code_is_rejected_before_network(self) -> None:
        with patch("ntu_course_index.ntu_client.urlopen") as open_url:
            with self.assertRaisesRegex(ValueError, "Course code"):
                get_course("SC2001?x=1", 2026, 1)
            with self.assertRaisesRegex(ValueError, "Semester"):
                get_course("SC2001", 2026, 3)
            open_url.assert_not_called()

    def test_network_failure_is_reported_and_not_cached(self) -> None:
        with patch.object(ntu_client, "MAX_RETRIES", 0), patch(
            "ntu_course_index.ntu_client.urlopen", side_effect=URLError("offline")
        ):
            with self.assertRaisesRegex(NTURequestError, "after 1 attempt"):
                get_course("SC2001", 2026, 1)

    def test_successful_parses_are_cached(self) -> None:
        with patch("ntu_course_index.ntu_client._fetch_html", return_value=(HTML, "https://ntu.example/course")) as fetch:
            first = get_course("SC2001", 2026, 1)
            second = get_course("SC2001", 2026, 1)
        fetch.assert_called_once()
        self.assertEqual(first.retrieved_at, second.retrieved_at)
        self.assertEqual(first.source_url, "https://ntu.example/course")

    def test_cache_evicts_oldest_entry_at_its_limit(self) -> None:
        def html_for(code: str) -> tuple[str, str]:
            return HTML.replace("SC2001", code), f"https://ntu.example/{code}"

        with patch.object(ntu_client, "MAX_CACHE_ENTRIES", 2), patch(
            "ntu_course_index.ntu_client._fetch_html",
            side_effect=lambda _term, code: html_for(code),
        ):
            get_course("SC2001", 2026, 1)
            get_course("SC2002", 2026, 1)
            get_course("SC2003", 2026, 1)

        self.assertEqual(set(ntu_client._cache), {(2026, "1", "SC2002"), (2026, "1", "SC2003")})


if __name__ == "__main__":
    unittest.main()

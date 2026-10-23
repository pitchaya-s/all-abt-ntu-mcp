from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from shared.public_http import PublicHTTPClient, PublicRequestError


URL = "https://example.org/feed"


class PublicHTTPTests(unittest.TestCase):
    def setUp(self):
        self.client = PublicHTTPClient("Example service", ["example.org", "static.example.org"], {"application/json"})
        pace = patch("shared.public_http.time.sleep")
        pace.start()
        self.addCleanup(pace.stop)

    def response(self, body=b"{}", content_type="application/json", url=URL):
        response = BytesIO(body)
        response.headers = Message()
        response.headers["Content-Type"] = content_type
        response.geturl = lambda: url
        return response

    def test_cache_refresh_expiry_and_no_auth_headers(self):
        with patch.object(self.client.opener, "open", side_effect=lambda *a, **k: self.response()) as get:
            first = self.client.get(URL)
            self.assertFalse(first[1]["cached"])
            self.assertTrue(self.client.get(URL)[1]["cached"])
            self.assertEqual(first[1]["retrieved_at"], self.client.get(URL)[1]["retrieved_at"])
            self.client.get(URL, refresh=True)
            self.assertEqual(get.call_count, 2)
            stamp, body, retrieved = self.client._cache[URL]
            self.client._cache[URL] = (stamp - 301, body, retrieved)
            self.assertFalse(self.client.get(URL)[1]["cached"])
            self.assertEqual(get.call_count, 3)
            self.assertNotIn("Cookie", get.call_args.args[0].headers)
            self.assertNotIn("Authorization", get.call_args.args[0].headers)

    def test_only_allowed_https_redirects_are_followed(self):
        for url in ["http://example.org/feed", "https://evil.example/feed", "https://example.org:8443/feed", "https://user@example.org/feed"]:
            with self.assertRaises(PublicRequestError):
                self.client.redirects.validate(url)
        self.client.redirects.validate("https://static.example.org:443/feed")
        with patch.object(self.client.opener, "open", return_value=self.response(url="https://evil.example/feed")):
            with self.assertRaises(PublicRequestError):
                self.client.get(URL)

    def test_bad_content_and_oversized_responses_are_not_cached(self):
        oversized = self.response()
        oversized.read = lambda n: b" " * n
        for response in [self.response(content_type="text/html"), oversized]:
            with patch.object(self.client.opener, "open", return_value=response), self.assertRaises(PublicRequestError):
                self.client.get(URL)
            self.assertFalse(self.client._cache)

    def test_transient_failures_retry_once_without_leaking_details(self):
        headers = Message()
        headers["Retry-After"] = "1"
        for error, attempts in [(URLError("private error detail"), 2),
                                (HTTPError(URL, 503, "unavailable", headers, None), 2),
                                (HTTPError(URL, 403, "denied", headers, None), 1)]:
            with patch.object(self.client.opener, "open", side_effect=error) as get:
                with self.assertRaises(PublicRequestError) as caught:
                    self.client.get(URL)
            self.assertEqual(get.call_count, attempts)
            self.assertNotIn("private error detail", str(caught.exception))

    def test_rate_limits_honor_long_numeric_and_http_date_delays(self):
        for value in ["120", format_datetime(datetime.now(timezone.utc) + timedelta(minutes=5))]:
            headers = Message()
            headers["Retry-After"] = value
            with patch.object(self.client.opener, "open", side_effect=HTTPError(URL, 429, "limited", headers, None)) as get:
                with self.assertRaises(PublicRequestError):
                    self.client.get(URL)
                self.assertEqual(get.call_count, 1)

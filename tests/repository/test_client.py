from email.message import Message
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from drntu.rest.client import RepositoryClient
from drntu.models import RepositoryError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = RepositoryClient()
        self.sleep = patch("drntu.rest.client.time.sleep").start()
        self.addCleanup(patch.stopall)

    def response(self, data=None, content_type="application/json", body=None):
        result = BytesIO(body if body is not None else json.dumps(data or {"ok": True}).encode())
        result.headers = Message()
        result.headers["Content-Type"] = content_type
        return result

    def test_cache_refresh_expiry_and_bounded_entries(self):
        with patch("drntu.rest.client.urlopen", side_effect=lambda *a, **k: self.response()) as fetch:
            first = self.client.get("/core/items/example")
            self.assertFalse(first[1]["cached"])
            self.assertTrue(self.client.get("/core/items/example")[1]["cached"])
            self.assertEqual(first[1]["retrieved_at"], self.client.get("/core/items/example")[1]["retrieved_at"])
            self.client.get("/core/items/example", refresh=True)
            self.assertEqual(fetch.call_count, 2)
            key = next(iter(self.client._cache))
            stamp, data, retrieved = self.client._cache[key]
            self.client._cache[key] = (stamp - 301, data, retrieved)
            self.assertFalse(self.client.get("/core/items/example")[1]["cached"])
            for number in range(65):
                self.client.get("/example/" + str(number))
            self.assertEqual(len(self.client._cache), 64)

    def test_query_encoding_preserves_multiple_filters_without_cookies(self):
        with patch("drntu.rest.client.urlopen", return_value=self.response()) as fetch:
            self.client.get("/discover/search/objects", {"query": "A & B", "f.subject": ["one,equals", "two,contains"]})
        request = fetch.call_args.args[0]
        params = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(params["query"], ["A & B"])
        self.assertEqual(params["f.subject"], ["one,equals", "two,contains"])
        self.assertNotIn("Cookie", request.headers)
        self.assertNotIn("Authorization", request.headers)

    def test_captcha_html_json_errors_and_oversized_responses_are_not_cached(self):
        oversized = self.response()
        oversized.read = lambda n: b" " * n
        for response, dataset, message in [
            (self.response(content_type="text/html", body=b"<html>CAPTCHA</html>"), True, "CAPTCHA"),
            (self.response(body=b"invalid json"), False, "invalid JSON"),
            (self.response(data=[1]), False, "unexpected response"),
            (oversized, False, "8 MB"),
        ]:
            with patch("drntu.rest.client.urlopen", return_value=response), self.assertRaisesRegex(RepositoryError, message):
                self.client.get("/example", dataset=dataset)
            self.assertFalse(self.client._cache)

    def test_service_failures_retry_and_public_access_denials_do_not(self):
        headers = Message()
        headers["Retry-After"] = "1"
        for error, attempts in [(URLError("untrusted detail"), 2),
                                (HTTPError("url", 503, "unavailable", headers, None), 2),
                                (HTTPError("url", 403, "denied", headers, None), 1),
                                (HTTPError("url", 404, "missing", headers, None), 1)]:
            with patch("drntu.rest.client.urlopen", side_effect=error) as fetch, self.assertRaises(RepositoryError) as caught:
                self.client.get("/example")
            self.assertEqual(fetch.call_count, attempts)
            self.assertNotIn("untrusted detail", str(caught.exception))
        headers.replace_header("Retry-After", "120")
        with patch("drntu.rest.client.urlopen", side_effect=HTTPError("url", 429, "limited", headers, None)) as fetch:
            with self.assertRaisesRegex(RepositoryError, "429"):
                self.client.get("/example")
            self.assertEqual(fetch.call_count, 1)

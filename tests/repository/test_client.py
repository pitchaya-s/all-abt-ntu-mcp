import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

from drntu.models import RepositoryError
from drntu.rest.client import RepositoryClient


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responses = []
        self.sleep = patch("shared.public_http.time.sleep").start()
        self.addCleanup(patch.stopall)
        self.client = RepositoryClient(transport=httpx.MockTransport(self.handle))
        self.addCleanup(self.client.http.close)

    def handle(self, request):
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)(request)
        return self.response(request)

    @staticmethod
    def response(request, data=None, content_type="application/json", body=None, status=200, headers=None):
        content = body if body is not None else json.dumps({"ok": True} if data is None else data).encode()
        return httpx.Response(
            status, headers={"content-type": content_type, **(headers or {})}, content=content, request=request,
        )

    def queue(self, **kwargs):
        self.responses.append(lambda request: self.response(request, **kwargs))

    def test_cache_refresh_expiry_and_bounded_entries(self):
        first = self.client.get("/core/items/example")
        self.assertFalse(first[1]["cached"])
        self.assertTrue(self.client.get("/core/items/example")[1]["cached"])
        self.assertEqual(first[1]["retrieved_at"], self.client.get("/core/items/example")[1]["retrieved_at"])
        self.client.get("/core/items/example", refresh=True)
        self.assertEqual(len(self.requests), 2)
        key = next(iter(self.client.http._cache))
        stamp, body, retrieved = self.client.http._cache[key]
        self.client.http._cache[key] = (stamp - 301, body, retrieved)
        self.assertFalse(self.client.get("/core/items/example")[1]["cached"])
        for number in range(65):
            self.client.get("/example/" + str(number))
        self.assertEqual(len(self.client.http._cache), 64)

    def test_query_encoding_preserves_multiple_filters_without_cookies(self):
        self.client.get("/discover/search/objects", {"query": "A & B", "f.subject": ["one,equals", "two,contains"]})
        request = self.requests[-1]
        params = parse_qs(request.url.query.decode())
        self.assertEqual(params["query"], ["A & B"])
        self.assertEqual(params["f.subject"], ["one,equals", "two,contains"])
        self.assertNotIn("cookie", request.headers)
        self.assertNotIn("authorization", request.headers)

    def test_captcha_html_json_errors_and_oversized_responses_are_not_cached(self):
        cases = [
            ({"body": b"<html>CAPTCHA</html>", "content_type": "text/html"}, True, "CAPTCHA"),
            ({"body": b"invalid json"}, False, "invalid JSON"),
            ({"data": [1]}, False, "unexpected response"),
            ({"body": b" " * 8_000_001}, False, "8 MB"),
        ]
        for response, dataset, message in cases:
            self.queue(**response)
            with self.assertRaisesRegex(RepositoryError, message):
                self.client.get("/example", dataset=dataset)
            self.assertFalse(self.client.http._cache)

    def test_service_failures_retry_and_public_access_denials_do_not(self):
        self.responses.extend([
            lambda request: self.response(request, status=503, headers={"retry-after": "0"}),
            lambda request: self.response(request),
        ])
        self.client.get("/retry")
        self.assertEqual(len(self.requests), 2)
        for status, message in [(403, "denied public access"), (404, "could not find")]:
            self.queue(status=status)
            with self.assertRaisesRegex(RepositoryError, message):
                self.client.get("/example")

        self.responses.append(lambda request: self.response(
            request, status=429, headers={"retry-after": "120"},
        ))
        before = len(self.requests)
        with self.assertRaisesRegex(RepositoryError, "HTTP 429"):
            self.client.get("/limited")
        self.assertEqual(len(self.requests) - before, 1)


if __name__ == "__main__":
    unittest.main()

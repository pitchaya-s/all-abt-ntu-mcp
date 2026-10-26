import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from unittest.mock import patch

import httpx

from shared.public_http import PublicHTTPClient, PublicRequestError

URL = "https://example.org/feed"


class PublicHTTPTests(unittest.TestCase):
    def make_client(self, handler, *, content_types=("application/json",)):
        client = PublicHTTPClient(
            "Example service", ["example.org", "static.example.org"], set(content_types),
            transport=httpx.MockTransport(handler),
        )
        self.addCleanup(client.close)
        return client

    def test_cache_refresh_expiry_and_no_auth_headers(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200, headers={"content-type": "application/json", "set-cookie": "session=private"},
                content=b"{}", request=request,
            )

        client = self.make_client(handle)
        with patch("shared.public_http.time.sleep"):
            first = client.get(URL)
            self.assertFalse(first[1]["cached"])
            self.assertTrue(client.get(URL)[1]["cached"])
            self.assertEqual(first[1]["retrieved_at"], client.get(URL)[1]["retrieved_at"])
            client.get(URL, refresh=True)
            self.assertEqual(len(requests), 2)
            stamp, body, retrieved = client._cache[URL]
            client._cache[URL] = (stamp - 301, body, retrieved)
            self.assertFalse(client.get(URL)[1]["cached"])
            self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertNotIn("cookie", request.headers)
            self.assertNotIn("authorization", request.headers)

    def test_only_allowed_https_redirects_are_followed(self):
        for url in [
            "http://example.org/feed", "https://evil.example/feed",
            "https://example.org:8443/feed", "https://user@example.org/feed",
        ]:
            with self.assertRaises(PublicRequestError):
                PublicHTTPClient("test", ["example.org"], {"application/json"}).redirects.validate(url)

        requests = []

        def allowed(request):
            requests.append(request)
            if request.url.host == "example.org":
                return httpx.Response(302, headers={"location": "https://static.example.org/feed"}, request=request)
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request)

        client = self.make_client(allowed)
        with patch("shared.public_http.time.sleep"):
            client.get(URL)
        self.assertEqual([request.url.host for request in requests], ["example.org", "static.example.org"])

        def denied(request):
            return httpx.Response(302, headers={"location": "https://evil.example/feed"}, request=request)

        unsafe = self.make_client(denied)
        with patch("shared.public_http.time.sleep"), self.assertRaises(PublicRequestError):
            unsafe.get(URL)

    def test_bad_content_and_oversized_responses_are_not_cached(self):
        for response in [
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>", request=request),
            lambda request: httpx.Response(
                200, headers={"content-type": "application/json"},
                content=b" " * (8_000_001), request=request,
            ),
        ]:
            client = self.make_client(response)
            with patch("shared.public_http.time.sleep"), self.assertRaises(PublicRequestError):
                client.get(URL)
            self.assertFalse(client._cache)

    def test_transient_failures_retry_once_without_leaking_details(self):
        for status, attempts in ((503, 2), (403, 1)):
            seen = []

            def handle(request, status=status, seen=seen):
                seen.append(request)
                return httpx.Response(status, headers={"retry-after": "0"}, request=request)

            client = self.make_client(handle)
            with patch("shared.public_http.time.sleep"), self.assertRaises(PublicRequestError) as caught:
                client.get(URL)
            self.assertEqual(len(seen), attempts)
            self.assertNotIn("private error detail", str(caught.exception))

        seen = []

        def connection_error(request):
            seen.append(request)
            raise httpx.ConnectError("private error detail", request=request)

        client = self.make_client(connection_error)
        with patch("shared.public_http.time.sleep"), self.assertRaises(PublicRequestError) as caught:
            client.get(URL)
        self.assertEqual(len(seen), 2)
        self.assertNotIn("private error detail", str(caught.exception))

    def test_rate_limits_honor_long_numeric_and_http_date_delays(self):
        for value in ["120", (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")]:
            seen = []

            def handle(request, value=value, seen=seen):
                seen.append(request)
                return httpx.Response(429, headers={"retry-after": value}, request=request)

            client = self.make_client(handle)
            with patch("shared.public_http.time.sleep"), self.assertRaises(PublicRequestError):
                client.get(URL)
            self.assertEqual(len(seen), 1)

    def test_independent_requests_can_overlap_but_same_url_is_single_flight(self):
        both_started = Barrier(2)
        requests = []

        def handle(request):
            requests.append(request.url.path)
            both_started.wait(timeout=2)
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request)

        client = self.make_client(handle)
        with patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.get, f"https://example.org/{path}") for path in ("one", "two")]
            [future.result(timeout=3) for future in futures]
        self.assertCountEqual(requests, ["/one", "/two"])

    def test_host_concurrency_is_shared_across_service_clients(self):
        host = "shared-scheduler.example"
        url = f"https://{host}/feed"
        first_entered = Event()
        second_entered = Event()
        release_first = Event()

        def first_handler(request):
            first_entered.set()
            if not release_first.wait(timeout=2):
                raise TimeoutError("first fixture request was not released")
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request)

        def second_handler(request):
            second_entered.set()
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request)

        first = PublicHTTPClient("first", [host], {"application/json"}, transport=httpx.MockTransport(first_handler))
        second = PublicHTTPClient("second", [host], {"application/json"}, transport=httpx.MockTransport(second_handler))
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        with (
            patch("shared.public_http.REQUEST_CONCURRENCY", 1),
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first_request = pool.submit(first.get, url)
            self.assertTrue(first_entered.wait(timeout=2))
            second_request = pool.submit(second.get, url)
            self.assertFalse(second_entered.wait(timeout=0.05))
            release_first.set()
            first_request.result(timeout=2)
            second_request.result(timeout=2)

        self.assertTrue(second_entered.is_set())

    def test_same_url_is_single_flight(self):
        entered = Event()
        release = Event()
        requests = []

        def handle(request):
            requests.append(request.url.path)
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test request was not released")
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request)

        client = self.make_client(handle)
        with patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.get, URL)
            self.assertTrue(entered.wait(timeout=2))
            second = pool.submit(client.get, URL)
            release.set()
            self.assertFalse(first.result(timeout=2)[1]["cached"])
            self.assertTrue(second.result(timeout=2)[1]["cached"])
        self.assertEqual(requests, ["/feed"])

    def test_closed_client_rejects_new_requests(self):
        client = self.make_client(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}", request=request))
        client.close()
        with self.assertRaisesRegex(PublicRequestError, "client is closed"):
            client.get(URL)

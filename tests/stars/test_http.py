import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from urllib.request import Request

import httpx

from stars.client import http
from stars.client.courses import BASE_URL
from stars.client.http import NTURequestError


class StarsHTTPTests(unittest.TestCase):
    def make_client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        self.addCleanup(client.close)
        return client

    def request(self, url=BASE_URL):
        return Request(url, headers={"User-Agent": http.USER_AGENT, "Accept": "text/html"})

    def test_public_client_does_not_retain_or_send_cookies(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8", "set-cookie": "session=private"},
                content=b"<html>ok</html>",
                request=request,
            )

        client = self.make_client(handle)
        client.cookies.jar.set_policy(http._NoCookies())
        with (
            patch.object(http, "_public_client", client),
            patch.object(http, "MIN_REQUEST_INTERVAL_SECONDS", 0),
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
        ):
            self.assertEqual(http._fetch_html_request(self.request(), "fixture"), "<html>ok</html>")
            self.assertEqual(http._fetch_html_request(self.request(), "fixture"), "<html>ok</html>")

        self.assertEqual(len(requests), 2)
        self.assertTrue(all("cookie" not in request.headers for request in requests))

    def test_redirect_outside_ntu_hosts_is_stopped_before_following(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                302,
                headers={"location": "https://attacker.example/collect"},
                request=request,
            )

        client = self.make_client(handle)
        with (
            patch.object(http, "_public_client", client),
            patch.object(http, "MIN_REQUEST_INTERVAL_SECONDS", 0),
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
            self.assertRaisesRegex(NTURequestError, "unexpected URL or redirect"),
        ):
            http._fetch_html_request(self.request(), "fixture")

        self.assertEqual(len(requests), 1)

    def test_transient_status_retries_and_decodes_legacy_charset(self):
        requests = []

        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(503, headers={"retry-after": "0"}, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content="caf\N{LATIN SMALL LETTER E WITH ACUTE}".encode("windows-1252"),
                request=request,
            )

        client = self.make_client(handle)
        with (
            patch.object(http, "_public_client", client),
            patch.object(http, "MIN_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(http, "MAX_RETRIES", 1),
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
        ):
            self.assertEqual(http._fetch_html_request(self.request(), "fixture"), "caf\N{LATIN SMALL LETTER E WITH ACUTE}")

        self.assertEqual(len(requests), 2)

    def test_concurrent_identical_public_requests_share_one_fetch(self):
        entered = Event()
        waiter_started = Event()
        release = Event()
        requests = []

        def handle(request):
            requests.append(request)
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("fixture request was not released")
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=b"<html>ok</html>", request=request
            )

        def wait_for_flight(flight):
            waiter_started.set()
            return flight.result()

        client = self.make_client(handle)
        client.cookies.jar.set_policy(http._NoCookies())
        with (
            patch.object(http, "_public_client", client),
            patch.object(http, "_await_inflight", side_effect=wait_for_flight),
            patch.object(http, "MIN_REQUEST_INTERVAL_SECONDS", 0),
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(http._fetch_html_request, self.request(), "fixture")
            self.assertTrue(entered.wait(timeout=2))
            second = pool.submit(http._fetch_html_request, self.request(), "fixture")
            self.assertTrue(waiter_started.wait(timeout=2))
            release.set()
            self.assertEqual(first.result(timeout=2), "<html>ok</html>")
            self.assertEqual(second.result(timeout=2), "<html>ok</html>")

        self.assertEqual(len(requests), 1)

    def test_html_type_and_size_limits_are_enforced(self):
        for headers, body, message in (
            ({"content-type": "application/json"}, b"{}", "expected HTML"),
            ({"content-type": "text/html", "content-length": str(http.MAX_RESPONSE_BYTES + 1)}, b"", "5 MB safety limit"),
        ):
            client = self.make_client(
                lambda request, headers=headers, body=body: httpx.Response(200, headers=headers, content=body, request=request)
            )
            with (
                patch.object(http, "_public_client", client),
                patch.object(http, "MIN_REQUEST_INTERVAL_SECONDS", 0),
                patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
                self.assertRaisesRegex(NTURequestError, message),
            ):
                http._fetch_html_request(self.request(), "fixture")


if __name__ == "__main__":
    unittest.main()

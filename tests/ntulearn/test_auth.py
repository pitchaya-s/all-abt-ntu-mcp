import asyncio
import http.cookiejar
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from ntulearn.client.browser_cookies import (
    SessionCookie,
    install_cookies,
    playwright_cookies,
    read_browser_cookie_sets,
)
from ntulearn.client.config import SessionConfig
from ntulearn.client.http import AuthGenerationChanged
from ntulearn.client.session import Session
from ntulearn.models import LearnError
from shared.credentials import CredentialError, Credentials

PREFIX = "/learn/api/public/v1"
COURSES = PREFIX + "/users/me/courses"
SECRET = "synthetic-session-secret-never-returned"
LOGIN_CREDENTIALS = Credentials(
    username="student001",
    email="student001@e.ntu.edu.sg",
    password="synthetic-password",
    revision="revision-one",
)


def cookies(value="expires:1,id:synthetic"):
    return (
        SessionCookie(
            "BbRouter", value, ".ntu.edu.sg", path="/", secure=True,
            domain_specified=True,
        ),
        SessionCookie(
            "XSRF-TOKEN", "synthetic-xsrf", "ntulearn.ntu.edu.sg", path="/learn",
            secure=True, domain_specified=False,
        ),
    )


def api_response(request, status=200, data=None, *, headers=None, content=None):
    if data is not None:
        return httpx.Response(status, json=data, headers=headers, request=request)
    return httpx.Response(status, content=content or b"", headers=headers, request=request)


class RoutingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request):
        result = self.handler(request)
        if hasattr(result, "__await__"):
            result = await result
        return result


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sessions = []

    async def asyncTearDown(self):
        await asyncio.gather(*(session.close() for session in self.sessions), return_exceptions=True)

    def make_session(
        self,
        handler,
        *,
        browser_reader=lambda: [],
        sso_login=None,
        external_handler=None,
        browser_cookies=False,
        transport_type="mock",
        **settings,
    ):
        env = {
            "NTULEARN_BROWSER_COOKIES": str(browser_cookies).lower(),
            "NTULEARN_REQUEST_INTERVAL_SECONDS": "0",
            **settings,
        }
        main_transport = (
            RoutingTransport(handler)
            if transport_type == "async"
            else httpx.MockTransport(handler)
        )
        external_transport = (
            httpx.MockTransport(external_handler)
            if external_handler is not None
            else None
        )
        async def unused_login(*args, **kwargs):
            raise AssertionError("SSO login was not expected")
        with patch.dict(os.environ, env):
            session = Session(
                browser_cookie_reader=browser_reader,
                sso_login=sso_login or unused_login,
                transport=main_transport,
                external_transport=external_transport,
            )
        self.sessions.append(session)
        return session

    def authenticated_handler(self, request):
        if request.url.path == PREFIX + "/users/me":
            return api_response(request, data={"id": "_900_1"})
        if request.url.path == COURSES:
            return api_response(request, data={"results": [{"id": "_100_1"}]})
        return api_response(request, status=404)

    async def test_config_bounds_and_browser_discovery_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = SessionConfig.from_env()
        self.assertFalse(config.browser_cookies)
        self.assertEqual(config.request_concurrency, 4)
        self.assertEqual(config.request_interval_seconds, 0.1)
        for env in (
            {"NTULEARN_REQUEST_CONCURRENCY": "0"},
            {"NTULEARN_REQUEST_CONCURRENCY": "9"},
            {"NTULEARN_REQUEST_INTERVAL_SECONDS": "nan"},
            {"NTULEARN_TIMEOUT_SECONDS": "0"},
            {"NTULEARN_BROWSER_COOKIES": "yes"},
        ):
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(LearnError):
                SessionConfig.from_env()

    async def test_transport_rejects_queued_requests_with_an_old_auth_generation(self):
        sent = []

        def handler(request):
            sent.append(request)
            return api_response(request, data={"results": []})

        session = self.make_session(handler)
        session.http.set_cookies(cookies(), generation=2)
        with self.assertRaises(AuthGenerationChanged):
            await session.http.get(COURSES, expected_generation=1)
        with self.assertRaises(AuthGenerationChanged):
            await session.http.download_bytes(
                PREFIX + "/courses/_1_1/contents/_2_1/attachments/_3_1/download",
                1000,
                expected_generation=1,
            )
        self.assertEqual(sent, [])

    async def test_stale_response_cannot_overwrite_rotated_session_cookies(self):
        request_started = asyncio.Event()
        release_response = asyncio.Event()
        received_cookie = []

        async def handler(request):
            received_cookie.append(request.headers.get("cookie", ""))
            request_started.set()
            await release_response.wait()
            return api_response(
                request,
                data={"results": []},
                headers={"set-cookie": "BbRouter=stale-response; Domain=ntu.edu.sg; Path=/; Secure"},
            )

        session = self.make_session(handler, transport_type="async")
        session.http.set_cookies(cookies("expires:1,id:old"), generation=0)
        request = asyncio.create_task(
            session.http.get(COURSES, expected_generation=0)
        )
        await request_started.wait()
        session.http.set_cookies(cookies("expires:1,id:new"), generation=1)
        release_response.set()
        with self.assertRaises(AuthGenerationChanged):
            await request
        self.assertIn("id:old", received_cookie[0])
        self.assertTrue(any(cookie.value == "expires:1,id:new" for cookie in session.http.client.cookies.jar))

    def test_browser_cookie_extraction_keeps_a_scoped_cookie_set_per_browser(self):
        seen = []

        def cookie(name, value, domain, *, expires=None):
            return SimpleNamespace(
                name=name, value=value, domain=domain, path="/", expires=expires,
                secure=True, domain_specified=domain.startswith("."), _rest={},
            )

        class BrowserModule:
            def edge(self, *, domain_name):
                seen.append(("edge", domain_name))
                raise OSError(SECRET)

            def chrome(self, *, domain_name):
                seen.append(("chrome", domain_name))
                return [
                    cookie("BbRouter", "expires:1,id:chrome", ".ntu.edu.sg"),
                    cookie("JSESSIONID", "secondary", "ntulearn.ntu.edu.sg"),
                    cookie("other", "foreign", ".example.invalid"),
                    cookie("expired", "old", ".ntu.edu.sg", expires=1),
                    cookie("unsafe", "bad\r\nvalue", ".ntu.edu.sg"),
                ]

            def firefox(self, *, domain_name):
                seen.append(("firefox", domain_name))
                return [cookie("BbRouter", "expires:1,id:firefox", ".ntu.edu.sg")]

        result = read_browser_cookie_sets(module=BrowserModule(), browsers=("edge", "chrome", "firefox"))
        self.assertEqual(seen, [("edge", "ntu.edu.sg"), ("chrome", "ntu.edu.sg"), ("firefox", "ntu.edu.sg")])
        self.assertEqual(len(result), 2)
        self.assertEqual({item.name for item in result[0]}, {"BbRouter", "JSESSIONID"})
        self.assertEqual(result[1][0].value, "expires:1,id:firefox")
        self.assertNotIn(SECRET, repr(result))

    def test_playwright_cookies_keep_all_ntulearn_state_and_reject_other_domains(self):
        result = playwright_cookies([
            {"name": "BbRouter", "value": "expires:1,id:one", "domain": ".ntu.edu.sg", "path": "/", "secure": True},
            {"name": "JSESSIONID", "value": "state", "domain": "ntulearn.ntu.edu.sg", "path": "/learn", "secure": True},
            {"name": "MSAuth", "value": "secret", "domain": "login.microsoftonline.com", "path": "/", "secure": True},
        ])
        self.assertEqual({cookie.name for cookie in result}, {"BbRouter", "JSESSIONID"})
        self.assertNotIn("secret", repr(result))
        jar = http.cookiejar.CookieJar()
        install_cookies(jar, result)
        self.assertEqual(len(list(jar)), 2)
        self.assertEqual(
            playwright_cookies([
                {"name": "BbRouter", "value": "malformed", "domain": "..ntu.edu.sg"},
                {"name": "BbRouter", "value": "malformed", "domain": None},
            ]),
            (),
        )

    async def test_validated_browser_cookies_skip_sso_and_are_reused(self):
        requests = []
        sso = AsyncMock()

        def handler(request):
            requests.append(request)
            return self.authenticated_handler(request)

        session = self.make_session(
            handler,
            browser_reader=lambda: [cookies()],
            sso_login=sso,
            browser_cookies=True,
        )
        first, freshness = await session.get(COURSES)
        second, cached = await session.get(COURSES)
        self.assertEqual(first, second)
        self.assertFalse(freshness["from_cache"])
        self.assertTrue(cached["from_cache"])
        self.assertEqual(len(requests), 2)
        self.assertIn("BbRouter=expires:1,id:synthetic", requests[-1].headers["cookie"])
        self.assertIn("XSRF-TOKEN=synthetic-xsrf", requests[-1].headers["cookie"])
        sso.assert_not_awaited()
        with patch("ntulearn.client.session.credential_status", return_value={
            "credentials_configured": False,
            "credential_storage": "os_keyring",
            "credential_error": None,
        }):
            status = await session.status()
        self.assertTrue(status.session_verified)
        self.assertEqual(status.authentication_method, "browser_cookie")

    async def test_invalid_browser_cookie_is_rejected_before_sso_fallback(self):
        seen = []

        def handler(request):
            seen.append((request.url.path, request.headers.get("cookie", "")))
            if request.url.path == PREFIX + "/users/me":
                if "id:valid" in request.headers.get("cookie", ""):
                    return api_response(request, data={"id": "_900_1"})
                return api_response(request, status=401)
            return api_response(request, data={"results": []})

        async def sso(credentials, *, headless):
            return cookies("expires:1,id:valid")

        session = self.make_session(
            handler,
            browser_reader=lambda: [cookies("expires:1,id:stale")],
            sso_login=sso,
            browser_cookies=True,
        )
        with patch("ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS):
            await session.get(COURSES)
        self.assertEqual(seen[0][0], PREFIX + "/users/me")
        self.assertIn("id:stale", seen[0][1])
        self.assertIn("id:valid", seen[1][1])
        self.assertEqual(session.auth.state.method, "sso")

    async def test_browser_extraction_failure_falls_back_without_leaking_error(self):
        async def sso(credentials, *, headless):
            return cookies("expires:1,id:sso")

        def broken_reader():
            raise RuntimeError(SECRET)

        session = self.make_session(
            self.authenticated_handler,
            browser_reader=broken_reader,
            sso_login=sso,
            browser_cookies=True,
        )
        with patch("ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS):
            data, _ = await session.get(COURSES)
        self.assertEqual(data["results"][0]["id"], "_100_1")
        self.assertNotIn(SECRET, str(session.auth.state))

    async def test_browser_discovery_opt_in_is_enforced(self):
        reader = Mock(return_value=[cookies()])

        async def sso(credentials, *, headless):
            return cookies("expires:1,id:sso")

        session = self.make_session(self.authenticated_handler, browser_reader=reader, sso_login=sso)
        with patch("ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS):
            await session.get(COURSES)
        reader.assert_not_called()
        self.assertEqual(session.auth.state.method, "sso")

    async def test_sso_is_lazy_and_uses_credentials_only_after_cookie_discovery(self):
        reader = Mock(return_value=[])
        logins = []

        async def sso(credentials, *, headless):
            logins.append((credentials.revision, headless))
            return cookies("expires:1,id:sso")

        session = self.make_session(
            self.authenticated_handler,
            browser_reader=reader,
            sso_login=sso,
            browser_cookies=True,
        )
        with patch("ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS):
            self.assertIsNone(session.auth.state)
            await session.get(COURSES)
            await session.get(COURSES)
        self.assertEqual(logins, [("revision-one", True)])
        self.assertEqual(reader.call_count, 1)

    async def test_tool_operation_checks_keyring_once_across_concurrent_reads(self):
        reads = 0

        def read():
            nonlocal reads
            reads += 1
            return LOGIN_CREDENTIALS

        async def sso(credentials, *, headless):
            return cookies("expires:1,id:sso")

        session = self.make_session(self.authenticated_handler, sso_login=sso)
        with patch("ntulearn.client.auth.read_credentials", side_effect=read):
            async with session.operation():
                await asyncio.gather(
                    session.get(COURSES, {"offset": 0}, True),
                    session.get(COURSES, {"offset": 1}, True),
                )
                await session.get(COURSES, {"offset": 2}, True)
            self.assertEqual(reads, 1)
            async with session.operation():
                await session.get(COURSES, {"offset": 3}, True)
            self.assertEqual(reads, 2)

    async def test_sso_login_failure_is_sanitized_and_rate_limited(self):
        calls = 0

        async def broken_login(credentials, *, headless):
            nonlocal calls
            calls += 1
            raise RuntimeError(SECRET)

        session = self.make_session(self.authenticated_handler, sso_login=broken_login)
        with patch("ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS):
            with self.assertRaises(LearnError) as error:
                await session.get(COURSES)
            self.assertNotIn(SECRET, str(error.exception))
            with self.assertRaisesRegex(LearnError, "recent login"):
                await session.get(COURSES)
        self.assertEqual(calls, 1)

    async def test_sso_mfa_is_never_bypassed_and_visible_browser_can_complete_it(self):
        class Page:
            def __init__(self):
                self.stage = "challenge"
                self.waits = []

            @property
            def url(self):
                if self.stage == "authenticated":
                    return "https://ntulearn.ntu.edu.sg/ultra/institution-page"
                return "https://login.microsoftonline.com/example/saml2"

            async def goto(self, *args, **kwargs):
                pass

            def locator(self, selector):
                return Body(self) if selector == "body" else EmptyLocator()

            async def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)
                self.stage = "authenticated"

        class Body:
            def __init__(self, page):
                self.page = page

            async def inner_text(self, **kwargs):
                return "Approve sign-in using Microsoft Authenticator"

        class EmptyLocator:
            @property
            def first(self):
                return self

            async def count(self):
                return 0

        page = Page()
        context = SimpleNamespace(
            new_page=AsyncMock(return_value=page),
            cookies=AsyncMock(return_value=[{
                "name": "BbRouter", "value": "expires:1,id:mfa", "domain": ".ntu.edu.sg", "path": "/", "secure": True,
            }]),
        )
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))

        class Manager:
            async def __aenter__(self):
                return playwright

            async def __aexit__(self, *args):
                return None

        package = ModuleType("playwright")
        package.__path__ = []
        api = ModuleType("playwright.async_api")
        api.async_playwright = Manager
        modules = {"playwright": package, "playwright.async_api": api}
        with patch.dict(sys.modules, modules):
            from ntulearn.client.sso import login

            with self.assertRaisesRegex(LearnError, "MFA or CAPTCHA"):
                await login(LOGIN_CREDENTIALS, headless=True)
            result = await login(LOGIN_CREDENTIALS, headless=False)
        self.assertEqual(result[0].name, "BbRouter")
        self.assertTrue(page.waits)
        self.assertGreaterEqual(browser.close.await_count, 2)

    async def test_concurrent_initial_requests_share_one_authentication_attempt(self):
        count = 0
        guard = Lock()
        active = maximum_active = 0

        def slow_reader():
            nonlocal count
            with guard:
                count += 1
            import time
            time.sleep(0.03)
            return [cookies()]

        async def handler(request):
            nonlocal active, maximum_active
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return api_response(request, data={"results": []})

        session = self.make_session(
            handler,
            browser_reader=slow_reader,
            browser_cookies=True,
            transport_type="async",
            **{"NTULEARN_REQUEST_CONCURRENCY": "2"},
        )
        results = await asyncio.gather(*(
            session.get(COURSES, {"offset": offset}, refresh=True)
            for offset in range(8)
        ))
        self.assertEqual(len(results), 8)
        self.assertEqual(count, 1)
        self.assertEqual(maximum_active, 2)

    async def test_simultaneous_401s_share_one_refresh_and_retry(self):
        pending = asyncio.Event()
        count_lock = asyncio.Lock()
        course_calls = 0
        browser_reads = 0

        def reader():
            nonlocal browser_reads
            browser_reads += 1
            return [cookies()]

        async def handler(request):
            nonlocal course_calls
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            async with count_lock:
                course_calls += 1
                current = course_calls
                if current == 2:
                    pending.set()
            if current <= 2:
                await pending.wait()
                return api_response(request, status=401)
            return api_response(request, data={"results": [{"offset": request.url.params.get("offset")}]})

        session = self.make_session(
            handler,
            browser_reader=reader,
            browser_cookies=True,
            transport_type="async",
        )
        results = await asyncio.gather(
            session.get(COURSES, {"offset": 0}, True),
            session.get(COURSES, {"offset": 1}, True),
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(browser_reads, 2)  # initial discovery plus one shared refresh
        self.assertEqual(course_calls, 4)
        self.assertEqual(session.auth.state.generation, 1)

    async def test_expired_session_rotates_browser_cookies_and_invalidates_cache(self):
        cookie_sets = iter([cookies("expires:1,id:old"), cookies("expires:1,id:new")])
        seen = []

        def handler(request):
            value = request.headers.get("cookie", "")
            seen.append((request.url.path, value))
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            if "id:old" in value:
                return api_response(request, status=401)
            return api_response(request, data={"results": [{"version": "new"}]})

        session = self.make_session(
            handler,
            browser_reader=lambda: [next(cookie_sets)],
            browser_cookies=True,
        )
        data, freshness = await session.get(COURSES, refresh=True)
        self.assertEqual(data["results"][0]["version"], "new")
        self.assertFalse(freshness["from_cache"])
        self.assertIn("id:old", seen[1][1])
        self.assertIn("id:new", seen[-1][1])
        self.assertEqual(session.auth.state.method, "browser_cookie")

    async def test_credential_rotation_reauthenticates_and_revocation_clears_cache(self):
        current = LOGIN_CREDENTIALS
        login_revisions = []
        api_calls = 0

        def read():
            if isinstance(current, Exception):
                raise current
            return current

        async def sso(credentials, *, headless):
            login_revisions.append(credentials.revision)
            return cookies(f"expires:1,id:{credentials.revision}")

        def handler(request):
            nonlocal api_calls
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            api_calls += 1
            return api_response(request, data={"results": [{"version": api_calls}]})

        session = self.make_session(handler, sso_login=sso)
        with patch("ntulearn.client.auth.read_credentials", side_effect=read):
            first, _ = await session.get(COURSES)
            self.assertEqual((await session.get(COURSES))[1]["from_cache"], True)
            current = Credentials("student001", "student001@e.ntu.edu.sg", "new-password", "revision-two")
            second, freshness = await session.get(COURSES)
            self.assertFalse(freshness["from_cache"])
            self.assertEqual(second["results"][0]["version"], 2)
            self.assertEqual(login_revisions, ["revision-one", "revision-two"])
            current = CredentialError("The native OS keyring is unavailable or locked.")
            with self.assertRaises(LearnError) as error:
                await session.get(COURSES)
            self.assertNotIn("new-password", str(error.exception))
            self.assertNotIn("revision-two", str(error.exception))
        self.assertEqual(first["results"][0]["version"], 1)
        self.assertEqual(session.cache._entries, {})

    async def test_inflight_old_account_response_cannot_repopulate_cleared_cache(self):
        current = LOGIN_CREDENTIALS
        old_request_started = asyncio.Event()
        release_old_request = asyncio.Event()
        old_requests = 0

        async def sso(credentials, *, headless):
            return cookies(f"expires:1,id:{credentials.revision}")

        async def handler(request):
            nonlocal old_requests
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            if request.url.params.get("offset") == "0" and old_requests == 0:
                old_requests += 1
                old_request_started.set()
                await release_old_request.wait()
                return api_response(request, data={"results": [{"account": "old"}]})
            revision = "new" if "revision-two" in request.headers.get("cookie", "") else "old"
            return api_response(request, data={"results": [{"account": revision}]})

        session = self.make_session(handler, sso_login=sso, transport_type="async")
        with patch("ntulearn.client.auth.read_credentials", side_effect=lambda: current):
            old_read = asyncio.create_task(session.get(COURSES, {"offset": 0}, True))
            await old_request_started.wait()
            current = Credentials("student001", "student001@e.ntu.edu.sg", "new-password", "revision-two")
            await session.get(COURSES, {"offset": 1}, True)
            release_old_request.set()
            old_data, _ = await old_read
            # A response issued with the previous account's cookies is
            # discarded; Session retries under the newly installed identity.
            self.assertEqual(old_data["results"][0]["account"], "new")

            fresh_data, freshness = await session.get(COURSES, {"offset": 0})
        self.assertEqual(fresh_data["results"][0]["account"], "new")
        self.assertTrue(freshness["from_cache"])

    async def test_429_retry_after_and_transient_5xx_are_retried(self):
        attempts = 0

        def handler(request):
            nonlocal attempts
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            attempts += 1
            if attempts == 1:
                return api_response(request, status=503, data={"error": "temporary"})
            if attempts == 2:
                return api_response(request, status=429, headers={"Retry-After": "2"}, data={"error": "slow down"})
            return api_response(request, data={"results": []})

        session = self.make_session(handler, browser_reader=lambda: [cookies()], browser_cookies=True)
        with patch("ntulearn.client.http.asyncio.sleep", new=AsyncMock()) as sleep:
            await session.get(COURSES, refresh=True)
        self.assertEqual(attempts, 3)
        sleep.assert_any_await(1.0)
        sleep.assert_any_await(2.0)

    async def test_excessive_retry_after_and_bad_json_fail_closed(self):
        def slow(request):
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            return api_response(request, status=429, headers={"Retry-After": "61"})

        session = self.make_session(slow, browser_reader=lambda: [cookies()], browser_cookies=True)
        with patch("ntulearn.client.http.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(LearnError, "longer than one minute"):
                await session.get(COURSES, refresh=True)

        def malformed(request):
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            return api_response(request, content=b"not-json", headers={"content-type": "application/json"})

        bad = self.make_session(malformed, browser_reader=lambda: [cookies()], browser_cookies=True)
        with self.assertRaisesRegex(LearnError, "malformed JSON"):
            await bad.get(COURSES, refresh=True)

    async def test_read_only_allowlist_and_cache_bypass(self):
        calls = 0

        def handler(request):
            nonlocal calls
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            calls += 1
            return api_response(request, data={"results": [{"call": calls}]})

        session = self.make_session(handler, browser_reader=lambda: [cookies()], browser_cookies=True)
        with self.assertRaisesRegex(LearnError, "not an academic JSON read endpoint"):
            await session.get("https://other.invalid/private")
        first, _ = await session.get(COURSES)
        first["results"].clear()
        cached, metadata = await session.get(COURSES)
        self.assertEqual(cached["results"], [{"call": 1}])
        self.assertTrue(metadata["from_cache"])
        fresh, metadata = await session.get(COURSES, refresh=True)
        self.assertEqual(fresh["results"], [{"call": 2}])
        self.assertFalse(metadata["from_cache"])
        self.assertEqual(calls, 2)

    async def test_external_download_redirect_never_receives_ntu_cookies(self):
        external_headers = []
        download_requests = 0
        path = f"{PREFIX}/courses/_1_1/contents/_2_1/attachments/_3_1/download"

        def internal(request):
            nonlocal download_requests
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            self.assertIn("BbRouter=", request.headers.get("cookie", ""))
            download_requests += 1
            host = "files.blackboard.com" if download_requests == 1 else "cdn.blackboardcdn.com"
            return api_response(request, 302, headers={"Location": f"https://{host}/file.pdf"})

        def external(request):
            external_headers.append(dict(request.headers))
            return api_response(request, content=b"%PDF-fixture", headers={
                "Content-Type": "application/pdf",
                "Set-Cookie": "vendor-session=must-not-be-reused; Domain=.blackboard.com; Path=/",
            })

        session = self.make_session(
            internal,
            browser_reader=lambda: [cookies()],
            external_handler=external,
            browser_cookies=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            for name in ("first.pdf", "second.pdf"):
                target = Path(directory) / name
                result = await session.download(path, str(target))
                self.assertEqual(target.read_bytes(), b"%PDF-fixture")
                self.assertEqual(result.bytes_written, len(b"%PDF-fixture"))
            self.assertEqual(len(external_headers), 2)
            self.assertTrue(all("cookie" not in headers for headers in external_headers))
            with self.assertRaisesRegex(LearnError, "never overwritten"):
                await session.download(path, str(Path(directory) / "first.pdf"))

    async def test_untrusted_download_redirect_is_rejected_without_requesting_it(self):
        path = f"{PREFIX}/courses/_1_1/contents/_2_1/attachments/_3_1/download"
        external = Mock()

        def internal(request):
            if request.url.path == PREFIX + "/users/me":
                return api_response(request, data={"id": "_900_1"})
            return api_response(request, 302, headers={"Location": "https://evil.invalid/file"})

        session = self.make_session(
            internal,
            browser_reader=lambda: [cookies()],
            external_handler=external,
            browser_cookies=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(LearnError, "unsupported external download host"):
                await session.download(path, str(Path(directory) / "file"))
        external.assert_not_called()

    async def test_cancellation_and_shutdown_close_pending_authentication(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        class BlockingTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        session = self.make_session(
            self.authenticated_handler,
            browser_reader=lambda: [cookies()],
            browser_cookies=True,
            transport_type="async",
        )
        await session.http.aclose()
        session.http.client = httpx.AsyncClient(
            base_url="https://ntulearn.ntu.edu.sg",
            follow_redirects=False,
            transport=BlockingTransport(),
        )
        request = asyncio.create_task(session.get(COURSES))
        await asyncio.wait_for(entered.wait(), 1)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(session.close(), 1)
        self.assertTrue(cancelled.is_set())
        with self.assertRaisesRegex(LearnError, "closed"):
            await session.get(COURSES)

    async def test_shutdown_waits_until_an_active_tool_operation_finishes(self):
        halfway = asyncio.Event()
        resume = asyncio.Event()
        session = self.make_session(
            self.authenticated_handler,
            browser_reader=lambda: [cookies()],
            browser_cookies=True,
        )

        async def operation():
            async with session.operation():
                await session.get(COURSES, {"offset": 0}, True)
                halfway.set()
                await resume.wait()
                await session.get(COURSES, {"offset": 1}, True)

        request = asyncio.create_task(operation())
        await halfway.wait()
        shutdown = asyncio.create_task(session.close())
        await asyncio.sleep(0)
        self.assertFalse(shutdown.done())
        resume.set()
        await request
        await shutdown


class SsoFlowTests(unittest.IsolatedAsyncioTestCase):
    def modules_for(self, page, context, browser):
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))

        class Manager:
            async def __aenter__(self):
                return playwright

            async def __aexit__(self, *args):
                return None

        package = ModuleType("playwright")
        package.__path__ = []
        api = ModuleType("playwright.async_api")
        api.async_playwright = Manager
        return {"playwright": package, "playwright.async_api": api}

    async def test_sso_form_only_submits_to_expected_hosts_and_returns_cookies(self):
        fills = []

        class Page:
            stage = "email"

            @property
            def url(self):
                if self.stage == "authenticated":
                    return "https://ntulearn.ntu.edu.sg/ultra/institution-page"
                return "https://login.microsoftonline.com/example/saml2"

            async def goto(self, *args, **kwargs):
                pass

            def locator(self, selector):
                if selector == "body":
                    return Body(self)
                if "loginfmt" in selector:
                    return Locator(self, "email")
                if "password" in selector:
                    return Locator(self, "password")
                return Locator(self, "back")

            def get_by_role(self, role, name, **kwargs):
                return Locator(self, name)

            async def wait_for_timeout(self, milliseconds):
                pass

        class Body:
            def __init__(self, page):
                self.page = page

            async def inner_text(self, **kwargs):
                return {"email": "Sign in", "password": "Enter password", "stay": "Stay signed in?", "authenticated": "Courses"}[self.page.stage]

        class Locator:
            def __init__(self, page, name):
                self.page, self.name = page, name

            @property
            def first(self):
                return self

            async def count(self):
                return int((self.name == "email" and self.page.stage == "email")
                           or (self.name == "password" and self.page.stage == "password")
                           or (self.name == "back" and self.page.stage == "stay"))

            async def fill(self, value):
                fills.append((self.page.url, value))

            async def wait_for(self, **kwargs):
                pass

            async def click(self):
                if self.name == "Next":
                    self.page.stage = "password"
                elif self.name == "Sign in":
                    self.page.stage = "stay"
                elif self.name == "back":
                    self.page.stage = "authenticated"

        page = Page()
        context = SimpleNamespace(
            new_page=AsyncMock(return_value=page),
            cookies=AsyncMock(return_value=[{
                "name": "BbRouter", "value": "expires:1,id:sso", "domain": ".ntu.edu.sg", "path": "/", "secure": True,
            }]),
        )
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        with patch.dict(sys.modules, self.modules_for(page, context, browser)):
            from ntulearn.client.sso import login

            result = await login(LOGIN_CREDENTIALS, headless=True)
        self.assertEqual([value for _, value in fills], [LOGIN_CREDENTIALS.email, LOGIN_CREDENTIALS.password])
        self.assertTrue(all(url.startswith("https://login.microsoftonline.com/") for url, _ in fills))
        self.assertEqual(result[0].name, "BbRouter")
        browser.close.assert_awaited_once()

    async def test_sso_stops_before_entering_credentials_on_unexpected_host(self):
        class Page:
            url = "https://attacker.invalid/login"

            async def goto(self, *args, **kwargs):
                pass

        context = SimpleNamespace(new_page=AsyncMock(return_value=Page()))
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        with patch.dict(sys.modules, self.modules_for(None, context, browser)):
            from ntulearn.client.sso import login

            with self.assertRaisesRegex(LearnError, "unexpected host"):
                await login(LOGIN_CREDENTIALS, headless=True)
        browser.close.assert_awaited_once()

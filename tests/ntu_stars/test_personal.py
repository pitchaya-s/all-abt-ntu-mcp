from shared.credentials import delete_credentials
from tests.credential_fixtures import stored_credentials
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ntu_stars_mcp.wish.forms import _is_login_page
from ntu_stars_mcp.wish.models import NTUAuthError
from ntu_stars_mcp.wish.session import (
    DEGREE_AUDIT_URL,
    LOGIN_URL,
    PLANNER_URL,
    WishSessionManager,
)
from ntu_stars_mcp.ntu_client import NTURequestError
from ntu_stars_mcp.parser import NTUPageError, parse_degree_audit_page, parse_stars_planner_page


FIXTURES = Path(__file__).parent / "fixtures"
PLANNER_HTML = (FIXTURES / "personal-stars-planner-sanitized.html").read_text()
AUDIT_HTML = (FIXTURES / "personal-degree-audit-sanitized.html").read_text()
USER_FORM = '<form action="/pls/webexe/ldap_login.login" method="post"><input name="UID" id="UID"><input type="submit" value="OK"></form>'
PASSWORD_FORM = '<form action="/pls/webexe/ldap_login.login" method="post"><input name="PW" id="PW" type="password"><input type="submit" value="OK"></form>'


class PersonalParserTests(unittest.TestCase):
    def test_stars_planner_extracts_registered_courses_and_timetable_tables(self) -> None:
        result = parse_stars_planner_page(PLANNER_HTML)
        self.assertEqual(result["service"], "stars_planner")
        self.assertEqual(result["registered_courses"][0]["course_code"], "ZZ0001")
        self.assertEqual(result["registered_courses_status"], "parsed")
        self.assertEqual(result["registered_courses"][0]["Index No"], "00001")
        self.assertEqual(len(result["timetable_tables"]), 1)
        self.assertEqual(result["timetable_tables"][0]["records"][0]["Day"], "TUE")

    def test_degree_audit_extracts_academic_tables_and_excludes_identity_tables(self) -> None:
        result = parse_degree_audit_page(AUDIT_HTML)
        self.assertEqual(result["requirements"][0]["records"][0]["Balance AU"], "15")
        self.assertEqual(result["requirements_status"], "parsed")
        self.assertEqual(result["examination_results"][0]["records"][0]["Grade"], "A")
        self.assertEqual(result["courses_registered"][0]["records"][0]["Index No"], "00002")
        self.assertEqual(len(result["requirements"]), 1)
        self.assertEqual(len(result["examination_results"]), 1)
        self.assertEqual(len(result["courses_registered"]), 1)
        self.assertNotIn("REDACTED", repr(result))

    def test_unrecognized_personal_pages_are_rejected(self) -> None:
        with self.assertRaisesRegex(NTUPageError, "not recognizable"):
            parse_stars_planner_page("<html><title>Unexpected</title><body>Changed</body></html>")
        with self.assertRaisesRegex(NTUPageError, "not recognizable"):
            parse_degree_audit_page("<html><title>Unexpected</title><body>Changed</body></html>")


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.request = type("Request", (), {"resource_type": "document"})()


class _FakeLocator:
    def __init__(self, page, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def fill(self, value: str) -> None:
        field = "UID" if "UID" in self.selector else "PW"
        self.page.filled[field] = value

    def click(self) -> None:
        if "submit" not in self.selector:
            return
        self.page.submit_count += 1
        if "UID" in self.page.filled and "PW" not in self.page.filled:
            self.page.html = "<p>MFA verification code</p>" if self.page.challenge else PASSWORD_FORM
        elif self.page.invalid:
            self.page.html = '<p>Invalid username or password</p><form><input name="UID"></form>'
        else:
            self.page.authenticated = True
            self.page.html = "<html><title>STARS Login</title><body>Login successful</body></html>"
        self.page.emit(200)


class _FakePage:
    def __init__(self, *, invalid: bool = False, challenge: bool = False, status: int = 200) -> None:
        self.invalid = invalid
        self.challenge = challenge
        self.status = status
        self.authenticated = False
        self.expired = False
        self.destination = PLANNER_URL
        self.html = ""
        self.url = ""
        self.filled: dict[str, str] = {}
        self.submit_count = 0
        self.goto_count = 0
        self.listener = None
        self.form_action = "/pls/webexe/ldap_login.login"
        self.form_method = "post"

    def on(self, event: str, callback) -> None:
        if event == "response":
            self.listener = callback

    def emit(self, status: int) -> None:
        if self.listener:
            self.listener(_FakeResponse(status))

    def goto(self, url: str, **_kwargs):
        self.goto_count += 1
        if self.status != 200:
            self.emit(self.status)
            return _FakeResponse(self.status)
        self.destination = parse_qs(urlsplit(url).query).get("w_url", [url])[0]
        if not self.authenticated or self.expired:
            self.html = USER_FORM.replace('/pls/webexe/ldap_login.login', self.form_action).replace('method="post"', f'method="{self.form_method}"')
            self.url = LOGIN_URL
            self.expired = False
        else:
            self.show_destination()
        self.emit(200)
        return _FakeResponse(200)

    def show_destination(self) -> None:
        if "DARS_RESULT_RO" in self.destination:
            self.html = AUDIT_HTML
            self.url = DEGREE_AUDIT_URL
        else:
            self.html = PLANNER_HTML + "<!-- failed -->"
            self.url = PLANNER_URL

    def locator(self, selector: str):
        return _FakeLocator(self, selector)

    def wait_for_load_state(self, *_args, **_kwargs) -> None:
        return None

    def wait_for_function(self, *_args, **_kwargs) -> None:
        if "Login successful" in self.html:
            self.show_destination()
            self.emit(200)

    def content(self) -> str:
        return self.html


class WishSessionTests(unittest.TestCase):
    def _manager(self, page: _FakePage | None = None) -> WishSessionManager:
        credentials = stored_credentials()
        credentials.__enter__()
        self.addCleanup(credentials.__exit__, None, None, None)
        manager = WishSessionManager()
        self.addCleanup(manager.close)
        if page is not None:
            page.on("response", manager._record_browser_response)
            manager._page = page
        parser = patch("ntu_stars_mcp.wish.session.read_stars_planner", side_effect=lambda page: parse_stars_planner_page(page.content()))
        parser.start()
        self.addCleanup(parser.stop)
        return manager

    def test_stars_login_success_landing_is_not_mistaken_for_login_form(self) -> None:
        self.assertFalse(_is_login_page("<html><title>STARS Login</title><body>Login successful</body></html>"))
        self.assertTrue(_is_login_page("<html><body>Session expired. Please log in.</body></html>"))

    def test_browser_login_reuses_session_and_personal_cache(self) -> None:
        page = _FakePage()
        manager = self._manager(page)
        planner = manager.get_stars_planner()
        cached = manager.get_stars_planner()
        audit = manager.get_degree_audit()

        self.assertEqual(page.submit_count, 2)
        self.assertEqual(page.goto_count, 2)
        self.assertEqual(page.filled, {"UID": "test-user", "PW": "test-secret"})
        self.assertFalse(planner["from_cache"])
        self.assertTrue(cached["from_cache"])
        self.assertEqual(audit["service"], "degree_audit")
        self.assertTrue(manager.status()["session_verified"])

    def test_expired_session_reauthenticates_once(self) -> None:
        page = _FakePage()
        page.authenticated = True
        page.expired = True
        manager = self._manager(page)
        result = manager._fetch_authenticated(PLANNER_URL, "planner")
        self.assertTrue(result.startswith(PLANNER_HTML))
        self.assertEqual(page.submit_count, 2)

    def test_refresh_bypasses_personal_cache(self) -> None:
        page = _FakePage()
        manager = self._manager(page)
        manager.get_stars_planner()
        fresh = manager.get_stars_planner(refresh=True)
        self.assertFalse(fresh["from_cache"])
        self.assertEqual(page.goto_count, 2)

    def test_planner_expiry_during_load_reopens_authenticated_flow_once(self) -> None:
        page = _FakePage()
        manager = self._manager(page)
        with patch("ntu_stars_mcp.wish.session.read_stars_planner", side_effect=[None, parse_stars_planner_page(PLANNER_HTML)]):
            result = manager.get_stars_planner()
        self.assertEqual(result["registered_courses_status"], "parsed")
        self.assertEqual(page.goto_count, 2)
        with patch("ntu_stars_mcp.wish.session.read_stars_planner", return_value=None):
            with self.assertRaisesRegex(NTUAuthError, "expired again"):
                manager.get_stars_planner(refresh=True)

    def test_bad_credentials_and_mfa_are_reported_without_leaking_secret(self) -> None:
        manager = self._manager(_FakePage(invalid=True))
        with self.assertRaisesRegex(NTUAuthError, "rejected the credentials") as error:
            manager._fetch_authenticated(PLANNER_URL, "planner")
        self.assertNotIn("test-secret", str(error.exception))

        challenge = self._manager(_FakePage(challenge=True))
        with self.assertRaisesRegex(NTUAuthError, "MFA"):
            challenge._fetch_authenticated(PLANNER_URL, "planner")

    def test_external_login_form_never_receives_credentials(self) -> None:
        page = _FakePage()
        page.form_action = "https://other.example/login"
        manager = self._manager(page)
        with self.assertRaisesRegex(NTUAuthError, "outside an HTTPS NTU domain"):
            manager._fetch_authenticated(PLANNER_URL, "planner")
        self.assertEqual(page.filled, {})
        self.assertEqual(page.submit_count, 0)

    def test_login_forms_using_get_never_receive_credentials(self) -> None:
        page = _FakePage()
        page.form_method = "get"
        manager = self._manager(page)
        with self.assertRaisesRegex(NTUAuthError, "did not use POST"):
            manager._fetch_authenticated(PLANNER_URL, "planner")
        self.assertEqual(page.filled, {})
        self.assertEqual(page.submit_count, 0)

    def test_concurrent_personal_calls_use_one_browser_thread(self) -> None:
        page = _FakePage()
        manager = self._manager(page)
        callers_ready = Barrier(2)
        browser_threads = []

        def fetch(url, _description):
            browser_threads.append(get_ident())
            page.html = PLANNER_HTML if url == PLANNER_URL else AUDIT_HTML
            return page.html

        def call(method):
            callers_ready.wait(timeout=5)
            return method()

        with patch.object(manager, "_fetch_authenticated", side_effect=fetch):
            with ThreadPoolExecutor(max_workers=2) as callers:
                jobs = [callers.submit(call, method) for method in (manager.get_stars_planner, manager.get_degree_audit)]
                results = [job.result(timeout=10) for job in jobs]
        self.assertEqual({r["service"] for r in results}, {"stars_planner", "degree_audit"})
        self.assertEqual(len(browser_threads), 2)
        self.assertEqual(len(set(browser_threads)), 1)
        self.assertNotEqual(browser_threads[0], get_ident())
        manager.close()
        self.assertFalse(manager.status()["session_verified"])
        self.assertEqual(manager._cache, {})

    def test_unavailable_service_and_missing_credentials_fail_clearly(self) -> None:
        manager = self._manager(_FakePage(status=503))
        with self.assertRaisesRegex(NTURequestError, "HTTP 503"):
            manager._fetch_authenticated(PLANNER_URL, "planner")

        delete_credentials()
        empty = WishSessionManager()
        self.addCleanup(empty.close)
        with self.assertRaisesRegex(NTUAuthError, "auth save"):
            empty.get_degree_audit()

if __name__ == "__main__":
    unittest.main()

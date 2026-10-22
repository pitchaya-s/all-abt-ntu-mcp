from shared.credentials import delete_credentials, save_credentials
from tests.credential_fixtures import stored_credentials
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from threading import get_ident
import unittest
from unittest.mock import Mock, patch

from ntulearn_mcp.ntu_client.session import BASE, Session, _READ_PATH
from ntulearn_mcp.models import LearnError

from .fixtures import COURSE, PREFIX, SECRET


class Response:
    def __init__(self, status=200, data=None, content_type="application/json", body=None, **headers):
        self.status = status
        self.headers = {"content-type": content_type, **headers}
        self.data = b'{}' if data is None else json.dumps(data).encode()
        if body is not None:
            self.data = body
        self.disposed = False

    def body(self):
        return self.data

    def dispose(self):
        self.disposed = True


class AuthTests(unittest.TestCase):
    def setUp(self):
        credentials = stored_credentials("student001", SECRET)
        credentials.__enter__()
        self.addCleanup(credentials.__exit__, None, None, None)
        self.env = patch.dict("os.environ", {"NTULEARN_HEADLESS": "true", "NTULEARN_CACHE_TTL_SECONDS": "300"})
        self.env.start()
        self.session = Session()
        self.session._verified = True

    def tearDown(self):
        self.session.close()
        self.env.stop()

    def test_cache_refresh_mutation_and_ttl(self):
        path = PREFIX + "/users/me/courses"
        responses = [Response(data={"results": []}) for _ in range(3)]
        with patch.object(self.session, "_request", side_effect=responses) as request:
            first, fresh = self.session.get(path)
            first["results"].append("mutated")
            cached, metadata = self.session.get(path)
            self.assertEqual(cached, {"results": []})
            self.assertTrue(metadata["from_cache"])
            self.assertEqual(fresh["retrieved_at"], metadata["retrieved_at"])
            self.session.get(path, refresh=True)
            self.session.ttl = 0
            self.session.get(path)
            self.assertEqual(request.call_count, 3)
        self.assertTrue(all(response.disposed for response in responses))

    def test_expiry_reauthenticates_once_and_rejects_repeated_expiry(self):
        for response in [Response(401), Response(302), Response(content_type="text/html", body=b'<form>login</form>')]:
            self.session._cache.clear()
            self.session._verified = True
            with patch.object(self.session, "_login") as login, patch.object(self.session, "_request", side_effect=[response, Response(data={"results": []})]):
                self.session.get(PREFIX + "/users/me/courses", refresh=True)
                login.assert_called_once()
                self.assertTrue(response.disposed)
        self.session._verified = True
        with patch.object(self.session, "_login") as login, patch.object(self.session, "_request", side_effect=[Response(401), Response(401)]):
            with self.assertRaisesRegex(LearnError, "expired again"):
                self.session.get(PREFIX + "/users/me/courses", refresh=True)
            login.assert_called_once()
            self.assertFalse(self.session.status().session_verified)

    def test_denied_access_and_server_errors_are_not_hidden_or_cached(self):
        for status in [400, 403, 404]:
            with patch.object(self.session, "_login") as login, patch.object(self.session, "_request", return_value=Response(status)):
                with self.assertRaisesRegex(LearnError, f"HTTP {status}"):
                    self.session.get(PREFIX + "/users/me/courses", refresh=True)
                login.assert_not_called()
        with patch("ntulearn_mcp.ntu_client.session.time.sleep"), patch.object(self.session, "_request", side_effect=[Response(503), Response(429), Response(data={"results": []})]) as request:
            self.session.get(PREFIX + "/users/me/courses", refresh=True)
            self.assertEqual(request.call_count, 3)

    def test_expired_response_is_disposed_before_replacing_its_context(self):
        events = []
        expired = Response(401)
        dispose = expired.dispose
        def close_response():
            self.assertNotIn("context_closed", events)
            events.append("response_disposed")
            dispose()
        expired.dispose = close_response
        def login():
            self.assertEqual(events, ["response_disposed"])
            events.append("context_closed")
            self.session._verified = True
        with patch.object(self.session, "_login", side_effect=login), patch.object(self.session, "_request", side_effect=[expired, Response(data={"results": []})]):
            self.session.get(PREFIX + "/users/me/courses", refresh=True)
        self.assertEqual(events, ["response_disposed", "context_closed"])

    def test_malformed_and_oversized_json_are_rejected(self):
        for response in [Response(body=b'invalid'), Response(body=b'0' * 5_000_001), Response(content_type="text/plain")]:
            with patch.object(self.session, "_request", return_value=response), self.assertRaises(LearnError):
                self.session.get(PREFIX + "/users/me/courses", refresh=True)
            self.assertTrue(response.disposed)

    def test_only_fixed_read_endpoints_reach_http(self):
        self.session._context = Mock()
        for path in ["https://other.invalid", "/learn/api/public/v1/users/me?x=1", "/learn/api/public/v1/courses/../users/me", "/learn/api/v1/messages/mailbox"]:
            with self.assertRaises(LearnError):
                self.session.get(path)
        self.session._context.request.get.assert_not_called()
        with self.assertRaisesRegex(LearnError, "closed"):
            self.session.close()
            self.session.get(PREFIX + "/users/me")

    def test_single_browser_thread_and_generic_errors_do_not_leak_secrets(self):
        def operation():
            return get_ident()
        with ThreadPoolExecutor(max_workers=3) as executor:
            identities = list(executor.map(lambda _: self.session.run(operation), range(6)))
        self.assertEqual(len(set(identities)), 1)
        self.assertNotEqual(identities[0], get_ident())
        def failure():
            raise RuntimeError(SECRET)
        with self.assertRaises(LearnError) as error:
            self.session.run(failure)
        self.assertNotIn(SECRET, str(error.exception))
        self.assertNotIn(SECRET, self.session.status().model_dump_json())

    def test_missing_credentials_and_cooldown_never_open_browser(self):
        with patch.object(self.session, "_open") as opened:
            delete_credentials()
            with self.assertRaisesRegex(LearnError, "auth save"):
                self.session.run(self.session._login)
            save_credentials("student001", SECRET)
            self.session._login_not_before = float("inf")
            with self.assertRaisesRegex(LearnError, "one minute"):
                self.session.run(self.session._login)
            opened.assert_not_called()

    def test_download_no_overwrite_redirect_rules_and_cleanup(self):
        path = PREFIX + "/courses/_1_1/contents/_2_1/attachments/_3_1/download"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "example.pdf"
            context = Mock()
            self.session._context = context
            context.request.get.side_effect = [Response(302, location="/bbcswebdav/example.pdf"), Response(content_type="application/pdf", body=b'%PDF-example')]
            with patch.object(self.session, "_get"), patch("ntulearn_mcp.ntu_client.session.time.sleep"):
                result = self.session.download(path, str(target))
                self.assertEqual(result.bytes_written, len(b'%PDF-example'))
                self.assertEqual(target.read_bytes(), b'%PDF-example')
                with self.assertRaisesRegex(LearnError, "never overwritten"):
                    self.session.download(path, str(target))
                target.unlink()
                context.request.get.side_effect = [Response(302, location="https://other.invalid/steal")]
                with self.assertRaisesRegex(LearnError, "external download host"):
                    self.session.download(path, str(target))
                self.assertFalse(target.exists())
                context.request.get.side_effect = [Response(content_type="text/html", body=b'<form>login</form>')]
                with self.assertRaisesRegex(LearnError, "no file was saved"):
                    self.session.download(path, str(target))
                context.request.get.side_effect = [Response(content_type="application/pdf", body=b'x' * 20_000_001)]
                with self.assertRaisesRegex(LearnError, "20 MB"):
                    self.session.download(path, str(target))
                self.assertFalse(target.exists())

    def test_vendor_file_redirect_uses_an_isolated_cookie_context(self):
        path = PREFIX + "/courses/_1_1/contents/_2_1/attachments/_3_1/download"
        self.session._context = Mock()
        self.session._context.request.get.return_value = Response(302, location="https://files.blackboard.com/example.pdf")
        self.session._playwright = Mock()
        remote = self.session._playwright.request.new_context.return_value
        remote.get.return_value = Response(content_type="application/pdf", body=b'%PDF-example')
        with tempfile.TemporaryDirectory() as directory, patch.object(self.session, "_get"), patch("ntulearn_mcp.ntu_client.session.time.sleep"):
            target = Path(directory) / "example.pdf"
            self.session.download(path, str(target))
            self.session._playwright.request.new_context.assert_called_once_with()
            remote.get.assert_called_once()
            remote.dispose.assert_called_once()
            self.assertEqual(target.read_bytes(), b'%PDF-example')



class Locator:
    def __init__(self, page, name):
        self.page, self.name = page, name

    @property
    def first(self):
        return self

    def count(self):
        if self.name == "email":
            return int(self.page.stage == "email")
        if self.name == "password":
            return int(self.page.stage in {"transition", "password"})
        return int(self.page.stage == "stay")

    def fill(self, value):
        if self.name == "password" and self.page.stage != "password":
            raise AssertionError("Filled a password before Microsoft's replacement field was ready")
        self.page.filled.append(self.name)

    def wait_for(self, **kwargs):
        if self.name == "Sign in" and self.page.stage == "transition":
            self.page.stage = "password"

    def click(self):
        if self.name == "Next":
            self.page.stage = "transition"
        elif self.name == "Sign in":
            self.page.stage = self.page.after_password
        else:
            self.page.stage = "authenticated"


class Page:
    def __init__(self, after_password="stay"):
        self.stage = "email"
        self.after_password = after_password
        self.filled = []

    @property
    def url(self):
        return BASE + "/ultra/institution-page" if self.stage == "authenticated" else "https://login.microsoftonline.com/example/saml2"

    def goto(self, *args, **kwargs):
        pass

    def locator(self, selector):
        if selector == "body":
            return self
        return Locator(self, "email" if "loginfmt" in selector else "password" if "password" in selector else "No")

    def inner_text(self, **kwargs):
        return {"email": "Sign in", "transition": "Sign in", "password": "Enter password", "stay": "Stay signed in?",
                "mfa": "Approve sign-in using Microsoft Authenticator", "rejected": "Your account or password is incorrect.",
                "authenticated": "Courses"}[self.stage]

    def get_by_role(self, role, name, **kwargs):
        return Locator(self, name)

    def wait_for_timeout(self, milliseconds):
        pass


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        credentials = stored_credentials("example@e.ntu.edu.sg", SECRET)
        credentials.__enter__()
        self.addCleanup(credentials.__exit__, None, None, None)

    def test_reauthentication_replaces_stale_context_without_restarting_browser(self):
        with stored_credentials("example", SECRET):
            session = Session()
        old_context, browser = Mock(), Mock()
        session._browser = browser
        session._context = old_context
        page = Page()
        browser.new_context.return_value.new_page.return_value = page
        try:
            with patch.object(session, "_open"), patch.object(session, "_request", return_value=Response(data={"id": "_900_1"})):
                session.run(session._login)
            old_context.close.assert_called_once()
            browser.new_context.assert_called_once_with(locale="en-US")
            self.assertTrue(session.status().session_verified)
            self.assertEqual(page.filled, ["email", "password"])
        finally:
            session.close()

    def test_password_waits_for_ready_form_and_no_persistent_signin(self):
        with stored_credentials("example@e.ntu.edu.sg", SECRET):
            session = Session()
        page = Page()
        session._page = page
        try:
            with patch.object(session, "_open"), patch.object(session, "_request", return_value=Response(data={"id": "_900_1"})):
                session.run(session._login)
            self.assertEqual(page.filled, ["email", "password"])
            self.assertTrue(session.status().session_verified)
            self.assertEqual(page.stage, "authenticated")
        finally:
            session.close()

    def test_mfa_and_wrong_password_stop_without_retry(self):
        for stage, expected in [("mfa", "MFA or CAPTCHA"), ("rejected", "rejected the login")]:
            with stored_credentials("example@e.ntu.edu.sg", SECRET), patch.dict("os.environ", {"NTULEARN_HEADLESS": "true"}):
                session = Session()
            page = Page(after_password=stage)
            session._page = page
            try:
                with patch.object(session, "_open"), self.assertRaisesRegex(LearnError, expected):
                    session.run(session._login)
                self.assertEqual(page.filled, ["email", "password"])
                self.assertFalse(session.status().session_verified)
            finally:
                session.close()


class ReadPathTests(unittest.TestCase):
    def test_allowlist_has_only_required_read_endpoints(self):
        for path in (f'{PREFIX}/courses/{COURSE}/users', f'/learn/api/v1/courses/{COURSE}/memberships',
                     '/learn/api/v1/messages/summary', f'/learn/api/v1/courses/{COURSE}/conversations/_800_1'):
            self.assertIsNotNone(_READ_PATH.fullmatch(path))
        for path in ('/learn/api/v1/users/_other_1', '/learn/api/v1/messages/send',
                     f'/learn/api/v1/courses/{COURSE}/conversations/../../users'):
            self.assertIsNone(_READ_PATH.fullmatch(path))

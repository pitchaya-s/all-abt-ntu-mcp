"""Ephemeral Microsoft SSO session and bounded, read-only Blackboard requests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
import time
from urllib.parse import urljoin, urlsplit

from shared.credentials import read_credentials

from .models import AuthStatus, Download, LearnError


BASE = "https://ntulearn.ntu.edu.sg"
TIMEOUT_MS = 30_000
MAX_BYTES = 5_000_000
ID = r"[A-Za-z0-9_-]{1,80}"
_READ_PATH = re.compile(
    rf"/learn/api/public/v1/(?:users/me(?:/courses)?|calendars/items|courses/{ID}"
    rf"(?:/announcements|/gradebook/(?:columns|users/{ID})|/contents(?:/{ID}(?:/children|/attachments(?:/{ID}/download)?)?)?)?)"
)
_CHALLENGE = re.compile(r"captcha|approve (?:the )?sign.in|verify your identity|verification code|authenticator|multi.factor|security info", re.I)


class Session:
    def __init__(self):
        credentials = read_credentials()
        self._username = credentials.email
        self._password = credentials.password
        try:
            self.ttl = int(os.environ.get("NTULEARN_CACHE_TTL_SECONDS", "300"))
        except ValueError as error:
            raise LearnError("NTULEARN_CACHE_TTL_SECONDS must be an integer from 0 to 86400.") from error
        if not 0 <= self.ttl <= 86400:
            raise LearnError("NTULEARN_CACHE_TTL_SECONDS must be an integer from 0 to 86400.")
        headless = os.environ.get("NTULEARN_HEADLESS", "true").lower()
        if headless not in {"true", "false"}:
            raise LearnError("NTULEARN_HEADLESS must be true or false.")
        self._headless = headless == "true"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ntulearn")
        self._lock = RLock()
        self._closed = False
        self._playwright = self._browser = self._context = self._page = None
        self._verified = False
        self._last_verified = None
        self._login_not_before = 0.0
        self._last_request = 0.0
        self._cache = {}

    def status(self):
        with self._lock:
            return AuthStatus(credentials_configured=bool(self._username and self._password),
                              session_verified=self._verified, last_verified_at=self._last_verified,
                              cache_ttl_seconds=self.ttl)

    def run(self, function, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise LearnError("The NTULearn session is closed; restart the MCP server.")
            future = self._executor.submit(function, *args, **kwargs)
        try:
            return future.result()
        except LearnError:
            raise
        except Exception:
            # Browser errors may embed URLs, call arguments, cookies, or page content.
            raise LearnError("NTULearn returned an unexpected response or the connection failed; retry later.") from None

    def _open(self):
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(locale="en-US")
            self._page = self._context.new_page()
        except Exception:
            self._dispose()
            raise LearnError("Could not start Chromium. Run `uvx --from 'playwright>=1.50,<2' playwright install chromium`.") from None

    def _login(self):
        if not self._username or not self._password:
            raise LearnError("Set NTU_USERNAME and NTU_PASSWORD in the MCP server environment.")
        if time.monotonic() < self._login_not_before:
            raise LearnError("A recent login did not complete. Wait one minute before retrying to avoid repeated login attempts.")
        self._login_not_before = time.monotonic() + 60
        self._verified = False
        self._last_verified = None
        self._cache.clear()
        existing_browser = self._browser is not None
        self._open()
        if existing_browser:
            # Expired Microsoft sessions can leave stale account-picker state in local storage.
            self._context.close()
            self._context = self._browser.new_context(locale="en-US")
            self._page = self._context.new_page()
        page = self._page
        try:
            page.goto(BASE, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            deadline = time.monotonic() + (60 if self._headless else 180)
            username_sent = password_sent = False
            while time.monotonic() < deadline:
                url = urlsplit(page.url)
                if url.scheme != "https" or not (url.hostname == "login.microsoftonline.com" or url.hostname == "ntu.edu.sg" or (url.hostname or "").endswith(".ntu.edu.sg")):
                    raise LearnError("The login reached an unexpected host; no further credentials were submitted.")
                if url.hostname == "ntulearn.ntu.edu.sg" and url.path.startswith("/ultra/"):
                    response = self._request("/learn/api/public/v1/users/me", {})
                    try:
                        if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                            data = self._json(response)
                            if isinstance(data, dict) and isinstance(data.get("id"), str):
                                self._verified = True
                                self._last_verified = datetime.now(timezone.utc)
                                return
                    finally:
                        response.dispose()
                    raise LearnError("NTULearn did not verify the authenticated session.")
                body = page.locator("body").inner_text(timeout=5000)
                if _CHALLENGE.search(body):
                    if self._headless:
                        raise LearnError("NTULearn requires MFA or CAPTCHA. Set NTULEARN_HEADLESS=false and complete it in the local browser; no security checks were bypassed.")
                    page.wait_for_timeout(500)
                    continue
                if password_sent and re.search(r"password (?:is )?incorrect|incorrect password|account.*locked|too many.*attempts|sign.in.*blocked", body, re.I):
                    raise LearnError("Microsoft rejected the login or account access. Check your NTULearn credentials; no automatic password retry was made.")
                email = page.locator('input[name="loginfmt"]:visible')
                password = page.locator('input[type="password"]:visible')
                if email.count() and not username_sent:
                    email.first.fill(self._username)
                    username_sent = True
                    page.get_by_role("button", name="Next", exact=True).click()
                elif password.count() and not password_sent:
                    # Microsoft briefly exposes this input before replacing it during the Next transition.
                    submit = page.get_by_role("button", name="Sign in", exact=True)
                    submit.wait_for(state="visible", timeout=TIMEOUT_MS)
                    password.first.fill(self._password)
                    password_sent = True
                    submit.click()
                elif "Stay signed in?" in body and page.locator("#idBtn_Back:visible").count():
                    page.locator("#idBtn_Back").click()
                page.wait_for_timeout(500)
            raise LearnError("NTULearn login did not finish. Check the account and complete any required interaction in a visible browser.")
        except LearnError:
            raise
        except Exception:
            raise LearnError("NTULearn login failed or timed out; no automatic password retry was made.") from None

    def _request(self, path, params):
        if not _READ_PATH.fullmatch(path):
            raise LearnError("This NTULearn endpoint is not in the read-only allowlist.")
        delay = 0.5 - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()
        return self._context.request.get(BASE + path, params=params, timeout=TIMEOUT_MS, max_redirects=0)

    def _json(self, response):
        if "application/json" not in response.headers.get("content-type", ""):
            raise LearnError("NTULearn returned a non-JSON page instead of academic data; no data was inferred.")
        body = response.body()
        if len(body) > MAX_BYTES:
            raise LearnError("NTULearn's response exceeded the 5 MB limit; request a smaller page.")
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise LearnError("NTULearn returned malformed JSON; no data was inferred.") from None

    def _get(self, path, params, refresh):
        if not _READ_PATH.fullmatch(path) or path.endswith("/download"):
            raise LearnError("This NTULearn endpoint is not an academic JSON read endpoint.")
        key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(key)
        if not refresh and self.ttl and cached and time.monotonic() - cached[0] < self.ttl:
            return deepcopy(cached[1]), {"retrieved_at": cached[2], "from_cache": True, "cache_age_seconds": int(time.monotonic() - cached[0])}
        if not self._verified:
            self._login()
        for attempt in range(3):
            response = self._request(path, params)
            try:
                status = response.status
                is_html = "text/html" in response.headers.get("content-type", "")
                expired = status == 401 or status in {301, 302, 303, 307, 308} or (status == 200 and is_html)
                if expired:
                    response.dispose()
                    response = None
                    self._verified = False
                    self._last_verified = None
                    self._cache.clear()
                    if attempt == 0:
                        # Successful sessions may expire immediately; do not bypass NTU's timeout.
                        self._login_not_before = 0
                        self._login()
                        continue
                    raise LearnError("NTULearn's session expired again after reauthentication; retry later.")
                if status in {429, 500, 502, 503, 504} and attempt < 2:
                    try:
                        delay = min(10, max(1, int(response.headers.get("retry-after", "2"))))
                    except ValueError:
                        delay = 2
                    time.sleep(delay)
                    continue
                if status == 403:
                    raise LearnError("NTULearn denied access to this resource (HTTP 403); no alternate access was attempted.")
                if status == 404:
                    raise LearnError("NTULearn did not find this resource, or it is not visible to your account (HTTP 404).")
                if status != 200:
                    raise LearnError(f"NTULearn could not complete this read request (HTTP {status}).")
                data = self._json(response)
                now = datetime.now(timezone.utc)
                if self.ttl:
                    if len(self._cache) >= 128:
                        del self._cache[min(self._cache, key=lambda k: self._cache[k][0])]
                    self._cache[key] = (time.monotonic(), deepcopy(data), now)
                return data, {"retrieved_at": now, "from_cache": False, "cache_age_seconds": 0}
            finally:
                if response is not None:
                    response.dispose()
        raise LearnError("NTULearn is temporarily unavailable.")

    def get(self, path, params=None, refresh=False):
        return self.run(self._get, path, params or {}, refresh)

    def _download(self, path, destination):
        if not _READ_PATH.fullmatch(path) or not path.endswith("/download"):
            raise LearnError("Use a Blackboard attachment download endpoint.")
        target = Path(destination).expanduser().absolute()
        if target.exists() or not target.parent.is_dir():
            raise LearnError("Choose a new file path in an existing directory; existing files are never overwritten.")
        self._get("/learn/api/public/v1/users/me", {}, True)
        url = BASE + path
        body = None
        remote_context = None
        try:
            for _ in range(4):
                delay = 0.5 - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
                self._last_request = time.monotonic()
                if urlsplit(url).hostname == "ntulearn.ntu.edu.sg":
                    request_context = self._context.request
                else:
                    if remote_context is None:
                        remote_context = self._playwright.request.new_context()
                    request_context = remote_context
                response = request_context.get(url, timeout=TIMEOUT_MS, max_redirects=0)
                try:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location", "")
                        next_url = urljoin(url, location)
                        parsed = urlsplit(next_url)
                        host = parsed.hostname or ""
                        trusted = host == "ntulearn.ntu.edu.sg" or host.endswith((".blackboard.com", ".blackboardcdn.com"))
                        if not location or parsed.scheme != "https" or parsed.netloc != host or not trusted:
                            raise LearnError("The file requires an unsupported external download host; open the attachment in NTULearn manually.")
                        url = next_url
                        continue
                    if response.status != 200:
                        raise LearnError(f"NTULearn could not download this attachment (HTTP {response.status}).")
                    if "text/html" in response.headers.get("content-type", "") or "application/json" in response.headers.get("content-type", ""):
                        raise LearnError("NTULearn returned a login/error page or unsupported HTML/JSON attachment; no file was saved.")
                    body = response.body()
                    if len(body) > 20_000_000:
                        raise LearnError("This attachment exceeds the 20 MB download limit; download it manually.")
                    break
                finally:
                    response.dispose()
        finally:
            if remote_context is not None:
                remote_context.dispose()
        if body is None:
            raise LearnError("NTULearn returned too many file redirects; no file was saved.")
        created = False
        try:
            with target.open("xb") as output:
                created = True
                output.write(body)
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            raise LearnError("Could not save the download. Check the destination and available space; existing files were not overwritten.") from None
        return Download(path=str(target), bytes_written=len(body), downloaded_at=datetime.now(timezone.utc))

    def download(self, path, destination):
        return self.run(self._download, path, destination)

    def _dispose(self):
        for resource in (self._context, self._browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._context = self._browser = self._page = self._playwright = None
        self._cache.clear()
        self._verified = False
        self._last_verified = None

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            future = self._executor.submit(self._dispose)
        try:
            future.result()
        finally:
            self._executor.shutdown(wait=True)

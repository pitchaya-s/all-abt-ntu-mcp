from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
import re
from threading import RLock
import time
from typing import cast
from urllib.parse import urlencode, urljoin, urlsplit

from shared.credentials import CredentialError, credential_status, read_credentials
from .forms import (
    _CHALLENGE_MESSAGE,
    _Forms,
    _allowed_form_url,
    _is_challenge,
    _is_login_page,
    _password_input,
    _username_input,
)
from ..client.http import NTURequestError, REQUEST_TIMEOUT_SECONDS, _wait_for_request_slot
from ..parser import NTUPageError, parse_degree_audit_page
from .models import (
    AuthStatus,
    DegreeAuditResult,
    NTUAuthError,
    NTUPersonalDataError,
    StarsPlannerResult,
    SavePlanResult,
)
from .planner import PLANNER_VIEW_URL, read_stars_planner
from .plan_editor import course_assignments, prepare_stars_plan, submit_stars_plan, validate_plan_request
from .planner import SAVE_PLAN_URL

PLANNER_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/aus_stars_planner.main"
DEGREE_AUDIT_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/DARS_RESULT_RO.main_display"
LOGIN_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/ldap_login.login"
MAX_PERSONAL_CACHE_ENTRIES = 4

try:
    PERSONAL_CACHE_TTL_SECONDS = int(os.environ.get("NTU_PERSONAL_CACHE_TTL_SECONDS", "300"))
except ValueError as error:
    raise RuntimeError("NTU_PERSONAL_CACHE_TTL_SECONDS must be an integer number of seconds.") from error
if not 0 <= PERSONAL_CACHE_TTL_SECONDS <= 86_400:
    raise RuntimeError("NTU_PERSONAL_CACHE_TTL_SECONDS must be between 0 and 86400 seconds.")

class WishSessionManager:
    """One in-memory WISH cookie session shared by the personal tools."""

    def __init__(self) -> None:
        self._credential_revision: str | None = None
        self._lock = RLock()
        self._authenticated = False
        self._last_verified_at: str | None = None
        self._cache: dict[str, tuple[float, dict[str, object]]] = {}
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_browser_status: int | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    def status(self) -> AuthStatus:
        with self._lock:
            credentials = credential_status()
            return {
                **credentials,
                "session_verified": self._authenticated and credentials["credentials_configured"] is True,
                "last_verified_at": self._last_verified_at,
                "session_storage": "in_memory_only",
                "personal_cache_ttl_seconds": PERSONAL_CACHE_TTL_SECONDS,
            }

    def _check_credentials(self):
        try:
            credentials = read_credentials()
            credentials.require_login()
        except CredentialError as error:
            self._close_browser()
            raise NTUAuthError(str(error)) from None
        if self._credential_revision is not None and self._credential_revision != credentials.revision:
            self._close_browser()
        self._credential_revision = credentials.revision
        return credentials

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executor = self._executor
        if executor is None:
            self._close_browser()
        else:
            try:
                executor.submit(self._close_browser).result()
            finally:
                executor.shutdown(wait=True)

    def _close_browser(self) -> None:
        for resource, method in ((self._context, "close"), (self._browser, "close"), (self._playwright, "stop")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        self._page = self._context = self._browser = self._playwright = None
        self._authenticated = False
        self._last_verified_at = None
        self._cache.clear()

    def _record_browser_response(self, response: object) -> None:
        request = getattr(response, "request", None)
        if request is not None and getattr(request, "resource_type", None) == "document":
            self._last_browser_status = cast(int, getattr(response, "status", 0))

    def _browser_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise NTUAuthError(
                "Authenticated WISH tools require Playwright. Add `--with 'playwright>=1.50,<2'` to your uvx command or run `uv sync --extra personal` locally."
            ) from error
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.on("response", self._record_browser_response)
            return self._page
        except Exception as error:
            self._close_browser()
            raise NTUAuthError(
                "Could not start Chromium for NTU WISH. Run `uvx --from 'playwright>=1.50,<2' playwright install chromium` and retry."
            ) from error

    def _check_browser_status(self, description: str) -> None:
        status = self._last_browser_status
        self._last_browser_status = None
        if status and status >= 400:
            if status in {401, 403}:
                raise NTUAuthError(f"NTU refused access to {description} (HTTP {status}).")
            raise NTURequestError(f"NTU returned HTTP {status} for {description}.")

    def _wait_for_page(self, page, destination: str) -> None:
        target_path = urlsplit(destination).path.casefold()
        page.wait_for_function(
            """target => {
              const body = document.body?.innerText || '';
              if (document.querySelector('#UID, #PW, input[type="password"]') ||
                  /captcha|multi[- ]factor|two[- ]factor|mfa|verification code|authenticator/i.test(body) ||
                  /invalid|incorrect|failed|wrong password/i.test(body)) return true;
              const path = location.pathname.toLowerCase();
              const planner = target.endsWith('aus_stars_planner.main');
              const expected = planner
                ? /aus_stars_planner[.](time_table|planner)$/.test(path)
                : path === target;
              return expected && document.readyState === 'complete';
            }""",
            arg=target_path,
            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
        )

    def _login(self, page, destination: str, description: str) -> None:
        credentials = self._check_credentials()
        username_sent = False
        password_sent = False
        html = page.content()
        for _ in range(3):
            if _is_challenge(html):
                raise NTUAuthError(
                    _CHALLENGE_MESSAGE
                )
            if (username_sent or password_sent) and _is_login_page(html) and re.search(
                r"invalid|incorrect|failed|wrong password", html, re.I
            ):
                raise NTUAuthError("NTU rejected the credentials. Update them locally with `all-abt-ntu-mcp auth save`.")
            forms = _Forms()
            forms.feed(html)
            matching = next(
                (form for form in forms.forms if _username_input(form) or _password_input(form)),
                None,
            )
            if matching is None:
                if password_sent and not _is_login_page(html):
                    return
                raise NTUAuthError("NTU's login form changed; no further credentials were submitted.")
            action = urljoin(page.url, matching.action or page.url)
            if not _allowed_form_url(action):
                raise NTUAuthError("NTU's login form pointed outside an HTTPS NTU domain; credentials were not submitted.")
            if matching.method != "post":
                raise NTUAuthError("NTU's login form did not use POST; credentials were not submitted.")

            user_field = _username_input(matching)
            password_field = _password_input(matching)
            sent_field = False
            if user_field is not None and not username_sent:
                selector = f"#{user_field.field_id}" if user_field.field_id else f'[name="{user_field.name}"]'
                page.locator(selector).first.fill(credentials.username)
                username_sent = sent_field = True
            if password_field is not None and not password_sent:
                selector = f"#{password_field.field_id}" if password_field.field_id else f'[name="{password_field.name}"]'
                page.locator(selector).first.fill(credentials.password)
                password_sent = sent_field = True
            if not sent_field:
                raise NTUAuthError("NTU's login form did not expose a supported username or password field.")

            _wait_for_request_slot()
            self._last_browser_status = None
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            page.wait_for_load_state("domcontentloaded", timeout=REQUEST_TIMEOUT_SECONDS * 1000)
            self._check_browser_status("NTU WISH login")
            self._wait_for_page(page, destination)
            self._check_browser_status(description)
            html = page.content()
            if _is_challenge(html):
                raise NTUAuthError(
                    _CHALLENGE_MESSAGE
                )
            if password_sent:
                if _is_login_page(html):
                    if re.search(r"invalid|incorrect|failed|wrong password", html, re.I):
                        raise NTUAuthError("NTU rejected the credentials. Update them locally with `all-abt-ntu-mcp auth save`.")
                    raise NTUAuthError("NTU did not accept the login; check credentials or account access.")
                return
        raise NTUAuthError("NTU's login flow did not complete a supported password login.")

    def _fetch_authenticated(self, url: str, description: str) -> str:
        self._check_credentials()
        try:
            page = self._browser_page()
            login_url = f"{LOGIN_URL}?{urlencode({'w_url': url})}"
            _wait_for_request_slot()
            self._last_browser_status = None
            response = page.goto(login_url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_SECONDS * 1000)
            if response is not None:
                self._last_browser_status = response.status
            self._check_browser_status(description)
            self._wait_for_page(page, url)
            self._check_browser_status(description)
            html = page.content()
            if _is_challenge(html):
                raise NTUAuthError(
                    _CHALLENGE_MESSAGE
                )
            if _is_login_page(html):
                self._authenticated = False
                self._last_verified_at = None
                self._login(page, url, description)
                html = page.content()
            if _is_challenge(html):
                raise NTUAuthError(
                    _CHALLENGE_MESSAGE
                )
            if _is_login_page(html):
                raise NTUAuthError("NTU returned its login page after authentication; the session was not accepted.")
            self._check_browser_status(description)
            return html
        except NTURequestError:
            raise
        except Exception as error:
            raise NTURequestError(
                f"Could not retrieve {description} through NTU's browser login ({type(error).__name__})."
            ) from None

    def _get_personal_data(self, service: str, url: str, *, refresh: bool = False) -> dict[str, object]:
        with self._lock:
            self._check_credentials()
            now = time.monotonic()
            cached = self._cache.get(service)
            if not refresh and PERSONAL_CACHE_TTL_SECONDS and cached and now - cached[0] < PERSONAL_CACHE_TTL_SECONDS:
                result = deepcopy(cached[1])
                result.update({"from_cache": True, "cache_age_seconds": int(now - cached[0])})
                return result

            try:
                for attempt in range(2):
                    html = self._fetch_authenticated(url, f"NTU {service.replace('_', ' ')}")
                    result = read_stars_planner(self._page) if service == "stars_planner" else parse_degree_audit_page(html)
                    if result is not None:
                        break
                    self._authenticated = False
                    self._last_verified_at = None
                    if attempt:
                        raise NTUAuthError("NTU's Planner session expired again after a fresh login; retry later.")
            except NTUPageError as error:
                raise NTUPersonalDataError(f"Could not safely parse NTU's {service.replace('_', ' ')} response: {error}") from error
            except NTURequestError:
                raise
            except Exception as error:
                raise NTUPersonalDataError(
                    f"Could not read NTU's {service.replace('_', ' ')} display ({type(error).__name__}); retry or check NTU manually."
                ) from error

            retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result.update({"source_url": PLANNER_VIEW_URL if service == "stars_planner" else url, "retrieved_at": retrieved_at, "from_cache": False, "cache_age_seconds": 0})
            self._authenticated = True
            self._last_verified_at = retrieved_at
            if PERSONAL_CACHE_TTL_SECONDS:
                cached_at = time.monotonic()
                self._cache[service] = (cached_at, deepcopy(result))
                if len(self._cache) > MAX_PERSONAL_CACHE_ENTRIES:
                    del self._cache[min(self._cache, key=lambda key: self._cache[key][0])]
            return result

    def _run_browser_operation(self, operation, *args, **kwargs):
        # Playwright's sync browser must stay on its owning thread across MCP calls.
        with self._lock:
            if self._closed:
                raise NTUAuthError("The WISH session manager is closed; restart the MCP server.")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ntu-wish")
            future = self._executor.submit(operation, *args, **kwargs)
        try:
            return future.result()
        except NTURequestError:
            raise
        except Exception as error:
            raise NTUPersonalDataError(
                f"Could not complete the STARS browser operation ({type(error).__name__}). Refresh the Planner before retrying."
            ) from None

    def _run_personal_data(self, service: str, url: str, *, refresh: bool = False) -> dict[str, object]:
        return self._run_browser_operation(self._get_personal_data, service, url, refresh=refresh)

    def get_stars_planner(self, *, refresh: bool = False) -> StarsPlannerResult:
        return cast(StarsPlannerResult, self._run_personal_data("stars_planner", PLANNER_URL, refresh=refresh))

    def get_degree_audit(self) -> DegreeAuditResult:
        return cast(DegreeAuditResult, self._run_personal_data("degree_audit", DEGREE_AUDIT_URL))

    def _save_stars_plan(
        self, plan_number: int, courses: list[dict[str, str]], academic_year: int, semester: int
    ) -> SavePlanResult:
        with self._lock:
            before = self._get_personal_data("stars_planner", PLANNER_URL, refresh=True)
            if (before["academic_year"], before["semester"]) != (academic_year, semester):
                raise NTUPersonalDataError("The requested term differs from NTU's current Planner term; no plan was saved.")
            selected = next(plan for plan in before["saved_plans"] if plan["plan_number"] == plan_number)
            if selected["status"] not in {"loaded", "not_saved"}:
                raise NTUPersonalDataError("The existing plan could not be read safely; no plan was saved.")
            status = "unchanged"
            if course_assignments(selected["courses"]) != course_assignments(courses):
                try:
                    fields = prepare_stars_plan(self._page, courses, academic_year, semester)
                except NTUPageError as error:
                    raise NTUPersonalDataError(str(error)) from error
                # Invalidate before submitting: a lost save response must not leave stale plans cached.
                self._cache.pop("stars_planner", None)
                submit_stars_plan(self._page, fields, plan_number)
                try:
                    after = self._get_personal_data("stars_planner", PLANNER_URL, refresh=True)
                except Exception as error:
                    raise NTUPersonalDataError("The save was submitted but read-back verification failed. Refresh the Planner before retrying; no automatic save retry was attempted.") from error
                if (after["academic_year"], after["semester"]) != (academic_year, semester):
                    self._cache.pop("stars_planner", None)
                    raise NTUPersonalDataError("The Planner term changed during save verification; refresh the Planner before retrying.")
                selected = next(plan for plan in after["saved_plans"] if plan["plan_number"] == plan_number)
                if selected["status"] != "loaded" or course_assignments(selected["courses"]) != course_assignments(courses):
                    self._cache.pop("stars_planner", None)
                    raise NTUPersonalDataError("NTU's saved plan did not match the requested courses/indexes. Refresh the Planner before retrying; the save was not repeated.")
                status = "saved"
            return {
                "status": status,
                "academic_year": academic_year,
                "semester": semester,
                "saved_plan": selected,
                "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_url": SAVE_PLAN_URL,
            }

    def save_stars_plan(
        self, plan_number: int, courses: list[dict[str, str]], academic_year: int, semester: int
    ) -> SavePlanResult:
        normalized = validate_plan_request(plan_number, courses, academic_year, semester)
        return self._run_browser_operation(self._save_stars_plan, plan_number, normalized, academic_year, semester)

wish_session = WishSessionManager()

def ntu_auth_status() -> AuthStatus:
    return wish_session.status()

def get_stars_planner(refresh: bool = False) -> StarsPlannerResult:
    return wish_session.get_stars_planner(refresh=refresh)

def get_degree_audit() -> DegreeAuditResult:
    return wish_session.get_degree_audit()

def save_stars_plan(
    plan_number: int, courses: list[dict[str, str]], academic_year: int, semester: int
) -> SavePlanResult:
    return wish_session.save_stars_plan(plan_number, courses, academic_year, semester)

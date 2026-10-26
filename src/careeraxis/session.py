"""In-memory CareerAxis browser session using the shared NTU keyring entry."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
import re
from threading import RLock
import time
from urllib.parse import urlsplit

from shared.credentials import CredentialError, credential_status, read_credentials

from .models import AuthStatus, CareerAxisError


BASE = "https://careeraxis.ntu.edu.sg"
SEARCH_PATH = "/students/jobs/search"
_ALLOWED_HOSTS = {"careeraxis.ntu.edu.sg", "loginfs.ntu.edu.sg"}
_CHALLENGE = re.compile(
    r"captcha|approve (?:the )?sign.in|verify your identity|verification code|authenticator|multi.factor",
    re.I,
)
_BAD_LOGIN = re.compile(r"incorrect|invalid password|account.*locked|too many.*attempts|sign.in.*blocked", re.I)
_SEARCH_INPUTS = (
    'input[type="search"], input[name*="search" i], input[name*="keyword" i], '
    'input[id*="search" i], input[id*="keyword" i], input[placeholder*="search" i], '
    'input[placeholder*="keyword" i], input[aria-label*="search" i], input[aria-label*="keyword" i]'
)
_JOB_STATE = r"""() => {
  const urls = [...new Set([...document.querySelectorAll("a[href]")].flatMap(anchor => {
    try {
      const url = new URL(anchor.href, location.href);
      return url.origin === location.origin && /^\/students\/jobs\/\d+\/?$/.test(url.pathname)
        ? [url.href] : [];
    } catch { return []; }
  }))];
  const text = (document.body && document.body.innerText || "").replace(/\s+/g, " ");
  return {
    urls,
    no_results: /\b(no (jobs?|job postings?|opportunities|matching results?) found|nothing found|0 (jobs?|results?))\b/i.test(text)
  };
}"""
_SEARCH_SNAPSHOT = r"""() => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const opportunities = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll("a[href]")) {
    let url;
    try { url = new URL(anchor.href, location.href); } catch { continue; }
    if (url.origin !== location.origin || !/^\/students\/jobs\/\d+\/?$/.test(url.pathname)
        || /\/(apply|saved|delete)(\/|$)/i.test(url.pathname)) continue;
    const linkTitle = clean(anchor.innerText || anchor.textContent);
    if (!linkTitle || seen.has(url.href)) continue;
    let card = anchor;
    for (let node = anchor.parentElement, depth = 0; node && depth < 7; node = node.parentElement, depth++) {
      const identity = `${node.className || ""} ${node.id || ""}`;
      if (/^(ARTICLE|LI|TR)$/.test(node.tagName) || node.getAttribute("role") === "article"
          || /(job|opportunit|listing|result|position|posting)/i.test(identity)) {
        card = node;
        break;
      }
    }
    const heading = card.querySelector("h1,h2,h3,h4,h5,[class*=title i]");
    const title = clean(heading && (heading.innerText || heading.textContent)) || linkTitle;
    const details = clean(card.innerText || card.textContent).slice(0, 4000);
    opportunities.push({title, url: url.href, details});
    seen.add(url.href);
  }
  const controls = [...document.querySelectorAll("a,button,[role=button]")];
  const hasNext = controls.some(el => {
    const label = clean(el.getAttribute("aria-label") || el.innerText || el.textContent).toLowerCase();
    return /^(next|next page|load more results|›|»)$/.test(label)
      && el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden'
      && !el.closest('.disabled,[disabled],[aria-disabled="true"]');
  });
  const bodyText = clean(document.body && document.body.innerText);
  const noResults = /\b(no (jobs?|job postings?|opportunities|matching results?) found|nothing found|0 (jobs?|results?))\b/i.test(bodyText);
  return {opportunities, has_next_page: hasNext, no_results: noResults};
}"""
_DETAIL_SNAPSHOT = r"""() => {
  const main = document.querySelector("main") || document.querySelector("[role=main]") || document.body;
  const clean = value => (value || "").replace(/[\u200B-\u200F\uFEFF\u2060-\u206F]/g, "").replace(/\s+/g, " ").trim();
  const documentTitle = clean(document.title.replace(/^[^|]+\|\s*/, ""));
  const genericTitle = /^(students|loading\.\.\.|be scam-aware|appointments|documents|resources|search events|search topics|search organisations|internship|internship opportunities|opportunity details|careeraxis|careeraxis opportunities|opportunities|notifications)$/i;
  const headings = [...main.querySelectorAll("h1,h2,h3")]
    .map(heading => clean(heading.innerText || heading.textContent))
    .filter(heading => heading && !genericTitle.test(heading) && !/\{\{[^}]+\}\}/.test(heading));
  const recordTitle = !genericTitle.test(documentTitle) ? documentTitle : headings[0] || "";
  const links = [...main.querySelectorAll("a[href]")]
    .filter(a => /apply|application|employer site|external/i.test(
      `${a.innerText || a.textContent} ${a.getAttribute("aria-label") || ""} ${a.title || ""}`
    ))
    .map(a => a.href);
  return {
    title: recordTitle,
    text: clean(main.innerText || main.textContent).slice(0, 20000),
    application_links: links,
    links: [...main.querySelectorAll("a[href]")].flatMap(a => {
      try {
        const url = new URL(a.href, location.href);
        const navigation = new Set([
          "/students", "/students/jobs", "/students/jobs/search", "/students/organisations", "/students/events",
          "/students/appointments", "/students/resources", "/students/notifications", "/students/dashboard",
          "/students/profile", "/students/bookmarks", "/students/settings/preferences",
          "/students/settings/communication", "/students/account", "/students/info/contact",
          "/students/info/termsandconditions", "/students/logout", "/workgroups/internship", "/workgroups/mlcps"
        ]);
        if (url.href === location.href || navigation.has(url.pathname)) return [];
        return url.protocol === "https:" ? [url.href] : [];
      } catch { return []; }
    })
  };
}"""
_SECTION_PATHS = {
    "events": "/students/events",
    "resources": "/students/resources/search/",
    "organisations": "/students/organisations/Search",
    "appointment_topics": "/students/appointments/topics",
    "internship_jobs": "/workgroups/internship/Jobs",
}
_PORTAL_SNAPSHOT = r"""(section) => {
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const patterns = {
    events: /^\/students\/events\/detail\/\d+\/?$/,
    resources: /^\/students\/docs\/detail\/\d+\/?$/,
    organisations: /^\/students\/organisations\/detail\/\d+\/[A-Za-z0-9._-]+\/?$/,
    appointment_topics: /^\/students\/appointments\/topics\/\d+\/?$/,
    internship_jobs: /^\/workgroups\/internship\/Jobs\/detail\/\d+\/?$/
  };
  const items = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll("a[href]")) {
    let url;
    try { url = new URL(anchor.href, location.href); } catch { continue; }
    if (url.origin !== location.origin || !patterns[section]?.test(url.pathname) || seen.has(url.href)) continue;
    const title = clean(anchor.innerText || anchor.textContent);
    if (!title) continue;
    const card = anchor.closest("article,li,tr,[role=article],.list-group-item") || anchor;
    items.push({title, url: url.href, summary: clean(card.innerText || card.textContent).slice(0, 4000)});
    seen.add(url.href);
  }
  const labels = [...document.querySelectorAll("a,button,[role=button]")]
    .filter(el=>el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden'
      && !el.closest('.disabled,[disabled],[aria-disabled="true"]')).map(el =>
    clean(el.getAttribute("aria-label") || el.innerText || el.textContent).toLowerCase()
  );
  const currentPage = Number(clean(document.querySelector(".pagination li.active")?.innerText || "1"));
  const pageNumbers = [...document.querySelectorAll(".pagination a")]
    .filter(el=>el.getClientRects().length>0&&!el.closest('.disabled,[disabled],[aria-disabled="true"]'))
    .map(el => Number(clean(el.innerText))).filter(Number.isFinite);
  const hasNext = labels.some(label => /^(next|next page|load more results|show more|›|»)$/.test(label))
    || (Number.isFinite(currentPage) && pageNumbers.some(number => number > currentPage));
  const bodyText = clean(document.body && document.body.innerText);
  const noResults = /\b(no (jobs?|events?|resources?|organisations?|topics?|matching results?) found|nothing found|0 (jobs?|events?|results?))\b/i.test(bodyText);
  return {items, has_next_page: hasNext, no_results: noResults};
}"""


class CareerAxisSession:
    def __init__(self):
        try:
            self.ttl = int(os.environ.get("CAREERAXIS_CACHE_TTL_SECONDS", "60"))
        except ValueError as error:
            raise CareerAxisError("CAREERAXIS_CACHE_TTL_SECONDS must be an integer from 0 to 3600.") from error
        if not 0 <= self.ttl <= 3600:
            raise CareerAxisError("CAREERAXIS_CACHE_TTL_SECONDS must be an integer from 0 to 3600.")
        headless = os.environ.get("CAREERAXIS_HEADLESS", "true").lower()
        if headless not in {"true", "false"}:
            raise CareerAxisError("CAREERAXIS_HEADLESS must be true or false.")
        self._headless = headless == "true"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="careeraxis")
        self._lock = RLock()
        self._closed = False
        self._playwright = self._browser = self._context = self._page = None
        self._credential_revision = None
        self._verified = False
        self._last_verified = None
        self._login_not_before = self._last_request = 0.0
        self._cache = OrderedDict()

    def status(self):
        return self._run(self._status)

    def _status(self):
        credentials = credential_status()
        if credentials["credentials_configured"] is True:
            try:
                self._credentials()
            except CareerAxisError:
                credentials = credential_status()
        else:
            self._dispose()
        return AuthStatus(**credentials, session_verified=self._verified, last_verified_at=self._last_verified)

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._executor.submit(self._dispose).result()
                finally:
                    self._executor.shutdown()

    def search(self, query, page, limit, refresh):
        return self._run(self._search, query, page, limit, refresh)

    def search_section(self, section, query, page, limit, refresh, *, current_opportunities_only=False):
        return self._run(
            self._search_section, section, query, page, limit, refresh,
            current_opportunities_only,
        )

    def get_opportunity(self, url, refresh):
        return self._run(self._get_opportunity, url, refresh)

    def get_portal_record(self, url, refresh):
        return self._run(self._get_portal_record, url, refresh)

    def _run(self, function, *args):
        with self._lock:
            if self._closed:
                raise CareerAxisError("The CareerAxis session is closed; restart the MCP server.")
            future = self._executor.submit(function, *args)
        try:
            return future.result()
        except CareerAxisError:
            raise
        except Exception:
            # Browser errors may contain session URLs, cookies, credentials, or page text.
            raise CareerAxisError("CareerAxis returned an unexpected page or the connection failed; retry later.") from None

    def _credentials(self):
        try:
            credentials = read_credentials()
            credentials.require_login()
        except CredentialError as error:
            self._dispose()
            self._verified = False
            self._last_verified = None
            raise CareerAxisError(str(error)) from None
        if self._credential_revision is not None and self._credential_revision != credentials.revision:
            self._dispose()
            self._verified = False
            self._last_verified = None
            self._login_not_before = 0
        self._credential_revision = credentials.revision
        return credentials

    def _open(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(locale="en-US")
            self._page = self._context.new_page()
        except Exception:
            self._dispose()
            raise CareerAxisError(
                "CareerAxis login needs Playwright and Chromium. Install the personal extra and run `uvx --from 'playwright>=1.50,<2' playwright install chromium`."
            ) from None

    def _pace(self):
        time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()

    def _navigate(self, path, credentials):
        self._open()
        self._pace()
        page = self._page
        self._verified = False
        self._last_verified = None
        response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            raise CareerAxisError(f"CareerAxis returned HTTP {response.status}; retry later.")
        deadline = time.monotonic() + (60 if self._headless else 180)
        password_sent = False
        while time.monotonic() < deadline:
            parsed = urlsplit(page.url)
            body = page.locator("body").inner_text(timeout=5000)
            if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.hostname not in _ALLOWED_HOSTS:
                raise CareerAxisError("CareerAxis reached an unsupported login host; no further credentials were submitted.")
            if parsed.hostname == "loginfs.ntu.edu.sg" and _CHALLENGE.search(body):
                if self._headless:
                    raise CareerAxisError(
                        "CareerAxis requires MFA or CAPTCHA. Set CAREERAXIS_HEADLESS=false and complete it in the local browser; no verification was bypassed."
                    )
                page.wait_for_timeout(500)
                continue
            if parsed.hostname == "loginfs.ntu.edu.sg" and password_sent and _BAD_LOGIN.search(body):
                raise CareerAxisError("NTU rejected the CareerAxis login; check the saved account. No password retry was made.")
            if parsed.hostname == "loginfs.ntu.edu.sg":
                self._verified = False
                self._last_verified = None
            if parsed.hostname == "careeraxis.ntu.edu.sg" and parsed.path.startswith(("/students/", "/workgroups/")):
                if re.search(r"page expired|please wait, redirecting to login", body, re.I):
                    raise CareerAxisError("CareerAxis SSO did not finish; retry after checking the NTU login session.")
                shell_deadline = time.monotonic() + 15
                while time.monotonic() < shell_deadline:
                    if page.locator('a[href="/students/logout"]').count():
                        self._verified = True
                        self._last_verified = datetime.now(timezone.utc)
                        return
                    page.wait_for_timeout(250)
                raise CareerAxisError("CareerAxis did not render its authenticated navigation; no account page was read.")
            if parsed.hostname == "loginfs.ntu.edu.sg" and parsed.path == "/adfs/ls/" and page.locator("#passwordInput:visible").count() and not password_sent:
                if not credentials.email.lower().endswith("@e.ntu.edu.sg"):
                    raise CareerAxisError("CareerAxis student tools require a saved NTU student network account.")
                if time.monotonic() < self._login_not_before:
                    raise CareerAxisError("A recent CareerAxis login did not complete. Wait one minute before retrying.")
                self._login_not_before = time.monotonic() + 60
                page.locator("#userNameInput").fill(credentials.username + "@student.main.ntu.edu.sg")
                page.locator("#passwordInput").fill(credentials.password)
                password_sent = True
                page.locator("#submitButton").click()
            page.wait_for_timeout(300)
        raise CareerAxisError("CareerAxis login timed out; no automatic password retry was made.")

    def _search(self, query, page_number, limit, refresh):
        credentials = self._credentials()
        key = ("search", query, page_number, limit)
        cached = self._cached(key, refresh)
        if cached is not None:
            return cached
        self._navigate(SEARCH_PATH, credentials)
        page = self._page
        if query:
            fields = page.locator(_SEARCH_INPUTS)
            field = None
            for index in range(fields.count()):
                candidate = fields.nth(index)
                if candidate.is_visible() and candidate.is_enabled():
                    field = candidate
                    break
            if field is None:
                try:
                    fields.first.wait_for(state="visible", timeout=15000)
                except Exception:
                    raise CareerAxisError("Could not identify CareerAxis's keyword search field; no filtered results were inferred.") from None
                field = fields.first
            field.fill(query)
            if field.evaluate("element => Boolean(element.form)"):
                field.press("Enter")
            else:
                button = page.get_by_role("button", name=re.compile("search", re.I))
                if button.count() == 0:
                    raise CareerAxisError("Could not identify CareerAxis's search action; no filtered results were inferred.")
                button.first.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            self._wait_for_job_results(page)
        else:
            self._wait_for_job_results(page)
        data = self._collect_pages(page, _SEARCH_SNAPSHOT, "opportunities", page_number * limit)
        result = {
            "data": data,
            "snapshot": {
                "retrieved_at": datetime.now(timezone.utc),
                "source_url": page.url,
                "cached": False,
            },
        }
        self._store(key, result)
        return result

    def _search_section(self, section, query, page_number, limit, refresh, current_opportunities_only):
        if section not in _SECTION_PATHS:
            raise CareerAxisError("Choose events, resources, organisations, appointment topics, or internship jobs.")
        credentials = self._credentials()
        key = ("section", section, query, page_number, limit, current_opportunities_only)
        cached = self._cached(key, refresh)
        if cached is not None:
            return cached

        self._navigate(_SECTION_PATHS[section], credentials)
        page = self._page
        previous_urls = None

        if section == "events" and query:
            self._expand_event_filters(page)
            previous_urls = tuple(item["url"] for item in page.evaluate(_PORTAL_SNAPSHOT, section)["items"])
            field = self._first_visible(page, "#text-search")
            field.fill(query)
            field.press("Enter")
        elif section == "resources" and query:
            previous_urls = tuple(item["url"] for item in page.evaluate(_PORTAL_SNAPSHOT, section)["items"])
            self._first_visible(page, "#resource-search").fill(query)
            self._click_search(page)
        elif section == "organisations" and (query or current_opportunities_only):
            previous_urls = tuple(item["url"] for item in page.evaluate(_PORTAL_SNAPSHOT, section)["items"])
            if query:
                self._first_visible(page, "#query").fill(query)
            if current_opportunities_only:
                checkbox = page.locator('input[name="WithCurrentJobs"]')
                if not checkbox.count():
                    raise CareerAxisError("CareerAxis did not expose the current-opportunities filter; no filtered results were inferred.")
                self._click_associated_label(checkbox.first)
                if not checkbox.first.is_checked():
                    raise CareerAxisError("CareerAxis did not apply the current-opportunities filter.")
            self._click_search(page)
        elif section == "appointment_topics" and query:
            previous_urls = tuple(item["url"] for item in page.evaluate(_PORTAL_SNAPSHOT, section)["items"])
            field = self._first_visible(page, 'input[placeholder*="Search topics" i]')
            field.fill(query)
            field.press("Enter")

        if previous_urls is not None:
            page.wait_for_load_state("networkidle", timeout=20000)
        self._wait_for_portal_results(page, section)
        accept = None
        if section == "internship_jobs" and query:
            needle = query.casefold()
            accept = lambda item: needle in (item["title"] + " " + item["summary"]).casefold()
        data = self._collect_pages(page, _PORTAL_SNAPSHOT, "items", page_number * limit,
                                   section=section, accept=accept)

        result = {
            "data": data,
            "snapshot": {
                "retrieved_at": datetime.now(timezone.utc),
                "source_url": page.url,
                "cached": False,
            },
        }
        self._store(key, result)
        return result

    @staticmethod
    def _next_page_control(page, native_page):
        selectors = 'a[rel="next"],a[aria-label*="next" i],button[aria-label*="next" i]'
        groups = [page.locator(selectors),
                  page.get_by_role("button", name=re.compile(r"^(next(?: page)?|load more results|show more)$", re.I)),
                  page.get_by_role("link", name=re.compile(r"^(next(?: page)?|load more results|show more|›|»)$", re.I)),
                  page.locator(".pagination a").filter(has_text=re.compile(r"^\s*" + str(native_page + 1) + r"\s*$"))]
        for controls in groups:
            for index in range(controls.count()):
                control = controls.nth(index)
                if control.is_visible() and control.is_enabled() and control.evaluate(
                    "el=>!el.closest('.disabled,[disabled],[aria-disabled=\"true\"]')"
                ):
                    return control
        return None

    def _collect_pages(self, page, projection, key, target_count, *, section=None, accept=None):
        """Collect native pages before applying the caller's page size; supports append and replace UIs."""
        records = OrderedDict()
        read = lambda: page.evaluate(projection, section) if section else page.evaluate(projection)
        data = read()
        for native_page in range(1, 51):
            for item in data[key]:
                if accept is None or accept(item):
                    records.setdefault(item["url"], item)
            if len(records) >= target_count or not data["has_next_page"]:
                break
            if native_page == 50:
                raise CareerAxisError("This lookup exceeded 50 native result pages; narrow the search.")
            control = self._next_page_control(page, native_page)
            if control is None:
                raise CareerAxisError("CareerAxis reported another page but did not expose a usable next-page control.")
            previous = tuple(item["url"] for item in data[key])
            control.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            if section:
                self._wait_for_portal_results(page, section, previous_urls=previous)
            else:
                self._wait_for_job_results(page, previous_urls=previous)
            data = read()
        data[key] = list(records.values())
        data["no_results"] = not records and (accept is not None or data.get("no_results") is True)
        return data

    @staticmethod
    def _first_visible(page, selector):
        fields = page.locator(selector)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for index in range(fields.count()):
                field = fields.nth(index)
                if field.is_visible() and field.is_enabled():
                    return field
            page.wait_for_timeout(250)
        raise CareerAxisError("CareerAxis did not expose the requested search field; no search was inferred.")

    @staticmethod
    def _expand_event_filters(page):
        buttons = page.get_by_role("button", name="Show filter", exact=True)
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.is_visible() and button.is_enabled():
                button.click()
                page.wait_for_timeout(350)
                break
        CareerAxisSession._first_visible(page, "#text-search")

    @staticmethod
    def _click_associated_label(control):
        if control.is_checked():
            return
        control.evaluate("element => { const label = element.labels && element.labels[0]; if (label) label.click(); else element.click(); }")

    @staticmethod
    def _click_search(page):
        buttons = page.get_by_role("button", name="Search", exact=True)
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.is_visible() and button.is_enabled():
                button.click()
                return
        raise CareerAxisError("CareerAxis did not expose its search action; no filtered results were inferred.")

    @staticmethod
    def _wait_for_portal_results(page, section, *, previous_urls=None):
        deadline = time.monotonic() + 20
        empty_since = None
        while time.monotonic() < deadline:
            state = page.evaluate(_PORTAL_SNAPSHOT, section)
            urls = tuple(item["url"] for item in state["items"])
            if urls and (previous_urls is None or urls != previous_urls):
                return state
            if state["no_results"] and not urls:
                empty_since = empty_since or time.monotonic()
                if time.monotonic() - empty_since >= 3:
                    return state
            else:
                empty_since = None
            page.wait_for_timeout(300)
        raise CareerAxisError("CareerAxis did not finish loading this section; no records were inferred.")

    def _get_opportunity(self, url, refresh):
        credentials = self._credentials()
        key = ("opportunity", url)
        cached = self._cached(key, refresh)
        if cached is not None:
            return cached
        path = urlsplit(url).path
        query = urlsplit(url).query
        if query:
            path += "?" + query
        self._navigate(path, credentials)
        page = self._page
        self._wait_for_detail(page)
        result = {
            "data": page.evaluate(_DETAIL_SNAPSHOT),
            "snapshot": {
                "retrieved_at": datetime.now(timezone.utc),
                "source_url": page.url,
                "cached": False,
            },
        }
        self._store(key, result)
        return result

    def _get_portal_record(self, url, refresh):
        credentials = self._credentials()
        key = ("portal_record", url)
        cached = self._cached(key, refresh)
        if cached is not None:
            return cached
        parsed = urlsplit(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        self._navigate(path, credentials)
        page = self._page
        self._wait_for_detail(page)
        result = {
            "data": page.evaluate(_DETAIL_SNAPSHOT),
            "snapshot": {
                "retrieved_at": datetime.now(timezone.utc),
                "source_url": page.url,
                "cached": False,
            },
        }
        self._store(key, result)
        return result

    @staticmethod
    def _wait_for_job_results(page, *, previous_urls=None):
        deadline = time.monotonic() + 20
        empty_since = None
        while time.monotonic() < deadline:
            state = page.evaluate(_JOB_STATE)
            urls = tuple(state["urls"])
            if urls and (previous_urls is None or urls != previous_urls):
                return
            if state["no_results"] and not urls:
                empty_since = empty_since or time.monotonic()
                if time.monotonic() - empty_since >= 3:
                    return
            else:
                empty_since = None
            page.wait_for_timeout(250)
        raise CareerAxisError("CareerAxis job results did not finish loading; no results were inferred.")

    @staticmethod
    def _wait_for_detail(page):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = page.evaluate(r"""() => {
              const clean = value => (value || "").replace(/[\u200B-\u200F\uFEFF\u2060-\u206F]/g, "").replace(/\s+/g, " ").trim();
              const main = document.querySelector("main") || document.querySelector("[role=main]") || document.body;
              const generic = /^(students|loading\.\.\.|be scam-aware|appointments|documents|resources|search events|search topics|search organisations|internship|internship opportunities|opportunity details|careeraxis|careeraxis opportunities|opportunities|notifications)$/i;
              const headings = [...main.querySelectorAll("h1,h2,h3")].map(node => clean(node.innerText || node.textContent));
              const documentTitle = clean(document.title.replace(/^[^|]+\|\s*/, ""));
              const heading = !generic.test(documentTitle) && !/\{\{[^}]+\}\}/.test(documentTitle)
                ? documentTitle
                : headings.find(value => value && !generic.test(value) && !/\{\{[^}]+\}\}/.test(value));
              const text = clean(main.innerText || main.textContent);
              const placeholder = !heading;
              return {ready: !placeholder && text.length > 250, heading};
            }""")
            if state["ready"]:
                return
            page.wait_for_timeout(250)
        raise CareerAxisError("CareerAxis detail page did not finish loading; no detail text was inferred.")

    def _cached(self, key, refresh):
        entry = self._cache.get(key)
        if not refresh and self.ttl and entry and time.monotonic() - entry[0] < self.ttl:
            self._cache.move_to_end(key)
            result = deepcopy(entry[1])
            result["snapshot"]["cached"] = True
            return result
        return None

    def _store(self, key, result):
        if self.ttl:
            self._cache[key] = (time.monotonic(), deepcopy(result))
            self._cache.move_to_end(key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)

    def _dispose(self):
        for resource, method in ((self._context, "close"), (self._browser, "close"), (self._playwright, "stop")):
            if resource:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        self._playwright = self._browser = self._context = self._page = None
        self._verified = False
        self._last_verified = None
        self._cache.clear()

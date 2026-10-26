"""Ephemeral SSO and serialized native Service Portal workflows."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from threading import RLock, get_ident
import time
from urllib.parse import urlencode, urlsplit

from shared.credentials import CredentialError, credential_status, read_credentials
from .models import AuthStatus, OneStopError


BASE = "https://ntuadminonestop.service-now.com"
PORTAL = BASE + "/ntussp"
SYS_ID = re.compile(r"[0-9a-f]{32}")
LIST_PAGES = {
    ("case", "open"): "my_open_incidents",
    ("case", "closed"): "my_closed_incidents",
    ("request", "open"): "my_open_requests",
    ("request", "closed"): "my_closed_requests",
}
_PAGES = {
    "__home__": set(), "ntu_announcements": set(), "ntu_to_do_detail": set(),
    "ntu_popularsites": set(), "ntu_appointment_list": set(), "sc_favourite": set(),
    "ntu_adhoc_payment": set(), "user_profile": set(), "sc_cart": set(),
    "search": {"q", "t"}, "sc_home": set(), "sc_category": {"sys_id"},
    "sc_cat_item": {"sys_id"}, "kb_article_view": {"sys_kb_id"},
    "sc_request": {"sys_id", "table", "view"}, "ticket": {"sys_id", "table", "view"},
    **{page: set() for page in LIST_PAGES.values()},
}
_CHALLENGE = re.compile(
    r"captcha|approve (?:the )?sign.in|verify your identity|verification code|authenticator|multi.factor", re.I
)

# Read data from the hydrated widget scope. The initial /api/now/sp/page response
# is incomplete for several NTU widgets. No controllers or server actions run here.
_EXTRACT = r"""() => {
  const result = {};
  const sce = angular.element(document.body).injector().get('$sce');
  const html = v => { const text=sce.valueOf(v); return typeof text==='string'?text:''; };
  const pick = (o, keys) => Object.fromEntries(keys.filter(k => k in o).map(k => [k, o[k]]));
  const item = x => pick(x, ['sys_id', 'name', 'short_description', 'type', 'content_type',
    'url', 'page', 'kb_article', 'number', 'text', 'publishedUTC']);
  const field = x => pick(x, ['name', 'label', 'display_value', 'visible_standalone', 'visible_summary']);
  for (const e of document.querySelectorAll('div[widget][data]')) {
    const s = angular.element(e).scope();
    if (!s || !s.widget || !s.data) continue;
    const d = s.data, id = s.widget.id;
    if (id === 'ntu-sc-categories') result.categories = pick(d, ['total', 'categoriesList']);
    if (s.widget.name === 'SC Popular Items') result.popular = {
      items: (d.items || []).map(item), limit: d.limit};
    if (id === 'ntu_sc_category_page') result.category = {
      ...pick(d, ['category_id', 'category', 'total_item', 'limit']), items: (d.items || []).map(item)};
    if (id === 'ntu_search_page') result.search = {
      ...pick(d, ['q', 't', 'limit']), results: (d.results || []).map(item)};
    if (id === 'ntu-widget-sc-cat-item-v2') {
      const i = d.sc_cat_item;
      result.item = {recordFound: d.recordFound};
      if (i) result.item = {...result.item,
        ...pick(i, ['sys_id', 'name', 'short_description', 'can_view', 'mandatory_attachment']),
        description: html(i.description),
        fields: Object.values(i._fields || {}).filter(f => f.visible === true && f.label &&
          !['container_start', 'container_end', 'container_split', 'widget', 'macro', 'macro_with_label'].includes(f.type)).map(f => ({
          name: f.name, label: f.label, type: f.type,
          mandatory: f.mandatory === true, read_only: f.readonly === true || f.read_only === true,
          choices: (f.choices || []).map(c => ({value: String(c.value), label: c.label}))
        }))};
    }
    if (id === 'kb-article-content') result.article = {
      ...pick(d, ['isValid', 'knowledgeExists', 'article_sys_id', 'number', 'shortDesc', 'sys_updated_on']),
      isTemplate: d.articleType==='wiki'?false:d.kbContentData ? d.kbContentData.isTemplate : null,
      template_fields: d.kbContentData?.isTemplate&&Array.isArray(d.kbContentData.data)?
        d.kbContentData.data.map(f=>({label:f.label||'',type:f.type,content:html(f.content)})):null,
      content: d.articleType==='wiki'?html(d.kbWiki):d.kbContentData&&!d.kbContentData.isTemplate?html(d.kbContentData.data):''};
    if (id === 'simple-list-w-menu') result.requests = {
      ...pick(d, ['isValid', 'count', 'maxCount']),
      secondary_names: s.options.secondary_fields,
      list: (d.list || []).map(r => ({...pick(r, ['sys_id', 'className', 'url']),
        display_field: field(r.display_field), secondary_fields: r.secondary_fields.map(field)}))};
    if (id === 'ntu_ticket_fields') result.ticket_fields = {
      ...pick(d, ['canRead', 'sys_id', 'table']), fields: (d.fields || []).map(field),
      variables: (d.variables || []).filter(f => f.visible_standalone === true).map(field)};
    if (id === 'ntu_new_requested_items') result.requested_items = (d.list || []).map(r => pick(r, ['sys_id', 'stage']));
  }
  const serialized = JSON.stringify(result);
  if (new TextEncoder().encode(serialized).byteLength > 5000000) throw new Error('One Stop widget data exceeded 5 MB');
  return JSON.parse(serialized);
}"""


@dataclass
class PortalPage:
    data: dict
    retrieved_at: datetime
    source_url: str
    revision: str
    cached: bool = False

    def metadata(self):
        return dict(retrieved_at=self.retrieved_at, source_url=self.source_url, cached=self.cached)


def page_url(page_id, params):
    if page_id not in _PAGES or set(params) != _PAGES[page_id]:
        raise OneStopError("This One Stop page is not an allowed read operation.")
    for name in ("sys_id", "sys_kb_id"):
        if name in params and not SYS_ID.fullmatch(params[name]):
            raise OneStopError("One Stop IDs must be 32 lowercase hexadecimal characters.")
    if page_id == "search" and (
        params["t"] not in {"sc", "kb"} or not isinstance(params["q"], str)
        or not 1 <= len(params["q"].strip()) <= 200
        or any(ord(c) < 32 for c in params["q"])
    ):
        raise OneStopError("Provide a search query of 1–200 characters without control characters.")
    if page_id in {"sc_request", "ticket"} and (
        not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", params["table"]) or params["view"] != "ntusp"
    ):
        raise OneStopError("One Stop returned an unsupported ticket link.")
    return PORTAL if page_id == "__home__" else PORTAL + "?" + urlencode({"id": page_id, **params})


class OneStopSession:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onestop")
        self._lock = RLock()
        self._closed = False
        self._playwright = self._browser = self._context = self._page = None
        self._revision = None
        self._verified = False
        self._last_verified = None
        self._login_not_before = self._last_request = 0.0
        self._cache = OrderedDict()
        self._drafts = {}
        self._checkouts = {}
        self._worker_id = None

    def _run(self, function, *args):
        if get_ident() == self._worker_id:
            return function(*args)
        with self._lock:
            if self._closed:
                raise OneStopError("The One Stop session is closed; restart the MCP server.")
            future = self._executor.submit(self._invoke, function, args)
        try:
            return future.result()
        except OneStopError:
            raise
        except Exception:
            # Playwright exceptions can embed login arguments and authenticated URLs.
            raise OneStopError("One Stop returned an unexpected page or the connection failed; retry later.") from None

    def _invoke(self, function, args):
        self._worker_id = get_ident()
        return function(*args)

    def workflow(self, function, *args):
        """Serialize a whole portal workflow, including its ownership checks."""
        return self._run(self._workflow, function, args)

    def _workflow(self, function, args):
        credentials = self._credentials()
        try:
            credentials.require_login()
        except CredentialError as error:
            raise OneStopError(str(error)) from None
        if not self._verified:
            self._login(credentials)
        return function(self, credentials.revision, *args)

    def before_write(self, revision):
        credentials = self._credentials()
        try:
            credentials.require_login()
        except CredentialError as error:
            raise OneStopError(str(error)) from None
        if credentials.revision != revision:
            raise OneStopError("The saved account changed; prepare this action again.")
        self._cache.clear()

    def _dispose(self):
        for resource, method in ((self._browser, "close"), (self._playwright, "stop")):
            if resource:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        self._playwright = self._browser = self._context = self._page = None
        self._verified = False
        self._last_verified = None
        self._cache.clear()
        self._drafts.clear()
        self._checkouts.clear()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._executor.submit(self._dispose).result()
                finally:
                    self._executor.shutdown()

    def _credentials(self):
        try:
            credentials = read_credentials()
        except CredentialError as error:
            self._dispose()
            raise OneStopError(str(error)) from None
        if self._revision != credentials.revision or not credentials.username:
            self._dispose()
            self._login_not_before = 0
            self._revision = credentials.revision
        return credentials

    def status(self):
        return self._run(self._status)

    def _status(self):
        status = credential_status()
        if status["credentials_configured"] is True:
            try:
                self._credentials()
            except OneStopError:
                status = credential_status()
        else:
            self._dispose()
        return AuthStatus(**status, session_verified=self._verified, last_verified_at=self._last_verified)

    def _open(self):
        if self._browser:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
        except Exception:
            self._dispose()
            raise OneStopError(
                "One Stop needs the personal extra and Chromium. Run `uvx --from 'playwright>=1.50,<2' playwright install chromium`."
            ) from None

    def _logged_in(self):
        u = urlsplit(self._page.url)
        return u.scheme == "https" and u.netloc == urlsplit(BASE).netloc and self._page.evaluate(
            "typeof logged_in !== 'undefined' && logged_in === true"
        )

    def _login(self, credentials):
        if time.monotonic() < self._login_not_before:
            raise OneStopError("A recent One Stop login did not complete. Wait one minute before retrying.")
        self._login_not_before = time.monotonic() + 60
        self._verified = False
        self._last_verified = None
        self._cache.clear()
        self._open()
        self._page.goto(PORTAL, wait_until="domcontentloaded", timeout=30000)
        from playwright.sync_api import Error
        deadline = time.monotonic() + 60
        password_sent = False
        while time.monotonic() < deadline:
            try:
                u = urlsplit(self._page.url)
                if (u.scheme != "https" or u.port not in (None, 443) or u.username or u.password
                    or u.hostname not in {urlsplit(BASE).hostname, "loginfs.ntu.edu.sg"}):
                    raise OneStopError("One Stop reached an unsupported login host; no further credentials were submitted.")
                if self._logged_in():
                    self._verified = True
                    self._last_verified = datetime.now(timezone.utc)
                    self._login_not_before = 0
                    return
                if u.hostname == "loginfs.ntu.edu.sg":
                    body = self._page.locator("body").inner_text(timeout=5000)
                    if _CHALLENGE.search(body):
                        raise OneStopError("One Stop requires interactive MFA or CAPTCHA; this tool cannot complete it.")
                    if password_sent and re.search(r"incorrect|invalid password|account.*locked|too many.*attempts", body, re.I):
                        raise OneStopError("NTU rejected the One Stop login. No automatic password retry was made.")
                    if not password_sent and u.path == "/adfs/ls/" and self._page.locator("#passwordInput:visible").count():
                        # This integration is for the student portal, like LibFacilities.
                        if not credentials.email.lower().endswith("@e.ntu.edu.sg"):
                            raise OneStopError("One Stop student tools require a saved NTU student network account.")
                        self._page.locator("#userNameInput").fill(credentials.username + "@student.main.ntu.edu.sg")
                        self._page.locator("#passwordInput").fill(credentials.password)
                        password_sent = True
                        self._page.locator("#submitButton").click()
            except Error as error:
                if not any(message in str(error) for message in ("Execution context was destroyed", "navigation")):
                    raise
            self._page.wait_for_timeout(300)
        raise OneStopError("One Stop login timed out. No automatic password retry was made.")

    def read(self, page_id, params=None, refresh=False):
        params = params or {}
        url = page_url(page_id, params)
        return self._run(self._read, url, refresh)

    def _read(self, url, refresh):
        credentials = self._credentials()
        try:
            credentials.require_login()
        except CredentialError as error:
            raise OneStopError(str(error)) from None
        cached = self._cache.get(url)
        if not refresh and cached and time.monotonic() - cached[0] < 60:
            self._cache.move_to_end(url)
            result = deepcopy(cached[1])
            result.cached = True
            return result
        if not self._verified:
            self._login(credentials)
        for attempt in range(2):
            time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            response = self._page.goto(url, wait_until="networkidle", timeout=30000)
            if response is not None and response.status >= 400:
                raise OneStopError(f"One Stop returned HTTP {response.status}; retry later.")
            if not self._logged_in():
                self._verified = False
                self._last_verified = None
                self._cache.clear()
                if attempt == 0:
                    self._login(credentials)
                    continue
                raise OneStopError("One Stop's session expired again after login; retry later.")
            self._page.wait_for_function(
                "typeof angular !== 'undefined' && !!document.querySelector('div[widget][data]')",
                timeout=15000,
            )
            # Expand only the native read controls, preserving their own filters.
            self._page.evaluate(r"""async () => {
              const scopes=[...document.querySelectorAll('div[widget][data]')]
                .map(e=>angular.element(e).scope()).filter(s=>s&&s.widget&&s.data);
              for(const s of scopes) {
                if(s.widget.id==='simple-list-w-menu' && s.data.count>s.data.list.length) {
                  s.options.maximum_entries=Math.min(500,s.data.count);
                  await s.server.update();
                }
                if(s.widget.id==='ntu_sc_category_page' && s.data.total_item>s.data.items.length) {
                  s.data.new_limit=Math.min(500,s.data.total_item);
                  await s.server.update();
                }
                if(s.widget.id==='ntu-sc-categories'&&s.data.total>s.data.categoriesList.length) {
                  s.data.getAll=true; await s.server.update();
                }
              }
            }""")
            data = self._page.evaluate(_EXTRACT)
            if not isinstance(data, dict):
                raise OneStopError("One Stop returned an unsupported widget format.")
            result = PortalPage(data, datetime.now(timezone.utc), url, credentials.revision)
            self._cache[url] = (time.monotonic(), deepcopy(result))
            self._cache.move_to_end(url)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return result

"""Optional in-memory LibFacilities login and read-only daily time grids."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math
import re
from threading import RLock
import time
from urllib.parse import parse_qs, urlsplit

from shared.credentials import CredentialError, read_credentials
from .facilities import BASE, requested_time
from .models import FacilitySchedule, LibraryError, SpaceSchedule
from .schedule import parse_slots, schedule_path


_CHALLENGE = re.compile(
    r"captcha|approve (?:the )?sign.in|verify your identity|verification code|authenticator|multi.factor",
    re.I,
)


class FacilitySession:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libfacilities")
        self._lock = RLock()
        self._closed = False
        self._playwright = self._browser = self._context = self._page = None
        self._revision = None
        self._login_not_before = self._last_request = 0.0
        self._cache = OrderedDict()

    def _dispose(self):
        for resource, method in ((self._browser, "close"), (self._playwright, "stop")):
            if resource:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        self._playwright = self._browser = self._context = self._page = None
        self._cache.clear()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._executor.submit(self._dispose).result()
                finally:
                    self._executor.shutdown()

    def get_schedule(self, day, space_id=None, location_id=None, group_id=None, refresh=False):
        requested_time(day, "00:00")
        path = schedule_path(space_id, location_id, group_id)
        with self._lock:
            if self._closed:
                raise LibraryError("The library session is closed; restart the MCP server.")
            future = self._executor.submit(self._get_schedule, path, day, refresh)
        try:
            return future.result()
        except LibraryError:
            raise
        except Exception:
            # Playwright errors can contain credentials, session URLs, and page content.
            raise LibraryError(
                "LibFacilities returned an unexpected page or a connection failed; retry later."
            ) from None

    def _pace(self):
        time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()

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
            raise LibraryError(
                "LibFacilities login needs Playwright and Chromium. Install the personal extra and run `uvx --from 'playwright>=1.50,<2' playwright install chromium`."
            ) from None

    def _navigate(self, path, credentials):
        self._open()
        self._pace()
        page = self._page
        response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            raise LibraryError(f"LibFacilities returned HTTP {response.status}; retry later.")
        deadline = time.monotonic() + 45
        password_sent = False
        while time.monotonic() < deadline:
            parsed = urlsplit(page.url)
            body = page.locator("body").inner_text(timeout=5000)
            if _CHALLENGE.search(body):
                raise LibraryError(
                    "LibFacilities requires MFA or CAPTCHA; this tool cannot complete interactive verification."
                )
            if (
                parsed.scheme != "https"
                or parsed.port not in (None, 443)
                or parsed.username
                or parsed.hostname
                not in {
                    "libcalendar.ntu.edu.sg",
                    "au.libauth.com",
                    "loginfs.ntu.edu.sg",
                }
            ):
                raise LibraryError(
                    "LibFacilities reached an unsupported login flow; no further credentials were submitted."
                )
            if (
                parsed.hostname == "libcalendar.ntu.edu.sg"
                and parsed.path == urlsplit(path).path
                and page.evaluate("typeof springyPage !== 'undefined' && springyPage.locationId > 0")
            ):
                return
            if password_sent and re.search(
                r"incorrect|invalid password|account.*locked|too many.*attempts", body, re.I
            ):
                raise LibraryError(
                    "NTU rejected the library login. Check the saved credentials; no password retry was made."
                )
            if (
                parsed.hostname == "loginfs.ntu.edu.sg"
                and parsed.path == "/adfs/ls/"
                and page.locator("#passwordInput:visible").count()
                and not password_sent
            ):
                if time.monotonic() < self._login_not_before:
                    raise LibraryError(
                        "A recent library login did not complete. Wait one minute before retrying."
                    )
                self._login_not_before = time.monotonic() + 60
                page.locator("#userNameInput").fill(credentials.username + "@student.main.ntu.edu.sg")
                page.locator("#passwordInput").fill(credentials.password)
                password_sent = True
                page.locator("#submitButton").click()
            page.wait_for_timeout(300)
        raise LibraryError(
            "LibFacilities login timed out; retry later. No automatic password retry was made."
        )

    def _get_schedule(self, path, day, refresh):
        try:
            credentials = read_credentials()
            credentials.require_login()
        except CredentialError as error:
            self._dispose()
            raise LibraryError(str(error)) from None
        if self._revision != credentials.revision:
            self._dispose()
            self._login_not_before = 0
            self._revision = credentials.revision
        key = (path, day)
        cached = self._cache.get(key)
        if not refresh and cached and time.monotonic() - cached[0] < 60:
            result = deepcopy(cached[1])
            result.cached = True
            self._cache.move_to_end(key)
            return result
        for attempt in range(2):
            self._navigate(path, credentials)
            page = self._page
            settings = page.evaluate(
                "({lid:springyPage.locationId,gid:springyPage.groupId,eid:springyPage.itemId,seat:springyPage.isSeatBooking,seatId:springyPage.seatId,zone:springyPage.zoneId,pageSize:springyPage.pageSize,count:springyPage.resourceCount})"
            )
            if (
                any(
                    type(settings[k]) is not int or settings[k] < 0
                    for k in ("lid", "gid", "seat", "seatId", "zone", "pageSize", "count")
                )
                or type(settings["eid"]) is not int
                or settings["eid"] < -1
                or settings["pageSize"] == 0
                or settings["count"] > 180
            ):
                raise LibraryError(
                    "LibFacilities returned an unsupported resource list; request a specific space_id."
                )
            if path.startswith("/space/"):
                matches = settings["eid"] == int(path.rsplit("/", 1)[1])
            else:
                query = parse_qs(urlsplit(path).query)
                matches = settings["lid"] == int(query["lid"][0]) and settings["gid"] == int(query["gid"][0])
            if not matches:
                raise LibraryError("LibFacilities returned a different facility than requested.")
            title = " ".join(page.locator("h1").first.inner_text().split())
            description = (
                page.locator("#s-lc-group-description").inner_text()
                if page.locator("#s-lc-group-description").count()
                else None
            )
            resources = page.evaluate(
                "resources.map(r=>[String(r.id).replace(/^eid_/,''),typeof r.title==='string'?r.title:null])"
            )
            names = dict(resources)
            if (
                len(names) != len(resources)
                or len(names) != settings["count"]
                or any(not re.fullmatch(r"[1-9][0-9]*", key) for key in names)
            ):
                raise LibraryError("LibFacilities returned an inconsistent resource list.")
            all_slots = []
            expired = False
            window_end = None
            for index in range(max(1, math.ceil(settings["count"] / settings["pageSize"]))):
                self._pace()
                response = self._context.request.post(
                    BASE + "/spaces/availability/grid",
                    form={
                        **{
                            k: settings[k]
                            for k in ("lid", "gid", "eid", "seat", "seatId", "zone", "pageSize")
                        },
                        "start": day,
                        "end": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                        "pageIndex": index,
                    },
                    headers={"X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": BASE + path},
                    max_redirects=0,
                    timeout=30000,
                )
                try:
                    if response.status in (301, 302, 303, 307, 308, 401):
                        expired = True
                        break
                    if response.status != 200 or "application/json" not in response.headers.get(
                        "content-type", ""
                    ):
                        raise LibraryError(
                            f"LibFacilities did not return a readable availability grid (HTTP {response.status}); retry later."
                        )
                    if len(response.body()) > 5_000_000:
                        raise LibraryError(
                            "LibFacilities time grid exceeded the 5 MB limit; request one space."
                        )
                    data = response.json()
                    all_slots.extend(parse_slots(data, {}, day))
                    window_end = data.get("windowEnd")
                finally:
                    response.dispose()
            if expired:
                if attempt == 0:
                    self._cache.clear()
                    self._context.clear_cookies()
                    continue
                raise LibraryError("LibFacilities session expired again; retry later.")
            if len({s.item_id for s in all_slots}) != len(all_slots):
                raise LibraryError(
                    "LibFacilities repeated resources across pages; no complete timetable was inferred."
                )
            for item in all_slots:
                item.name = names.get(item.item_id)
                if item.item_id not in names:
                    raise LibraryError("LibFacilities returned slots for an unexpected resource.")
            known = {item.item_id for item in all_slots}
            all_slots.extend(
                SpaceSchedule(item_id=key, name=name, slots=[])
                for key, name in names.items()
                if key not in known
            )
            result = FacilitySchedule(
                date=day,
                title=title,
                description=description,
                spaces=all_slots,
                window_end=window_end,
                retrieved_at=datetime.now(timezone.utc),
                source_url=BASE + path,
                cached=False,
            )
            self._cache[key] = (time.monotonic(), result)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return deepcopy(result)

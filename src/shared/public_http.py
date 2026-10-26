"""Pooled, bounded public HTTPS reads shared by NTU services."""

import os
import time
import weakref
from collections import OrderedDict
from concurrent.futures import Future, wait
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookiejar import DefaultCookiePolicy
from threading import BoundedSemaphore, Lock
from urllib.parse import urljoin, urlsplit

import httpx

MAX_RESPONSE_BYTES = 8_000_000
MAX_RETRY_DELAY_SECONDS = 10.0
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 2
REQUEST_CONCURRENCY = 2
REQUEST_INTERVAL_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 20.0
CACHE_TTL_SECONDS = 300.0
MAX_CACHE_ENTRIES = 64
_RETRYABLE = {429, 500, 502, 503, 504}
_REDIRECTS = {301, 302, 303, 307, 308}
_SCHEDULERS_LOCK = Lock()


def _setting(name, default, cast, minimum, maximum):
    try:
        value = cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise RuntimeError(
            f"{name} must be a number between {minimum} and {maximum}."
        ) from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be a number between {minimum} and {maximum}.")
    return value


REQUEST_CONCURRENCY = _setting(
    "NTU_PUBLIC_HTTP_CONCURRENCY", REQUEST_CONCURRENCY, int, 1, 8
)
REQUEST_INTERVAL_SECONDS = _setting(
    "NTU_PUBLIC_HTTP_INTERVAL_SECONDS", REQUEST_INTERVAL_SECONDS, float, 0.0, 10.0
)
REQUEST_TIMEOUT_SECONDS = _setting(
    "NTU_PUBLIC_HTTP_TIMEOUT_SECONDS", REQUEST_TIMEOUT_SECONDS, float, 1.0, 120.0
)
MAX_RETRY_DELAY_SECONDS = _setting(
    "NTU_PUBLIC_HTTP_MAX_RETRY_DELAY_SECONDS", MAX_RETRY_DELAY_SECONDS, float, 0.0, 30.0
)


class PublicRequestError(RuntimeError):
    def __init__(
        self, message, *, status=None, content_type=None, response_too_large=False
    ):
        super().__init__(message)
        self.status = status
        self.content_type = content_type
        self.response_too_large = response_too_large


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class _HostScheduler:
    """Share concurrency and pacing between clients that call the same host."""

    def __init__(self):
        self._slots = BoundedSemaphore(REQUEST_CONCURRENCY)
        self._pace_lock = Lock()
        self._last_request = 0.0
        self._defer_until = 0.0

    @contextmanager
    def request_slot(self):
        self._slots.acquire()
        try:
            with self._pace_lock:
                now = time.monotonic()
                ready_at = max(
                    self._defer_until,
                    self._last_request + REQUEST_INTERVAL_SECONDS,
                )
                delay = max(0.0, ready_at - now)
                if delay:
                    time.sleep(delay)
                self._last_request = time.monotonic()
            yield
        finally:
            self._slots.release()

    def defer(self, seconds):
        if seconds <= 0:
            return
        with self._pace_lock:
            self._defer_until = max(self._defer_until, time.monotonic() + seconds)


_SCHEDULERS: dict[str, _HostScheduler] = {}


def _scheduler_for(url):
    host = urlsplit(url).hostname
    if host is None:
        raise PublicRequestError(
            "The public service returned an unexpected URL; retrieval stopped."
        )
    host = host.lower()
    with _SCHEDULERS_LOCK:
        scheduler = _SCHEDULERS.get(host)
        if scheduler is None:
            scheduler = _HostScheduler()
            _SCHEDULERS[host] = scheduler
        return scheduler


@contextmanager
def host_request_slot(url):
    """Apply the process-wide public request limit for the URL's host."""
    with _scheduler_for(url).request_slot():
        yield


def defer_host_requests(url, seconds):
    _scheduler_for(url).defer(seconds)


class _Redirects:
    def __init__(self, hosts):
        self.hosts = frozenset(host.lower() for host in hosts)

    def validate(self, url):
        try:
            parsed = urlsplit(url)
            safe = (
                parsed.scheme == "https"
                and parsed.hostname is not None
                and parsed.hostname.lower() in self.hosts
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
            )
        except (TypeError, ValueError):
            safe = False
        if not safe:
            raise PublicRequestError(
                "The public service returned an unexpected URL or redirect; retrieval stopped."
            )


class PublicHTTPClient:
    def __init__(
        self,
        service,
        hosts,
        content_types,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.service = service
        self.content_types = frozenset(value.lower() for value in content_types)
        self.redirects = _Redirects(hosts)
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                REQUEST_TIMEOUT_SECONDS, connect=min(10.0, REQUEST_TIMEOUT_SECONDS)
            ),
            follow_redirects=False,
            transport=transport,
            headers={
                "User-Agent": "all-abt-ntu-mcp/0.1 (public NTU lookup)",
                "Accept": ", ".join(sorted(self.content_types)),
            },
        )
        self.client.cookies.jar.set_policy(_NoCookies())
        self._lock = Lock()
        self._cache: OrderedDict[str, tuple[float, bytes, datetime]] = OrderedDict()
        self._inflight: dict[tuple[str, bool], Future[tuple[bytes, datetime]]] = {}
        self._closed = False
        self._finalizer = weakref.finalize(self, self.client.close)

    def get(self, url, refresh=False):
        self.redirects.validate(url)
        key = (url, bool(refresh))
        with self._lock:
            if self._closed:
                raise PublicRequestError(
                    f"The {self.service} HTTP client is closed; restart the MCP server."
                )
            cached = self._cache.get(url)
            if (
                not refresh
                and cached is not None
                and time.monotonic() - cached[0] < CACHE_TTL_SECONDS
            ):
                self._cache.move_to_end(url)
                return cached[1], self._snapshot(url, cached[2], cached=True)
            flight = self._inflight.get(key)
            owner = flight is None
            if owner:
                flight = Future()
                self._inflight[key] = flight

        if not owner:
            body, retrieved = flight.result()
            return body, self._snapshot(url, retrieved, cached=True)

        try:
            body, retrieved = self._fetch(url)
        except Exception as error:
            with self._lock:
                if self._inflight.get(key) is flight:
                    del self._inflight[key]
                flight.set_exception(error)
            raise

        with self._lock:
            self._cache[url] = (time.monotonic(), body, retrieved)
            self._cache.move_to_end(url)
            while len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)
            if self._inflight.get(key) is flight:
                del self._inflight[key]
            flight.set_result((body, retrieved))
        return body, self._snapshot(url, retrieved, cached=False)

    @staticmethod
    def _snapshot(url, retrieved, *, cached):
        return dict(retrieved_at=retrieved, source_url=url, cached=cached)

    def invalidate(self, url):
        with self._lock:
            self._cache.pop(url, None)

    def _fetch(self, url):
        current_url = url
        for attempt in range(MAX_ATTEMPTS):
            try:
                status, headers, body = self._request_chain(current_url)
            except httpx.RequestError:
                if attempt + 1 < MAX_ATTEMPTS:
                    defer_host_requests(current_url, min(4.0, 2.0**attempt))
                    continue
                raise PublicRequestError(
                    f"Could not reach {self.service} after two attempts; try again later."
                ) from None
            except httpx.HTTPError:
                raise PublicRequestError(
                    f"{self.service} returned an invalid HTTP response; retrieval stopped."
                ) from None

            if status in _RETRYABLE and attempt + 1 < MAX_ATTEMPTS:
                delay = self._retry_delay(headers.get("retry-after"))
                if delay <= MAX_RETRY_DELAY_SECONDS:
                    defer_host_requests(current_url, delay)
                    continue
            if status >= 400:
                raise PublicRequestError(
                    f"{self.service} returned HTTP {status}; check the request or try again later.",
                    status=status,
                )
            retrieved = datetime.now(timezone.utc)
            return body, retrieved
        raise PublicRequestError(
            f"Could not reach {self.service} after two attempts; try again later."
        )

    def _request_chain(self, url):
        current_url = url
        for _ in range(MAX_REDIRECTS + 1):
            self.redirects.validate(current_url)
            with (
                host_request_slot(current_url),
                self.client.stream("GET", current_url) as response,
            ):
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise PublicRequestError(
                            f"{self.service} returned an incomplete redirect; retrieval stopped."
                        )
                    current_url = urljoin(current_url, location)
                    self.redirects.validate(current_url)
                    continue

                headers = response.headers
                status = response.status_code
                if status in _RETRYABLE or status >= 400:
                    return status, headers, b""
                content_type = (
                    headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type not in self.content_types:
                    raise PublicRequestError(
                        f"{self.service} returned an unexpected content type; no data was inferred.",
                        content_type=content_type,
                    )
                length = headers.get("content-length")
                if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                    raise PublicRequestError(
                        f"{self.service} response exceeded the 8 MB safety limit.",
                        response_too_large=True,
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise PublicRequestError(
                            f"{self.service} response exceeded the 8 MB safety limit.",
                            response_too_large=True,
                        )
                return status, headers, bytes(body)
        raise PublicRequestError(
            f"{self.service} returned too many redirects; retrieval stopped."
        )

    @staticmethod
    def _retry_delay(value):
        if value is None:
            return 1.0
        try:
            delay = max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = max(
                    0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()
                )
            except (TypeError, ValueError, OverflowError):
                delay = 1.0
        return delay

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            flights = tuple(self._inflight.values())
        wait(flights)
        try:
            self.client.close()
        finally:
            self._finalizer.detach()

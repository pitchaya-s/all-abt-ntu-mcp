"""Pooled public HTML requests for STARS data endpoints."""

import atexit
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookiejar import DefaultCookiePolicy
from threading import BoundedSemaphore, Lock
from urllib.parse import urljoin, urlsplit
from urllib.request import Request

import httpx

from shared.public_http import defer_host_requests, host_request_slot

USER_AGENT = "all-abt-ntu-mcp/0.1 (NTU timetable lookup)"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 5_000_000
MAX_RETRIES = 2
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_CONCURRENT_REQUESTS = 2
MAX_REDIRECTS = 5
_RETRYABLE = {429, 500, 502, 503, 504}
_REDIRECTS = {301, 302, 303, 307, 308}
_ALLOWED_HOSTS = frozenset({"wis.ntu.edu.sg", "wish.wis.ntu.edu.sg"})


class NTURequestError(RuntimeError):
    pass


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


_public_client = httpx.Client(
    timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=10.0),
    follow_redirects=False,
    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
)
_public_client.cookies.jar.set_policy(_NoCookies())
atexit.register(_public_client.close)

_request_slots = BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_pace_lock = Lock()
_last_request_started = 0.0
_inflight_lock = Lock()
_inflight: dict[tuple[object, ...], Future[str]] = {}


def _wait_for_request_slot() -> None:
    global _last_request_started
    with _pace_lock:
        delay = MIN_REQUEST_INTERVAL_SECONDS - (
            time.monotonic() - _last_request_started
        )
        if delay > 0:
            time.sleep(delay)
        _last_request_started = time.monotonic()


def _retry_delay(headers: httpx.Headers | None, attempt: int) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    if value:
        try:
            return min(10.0, max(0.0, float(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return min(
                    10.0,
                    max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()),
                )
            except (TypeError, ValueError, OverflowError):
                pass
    return min(4.0, 2.0**attempt)


def _validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.lower() in _ALLOWED_HOSTS
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise NTURequestError(
            "NTU returned an unexpected URL or redirect; retrieval stopped."
        )


def _request_html(client: httpx.Client, request: Request, page_description: str):
    current_url = request.full_url
    method = request.get_method()
    content = request.data
    if content is not None and not isinstance(content, (str, bytes)):
        raise NTURequestError(
            f"NTU request body for {page_description} is not a supported encoded form."
        )
    headers = dict(request.header_items())

    for _ in range(MAX_REDIRECTS + 1):
        _validate_url(current_url)
        with _request_slots:
            _wait_for_request_slot()
            with (
                host_request_slot(current_url),
                client.stream(
                    method, current_url, content=content, headers=headers
                ) as response,
            ):
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise NTURequestError(
                            f"NTU returned an incomplete redirect for {page_description}."
                        )
                    next_url = urljoin(current_url, location)
                    _validate_url(next_url)
                    if response.status_code in {301, 302, 303} and method not in {
                        "GET",
                        "HEAD",
                    }:
                        method, content = "GET", None
                        headers = {
                            name: value
                            for name, value in headers.items()
                            if name.casefold() not in {"content-length", "content-type"}
                        }
                    current_url = next_url
                    continue

                status = response.status_code
                response_headers = response.headers
                if status >= 400:
                    return (
                        status,
                        response.reason_phrase,
                        response_headers,
                        b"",
                        current_url,
                    )

                content_type = (
                    response_headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type != "text/html":
                    raise NTURequestError(
                        f"NTU returned {content_type!r}; expected HTML for {page_description}."
                    )
                length = response_headers.get("content-length")
                if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                    raise NTURequestError(
                        f"NTU's {page_description} page exceeded the 5 MB safety limit."
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise NTURequestError(
                            f"NTU's {page_description} page exceeded the 5 MB safety limit."
                        )
                return (
                    status,
                    response.reason_phrase,
                    response_headers,
                    bytes(body),
                    current_url,
                )

    raise NTURequestError(
        f"NTU returned too many redirects for {page_description}; retrieval stopped."
    )


def _decode_html(body: bytes, headers: httpx.Headers) -> str:
    charset = None
    for parameter in headers.get("content-type", "").split(";")[1:]:
        name, separator, value = parameter.strip().partition("=")
        if separator and name.casefold() == "charset":
            charset = value.strip().strip("\"'")
            break
    try:
        return body.decode(charset or "windows-1252", errors="replace")
    except LookupError:
        return body.decode("windows-1252", errors="replace")


def _await_inflight(flight: Future[str]) -> str:
    return flight.result()


def _fetch_html_request(
    request: Request, page_description: str, client: httpx.Client | None = None
) -> str:
    request_client = client or _public_client
    key = (
        id(request_client),
        request.get_method(),
        request.full_url,
        request.data,
        page_description,
        tuple(
            sorted((name.casefold(), value) for name, value in request.header_items())
        ),
    )
    with _inflight_lock:
        flight = _inflight.get(key)
        owner = flight is None
        if owner:
            flight = Future()
            _inflight[key] = flight
    if flight is None:
        raise RuntimeError("The STARS request flight was not initialized.")

    if not owner:
        return _await_inflight(flight)

    try:
        result = _fetch_html_request_once(request, page_description, request_client)
    except BaseException as error:
        with _inflight_lock:
            if _inflight.get(key) is flight:
                del _inflight[key]
            flight.set_exception(error)
        raise
    with _inflight_lock:
        if _inflight.get(key) is flight:
            del _inflight[key]
        flight.set_result(result)
    return result


def _fetch_html_request_once(
    request: Request, page_description: str, request_client: httpx.Client
) -> str:
    last_error = "unknown network error"

    for attempt in range(MAX_RETRIES + 1):
        response_headers = None
        response_url = request.full_url
        try:
            status, reason, response_headers, body, response_url = _request_html(
                request_client, request, page_description
            )
            if status < 400:
                return _decode_html(body, response_headers)
            retryable = status == 429 or 500 <= status <= 599
            last_error = f"HTTP {status} {reason}"
        except httpx.RequestError:
            retryable = True
            last_error = "network error"

        if not retryable or attempt >= MAX_RETRIES:
            break
        defer_host_requests(response_url, _retry_delay(response_headers, attempt))

    raise NTURequestError(
        f"Could not retrieve {page_description} from NTU after {MAX_RETRIES + 1} attempt(s): {last_error}."
    )

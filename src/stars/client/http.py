from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from threading import BoundedSemaphore, Lock
import time
from urllib.error import HTTPError, URLError
from urllib.request import OpenerDirector, Request, urlopen

USER_AGENT = "all-abt-ntu-mcp/0.1 (NTU timetable lookup)"

REQUEST_TIMEOUT_SECONDS = 20

MAX_RESPONSE_BYTES = 5_000_000

MAX_RETRIES = 2

MIN_REQUEST_INTERVAL_SECONDS = 1.0

MAX_CONCURRENT_REQUESTS = 2

class NTURequestError(RuntimeError):
    pass

def _wait_for_request_slot() -> None:
    global _last_request_started
    with _pace_lock:
        delay = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_started)
        if delay > 0:
            time.sleep(delay)
        _last_request_started = time.monotonic()

def _retry_delay(error: HTTPError | None, attempt: int) -> float:
    if error is not None:
        value = error.headers.get("Retry-After")
        if value:
            try:
                return min(10.0, max(0.0, float(value)))
            except ValueError:
                try:
                    return min(10.0, max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
    return min(4.0, 2.0**attempt)

def _fetch_html_request(
    request: Request, page_description: str, opener: OpenerDirector | None = None
) -> str:
    last_error: str | None = None

    for attempt in range(MAX_RETRIES + 1):
        retryable = False
        http_error: HTTPError | None = None
        try:
            with _request_slots:
                _wait_for_request_slot()
                response_context = (
                    opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
                    if opener is not None
                    else urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
                )
                with response_context as response:
                    content_type = response.headers.get_content_type()
                    if content_type != "text/html":
                        raise NTURequestError(f"NTU returned {content_type!r}; expected HTML for {page_description}.")
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise NTURequestError(f"NTU's {page_description} page exceeded the 5 MB safety limit.")
                    charset = response.headers.get_content_charset() or "windows-1252"
                    try:
                        return body.decode(charset, errors="replace")
                    except LookupError:
                        return body.decode("windows-1252", errors="replace")
        except HTTPError as error:
            http_error = error
            retryable = error.code == 429 or 500 <= error.code <= 599
            last_error = f"HTTP {error.code} {error.reason}"
            error.close()
        except (URLError, HTTPException, OSError) as error:
            retryable = True
            last_error = str(getattr(error, "reason", error))

        if not retryable or attempt >= MAX_RETRIES:
            break
        time.sleep(_retry_delay(http_error, attempt))

    raise NTURequestError(
        f"Could not retrieve {page_description} from NTU after {MAX_RETRIES + 1} attempt(s): "
        f"{last_error or 'unknown network error'}."
    )

_request_slots = BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_pace_lock = Lock()
_last_request_started = 0.0

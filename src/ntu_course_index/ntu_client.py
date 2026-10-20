from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from threading import BoundedSemaphore, Lock
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .domain import Course
from .parser import (
    CourseUnavailable,
    NTUPageError,
    parse_course_description,
    parse_course_page,
    parse_graduate_course_page,
)


BASE_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1"
SCHEDULE_FORM_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class"
COURSE_CONTENT_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1"
COURSE_CONTENT_FORM_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main"
GRADUATE_SCHEDULE_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable"
USER_AGENT = "ntu-course-index/0.1 (public NTU timetable lookup)"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 5_000_000
MAX_RETRIES = 2
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_CONCURRENT_REQUESTS = 2
MAX_CACHE_ENTRIES = 128
try:
    CACHE_TTL_SECONDS = int(os.environ.get("NTU_CACHE_TTL_SECONDS", "3600"))
except ValueError as error:
    raise RuntimeError("NTU_CACHE_TTL_SECONDS must be an integer number of seconds.") from error
if CACHE_TTL_SECONDS < 0:
    raise RuntimeError("NTU_CACHE_TTL_SECONDS must be zero or greater.")

_request_slots = BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_pace_lock = Lock()
_cache_lock = Lock()
_last_request_started = 0.0
_cache: dict[tuple[int, str, str], tuple[float, Course]] = {}
_graduate_cache: dict[str, tuple[float, dict[str, object]]] = {}


class NTURequestError(RuntimeError):
    pass


def validate_course_code(course_code: str) -> str:
    code = course_code.strip().upper()
    if len(code) > 10 or not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]+", code):
        raise ValueError("Course code must contain only letters and digits, including at least one of each.")
    return code


def _academic_term(academic_year: int, semester: int | str) -> tuple[int, str, str]:
    if isinstance(academic_year, bool) or not isinstance(academic_year, int) or not 2000 <= academic_year <= 2100:
        raise ValueError("Academic year must be a four-digit NTU year, such as 2026 (AY2026/27).")
    semester_text = str(semester).upper()
    if semester_text not in {"1", "2", "S"}:
        raise ValueError("Semester must be 1, 2, or 'S' for Special Term.")
    return academic_year, semester_text, f"{academic_year};{semester_text}"


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


def _fetch_html_request(request: Request, page_description: str) -> str:
    last_error: str | None = None

    for attempt in range(MAX_RETRIES + 1):
        retryable = False
        http_error: HTTPError | None = None
        try:
            with _request_slots:
                _wait_for_request_slot()
                with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
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


def _fetch_html(acadsem: str, course_code: str) -> tuple[str, str]:
    form = urlencode(
        {
            "acadsem": acadsem,
            "r_course_yr": "",
            "r_subj_code": course_code,
            "r_search_type": "F",
            "boption": "Search",
            # This is the hidden value in NTU's public form; no credentials are sent.
            "staff_access": "true",
        }
    ).encode()
    request = Request(
        BASE_URL,
        data=form,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": SCHEDULE_FORM_URL,
        },
    )
    return _fetch_html_request(request, f"class schedule for {course_code}"), BASE_URL


def _fetch_course_content_html(year: int, semester: str, course_code: str) -> tuple[str, str]:
    form = urlencode(
        {
            "acad": year,
            "semester": semester,
            "acadsem": f"{year}_{semester}",
            "r_course_yr": "",
            "r_subj_code": course_code,
            "boption": "Search",
        }
    ).encode()
    request = Request(
        COURSE_CONTENT_URL,
        data=form,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": COURSE_CONTENT_FORM_URL,
        },
    )
    return _fetch_html_request(request, f"course content for {course_code}"), COURSE_CONTENT_URL


def get_course(course_code: str, academic_year: int, semester: int | str) -> Course:
    code = validate_course_code(course_code)
    year, semester_text, acadsem = _academic_term(academic_year, semester)
    key = (year, semester_text, code)
    now = time.monotonic()
    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached = _cache.get(key)
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return cached[1]

    html, source_url = _fetch_html(acadsem, code)
    try:
        course = parse_course_page(html, code)
    except CourseUnavailable as error:
        raise NTURequestError(str(error)) from error
    except NTUPageError as error:
        raise NTURequestError(f"Could not safely parse NTU's response for {code}: {error}") from error

    description: str | None = None
    description_status = "unavailable"
    description_source = COURSE_CONTENT_URL
    try:
        content_html, description_source = _fetch_course_content_html(year, semester_text, code)
        description = parse_course_description(content_html, code)
        description_status = "available" if description else "not_listed"
    except (NTURequestError, NTUPageError):
        pass

    course = course.with_request_metadata(
        academic_year=year,
        semester=semester_text,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_url=source_url,
    ).with_course_description(
        description=description,
        status=description_status,
        source_url=description_source,
    )
    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached_at = time.monotonic()
            for expired in [
                cache_key
                for cache_key, (created_at, _) in _cache.items()
                if cached_at - created_at >= CACHE_TTL_SECONDS
            ]:
                del _cache[expired]
            if key not in _cache and len(_cache) >= MAX_CACHE_ENTRIES:
                oldest = min(_cache, key=lambda cache_key: _cache[cache_key][0])
                del _cache[oldest]
            _cache[key] = (cached_at, course)
    return course


def get_graduate_course_schedule(course_code: str) -> dict[str, object]:
    code = validate_course_code(course_code)
    now = time.monotonic()
    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached = _graduate_cache.get(code)
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return deepcopy(cached[1])

    query = urlencode({"bOption": "Next", "choiceSubj": code})
    source_url = f"{GRADUATE_SCHEDULE_URL}?{query}"
    request = Request(source_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    html = _fetch_html_request(request, f"graduate class schedule for {code}")
    try:
        result = parse_graduate_course_page(html, code)
    except CourseUnavailable as error:
        raise NTURequestError(str(error)) from error
    except NTUPageError as error:
        raise NTURequestError(f"Could not safely parse NTU's graduate timetable for {code}: {error}") from error
    result["source_url"] = source_url

    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached_at = time.monotonic()
            for expired in [
                key for key, (created_at, _) in _graduate_cache.items()
                if cached_at - created_at >= CACHE_TTL_SECONDS
            ]:
                del _graduate_cache[expired]
            if code not in _graduate_cache and len(_graduate_cache) >= MAX_CACHE_ENTRIES:
                oldest = min(_graduate_cache, key=lambda key: _graduate_cache[key][0])
                del _graduate_cache[oldest]
            _graduate_cache[code] = (cached_at, deepcopy(result))
    return result

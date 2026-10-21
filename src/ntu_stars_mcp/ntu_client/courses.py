from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
import time
from urllib.parse import urlencode
from urllib.request import Request

from .cache import CACHE_TTL_SECONDS, MAX_CACHE_ENTRIES
from .http import USER_AGENT, NTURequestError, _fetch_html_request
from .validation import _academic_term, validate_course_code
from ..domain import Course
from ..parser import CourseUnavailable, NTUPageError, parse_course_description, parse_course_page

_cache_lock = Lock()
_cache: dict[tuple[int, str, str], tuple[float, Course]] = {}

BASE_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1"

SCHEDULE_FORM_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class"

COURSE_CONTENT_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1"

COURSE_CONTENT_FORM_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main"

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

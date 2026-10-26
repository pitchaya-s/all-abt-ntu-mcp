from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request

import httpx

from ..parser import (
    CourseUnavailable,
    NTUPageError,
    parse_undergraduate_exam_plan,
    parse_undergraduate_exam_schedule,
)
from .cache import CACHE_TTL_SECONDS, MAX_CACHE_ENTRIES
from .http import USER_AGENT, NTURequestError, _fetch_html_request
from .validation import _academic_term, validate_course_code

_cache_lock = Lock()
_exam_cache: dict[tuple[str, int | None, str | None], tuple[float, dict[str, object]]] = {}

UNDERGRAD_EXAM_BASE_URL = "https://wis.ntu.edu.sg/webexe/owa/"

UNDERGRAD_EXAM_FORM_URL = f"{UNDERGRAD_EXAM_BASE_URL}exam_timetable_und.main"

UNDERGRAD_EXAM_SUBMIT_URL = f"{UNDERGRAD_EXAM_BASE_URL}exam_timetable_und.MainSubmit"

UNDERGRAD_EXAM_TERM_URL = f"{UNDERGRAD_EXAM_BASE_URL}exam_timetable_und.query_page"

UNDERGRAD_EXAM_DETAIL_URL = f"{UNDERGRAD_EXAM_BASE_URL}exam_timetable_und.Get_detail"

def _post_exam_form(
    client: httpx.Client, url: str, fields: dict[str, str], referer: str, description: str
) -> str:
    request = Request(
        url,
        data=urlencode(fields).encode(),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
        },
    )
    return _fetch_html_request(request, description, client)


def _fetch_exam_html(course_code: str, academic_year: int | None, semester: str | None):
    with httpx.Client(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        landing_request = Request(
            UNDERGRAD_EXAM_FORM_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        landing_html = _fetch_html_request(landing_request, "undergraduate exam timetable form", client)
        if "General Access" not in landing_html or "For Undergraduate Programmes" not in landing_html:
            raise NTURequestError("NTU's public undergraduate exam form changed or is unavailable.")

        term_html = _post_exam_form(
            client,
            UNDERGRAD_EXAM_SUBMIT_URL,
            {"p_opt": "1", "p_type": "UE", "bOption": "Next"},
            UNDERGRAD_EXAM_FORM_URL,
            "undergraduate exam terms",
        )
        try:
            plan = parse_undergraduate_exam_plan(term_html, academic_year, semester)
        except (CourseUnavailable, NTUPageError) as error:
            raise NTURequestError(str(error)) from error

        year = int(plan["academic_year"])
        selected_semester = str(plan["semester"])
        plan_number = str(plan["plan_number"])
        filter_html = _post_exam_form(
            client,
            UNDERGRAD_EXAM_TERM_URL,
            {"p_plan_no": plan_number, "p1": "", "p2": "", "p_type": "UE", "bOption": "Next"},
            UNDERGRAD_EXAM_SUBMIT_URL,
            "undergraduate exam course filter",
        )
        if 'name="p_subj"' not in filter_html and "name='p_subj'" not in filter_html:
            raise NTURequestError("NTU's undergraduate exam course filter changed; no course selector was found.")

        result_html = _post_exam_form(
            client,
            UNDERGRAD_EXAM_DETAIL_URL,
            {
                "p_exam_dt": "",
                "p_start_time": "",
                "p_dept": "",
                "p_subj": course_code,
                "p_venue": "",
                "p_matric": "",
                "academic_session": str(plan["academic_session"]),
                "p_plan_no": plan_number,
                "p_exam_yr": str(year),
                "p_semester": selected_semester,
                "p_type": "UE",
                "bOption": "Next",
            },
            UNDERGRAD_EXAM_TERM_URL,
            f"undergraduate exam schedule for {course_code}",
        )
    return result_html, year, selected_semester

def get_undergraduate_exam_schedule(
    course_code: str, academic_year: int | None = None, semester: int | str | None = None
) -> dict[str, object]:
    code = validate_course_code(course_code)
    if academic_year is None and semester is None:
        semester_text = None
    elif academic_year is not None and semester is not None:
        academic_year, semester_text, _ = _academic_term(academic_year, semester)
        if semester_text not in {"1", "2"}:
            raise ValueError("Undergraduate exam timetables are available for semester 1 or 2, not Special Term.")
    else:
        raise ValueError("Provide both academic_year and semester, or neither for the latest published exam term.")

    key = (code, academic_year, semester_text)
    now = time.monotonic()
    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached = _exam_cache.get(key)
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return deepcopy(cached[1])

    # This public workflow retains its form cookie only for its own requests.
    result_html, year, selected_semester = _fetch_exam_html(code, academic_year, semester_text)
    try:
        result = parse_undergraduate_exam_schedule(result_html, code)
    except NTUPageError as error:
        raise NTURequestError(f"Could not safely parse NTU's undergraduate exam timetable for {code}: {error}") from error
    if (result["academic_year"], result["semester"]) != (year, selected_semester):
        raise NTURequestError("NTU returned an exam timetable for a different academic term than requested.")
    result["source_url"] = UNDERGRAD_EXAM_DETAIL_URL
    result["retrieved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if CACHE_TTL_SECONDS:
        with _cache_lock:
            cached_at = time.monotonic()
            for expired in [
                cache_key for cache_key, (created_at, _) in _exam_cache.items()
                if cached_at - created_at >= CACHE_TTL_SECONDS
            ]:
                del _exam_cache[expired]
            if key not in _exam_cache and len(_exam_cache) >= MAX_CACHE_ENTRIES:
                oldest = min(_exam_cache, key=lambda cache_key: _exam_cache[cache_key][0])
                del _exam_cache[oldest]
            _exam_cache[key] = (cached_at, deepcopy(result))
    return result

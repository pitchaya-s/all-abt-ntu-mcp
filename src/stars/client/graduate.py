from __future__ import annotations

from copy import deepcopy
from threading import Lock
import time
from urllib.parse import urlencode
from urllib.request import Request

from .cache import CACHE_TTL_SECONDS, MAX_CACHE_ENTRIES
from .http import USER_AGENT, NTURequestError, _fetch_html_request
from .validation import validate_course_code
from ..parser import CourseUnavailable, NTUPageError, parse_graduate_course_page

_cache_lock = Lock()
_graduate_cache: dict[str, tuple[float, dict[str, object]]] = {}

GRADUATE_SCHEDULE_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable"

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

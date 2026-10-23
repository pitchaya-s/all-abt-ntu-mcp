from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from .cache import CACHE_TTL_SECONDS, MAX_CACHE_ENTRIES
from .http import USER_AGENT, NTURequestError, _fetch_html_request
from .validation import _academic_term, validate_course_code
from ..parser import NTUPageError, parse_course_vacancies

VACANCY_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy2"
VACANCY_FORM_URL = "https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy"
VACANCY_CACHE_TTL_SECONDS = min(CACHE_TTL_SECONDS, 60)
_cache_lock = Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def get_course_vacancies(course_code: str, academic_year: int, semester: int | str) -> dict[str, Any]:
    """Get a short-lived public snapshot; never apply another term's counts."""
    code = validate_course_code(course_code)
    year, semester_text, _ = _academic_term(academic_year, semester)
    if not 9 <= datetime.now(timezone(timedelta(hours=8))).hour < 22:
        return {
            "status": "closed",
            "academic_year": None,
            "semester": None,
            "retrieved_at": None,
            "source_url": VACANCY_URL,
            "from_cache": False,
            "cache_age_seconds": None,
            "indexes": {},
            "message": "Vacancy lookup is available only from 09:00 to 22:00 Singapore time (UTC+8).",
        }
    # Serialize misses so concurrent tools reuse one request for the same course.
    with _cache_lock:
        cached = _cache.get(code)
        age = time.monotonic() - cached[0] if cached else 0.0
        from_cache = bool(VACANCY_CACHE_TTL_SECONDS and cached and age < VACANCY_CACHE_TTL_SECONDS)
        if from_cache:
            result = deepcopy(cached[1])
        else:
            request = Request(
                VACANCY_URL,
                data=urlencode({"subj": code}).encode(),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": VACANCY_FORM_URL,
                },
            )
            html = _fetch_html_request(request, f"vacancies for {code}")
            try:
                result = parse_course_vacancies(html, code)
            except NTUPageError as error:
                raise NTURequestError(f"Could not safely parse NTU's vacancies for {code}: {error}") from error
            result.update(source_url=VACANCY_URL, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            age = 0.0
            if VACANCY_CACHE_TTL_SECONDS:
                if code not in _cache and len(_cache) >= MAX_CACHE_ENTRIES:
                    del _cache[min(_cache, key=lambda key: _cache[key][0])]
                _cache[code] = (time.monotonic(), deepcopy(result))
    result.update(from_cache=from_cache, cache_age_seconds=round(age, 3), status="available")
    if (result["academic_year"], result["semester"]) != (year, semester_text):
        result.update(
            status="term_mismatch",
            indexes={},
            message="NTU's public vacancy page reports a different academic term; counts were not attached.",
        )
    return result

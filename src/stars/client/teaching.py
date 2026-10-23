"""One bounded, cached term-wide read for each public undergraduate study mode."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Lock
import time

from .cache import CACHE_TTL_SECONDS
from .courses import BASE_URL, _fetch_html
from .http import NTURequestError
from .validation import _academic_term
from ..domain.models import Course
from ..parser.common import NTUPageError
from ..parser.schedule import parse_teaching_schedule


@dataclass(frozen=True)
class TeachingSnapshot:
    academic_year: int
    semester: str
    courses: tuple[Course, ...]
    retrieved_at: str
    source_url: str = BASE_URL
    cached: bool = False


_lock = Lock()
_cache = OrderedDict()


def get_teaching_snapshot(academic_year, semester, refresh=False):
    year, term, acadsem = _academic_term(academic_year, semester)
    key = year, term
    with _lock:
        cached = _cache.get(key)
        if not refresh and CACHE_TTL_SECONDS and cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            _cache.move_to_end(key)
            return replace(cached[1], cached=True)
        courses = []
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for mode in ("F", "P"):
            html, _ = _fetch_html(acadsem, "", study_mode=mode)
            try:
                courses.extend(parse_teaching_schedule(html, year, term))
            except NTUPageError as error:
                raise NTURequestError(
                    f"Could not safely read the complete teaching schedule: {error}"
                ) from None
        if not courses:
            raise NTURequestError(
                "NTU has no published undergraduate teaching schedules for this term; no room availability was inferred."
            )
        result = TeachingSnapshot(year, term, tuple(courses), retrieved)
        if CACHE_TTL_SECONDS:
            _cache[key] = time.monotonic(), result
            _cache.move_to_end(key)
            while len(_cache) > 4:
                _cache.popitem(last=False)
        return result

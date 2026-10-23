"""All course/index tables in NTU's blank-query teaching schedule response."""

import re

from .common import NTUPageError, _Rows
from .course import _parse_course_rows
from .search import parse_course_search


def parse_teaching_schedule(html: str, academic_year: int, semester: str):
    if not re.search(r"</html>\s*$", html, re.I):
        raise NTUPageError("The term-wide timetable is incomplete; no room availability was inferred.")
    matches = parse_course_search(html, academic_year, semester)
    if not matches:
        return ()
    parser = _Rows()
    parser.feed(html)
    codes = {course["course_code"] for course in matches}
    starts = [(i, row[0]) for i, row in enumerate(parser.rows) if len(row) == 3 and row[0] in codes]
    if len(starts) != len(matches) or len({code for _, code in starts}) != len(matches):
        raise NTUPageError("The term-wide timetable has duplicate or missing course blocks.")
    courses = []
    for position, (start, code) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(parser.rows)
        course = _parse_course_rows(parser.rows[start:end], code)
        courses.append(course)
    return tuple(courses)

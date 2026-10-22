"""Course headers from NTU's multi-course Class Schedule search response."""

import re

from ..schemas import CourseSearchMatch
from .common import NTUPageError, _Rows


def parse_course_search(html: str, academic_year: int, semester: str) -> list[CourseSearchMatch]:
    parser = _Rows()
    parser.feed(html)
    text = " ".join(" ".join(parser.text_parts).split())
    term = re.search(r"\bClass Schedule\s+(\d{4})\s+Semester\s+([12S])\b", text, re.I)
    if term is None or (int(term[1]), term[2].upper()) != (academic_year, semester):
        raise NTUPageError("NTU's course search did not identify the requested academic term.")

    courses: dict[str, CourseSearchMatch] = {}
    course_count = 0
    for row in parser.rows:
        if len(row) != 3 or not re.fullmatch(r"(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{2,10}", row[0]):
            continue
        au = re.fullmatch(r"(\d+(?:\.\d+)?)\s*AU", row[2], re.I)
        if not row[1] or (row[2] and au is None):
            raise NTUPageError("NTU's course search returned an unfamiliar course title or AU field.")
        course: CourseSearchMatch = {"course_code": row[0], "course_name": row[1], "au": float(au[1]) if au else None}
        if row[0] in courses and courses[row[0]] != course:
            raise NTUPageError("NTU's course search returned conflicting details for the same course.")
        courses[row[0]] = course
        course_count += 1

    lesson_headers = sum(row == ["INDEX", "TYPE", "GROUP", "DAY", "TIME", "VENUE", "REMARK"] for row in parser.rows)
    if course_count and course_count == lesson_headers:
        return list(courses.values())
    if not course_count and not lesson_headers and re.search(r"class schedule is not available\.|no records found", text, re.I):
        return []
    raise NTUPageError("NTU returned an unrecognized or incomplete course-search response.")

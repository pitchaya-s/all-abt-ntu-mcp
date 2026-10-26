from __future__ import annotations

import re

from .common import NTUPageError
from .course import _parse_time, parse_teaching_weeks
from .personal import (
    _COURSE_CODE,
    _course_status,
    _parse,
    _records_with_course_code,
    _table_status,
)

_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
_EMPTY_NOTICE = "You have no course registration or course timetable."


def _headers(table: dict[str, object]) -> list[str]:
    values = table.get("headers")
    return [str(value) for value in values] if isinstance(values, list) else []


def _is_calendar(table: dict[str, object]) -> bool:
    return len(_DAYS.intersection(_headers(table))) >= 2


def _looks_like_registration_table(table: dict[str, object]) -> bool:
    headers = [value.strip().casefold() for value in _headers(table)]
    has_course = any(
        "course" in header and "type" not in header
        for header in headers
    )
    has_index = any("index" in header for header in headers)
    return has_course and has_index and not _is_calendar(table)


def parse_stars_planner_page(html: str) -> dict[str, object]:
    title, text, tables = _parse(html)
    registered = []
    in_registration = False
    for table in tables:
        section = str(table["section"] or "").casefold()
        if re.search(r"courses registered|registered courses", section):
            in_registration = True
            registered.append(table)
        elif in_registration and section == "timetable":
            registered.append(table)
    selection_page = re.search(r"course selection|select(?:ing)? courses|search for courses", text, re.I)
    if not registered and "planner" in title.casefold() and not selection_page:
        candidates = [
            table for table in tables
            if _looks_like_registration_table(table) and _records_with_course_code([table])
        ]
        if len(candidates) == 1:
            registered = candidates
    courses = _records_with_course_code([
        table for table in registered
        if not _is_calendar(table) and "index" in " ".join(table["headers"]).casefold()
    ])
    empty = _EMPTY_NOTICE.casefold() in text.casefold()
    if not registered and not empty:
        raise NTUPageError("NTU's Planner response was not recognizable: the registered-course view was missing; the course-selection landing page is insufficient.")
    if empty and courses:
        raise NTUPageError("NTU's Planner response contained conflicting registered-course information.")
    term = re.search(r"Courses Registered\s+(20\d{2})[-/](20\d{2})\s+Semester\s+([12])", text, re.I)
    if term and int(term[2]) != int(term[1]) + 1:
        raise NTUPageError("NTU's Planner academic year was inconsistent.")
    timetable = [
        table for table in registered
        if any(marker in " ".join(table["headers"]).casefold() for marker in ("day", "time", "venue"))
    ]
    planner = [
        table for table in tables if table not in registered
        and (_is_calendar(table) or _COURSE_CODE.search(" ".join(" ".join(row) for row in table["rows"])))
    ]
    return {
        "service": "stars_planner",
        "page_title": title or None,
        "academic_year": int(term[1]) if term else None,
        "semester": int(term[3]) if term else None,
        "registration_notice": _EMPTY_NOTICE if empty else None,
        "registered_courses": courses,
        "registered_courses_status": "empty" if empty else _course_status(registered, courses),
        "planner_tables": planner,
        "timetable_tables": timetable,
        "timetable_status": "empty" if empty else _table_status(timetable),
        "saved_plans": [],
    }


def parse_saved_plan_timetable(html: str, courses: list[dict[str, object]]) -> dict[str, object]:
    _, text, tables = _parse(html)
    calendars = [table for table in tables if _is_calendar(table)]
    if not calendars:
        raise NTUPageError("NTU's saved-plan calendar was missing or changed.")
    indexes = {course["course_code"]: course["index"] for course in courses}
    sessions: list[dict[str, object]] = []
    unparsed: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for table in calendars:
        for record in table["records"]:
            for day, cell in record.items():
                if day not in _DAYS or not cell or (day, cell) in seen:
                    continue
                seen.add((day, cell))
                matches = list(_COURSE_CODE.finditer(cell))
                if not matches:
                    unparsed.append({"day": day, "text": cell})
                for position, match in enumerate(matches):
                    end = matches[position + 1].start() if position + 1 < len(matches) else len(cell)
                    raw = cell[match.end():end].strip()
                    detail = re.fullmatch(
                        r"(\S+)\s+(\S+)\s+(.+?)\s+(\d{4})\s*to\s*(\d{4})\s*-\s*(.*)", raw, re.I
                    )
                    if not detail or match[0].upper() not in indexes:
                        unparsed.append({"day": day, "text": cell[match.start():end]})
                        continue
                    kind, group, venue, start, finish, remark = detail.groups()
                    start, finish, unknown_time = _parse_time(f"{start}-{finish}")
                    remark = remark.rstrip("; ").strip()
                    weeks = parse_teaching_weeks(remark)
                    if not remark and "Course without weekly information is conducted Wk1-13" in text:
                        weeks = tuple(range(1, 14))
                    sessions.append({
                        "course_code": match[0].upper(), "index": indexes[match[0].upper()],
                        "lesson_type": kind, "group": group, "day": day,
                        "start_time": start, "end_time": finish, "venue": venue,
                        "teaching_weeks": list(weeks) if weeks is not None else None,
                        "remarks": remark or None, "raw_time": unknown_time,
                    })
    return {
        "sessions": sessions,
        "unparsed_sessions": unparsed,
        "timetable_status": (
            "unparsed" if unparsed else
            "partial" if any(s["start_time"] is None or s["teaching_weeks"] is None for s in sessions) else
            "parsed" if sessions else "empty"
        ),
    }

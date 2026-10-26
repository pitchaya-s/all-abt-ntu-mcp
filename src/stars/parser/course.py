from __future__ import annotations

import re

from ..domain import Course, Session
from .common import CourseUnavailable, NTUPageError, _CourseContentRows, _Rows

def parse_course_description(html: str, expected_code: str) -> str | None:
    """Extract the wide description cell from NTU's Content of Courses response."""
    parser = _CourseContentRows()
    parser.feed(html)
    header_index = next(
        (
            index
            for index, row in enumerate(parser.rows)
            if len(row) >= 4
            and [cell[1].strip().upper() for cell in row[:3]] == ["COURSE CODE", "TITLE", "AU"]
        ),
        None,
    )
    if header_index is None:
        raise NTUPageError("NTU returned an unrecognized course-content page; no course table was found.")

    code = expected_code.upper()
    course_index = next(
        (
            index
            for index, row in enumerate(parser.rows[header_index + 1 :], header_index + 1)
            if row and row[0][1].strip().upper() == code
        ),
        None,
    )
    if course_index is None:
        return None

    descriptions: list[str] = []
    for row in parser.rows[course_index + 1 :]:
        if row and row[0][1].strip().upper() == code:
            break
        for attrs, text in row:
            width = attrs.get("width") or ""
            colspan = attrs.get("colspan") or ""
            is_description = (width.isdigit() and int(width) >= 500) or (colspan.isdigit() and int(colspan) >= 4)
            if text and is_description:
                descriptions.append(text)
    description = "\n".join(descriptions).strip()
    return description or None


def parse_course_prerequisite_metadata(html: str, expected_code: str) -> dict[str, str | float | None] | None:
    """Extract a course's published title, AU, and prerequisite text from Content of Courses."""
    parser = _CourseContentRows()
    parser.feed(html)
    header_index = next(
        (
            index
            for index, row in enumerate(parser.rows)
            if len(row) >= 4
            and [cell[1].strip().upper() for cell in row[:3]] == ["COURSE CODE", "TITLE", "AU"]
        ),
        None,
    )
    if header_index is None:
        raise NTUPageError("NTU returned an unrecognized course-content page; no course table was found.")

    code = expected_code.upper()
    course_index = next(
        (
            index
            for index, row in enumerate(parser.rows[header_index + 1 :], header_index + 1)
            if row and row[0][1].strip().upper() == code
        ),
        None,
    )
    if course_index is None:
        return None

    course_row = parser.rows[course_index]
    if len(course_row) < 3:
        raise NTUPageError("NTU returned an incomplete course-content record.")
    au_match = re.fullmatch(r"\s*((?:\d+(?:\.\d+)?|\.\d+))\s*", course_row[2][1])
    au = float(au_match[1]) if au_match else None
    detail_rows: list[list[str]] = []
    for row in parser.rows[course_index + 1 :]:
        is_description = any(
            text
            and (
                ((attrs.get("width") or "").isdigit() and int(attrs["width"]) >= 500)
                or ((attrs.get("colspan") or "").isdigit() and int(attrs["colspan"]) >= 4)
            )
            for attrs, text in row
        )
        if is_description:
            break
        detail_rows.append([text for _, text in row])
    details = _course_details(detail_rows)
    return {
        "course_code": code,
        "course_name": course_row[1][1].strip() or None,
        "au": au,
        "prerequisite": details.get("prerequisite"),
    }

def parse_teaching_weeks(remark: str) -> tuple[int, ...] | None:
    """Parse an explicit NTU week range/list; leave unfamiliar remarks untouched."""
    match = re.fullmatch(
        r"\s*(?:teaching\s+)?(?:wk|weeks?)\s*([\d\s,-]+)\s*",
        remark,
        re.IGNORECASE,
    )
    if not match:
        return None

    weeks: set[int] = set()
    for part in match.group(1).split(","):
        part = part.strip()
        if not part:
            return None
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2 or not all(bound.strip().isdigit() for bound in bounds):
                return None
            try:
                start, end = map(int, bounds)
            except ValueError:
                return None
            if not 1 <= start <= end <= 20:
                return None
            weeks.update(range(start, end + 1))
        elif part.isdigit():
            try:
                week = int(part)
            except ValueError:
                return None
            if not 1 <= week <= 20:
                return None
            weeks.add(week)
        else:
            return None

    if not weeks:
        return None
    return tuple(sorted(weeks))

def _parse_time(value: str) -> tuple[str | None, str | None, str | None]:
    match = re.fullmatch(r"\s*(\d{2}):?(\d{2})\s*-\s*(\d{2}):?(\d{2})\s*", value)
    if not match:
        return None, None, value or None
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    if max(start_hour, end_hour) > 23 or max(start_minute, end_minute) > 59:
        return None, None, value or None
    start = f"{start_hour:02d}:{start_minute:02d}"
    end = f"{end_hour:02d}:{end_minute:02d}"
    if start >= end:
        return None, None, value or None
    return start, end, None

def _course_details(rows: list[list[str]]) -> dict[str, str]:
    details: dict[str, list[str]] = {}
    current_label: str | None = None
    for row in rows:
        if not row:
            continue
        first = row[0].strip()
        if first.endswith(":"):
            current_label = first[:-1].strip().casefold()
            details.setdefault(current_label, [])
            details[current_label].extend(value for value in row[1:] if value)
        elif not first and current_label:
            details[current_label].extend(value for value in row[1:] if value)
        else:
            current_label = None
    return {
        label: " ".join(value for value in values if value).strip()
        for label, values in details.items()
        if any(values)
    }

def parse_course_page(html: str, expected_code: str) -> Course:
    rows_parser = _Rows()
    rows_parser.feed(html)
    return _parse_course_rows(rows_parser.rows, expected_code, " ".join(rows_parser.text_parts))


def _parse_course_rows(rows: list[list[str]], expected_code: str, plain_text: str = "") -> Course:
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if len(row) >= 7
            and [cell.strip().upper() for cell in row[:7]]
            == ["INDEX", "TYPE", "GROUP", "DAY", "TIME", "VENUE", "REMARK"]
        ),
        None,
    )
    if header_index is None:
        plain_text = plain_text.casefold()
        if "class schedule is not available" in plain_text or "no records found" in plain_text:
            raise CourseUnavailable(
                f"NTU has no class schedule for {expected_code} in the requested academic year and semester."
            )
        raise NTUPageError("NTU returned an unrecognized class-schedule page; no lesson table was found.")

    course_row_index = next(
        (
            index
            for index, row in enumerate(rows[:header_index])
            if len(row) >= 3 and row[0].strip().upper() == expected_code.upper()
        ),
        None,
    )
    if course_row_index is None:
        raise NTUPageError(f"NTU's schedule page did not identify course {expected_code}.")
    course_row = rows[course_row_index]
    course_code = course_row[0].strip().upper()
    course_name = course_row[1].strip()
    au_match = re.search(r"(?<![\d.])((?:\d+(?:\.\d+)?|\.\d+))\s*AU\b", course_row[2], re.IGNORECASE)
    au = float(au_match.group(1)) if au_match else None
    details = _course_details(rows[course_row_index + 1 : header_index])

    indexes: dict[str, list[Session]] = {}
    current_index: str | None = None
    for row in rows[header_index + 1 :]:
        if not any(row):
            continue
        if len(row) != 7:
            raise NTUPageError("NTU's lesson table changed shape; expected seven columns per lesson.")

        index_text, lesson_type, group, day_text, time_text, venue, remark = row
        if index_text:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", index_text):
                raise NTUPageError(f"NTU returned an invalid index number: {index_text!r}.")
            current_index = index_text
            indexes.setdefault(current_index, [])
        if current_index is None:
            raise NTUPageError("NTU returned a lesson row without an index number.")

        day = day_text.strip().upper()
        known_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
        start_time, end_time, raw_time = _parse_time(time_text)
        remark = remark.strip()
        indexes[current_index].append(
            Session(
                course_code=course_code,
                index=current_index,
                lesson_type=lesson_type.strip() or None,
                group=group.strip() or None,
                day=day if day in known_days else None,
                start_time=start_time,
                end_time=end_time,
                venue=venue.strip() or None,
                teaching_weeks=parse_teaching_weeks(remark),
                remarks=remark or None,
                raw_time=raw_time,
                raw_day=day if day and day not in known_days else None,
            )
        )

    return Course(
        course_code=course_code,
        course_name=course_name,
        au=au,
        details=details,
        indexes={index: tuple(sessions) for index, sessions in indexes.items()},
    )

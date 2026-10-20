from __future__ import annotations

from html.parser import HTMLParser
import re

from .domain import Course, Session


class NTUPageError(ValueError):
    pass


class CourseUnavailable(NTUPageError):
    pass


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text_parts: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).replace("\xa0", " ").split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.text_parts.append(data)
            if self._cell is not None:
                self._cell.append(data)


class _CourseContentRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[dict[str, str | None], str]]] = []
        self._row: list[tuple[dict[str, str | None], str]] | None = None
        self._cell: tuple[dict[str, str | None], list[str]] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = (dict(attrs), [])
        elif tag == "br" and self._cell is not None:
            self._cell[1].append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            attrs, parts = self._cell
            text = "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines())
            self._row.append((attrs, text.strip()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not self._ignored and self._cell is not None:
            self._cell[1].append(data.replace("\xa0", " "))


class _GraduateRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.table_depth = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _finish_row(self) -> None:
        if self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr" and self.table_depth == 1:
            self._finish_row()
            self.row = []
        elif tag in {"td", "th"} and self.table_depth == 1 and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.table_depth == 1 and self.row is not None and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.table_depth == 1:
            self._finish_row()
        elif tag == "table":
            if self.table_depth == 1:
                self._finish_row()
            self.table_depth = max(0, self.table_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data.replace("\xa0", " "))


def _lines(value: str) -> list[str]:
    return [line for part in value.splitlines() if (line := " ".join(part.split()))]


def _graduate_time(hour: str, minute: str, meridiem: str) -> str | None:
    hours, minutes = int(hour), int(minute)
    if not 1 <= hours <= 12 or minutes > 59:
        return None
    hours = hours % 12 + (12 if meridiem.upper() == "PM" else 0)
    return f"{hours:02d}:{minutes:02d}"


def _graduate_sessions(schedule_text: str) -> tuple[list[dict[str, str | None]], list[str]]:
    time_pattern = re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2}):(\d{2})\s*(AM|PM)\s+to\s+"
        r"(\d{1,2}):(\d{2})\s*(AM|PM)$",
        re.IGNORECASE,
    )
    sessions: list[dict[str, str | None]] = []
    remarks: list[str] = []
    current: dict[str, str | None] | None = None
    for line in _lines(schedule_text):
        match = time_pattern.fullmatch(line)
        if match:
            if current:
                sessions.append(current)
            start = _graduate_time(match[2], match[3], match[4])
            end = _graduate_time(match[5], match[6], match[7])
            current = {
                "day": match[1][:3].upper(),
                "start_time": start,
                "end_time": end,
                "venue": None,
                "commence_date": None,
                "teaching_weeks": None,
            }
        elif line.lower().startswith("commence date:"):
            if current is not None:
                current["commence_date"] = line.split(":", 1)[1].strip() or None
            else:
                remarks.append(line)
        elif current is not None and current["venue"] is None:
            current["venue"] = line
        else:
            remarks.append(line)
    if current:
        sessions.append(current)
    return sessions, remarks


def parse_graduate_course_page(html: str, expected_code: str) -> dict[str, object]:
    """Parse a public GSLink/PGR course timetable, which uses class groups, not indexes."""
    parser = _GraduateRows()
    parser.feed(html)
    header_index = next(
        (
            index
            for index, row in enumerate(parser.rows)
            if len(row) >= 9
            and " ".join(_lines(row[0])) == "Course"
            and " ".join(_lines(row[1])) == "Course Coordinator"
            and "Course AU" in " ".join(" ".join(_lines(value)) for value in row)
        ),
        None,
    )
    if header_index is None:
        raise NTUPageError("NTU returned an unrecognized graduate timetable page; no course table was found.")

    page_text = " ".join(" ".join(_lines(" ".join(row))) for row in parser.rows)
    term_match = re.search(r"Academic Year\s+(\d{4})\s*/\s*Term\s+(\d+)", html, re.IGNORECASE)
    if not term_match:
        raise NTUPageError("NTU's graduate timetable did not identify its academic year and term.")

    code = expected_code.upper()
    matched_rows: list[list[str]] = []
    for row in parser.rows[header_index + 1 :]:
        if len(row) < 9:
            continue
        course_lines = _lines(row[0])
        if course_lines and course_lines[0].upper() == code:
            matched_rows.append(row)
    if not matched_rows:
        if code not in page_text.upper():
            raise CourseUnavailable(f"NTU has no graduate timetable for {code} in the currently published term.")
        raise NTUPageError(f"NTU's graduate timetable listed {code} in an unexpected row format.")

    course_lines = _lines(matched_rows[0][0])
    course_name = " ".join(line for line in course_lines[1:] if not re.fullmatch(r"\[Class Group[^]]+\]", line, re.I))
    au_match = re.search(r"\d+(?:\.\d+)?", matched_rows[0][7])
    groups: list[dict[str, object]] = []
    for row in matched_rows:
        group_match = re.search(r"\[Class Group\s+([^\]]+)\]", row[0], re.IGNORECASE)
        schedule_text = "\n".join(_lines(row[2]))
        sessions, remarks = _graduate_sessions(schedule_text)
        groups.append(
            {
                "class_group": group_match[1].strip() if group_match else None,
                "coordinator": " ".join(_lines(row[1])) or None,
                "sessions": sessions,
                "schedule_remarks": remarks,
                "schedule_text": schedule_text or None,
            }
        )

    return {
        "course_code": code,
        "course_name": course_name,
        "au": float(au_match[0]) if au_match else None,
        "academic_year": int(term_match[1]),
        "term": term_match[2],
        "schedule_complete": bool(groups) and all(
            bool(group["sessions"])
            and all(session["day"] and session["start_time"] and session["end_time"] for session in group["sessions"])
            for group in groups
        ),
        "class_groups": groups,
    }


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
            start, end = map(int, bounds)
            if start > end:
                return None
            weeks.update(range(start, end + 1))
        elif part.isdigit():
            weeks.add(int(part))
        else:
            return None

    if not weeks or min(weeks) < 1 or max(weeks) > 20:
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
    rows = rows_parser.rows

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
        plain_text = " ".join(rows_parser.text_parts).casefold()
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
    au_match = re.search(r"(\d+(?:\.\d+)?)\s*AU\b", course_row[2], re.IGNORECASE)
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

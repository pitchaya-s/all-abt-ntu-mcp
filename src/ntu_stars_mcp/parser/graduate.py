from __future__ import annotations

from html.parser import HTMLParser
import re

from .common import CourseUnavailable, NTUPageError

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
            if start is not None and end is not None and start >= end:
                start = end = None
                remarks.append(line)
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

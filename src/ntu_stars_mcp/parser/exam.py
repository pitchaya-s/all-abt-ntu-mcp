from datetime import datetime
from html.parser import HTMLParser
import re

from .common import CourseUnavailable, NTUPageError, _Rows

class _ExamPlans(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.options: list[tuple[str, str]] = []
        self._value: str | None = None
        self._label: list[str] = []

    def _finish_option(self) -> None:
        if self._value is not None:
            self.options.append((self._value, " ".join("".join(self._label).split())))
            self._value = None
            self._label = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "input" and attributes.get("type", "").lower() == "radio" and attributes.get("name") == "p_plan_no":
            self._finish_option()
            self._value = attributes.get("value")
        elif tag == "br":
            self._finish_option()

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._finish_option()

    def handle_data(self, data: str) -> None:
        if self._value is not None:
            self._label.append(data)

def parse_undergraduate_exam_plan(
    html: str, academic_year: int | None = None, semester: str | None = None
) -> dict[str, str | int]:
    """Choose the latest public undergraduate exam term, or a requested available term."""
    parser = _ExamPlans()
    parser.feed(html)
    plans = []
    for plan_number, label in parser.options:
        match = re.search(r"AY(\d{4})-\d{2}\s+SEM\s*([12])", label, re.IGNORECASE)
        if match and plan_number:
            plans.append(
                {
                    "plan_number": plan_number,
                    "academic_year": int(match[1]),
                    "semester": match[2],
                }
            )
    if not plans:
        if "for undergraduate programmes" in html.casefold():
            raise CourseUnavailable("NTU has not published a public undergraduate exam timetable yet.")
        raise NTUPageError("NTU returned an unrecognized undergraduate exam-term page.")

    if academic_year is None:
        selected = max(plans, key=lambda plan: (plan["academic_year"], plan["semester"]))
    else:
        selected = next(
            (
                plan
                for plan in plans
                if plan["academic_year"] == academic_year and plan["semester"] == semester
            ),
            None,
        )
        if selected is None:
            raise CourseUnavailable(
                f"NTU has no public undergraduate exam timetable for AY{academic_year}/{str(academic_year + 1)[-2:]} "
                f"semester {semester}."
            )

    year = int(selected["academic_year"])
    selected_semester = str(selected["semester"])
    return {
        "plan_number": str(selected["plan_number"]),
        "academic_year": year,
        "semester": selected_semester,
        "academic_session": f"Semester {selected_semester} Academic Year {year}-{year + 1}",
    }

def _exam_date(value: str) -> str | None:
    for date_format in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            pass
    return None

def _exam_time(value: str) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,2})[.:](\d{2})\s*(AM|PM)\s*", value, re.IGNORECASE)
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if match[3].upper() == "PM" else 0)
    return f"{hour:02d}:{minute:02d}"

def _exam_duration(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(hr|hrs|hour|hours|min|mins|minute|minutes)\s*", value, re.I)
    if not match:
        return None
    return round(float(match[1]) * (60 if match[2].lower().startswith("h") else 1))

def parse_undergraduate_exam_schedule(html: str, expected_code: str) -> dict[str, object]:
    """Parse NTU's public General Access exam results; do not infer exam seat details."""
    parser = _Rows()
    parser.feed(html)
    header_index = next(
        (
            index
            for index, row in enumerate(parser.rows)
            if len(row) >= 6
            and [cell.strip().casefold() for cell in row[:6]]
            == ["date", "day", "time", "course", "course title", "duration"]
        ),
        None,
    )
    if header_index is None:
        raise NTUPageError("NTU returned an unrecognized undergraduate exam page; no exam table was found.")

    page_text = " ".join(parser.text_parts)
    term_match = re.search(r"Semester\s+([12])\s+Academic Year\s+(\d{4})-(\d{4})", page_text, re.I)
    if not term_match:
        raise NTUPageError("NTU's undergraduate exam page did not identify its academic year and semester.")

    code = expected_code.upper()
    notice = next(
        (row[0].strip() for row in parser.rows[:header_index] if row and "exam information shown" in row[0].casefold()),
        None,
    )
    exams: list[dict[str, object]] = []
    course_name: str | None = None
    for row in parser.rows[header_index + 1 :]:
        if len(row) <= 3 or row[3].strip().upper() != code:
            continue
        if len(row) != 6:
            raise NTUPageError("NTU's undergraduate exam table changed shape; expected six columns per exam.")

        raw_date, raw_day, raw_time, _, row_course_name, duration_text = (cell.strip() for cell in row)
        if course_name is None:
            course_name = row_course_name
        exam_date = _exam_date(raw_date)
        start_time = _exam_time(raw_time)
        duration_minutes = _exam_duration(duration_text)
        end_time = None
        if start_time is not None and duration_minutes is not None:
            end_minutes = int(start_time[:2]) * 60 + int(start_time[3:]) + duration_minutes
            if end_minutes < 24 * 60:
                end_time = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"

        day = raw_day[:3].upper() if raw_day[:3].upper() in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"} else None
        exam: dict[str, object] = {
            "date": exam_date,
            "day": day,
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration_minutes,
            "duration_text": duration_text,
        }
        if exam_date is None:
            exam["raw_date"] = raw_date
        if day is None:
            exam["raw_day"] = raw_day or None
        if start_time is None:
            exam["raw_time"] = raw_time or None
        exams.append(exam)

    return {
        "course_code": code,
        "course_name": course_name,
        "academic_year": int(term_match[2]),
        "semester": term_match[1],
        "exam_status": "available" if exams else "not_listed",
        "exam_count": len(exams),
        "exams": exams,
        "notice": notice,
    }

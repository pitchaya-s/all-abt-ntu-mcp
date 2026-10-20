from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, model_validator

from .domain import Course, compare_indexes as compare, course_metadata, find_matching_indexes as find
from .ntu_client import NTURequestError, get_course as fetch_course, validate_course_code


Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Semester = Literal[1, 2, "S"]
TimeText = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", description="24-hour time in HH:MM format")]
WeekNumber = Annotated[int, Field(ge=1, le=20)]


def _time_minutes(value: str) -> int:
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


class TimeWindow(BaseModel):
    day: Day
    start_time: TimeText
    end_time: TimeText

    @model_validator(mode="after")
    def end_follows_start(self) -> TimeWindow:
        if _time_minutes(self.end_time) <= _time_minutes(self.start_time):
            raise ValueError("end_time must be later than start_time")
        return self


class SessionRequirement(BaseModel):
    lesson_type: str | None = Field(default=None, description="Exact NTU lesson type, such as TUT or LAB")
    day: Day | None = None
    starts_at_or_after: TimeText | None = None
    starts_at_or_before: TimeText | None = None

    @model_validator(mode="after")
    def has_a_condition(self) -> SessionRequirement:
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("A required session must specify at least one condition")
        if (
            self.starts_at_or_after
            and self.starts_at_or_before
            and self.starts_at_or_after > self.starts_at_or_before
        ):
            raise ValueError("starts_at_or_before must not be earlier than starts_at_or_after")
        return self


class SearchConstraints(BaseModel):
    avoid_days: list[Day] = Field(default_factory=list, description="Reject indexes with a known class on these days")
    earliest_start: TimeText | None = Field(default=None, description="Every class must start at or after this time")
    latest_end: TimeText | None = Field(default=None, description="Every class must end by this time")
    avoid_windows: list[TimeWindow] = Field(default_factory=list, description="Reject classes overlapping these day/time windows")
    require_sessions: list[SessionRequirement] = Field(default_factory=list, description="Each requirement must match at least one session")
    teaching_weeks: list[WeekNumber] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="Evaluate only sessions meeting in these teaching weeks; unspecified week rules remain uncertain",
    )


class TimeSlot(BaseModel):
    day: Day | None = None
    start_time: TimeText | None = None
    end_time: TimeText | None = None
    teaching_weeks: list[WeekNumber] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_interval(self) -> TimeSlot:
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Provide both start_time and end_time, or neither")
        if self.start_time and self.end_time and _time_minutes(self.end_time) <= _time_minutes(self.start_time):
            raise ValueError("end_time must be later than start_time")
        return self


mcp = MCPServer(
    "ntu-course-index",
    version="0.1.0",
    instructions=(
        "Read-only NTU class schedule tools. Academic year is the first year printed by NTU "
        "(2026 means AY2026/27). Semester is 1, 2, or S. Data comes from the official public "
        "class schedule and is not registration vacancy or enrollment data. Unknown timetable "
        "details are preserved and marked uncertain."
    ),
)
_read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)


def _load_course(course_code: str, academic_year: int, semester: Semester) -> Course:
    try:
        return fetch_course(course_code, academic_year, semester)
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error


def _schedule_complete(sessions: tuple[Any, ...] | list[Any]) -> bool:
    return all(
        session.lesson_type is not None
        and session.day is not None
        and session.start_time is not None
        and session.end_time is not None
        for session in sessions
    )


@mcp.tool(annotations=_read_only)
def get_course(course_code: str, academic_year: int, semester: Semester) -> dict[str, Any]:
    """Get course metadata and every index with its complete timetable."""
    course = _load_course(course_code, academic_year, semester)
    result = course_metadata(course)
    result.update(
        {
            "index_count": len(course.indexes),
            "schedule_complete": bool(course.indexes) and all(_schedule_complete(sessions) for sessions in course.indexes.values()),
            "indexes": [
                {
                    "index": index,
                    "schedule_complete": _schedule_complete(sessions),
                    "sessions": [session.to_dict() for session in sessions],
                }
                for index, sessions in course.indexes.items()
            ],
        }
    )
    return result


@mcp.tool(annotations=_read_only)
def get_course_indexes(course_code: str, academic_year: int, semester: Semester) -> dict[str, Any]:
    """List all indexes for a course, including every lecture, tutorial, lab, and other session."""
    course = _load_course(course_code, academic_year, semester)
    result = course_metadata(course)
    result.update(
        {
            "index_count": len(course.indexes),
            "indexes": [
                {
                    "index": index,
                    "schedule_complete": _schedule_complete(sessions),
                    "sessions": [session.to_dict() for session in sessions],
                }
                for index, sessions in course.indexes.items()
            ],
        }
    )
    return result


@mcp.tool(annotations=_read_only)
def get_index_schedule(
    course_code: str, index: str, academic_year: int, semester: Semester
) -> dict[str, Any]:
    """Get every scheduled session for one course index."""
    try:
        code = validate_course_code(course_code)
    except ValueError as error:
        raise ToolError(str(error)) from error
    index = str(index).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", index):
        raise ToolError("Index number must contain only letters, digits, underscores, or hyphens.")
    course = _load_course(code, academic_year, semester)
    sessions = course.indexes.get(index)
    if sessions is None:
        raise ToolError(
            f"Index {index} is not listed for {code} in AY{academic_year}/{str(academic_year + 1)[-2:]} semester {semester}."
        )
    return {
        **course_metadata(course),
        "index": index,
        "schedule_complete": _schedule_complete(sessions),
        "sessions": [session.to_dict() for session in sessions],
    }


@mcp.tool(annotations=_read_only)
def compare_indexes(
    course_code: str,
    indexes: list[str],
    academic_year: int,
    semester: Semester,
    against_sessions: list[TimeSlot] | None = None,
) -> dict[str, Any]:
    """Compare shared and index-specific sessions; optionally check clashes with supplied time slots."""
    requested = [str(index).strip() for index in indexes]
    if len(requested) < 2:
        raise ToolError("Provide at least two index numbers to compare.")
    if len(set(requested)) != len(requested):
        raise ToolError("Index numbers must be unique.")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", index) for index in requested):
        raise ToolError("Index numbers must contain only letters, digits, underscores, or hyphens.")
    course = _load_course(course_code, academic_year, semester)
    existing = [slot.model_dump(exclude_none=True) for slot in against_sessions] if against_sessions is not None else None
    try:
        return compare(course, requested, existing)
    except ValueError as error:
        raise ToolError(str(error)) from error


@mcp.tool(annotations=_read_only)
def find_matching_indexes(
    course_code: str,
    academic_year: int,
    semester: Semester,
    constraints: SearchConstraints | None = None,
    against_sessions: list[TimeSlot] | None = None,
) -> dict[str, Any]:
    """Find indexes matching day/time/lesson/week rules and avoiding supplied timetable clashes."""
    course = _load_course(course_code, academic_year, semester)
    rules = constraints.model_dump(exclude_none=True) if constraints is not None else SearchConstraints().model_dump(exclude_none=True)
    existing = [slot.model_dump(exclude_none=True) for slot in against_sessions or []]
    return find(course, rules, existing)


def main() -> None:
    mcp.run(transport="stdio")

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, model_validator

from .compact import exam_fields, graduate_fields, personal_fields, saved_plan_fields, session_fields, timetable_fields
from .domain import Course, compare_indexes as compare, course_metadata, find_matching_indexes as find
from .schemas import (
    CompareIndexesResult,
    CourseIndexesResult,
    CourseMetadataResult,
    GraduateCourseResult,
    IndexResult,
    MatchingIndexesResult,
    SearchCoursesResult,
    UndergraduateExamResult,
)
from .wish import (
    AuthStatus,
    DegreeAuditResult,
    StarsPlannerResult,
    SavePlanResult,
    get_degree_audit as fetch_degree_audit,
    get_stars_planner as fetch_stars_planner,
    ntu_auth_status as fetch_ntu_auth_status,
    save_stars_plan as persist_stars_plan,
)
from .wish.session import wish_session
from .ntu_client import (
    NTURequestError,
    get_course as fetch_course,
    get_course_vacancies as fetch_course_vacancies,
    get_graduate_course_schedule as fetch_graduate_course_schedule,
    get_undergraduate_exam_schedule as fetch_undergraduate_exam_schedule,
    search_courses as fetch_course_search,
    validate_course_code,
)

Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Semester = Literal[1, 2, "S"]
ExamSemester = Literal[1, 2]
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
    teaching_weeks: list[WeekNumber] | None = Field(
        default=None, min_length=1, max_length=20,
        description="Known teaching weeks; omit if unknown. Overlapping times with unknown weeks remain uncertain.",
    )

    @model_validator(mode="after")
    def validate_interval(self) -> TimeSlot:
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Provide both start_time and end_time, or neither")
        if self.start_time and self.end_time and _time_minutes(self.end_time) <= _time_minutes(self.start_time):
            raise ValueError("end_time must be later than start_time")
        return self

class PlannedIndex(BaseModel):
    course_code: str = Field(description="NTU undergraduate course code")
    index: str = Field(pattern=r"^[0-9]{1,12}$", description="Index number as a string")

mcp = MCPServer(
    "ntu-stars-mcp",
    version="0.1.0",
    instructions=(
        "NTU timetable tools. Undergraduate tools use the official public Class Schedule; "
        "search_courses finds undergraduate courses by partial code or title in a published term. "
        "graduate lookup uses GSLink/PGR and reports the currently published term as class groups, "
        "not indexes. Undergraduate exam lookup uses General Access and returns published exam times, "
        "not exam-seat assignments. Academic year is the first year printed by NTU (2026 means AY2026/27); "
        "undergraduate semester is 1, 2, or S. get_course_indexes and get_index include public "
        "STARS vacancy snapshots only when the published vacancy term matches the requested term. Unknown "
        "undergraduate timetable details are preserved and marked uncertain. Optional personal tools "
        "use NTU_WISH_USERNAME and NTU_WISH_PASSWORD; personal records are cached only in memory. "
        "Session identifiers are inherited from their enclosing course/index; common_sessions apply to "
        "every indexes_compared entry. Personal tables omit rows only when headers and records reconstruct "
        "them exactly. Unknown raw values and timetable details are preserved. "
        "save_stars_plan replaces a saved plan's entire course/index list and verifies it by reloading; "
        "it does not register, drop, or swap registered courses."
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

def _load_vacancies(course: Course) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        result = fetch_course_vacancies(course.course_code, course.academic_year, course.semester)
    except NTURequestError as error:
        return {"status": "unavailable", "retrieved_at": None, "message": str(error)}, {}
    return {key: value for key, value in result.items() if key != "indexes"}, result["indexes"]

def _index_vacancies(index: str, metadata: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
    counts = indexes.get(index)
    return {
        "vacancy_status": metadata["status"] if metadata["status"] != "available" else (
            "available" if counts is not None else "not_listed"
        ),
        "vacancies_available": counts["vacancies_available"] if counts is not None else None,
        "waitlist_length": counts["waitlist_length"] if counts is not None else None,
    }

@mcp.tool(annotations=_read_only)
def search_courses(
    query: Annotated[str, Field(min_length=2, max_length=80, description="Partial course code or title words, such as SC20 or DATA STRUCTURES; no wildcards")],
    academic_year: int,
    semester: Semester,
    study_mode: Literal["full_time", "part_time"] = "full_time",
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> SearchCoursesResult:
    """Search NTU's public undergraduate Class Schedule by partial code or title keywords. Returns course codes, names and AUs for the requested term and study mode. Use offset/limit to page through matches, then get_course_metadata or get_course_indexes for details. This is not a graduate or all-catalogue search."""
    try:
        return fetch_course_search(query, academic_year, semester, study_mode, limit, offset)
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def get_course_metadata(course_code: str, academic_year: int, semester: Semester) -> CourseMetadataResult:
    """Get course name, AUs, prerequisites, description, and term metadata."""
    course = _load_course(course_code, academic_year, semester)
    return cast(CourseMetadataResult, course_metadata(course))

@mcp.tool(annotations=_read_only)
def get_course_indexes(course_code: str, academic_year: int, semester: Semester) -> CourseIndexesResult:
    """List all indexes with complete timetable details and matching-term vacancies/waitlists. Sessions inherit course_code and index from their enclosing result; null raw_day/raw_time are omitted."""
    course = _load_course(course_code, academic_year, semester)
    vacancy_metadata, vacancies = _load_vacancies(course)
    return {
        "course_code": course.course_code,
        "academic_year": course.academic_year,
        "semester": course.semester,
        "index_count": len(course.indexes),
        "vacancy_metadata": vacancy_metadata,
        "indexes": [
            {
                "index": index,
                **_index_vacancies(index, vacancy_metadata, vacancies),
                "schedule_complete": _schedule_complete(sessions),
                "sessions": [session_fields(session.to_dict()) for session in sessions],
            }
            for index, sessions in course.indexes.items()
        ],
    }

@mcp.tool(annotations=_read_only)
def get_graduate_course_schedule(course_code: str) -> GraduateCourseResult:
    """Get a graduate course's class groups for NTU's currently published academic term."""
    try:
        return cast(GraduateCourseResult, graduate_fields(fetch_graduate_course_schedule(course_code)))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def get_undergraduate_exam_schedule(
    course_code: str, academic_year: int | None = None, semester: ExamSemester | None = None
) -> UndergraduateExamResult:
    """Get public General Access exam dates and times for a course in the latest or specified published term."""
    try:
        return cast(UndergraduateExamResult, exam_fields(fetch_undergraduate_exam_schedule(course_code, academic_year, semester)))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def ntu_auth_status() -> AuthStatus:
    """Report whether WISH credentials are configured and whether this process has verified a session."""
    return fetch_ntu_auth_status()

@mcp.tool(annotations=_read_only)
def get_stars_planner(refresh: bool = False) -> StarsPlannerResult:
    """Get registered courses, the published term, and saved Plans 1–3 with indexes and timetables. Use refresh after editing a plan."""
    try:
        return cast(StarsPlannerResult, personal_fields(fetch_stars_planner(refresh=refresh)))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True))
def save_stars_plan(
    plan_number: Literal[1, 2, 3],
    courses: Annotated[list[PlannedIndex], Field(min_length=1, max_length=13)],
    academic_year: int,
    semester: Literal[1, 2],
) -> SavePlanResult:
    """Replace saved Plan 1, 2, or 3 with the complete supplied course/index list for the current Planner term. Omitted courses are removed from that plan. Verifies persistence by loading the saved plan. Does not perform course registration, dropping, or index swapping."""
    try:
        result = persist_stars_plan(plan_number, [course.model_dump() for course in courses], academic_year, semester)
        return {**result, "saved_plan": saved_plan_fields(result["saved_plan"])}
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def get_degree_audit() -> DegreeAuditResult:
    """Get your degree requirements, examination results, and registered courses from Degree Audit."""
    try:
        return cast(DegreeAuditResult, personal_fields(fetch_degree_audit()))
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def get_index(
    course_code: str, index: str, academic_year: int, semester: Semester
) -> IndexResult:
    """Get one index's complete schedule, vacancies, and waitlist where matching-term counts are published."""
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
    vacancy_metadata, vacancies = _load_vacancies(course)
    return {
        "course_code": course.course_code,
        "academic_year": course.academic_year,
        "semester": course.semester,
        "index": index,
        **_index_vacancies(index, vacancy_metadata, vacancies),
        "vacancy_metadata": vacancy_metadata,
        "schedule_complete": _schedule_complete(sessions),
        "sessions": [session_fields(session.to_dict()) for session in sessions],
    }

@mcp.tool(annotations=_read_only)
def compare_indexes(
    course_code: str,
    indexes: list[str],
    academic_year: int,
    semester: Semester,
    against_sessions: list[TimeSlot] | None = None,
) -> CompareIndexesResult:
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
        result = compare(course, requested, existing)
        clash_check = result["clash_check"]
        if clash_check is not None:
            clash_check = {**clash_check, "clashes_by_index": {
                index: [{**pair, "course_session": session_fields(pair["course_session"])} for pair in pairs]
                for index, pairs in clash_check["clashes_by_index"].items()
            }}
        return {
            **timetable_fields(result), "indexes_compared": result["indexes_compared"],
            "common_sessions": [session_fields(session) for session in result["common_sessions"]],
            "unique_sessions_by_index": {index: [session_fields(session) for session in sessions]
                                         for index, sessions in result["unique_sessions_by_index"].items()},
            "clash_check": clash_check,
        }
    except ValueError as error:
        raise ToolError(str(error)) from error

@mcp.tool(annotations=_read_only)
def find_matching_indexes(
    course_code: str,
    academic_year: int,
    semester: Semester,
    constraints: SearchConstraints | None = None,
    against_sessions: list[TimeSlot] | None = None,
) -> MatchingIndexesResult:
    """Find indexes matching day/time/lesson/week rules and avoiding supplied timetable clashes."""
    course = _load_course(course_code, academic_year, semester)
    rules = constraints.model_dump(exclude_none=True, exclude_defaults=True) if constraints is not None else {}
    existing = [slot.model_dump(exclude_none=True) for slot in against_sessions or []]
    result = find(course, rules, existing)
    return {
        **timetable_fields(result), "constraints": result["constraints"],
        "against_session_count": result["against_session_count"], "match_count": result["match_count"],
        "matches": [{**match, "sessions": [session_fields(session) for session in match["sessions"]]}
                    for match in result["matches"]],
    }

def main() -> None:
    try:
        mcp.run(transport="stdio")
    finally:
        wish_session.close()

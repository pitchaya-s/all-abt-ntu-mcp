"""Structured public MCP results. Optional keys preserve absent NTU information."""

from typing import Literal
from typing_extensions import NotRequired, TypedDict


class CourseTerm(TypedDict):
    course_code: str
    academic_year: int | None
    semester: str | None


class CourseNote(TypedDict):
    label: str
    text: str


class CourseMetadataResult(CourseTerm):
    course_name: str
    au: float | None
    course_description: str | None
    course_description_status: Literal["available", "not_listed", "unavailable"]
    course_description_source: str | None
    prerequisites: str | None
    course_notes: list[CourseNote]
    retrieved_at: str | None
    official_source: str | None


class Lesson(TypedDict):
    lesson_type: str | None
    group: str | None
    day: str | None
    start_time: str | None
    end_time: str | None
    venue: str | None
    teaching_weeks: list[int] | None
    remarks: str | None


class CompactSession(Lesson):
    """Course/index are inherited from the result; unfamiliar day/time text stays explicit."""
    raw_time: NotRequired[str]
    raw_day: NotRequired[str]


class VacancyMetadata(TypedDict):
    status: Literal["available", "closed", "term_mismatch", "unavailable"]
    retrieved_at: str | None
    academic_year: NotRequired[int | None]
    semester: NotRequired[str | None]
    source_url: NotRequired[str]
    from_cache: NotRequired[bool]
    cache_age_seconds: NotRequired[float | None]
    message: NotRequired[str]


class IndexVacancies(TypedDict):
    vacancy_status: Literal["available", "not_listed", "closed", "term_mismatch", "unavailable"]
    vacancies_available: int | None
    waitlist_length: int | None


class CourseIndex(IndexVacancies):
    index: str
    schedule_complete: bool
    sessions: list[CompactSession]


class CourseIndexesResult(CourseTerm):
    index_count: int
    vacancy_metadata: VacancyMetadata
    indexes: list[CourseIndex]


class IndexResult(CourseTerm, IndexVacancies):
    index: str
    vacancy_metadata: VacancyMetadata
    schedule_complete: bool
    sessions: list[CompactSession]


class ExistingSession(TypedDict, total=False):
    day: str
    start_time: str
    end_time: str
    teaching_weeks: list[int]


class ClashPair(TypedDict):
    course_session: CompactSession
    existing_session: ExistingSession


class ClashCheck(TypedDict):
    against_session_count: int
    clashes_by_index: dict[str, list[ClashPair]]
    uncertain_comparisons_by_index: dict[str, int]


class TimetableResult(CourseTerm):
    retrieved_at: str | None
    official_source: str | None


class CompareIndexesResult(TimetableResult):
    indexes_compared: list[str]
    common_sessions: list[CompactSession]
    unique_sessions_by_index: dict[str, list[CompactSession]]
    clash_check: ClashCheck | None


class TimeWindowResult(TypedDict):
    day: str
    start_time: str
    end_time: str


class SessionRule(TypedDict, total=False):
    lesson_type: str
    day: str
    starts_at_or_after: str
    starts_at_or_before: str


class ConstraintsResult(TypedDict, total=False):
    avoid_days: list[str]
    earliest_start: str
    latest_end: str
    avoid_windows: list[TimeWindowResult]
    require_sessions: list[SessionRule]
    teaching_weeks: list[int]


class MatchingIndex(TypedDict):
    index: str
    status: Literal["confirmed", "uncertain"]
    uncertainties: list[str]
    schedule_complete: bool
    sessions: list[CompactSession]


class MatchingIndexesResult(TimetableResult):
    constraints: ConstraintsResult
    against_session_count: int
    match_count: int
    matches: list[MatchingIndex]


class GraduateSession(TypedDict):
    day: str | None
    start_time: str | None
    end_time: str | None
    venue: str | None
    commence_date: str | None
    teaching_weeks: list[int] | None


class GraduateClassGroup(TypedDict):
    class_group: str | None
    coordinator: str | None
    sessions: list[GraduateSession]
    schedule_remarks: list[str]
    schedule_text: NotRequired[str | None]


class GraduateCourseResult(TypedDict):
    course_code: str
    course_name: str
    au: float | None
    academic_year: int
    term: str
    schedule_complete: bool
    class_groups: list[GraduateClassGroup]
    source_url: str


class ExamResult(TypedDict):
    date: str | None
    day: str | None
    start_time: str | None
    end_time: str | None
    duration_minutes: int | None
    duration_text: NotRequired[str]
    raw_date: NotRequired[str]
    raw_day: NotRequired[str | None]
    raw_time: NotRequired[str | None]


class UndergraduateExamResult(TypedDict):
    course_code: str
    course_name: str | None
    academic_year: int
    semester: str
    exam_status: Literal["available", "not_listed"]
    exam_count: int
    exams: list[ExamResult]
    notice: str | None
    source_url: str
    retrieved_at: str

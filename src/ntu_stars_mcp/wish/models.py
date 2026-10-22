from typing_extensions import NotRequired, TypedDict

from ..ntu_client.http import NTURequestError
from shared.credentials import CredentialStatus

class PersonalTable(TypedDict):
    section: str | None
    headers: list[str]
    rows: NotRequired[list[list[str]]]
    records: list[dict[str, str]]

class AuthStatus(CredentialStatus):
    session_verified: bool
    last_verified_at: str | None
    session_storage: str
    personal_cache_ttl_seconds: int

class PlannedCourse(TypedDict):
    course_code: str
    index: str | None
    course_type: str | None

class PlannerSession(TypedDict):
    course_code: str
    index: NotRequired[str | None]
    lesson_type: str
    group: str
    day: str
    start_time: str | None
    end_time: str | None
    venue: str
    teaching_weeks: list[int] | None
    remarks: str | None
    raw_time: NotRequired[str | None]

class SavedPlan(TypedDict):
    plan_number: int
    status: str
    courses: list[PlannedCourse]
    sessions: list[PlannerSession]
    unparsed_sessions: list[dict[str, str]]
    timetable_status: str

class StarsPlannerResult(TypedDict):
    service: str
    page_title: str | None
    academic_year: int | None
    semester: int | None
    registration_notice: str | None
    registered_courses: list[dict[str, str]]
    registered_courses_status: str
    planner_tables: list[PersonalTable]
    timetable_tables: list[PersonalTable]
    timetable_status: str
    saved_plans: list[SavedPlan]
    source_url: str
    retrieved_at: str
    from_cache: bool
    cache_age_seconds: int

class SavePlanResult(TypedDict):
    status: str
    academic_year: int
    semester: int
    saved_plan: SavedPlan
    verified_at: str
    source_url: str

class DegreeAuditResult(TypedDict):
    service: str
    page_title: str | None
    requirements: list[PersonalTable]
    requirements_status: str
    examination_results: list[PersonalTable]
    examination_results_status: str
    courses_registered: list[PersonalTable]
    courses_registered_status: str
    source_url: str
    retrieved_at: str
    from_cache: bool
    cache_age_seconds: int

class NTUAuthError(NTURequestError):
    """A WISH login, session, or verification problem."""

class NTUPersonalDataError(NTURequestError):
    """An authenticated personal page could not be parsed safely."""

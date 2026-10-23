"""Inputs and structured results for teaching-based room queries."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Semester = Literal[1, 2, "S"]
Year = Annotated[int, Field(ge=2000, le=2100, strict=True)]
TimeText = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
Weeks = Annotated[list[Annotated[int, Field(ge=1, le=20, strict=True)]], Field(min_length=1, max_length=20)]
RoomType = Literal["tutorial_room", "seminar_room", "lecture_theatre", "laboratory", "other"]
Label = Annotated[str, Field(min_length=1, max_length=80)]
Limit = Annotated[int, Field(ge=1, le=100, strict=True)]
Offset = Annotated[int, Field(ge=0, strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def minutes(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


class RoomFilters(Model):
    room_types: list[RoomType] | None = Field(
        default=None,
        min_length=1,
        max_length=5,
        description="Inferred from venue codes, not lesson types or an official room inventory.",
    )
    venue_contains: Label | None = None
    venue_prefixes: list[Label] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="Venue-code prefixes such as LHN, LHS, SPMS or S4. No geographic location is inferred for bare TR/LT labels.",
    )
    exclude_venues: list[Label] = Field(default_factory=list, max_length=100)
    used_for_lesson_types: list[Label] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="Candidate rooms must have at least one published lesson of these types. All lesson types still block availability.",
    )

    @field_validator("venue_contains")
    @classmethod
    def nonblank(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("Venue text must be nonblank and contain no control characters.")
        return value

    @field_validator("venue_prefixes", "exclude_venues", "used_for_lesson_types")
    @classmethod
    def nonblank_list(cls, values):
        if values is not None and any(not v.strip() or any(ord(c) < 32 for c in v) for v in values):
            raise ValueError("Filter labels must be nonblank and contain no control characters.")
        return values


class RoomWindow(Model):
    day: Day
    start_time: TimeText
    end_time: TimeText
    teaching_weeks: Weeks | None = Field(
        default=None,
        description="Free in every requested teaching week. Omit to consider every published meeting, conservatively across the whole term.",
    )
    buffer_minutes: int = Field(
        default=0,
        ge=0,
        le=120,
        strict=True,
        description="Additional teaching-free minutes required before and after the requested interval.",
    )

    @model_validator(mode="after")
    def interval(self):
        start, end = minutes(self.start_time), minutes(self.end_time)
        if start >= end:
            raise ValueError("end_time must be later than start_time on the same day.")
        if start - self.buffer_minutes < 0 or end + self.buffer_minutes > 1440:
            raise ValueError("The interval plus buffer must stay within one day.")
        return self


class RoomCoverage(Model):
    scope: Literal["published_undergraduate_full_time_and_part_time_teaching"] = (
        "published_undergraduate_full_time_and_part_time_teaching"
    )
    course_count: int
    courses_without_published_indexes: int
    index_count: int
    lesson_count: int
    observed_room_count: int
    excluded_venue_label_count: int
    unplaced_lesson_count: int


class RoomIdentity(Model):
    venue: str
    room_type: RoomType
    aliases: list[str]
    observed_lesson_types: list[str]


class AvailableRoom(RoomIdentity):
    free_from: str
    free_until: str


class RoomLesson(Model):
    course_code: str
    indexes: list[str]
    lesson_type: str | None
    group: str | None
    day: str | None
    start_time: str | None
    end_time: str | None
    teaching_weeks: list[int] | None
    remarks: str | None
    raw_day: str | None
    raw_time: str | None
    source_venue_labels: list[str] = Field(
        default_factory=list,
        description="Original venue text when it differs from the enclosing canonical room, including multi-room cells.",
    )


class RoomResult(Model):
    academic_year: int
    semester: str
    source_url: str
    retrieved_at: str
    cached: bool
    coverage: RoomCoverage


class AvailableRoomsResult(RoomResult):
    availability_basis: Literal["no_known_scheduled_teaching"] = "no_known_scheduled_teaching"
    window: RoomWindow
    match_count: int
    offset: int
    has_more: bool
    rooms: list[AvailableRoom]
    excluded_busy_count: int
    excluded_uncertain_count: int


class RoomScheduleResult(RoomResult):
    room: RoomIdentity
    session_count: int
    offset: int
    has_more: bool
    sessions: list[RoomLesson]

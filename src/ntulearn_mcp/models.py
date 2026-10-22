from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LearnError(RuntimeError):
    """A sanitized NTULearn authentication, network, or response error."""


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AuthStatus(Model):
    credentials_configured: bool
    session_verified: bool
    last_verified_at: datetime | None
    session_storage: Literal["in_memory_only"] = "in_memory_only"
    cache_ttl_seconds: int


class Freshness(Model):
    retrieved_at: datetime
    from_cache: bool
    cache_age_seconds: int


class Course(Model):
    id: str
    course_code: str | None = None
    name: str
    available: str | None = None
    role: str | None = None
    organization: bool | None = None


class Courses(Freshness):
    courses: list[Course]
    offset: int
    next_offset: int | None


class Content(Model):
    id: str
    title: str
    parent_id: str | None = None
    has_children: bool | None = None
    type: str | None = None
    body: str | None = None
    description: str | None = None
    modified: datetime | None = None


class Contents(Freshness):
    course_id: str
    contents: list[Content]
    offset: int
    next_offset: int | None


class Announcement(Model):
    id: str
    title: str
    body: str | None = None
    created: datetime | None = None
    modified: datetime | None = None


class Announcements(Freshness):
    course_id: str
    announcements: list[Announcement]
    offset: int
    next_offset: int | None


class CalendarItem(Model):
    id: str
    title: str
    type: str | None = None
    calendar_name: str | None = None
    course_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    description: str | None = None
    location: str | None = None


class Calendar(Freshness):
    since: datetime
    until: datetime
    items: list[CalendarItem]
    offset: int
    next_offset: int | None


class GradeColumn(Model):
    id: str
    name: str
    possible_score: float | None = None
    due: datetime | None = None
    available: str | None = None
    content_id: str | None = None


class Grade(Model):
    column_id: str
    score: float | None = None
    text: str | None = None
    status: str | None = None
    exempt: bool | None = None
    feedback: str | None = None


class Gradebook(Freshness):
    course_id: str
    columns: list[GradeColumn]
    grades: list[Grade]
    offset: int
    next_offset: int | None
    grades_next_offset: int | None
    grades_offset: int


class Attachment(Model):
    id: str
    file_name: str
    mime_type: str | None = None


class Attachments(Freshness):
    course_id: str
    content_id: str
    attachments: list[Attachment]
    offset: int
    next_offset: int | None


class Download(Model):
    path: str
    bytes_written: int = Field(ge=0)
    downloaded_at: datetime

from datetime import datetime

from pydantic import Field

from .common import Freshness, Model, ScanResult


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


class ContentNode(Content):
    children: list['ContentNode'] = Field(default_factory=list)
    children_complete: bool | None = None


class ContentTree(ScanResult):
    course_id: str
    contents: list[ContentNode]
    max_depth: int


class ContentMatch(Model):
    course_id: str
    content_id: str
    title: str
    breadcrumb: list[str]
    excerpt: str


class ContentSearch(ScanResult):
    query: str
    courses_searched: list[str]
    matches: list[ContentMatch]

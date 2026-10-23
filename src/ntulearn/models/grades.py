from datetime import datetime

from .common import Freshness, Model


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
    modified: datetime | None = None


class Gradebook(Freshness):
    course_id: str
    columns: list[GradeColumn]
    grades: list[Grade]
    offset: int
    next_offset: int | None
    grades_next_offset: int | None
    grades_offset: int

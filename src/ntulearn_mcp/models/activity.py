from datetime import datetime

from .common import Freshness, Model, ScanResult
from .grades import Grade, GradeColumn


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


class Upcoming(ScanResult):
    since: datetime
    until: datetime
    items: list[CalendarItem]


class RecentAnnouncement(Announcement):
    course_id: str
    changed_since: bool | None


class RecentGrade(Model):
    course_id: str
    column: GradeColumn | None = None
    grade: Grade
    changed_since: bool | None


class Digest(ScanResult):
    since: datetime
    until: datetime
    announcements: list[RecentAnnouncement]
    upcoming: list[CalendarItem]
    grades: list[RecentGrade]
    grade_change_note: str = 'Grades without a published change timestamp are current snapshots; changed_since is null.'

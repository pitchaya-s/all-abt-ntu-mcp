"""Typed academic reads using the authenticated user's own Blackboard permissions."""

from datetime import datetime, timedelta, timezone
import re

from .session import ID, Session
from ..models import (
    Announcement, Announcements, Attachment, Attachments, Calendar, CalendarItem,
    Content, Contents, Course, Courses, Grade, Gradebook, GradeColumn, LearnError,
)
from ..parser.response import records, required, text


PREFIX = "/learn/api/public/v1"


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise LearnError("Use an NTULearn ID returned by another tool; slashes, URLs, and query strings are not allowed.")
    return value


def page_parameters(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise LearnError("limit must be 1–100 and offset must be a nonnegative integer.")
    return {"limit": limit, "offset": offset}


def mapping(item, key):
    value = item.get(key) or {}
    if not isinstance(value, dict):
        raise LearnError("NTULearn returned an unfamiliar nested academic field.")
    return value


def model(cls, **values):
    try:
        return cls(**values)
    except ValueError:
        raise LearnError("NTULearn returned an unexpected academic-data format; no values were inferred.") from None


class LearnClient:
    def __init__(self, session: Session):
        self.session = session

    def _list(self, path, limit, offset, refresh=False, **params):
        data, freshness = self.session.get(path, {**page_parameters(limit, offset), **params}, refresh)
        rows, next_offset = records(data, path)
        if data.get("courseErrors"):
            raise LearnError("NTULearn reported errors for part of this request; narrow the calendar window or select a single course.")
        if next_offset is not None and next_offset <= offset:
            raise LearnError("NTULearn returned a pagination loop; no further pages were followed.")
        return rows, next_offset, freshness

    def list_courses(self, limit=50, offset=0, refresh=False) -> Courses:
        rows, next_offset, freshness = self._list(PREFIX + "/users/me/courses", limit, offset, refresh, expand="course")
        courses = []
        for row in rows:
            course = mapping(row, "course")
            courses.append(model(Course, id=required(course, "id"), name=required(course, "name"),
                                 course_code=course.get("courseId"), available=mapping(course, "availability").get("available"),
                                 role=row.get("courseRoleId"), organization=course.get("organization")))
        return model(Courses, courses=courses, offset=offset, next_offset=next_offset, **freshness)

    def get_course_contents(self, course_id, parent_id=None, limit=50, offset=0, refresh=False) -> Contents:
        course_id = identifier(course_id)
        path = f"{PREFIX}/courses/{course_id}/contents"
        if parent_id is not None:
            path += f"/{identifier(parent_id)}/children"
        rows, next_offset, freshness = self._list(path, limit, offset, refresh)
        contents = [model(Content, id=required(row, "id"), title=required(row, "title"),
                          parent_id=row.get("parentId"), has_children=row.get("hasChildren"),
                          type=mapping(row, "contentHandler").get("id"), body=text(row.get("body")),
                          description=text(row.get("description")), modified=row.get("modified")) for row in rows]
        return model(Contents, course_id=course_id, contents=contents, offset=offset, next_offset=next_offset, **freshness)

    def get_announcements(self, course_id, limit=50, offset=0, refresh=False) -> Announcements:
        course_id = identifier(course_id)
        rows, next_offset, freshness = self._list(f"{PREFIX}/courses/{course_id}/announcements", limit, offset, refresh)
        announcements = [model(Announcement, id=required(row, "id"), title=required(row, "title"),
                               body=text(row.get("body")), created=row.get("created"), modified=row.get("modified")) for row in rows]
        return model(Announcements, course_id=course_id, announcements=announcements, offset=offset, next_offset=next_offset, **freshness)

    def get_calendar(self, since=None, until=None, course_id=None, limit=50, offset=0, refresh=False) -> Calendar:
        since = since or datetime.now(timezone.utc)
        until = until or since + timedelta(days=14)
        if since.tzinfo is None or until.tzinfo is None or not timedelta(0) < until - since <= timedelta(days=112):
            raise LearnError("Use timezone-aware calendar times with an end after the start and a window of at most 112 days.")
        params = {"since": since.isoformat(), "until": until.isoformat()}
        if course_id is not None:
            params["courseId"] = identifier(course_id)
        rows, next_offset, freshness = self._list(PREFIX + "/calendars/items", limit, offset, refresh, **params)
        items = [model(CalendarItem, id=required(row, "id"), title=required(row, "title"), type=row.get("type"),
                       calendar_name=row.get("calendarName"), course_id=mapping(row, "dynamicCalendarItemProps").get("courseId"),
                       start=row.get("start"), end=row.get("end"), description=text(row.get("description")), location=row.get("location")) for row in rows]
        return model(Calendar, since=since, until=until, items=items, offset=offset, next_offset=next_offset, **freshness)

    def get_gradebook(self, course_id, limit=50, offset=0, grades_offset=0, refresh=False) -> Gradebook:
        course_id = identifier(course_id)
        columns, next_offset, freshness = self._list(f"{PREFIX}/courses/{course_id}/gradebook/columns", limit, offset, refresh)
        user, _ = self.session.get(PREFIX + "/users/me", refresh=refresh)
        user_id = identifier(required(user, "id"))
        grades, grades_next_offset, grade_freshness = self._list(f"{PREFIX}/courses/{course_id}/gradebook/users/{user_id}", limit, grades_offset, refresh)
        columns = [model(GradeColumn, id=required(row, "id"), name=required(row, "name"),
                         possible_score=mapping(row, "score").get("possible"), due=mapping(row, "grading").get("due"),
                         available=mapping(row, "availability").get("available"), content_id=row.get("contentId")) for row in columns]
        grades = [model(Grade, column_id=required(row, "columnId"), score=row.get("score"), text=row.get("text"),
                        status=row.get("status") or row.get("gradingStatus"), exempt=row.get("exempt"), feedback=text(row.get("feedback")),
                        modified=row.get("modified") or row.get("lastGraded")) for row in grades]
        freshness = {"retrieved_at": min(freshness["retrieved_at"], grade_freshness["retrieved_at"]),
                     "from_cache": freshness["from_cache"] and grade_freshness["from_cache"],
                     "cache_age_seconds": max(freshness["cache_age_seconds"], grade_freshness["cache_age_seconds"])}
        return model(Gradebook, course_id=course_id, columns=columns, grades=grades, offset=offset,
                     grades_offset=grades_offset, next_offset=next_offset, grades_next_offset=grades_next_offset, **freshness)

    def get_content_attachments(self, course_id, content_id, limit=50, offset=0, refresh=False) -> Attachments:
        course_id, content_id = identifier(course_id), identifier(content_id)
        rows, next_offset, freshness = self._list(f"{PREFIX}/courses/{course_id}/contents/{content_id}/attachments", limit, offset, refresh)
        attachments = [model(Attachment, id=required(row, "id"), file_name=required(row, "fileName"), mime_type=row.get("mimeType")) for row in rows]
        return model(Attachments, course_id=course_id, content_id=content_id, attachments=attachments,
                     offset=offset, next_offset=next_offset, **freshness)

    def download_file(self, course_id, content_id, attachment_id, destination, max_bytes=20_000_000):
        path = f"{PREFIX}/courses/{identifier(course_id)}/contents/{identifier(content_id)}/attachments/{identifier(attachment_id)}/download"
        return self.session.download(path, destination, max_bytes=max_bytes)

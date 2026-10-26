"""Cross-course calendar and recent-activity summaries with explicit partial results."""

import asyncio
from datetime import datetime, timedelta, timezone

from ..client.client import model
from ..models import Digest, Grade, GradeColumn, LearnError, RecentAnnouncement, RecentGrade, Upcoming
from .scan import LimitReached, Scan, aware, course_ids, pages


async def _upcoming(client, scan, since, until, selected, item_type, refresh):
    items = []
    try:
        selected = set(await course_ids(client, scan, selected, refresh)) if selected is not None else None
        async for item in pages(scan, client.get_calendar, 'items', since, until, refresh=refresh):
            if selected is not None and item.course_id not in selected:
                continue
            if item_type is None or item.type == item_type:
                items.append(item)
    except LearnError as error:
        scan.issue('calendar', error)
    return sorted(items, key=lambda item: item.start.timestamp() if item.start else float('inf'))


async def get_upcoming(client, since=None, until=None, selected=None, item_type=None, max_requests=100, refresh=False):
    since = aware(since, 'since') or datetime.now(timezone.utc)
    until = aware(until, 'until') or since + timedelta(days=14)
    if not timedelta(0) < until - since <= timedelta(days=112):
        raise LearnError('Calendar window must be greater than zero and no longer than 112 days.')
    scan = Scan(max_requests)
    items = await _upcoming(client, scan, since, until, selected, item_type, refresh)
    return model(Upcoming, since=since, until=until, items=items, **scan.metadata())


async def whats_new(client, since=None, until=None, selected=None, max_items=200, max_requests=100, refresh=False):
    now = datetime.now(timezone.utc)
    since = aware(since, 'since') or now - timedelta(days=7)
    until = aware(until, 'until') or now + timedelta(days=14)
    if since > now or not now < until <= now + timedelta(days=112):
        raise LearnError('since must be in the past and until must be within the next 112 days.')
    if type(max_items) is not int or not 1 <= max_items <= 500:
        raise LearnError('max_items must be between 1 and 500.')
    scan = Scan(max_requests)
    announcements, grades = [], []
    try:
        selected_courses = await course_ids(client, scan, selected, refresh)
    except LearnError as error:
        scan.issue('digest', error)
        selected_courses = []
    upcoming = await _upcoming(
        client, scan, now, until,
        selected_courses if selected is not None else None,
        None, refresh,
    )

    async def collect_course(course):
        course_announcements, course_grades = [], []
        try:
            async for announcement in pages(scan, client.get_announcements, 'announcements', course, refresh=refresh):
                changed = announcement.modified or announcement.created
                if changed is None or changed >= since:
                    course_announcements.append(RecentAnnouncement(course_id=course, changed_since=True if changed else None,
                                                                   **announcement.model_dump()))
                if len(course_announcements) >= max_items:
                    raise LimitReached('Announcement item limit reached; narrow the courses or cutoff.')
        except LearnError as error:
            scan.issue('announcements', error, course)
        try:
            offset = grades_offset = 0
            columns: dict[str, GradeColumn] = {}
            entries: dict[str, Grade] = {}
            while True:
                gradebook = await scan.call(
                    client.get_gradebook, course, limit=100, offset=offset,
                    grades_offset=grades_offset, refresh=refresh, cost=3,
                )
                columns.update((column.id, column) for column in gradebook.columns)
                entries.update((grade.column_id, grade) for grade in gradebook.grades)
                if gradebook.next_offset is None and gradebook.grades_next_offset is None:
                    break
                offset = gradebook.next_offset if gradebook.next_offset is not None else offset
                grades_offset = gradebook.grades_next_offset if gradebook.grades_next_offset is not None else grades_offset
            for grade in entries.values():
                if grade.modified is None or grade.modified >= since:
                    course_grades.append(RecentGrade(course_id=course, column=columns.get(grade.column_id), grade=grade,
                                                    changed_since=True if grade.modified else None))
                if len(course_grades) >= max_items:
                    raise LimitReached('Grade item limit reached; narrow the course selection.')
        except LearnError as error:
            scan.issue('gradebook', error, course)
        return course_announcements, course_grades

    course_semaphore = asyncio.Semaphore(4)

    async def bounded_course(course):
        async with course_semaphore:
            return await collect_course(course)

    results = await asyncio.gather(*(bounded_course(course) for course in selected_courses))
    for course_announcements, course_grades in results:
        announcements.extend(course_announcements)
        grades.extend(course_grades)
    if len(upcoming) > max_items:
        upcoming = upcoming[:max_items]
        scan.issue('calendar', 'Upcoming item limit reached; narrow the calendar window.')
    announcements.sort(key=lambda item: (item.modified or item.created).timestamp() if item.modified or item.created else float('-inf'), reverse=True)
    return model(Digest, since=since, until=until, announcements=announcements[:max_items], upcoming=upcoming,
                 grades=grades[:max_items], **scan.metadata())

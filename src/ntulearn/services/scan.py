"""Shared request budgets and pagination for cross-course reads."""

import asyncio
from datetime import datetime, timezone

from ..client.client import identifier
from ..models import Issue, LearnError


class LimitReached(LearnError):
    pass


class Scan:
    def __init__(self, max_requests):
        if type(max_requests) is not int or not 1 <= max_requests <= 200:
            raise LearnError('max_requests must be between 1 and 200.')
        self.limit = max_requests
        self.requests = 0
        self.freshness = []
        self.issues = []
        self._request_lock = asyncio.Lock()

    async def call(self, function, *args, cost=1, **kwargs):
        async with self._request_lock:
            if self.requests + cost > self.limit:
                raise LimitReached('Request budget reached; narrow the course selection or increase max_requests.')
            self.requests += cost
        result = await function(*args, **kwargs)
        if hasattr(result, 'retrieved_at'):
            self.freshness.append({key: getattr(result, key) for key in ('retrieved_at', 'from_cache', 'cache_age_seconds')})
        elif hasattr(result, 'downloaded_at'):
            self.freshness.append(dict(retrieved_at=result.downloaded_at, from_cache=False, cache_age_seconds=0))
        return result

    async def get(self, client, path, params=None, refresh=False):
        data, freshness = await self.call(client.session.get, path, params, refresh)
        self.freshness.append(freshness)
        return data

    def issue(self, service, error, course_id=None, content_id=None):
        self.issues.append(Issue(service=service, message=str(error), course_id=course_id, content_id=content_id))

    def metadata(self):
        return dict(complete=not self.issues, requests_used=self.requests, issues=self.issues,
                    retrieved_at=min((row['retrieved_at'] for row in self.freshness), default=datetime.now(timezone.utc)),
                    from_cache=bool(self.freshness) and all(row['from_cache'] for row in self.freshness),
                    cache_age_seconds=max((row['cache_age_seconds'] for row in self.freshness), default=0))


async def pages(scan, function, field, *args, refresh=False, **kwargs):
    offset = 0
    while True:
        result = await scan.call(function, *args, limit=100, offset=offset, refresh=refresh, **kwargs)
        for row in getattr(result, field):
            yield row
        if result.next_offset is None:
            return
        if result.next_offset <= offset:
            raise LearnError('NTULearn returned a pagination loop.')
        offset = result.next_offset


async def course_ids(client, scan, selected, refresh=False):
    if selected is not None:
        if not selected or len(selected) > 100:
            raise LearnError('Select between 1 and 100 course IDs, or omit course_ids.')
        return list(dict.fromkeys(identifier(value) for value in selected))
    result = []
    async for course in pages(scan, client.list_courses, 'courses', refresh=refresh):
        if course.available != 'No' and course.organization is not True:
            result.append(course.id)
    return result


def aware(value, name):
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None):
        raise LearnError(f'{name} must include a timezone.')
    return value

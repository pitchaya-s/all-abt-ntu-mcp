import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ntulearn.services.overview import whats_new


class ConcurrentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_course_digest_uses_bounded_fanout_and_request_budget(self):
        class Client:
            def __init__(self):
                self.active = 0
                self.maximum_active = 0

            async def _delayed(self):
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                await asyncio.sleep(0.01)
                self.active -= 1

            async def get_calendar(self, *args, **kwargs):
                return SimpleNamespace(
                    items=[], next_offset=None,
                    retrieved_at=datetime.now(timezone.utc),
                    from_cache=False, cache_age_seconds=0,
                )

            async def get_announcements(self, course_id, **kwargs):
                await self._delayed()
                return SimpleNamespace(
                    announcements=[], next_offset=None,
                    retrieved_at=datetime.now(timezone.utc),
                    from_cache=False, cache_age_seconds=0,
                )

            async def get_gradebook(self, course_id, **kwargs):
                await self._delayed()
                return SimpleNamespace(
                    columns=[], grades=[], next_offset=None, grades_next_offset=None,
                    retrieved_at=datetime.now(timezone.utc),
                    from_cache=False, cache_age_seconds=0,
                )

        client = Client()
        now = datetime.now(timezone.utc)
        selected = [f"_{number}_1" for number in range(1, 9)]
        result = await whats_new(
            client,
            since=now - timedelta(days=1),
            until=now + timedelta(days=14),
            selected=selected,
            max_requests=40,
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.requests_used, 33)
        self.assertEqual(client.maximum_active, 4)

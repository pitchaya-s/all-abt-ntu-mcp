import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from ntulearn.client.client import LearnClient
from ntulearn.models import LearnError
from ntulearn.parser.response import records, text

from .fixtures import CONTENT, COURSE, NOW, PREFIX, SECRET, USER, FixtureSession


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    async def test_courses_preserve_organizations_availability_and_pagination(self):
        first = await self.client.list_courses(limit=1)
        self.assertEqual(first.courses[0].id, COURSE)
        self.assertEqual(first.next_offset, 1)
        last = await self.client.list_courses(limit=1, offset=1)
        self.assertTrue(last.courses[0].organization)
        self.assertEqual(last.courses[0].available, "No")
        self.assertIsNone(last.next_offset)
        self.assertNotIn(SECRET, first.model_dump_json())
        self.assertNotIn(USER, first.model_dump_json())

    async def test_content_folders_body_and_announcements(self):
        root = await self.client.get_course_contents(COURSE)
        self.assertTrue(root.contents[0].has_children)
        self.assertEqual(root.contents[1].body, "Hello & welcome")
        self.assertIsNone(root.contents[1].has_children)
        children = await self.client.get_course_contents(COURSE, CONTENT)
        self.assertEqual(children.contents[0].parent_id, CONTENT)
        self.assertEqual((await self.client.get_announcements(COURSE)).announcements[0].body, "Bring your laptop.")
        self.assertEqual(text("<style>secret</style><p>a</p><p>b</p>"), "a\nb")

    async def test_grades_are_own_only_and_missing_is_not_zero(self):
        with patch.object(self.session, "get", wraps=self.session.get) as get:
            result = await self.client.get_gradebook(COURSE)
        self.assertIsNone(result.grades[0].score)
        self.assertEqual(result.grades[1].score, 0.0)
        self.assertEqual(result.grades[1].feedback, "Example feedback")
        self.assertEqual(result.columns[0].possible_score, 10.0)
        self.assertNotIn(USER, result.model_dump_json())
        self.assertTrue(any(call.args[0].endswith("/gradebook/users/" + USER) for call in get.await_args_list))

    async def test_gradebook_user_lookup_is_shared_and_resets_with_auth_generation(self):
        user_reads = 0
        original_get = self.session.get

        async def tracked_get(path, *args, **kwargs):
            nonlocal user_reads
            if path.endswith("/users/me"):
                user_reads += 1
                await asyncio.sleep(0.01)
            return await original_get(path, *args, **kwargs)

        self.session.get = tracked_get
        await asyncio.gather(
            self.client.get_gradebook(COURSE, refresh=True),
            self.client.get_gradebook(COURSE, refresh=True),
        )
        self.assertEqual(user_reads, 1)
        self.session.auth.generation += 1
        await self.client.get_gradebook(COURSE, refresh=True)
        self.assertEqual(user_reads, 2)

    async def test_calendar_windows_and_partial_errors(self):
        result = await self.client.get_calendar(since=NOW, until=NOW + timedelta(days=14))
        self.assertEqual(result.items[0].course_id, COURSE)
        for start, end in [(datetime(2026, 1, 1), NOW), (NOW, NOW), (NOW, NOW + timedelta(days=113))]:
            with self.assertRaises(LearnError):
                await self.client.get_calendar(since=start, until=end)
        with patch.object(self.session, "get", return_value=({"results": [], "courseErrors": [{}]}, {})):
            with self.assertRaisesRegex(LearnError, "part of this request"):
                await self.client.get_calendar()

    async def test_invalid_ids_and_pagination_never_reach_network(self):
        self.session.get = Mock()
        for value in ["../users", "https://other.invalid", "_1_1?x=1", "", "A" * 81]:
            with self.assertRaises(LearnError):
                await self.client.get_course_contents(value)
        for limit, offset in [(0, 0), (101, 0), (True, 0), (10, -1)]:
            with self.assertRaises(LearnError):
                await self.client.list_courses(limit=limit, offset=offset)
        self.session.get.assert_not_called()

    async def test_unexpected_json_and_unsafe_pagination_fail_closed(self):
        path = PREFIX + "/users/me/courses"
        for value in [{}, {"results": {}}, {"results": ["changed"]}, {"results": [], "paging": {"nextPage": "https://other.invalid/steal?offset=2"}},
                      {"results": [], "paging": {"nextPage": "/learn/api/public/v1/users/me?offset=2"}},
                      {"results": [], "paging": {"nextPage": path + "?offset=no"}}]:
            with self.subTest(value=value), self.assertRaises(LearnError):
                records(value, path)
        with patch.object(self.session, "get", return_value=({"results": [{"course": {"id": COURSE}}]}, {})):
            with self.assertRaises(LearnError):
                await self.client.list_courses()
        with patch.object(self.session, "get", return_value=({"results": [], "paging": {"nextPage": path + "?offset=0"}}, {})):
            with self.assertRaisesRegex(LearnError, "pagination loop"):
                await self.client.list_courses()

    async def test_attachments_preserve_file_metadata(self):
        result = await self.client.get_content_attachments(COURSE, "_202_1")
        self.assertEqual(result.attachments[0].file_name, "example.pdf")
        self.assertEqual(result.attachments[0].mime_type, "application/pdf")

from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock, patch

from ntulearn_mcp.client import LearnClient
from ntulearn_mcp.models import LearnError
from ntulearn_mcp.normalize import records, text
from .fixtures import COURSE, CONTENT, FixtureSession, NOW, PREFIX, SECRET, USER


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    def test_courses_preserve_organizations_availability_and_pagination(self):
        first = self.client.list_courses(limit=1)
        self.assertEqual(first.courses[0].id, COURSE)
        self.assertEqual(first.next_offset, 1)
        last = self.client.list_courses(limit=1, offset=1)
        self.assertTrue(last.courses[0].organization)
        self.assertEqual(last.courses[0].available, "No")
        self.assertIsNone(last.next_offset)
        self.assertNotIn(SECRET, first.model_dump_json())
        self.assertNotIn(USER, first.model_dump_json())

    def test_content_folders_body_and_announcements(self):
        root = self.client.get_course_contents(COURSE)
        self.assertTrue(root.contents[0].has_children)
        self.assertEqual(root.contents[1].body, "Hello & welcome")
        self.assertIsNone(root.contents[1].has_children)
        children = self.client.get_course_contents(COURSE, CONTENT)
        self.assertEqual(children.contents[0].parent_id, CONTENT)
        self.assertEqual(self.client.get_announcements(COURSE).announcements[0].body, "Bring your laptop.")
        self.assertEqual(text("<style>secret</style><p>a</p><p>b</p>"), "a\nb")

    def test_grades_are_own_only_and_missing_is_not_zero(self):
        with patch.object(self.session, "get", wraps=self.session.get) as get:
            result = self.client.get_gradebook(COURSE)
        self.assertIsNone(result.grades[0].score)
        self.assertEqual(result.grades[1].score, 0.0)
        self.assertEqual(result.grades[1].feedback, "Example feedback")
        self.assertEqual(result.columns[0].possible_score, 10.0)
        self.assertNotIn(USER, result.model_dump_json())
        self.assertTrue(any(call.args[0].endswith("/gradebook/users/" + USER) for call in get.call_args_list))

    def test_calendar_windows_and_partial_errors(self):
        result = self.client.get_calendar(since=NOW, until=NOW + timedelta(days=14))
        self.assertEqual(result.items[0].course_id, COURSE)
        for start, end in [(datetime(2026, 1, 1), NOW), (NOW, NOW), (NOW, NOW + timedelta(days=113))]:
            with self.assertRaises(LearnError):
                self.client.get_calendar(since=start, until=end)
        with patch.object(self.session, "get", return_value=({"results": [], "courseErrors": [{}]}, {})):
            with self.assertRaisesRegex(LearnError, "part of this request"):
                self.client.get_calendar()

    def test_invalid_ids_and_pagination_never_reach_network(self):
        self.session.get = Mock()
        for value in ["../users", "https://other.invalid", "_1_1?x=1", "", "A" * 81]:
            with self.assertRaises(LearnError):
                self.client.get_course_contents(value)
        for limit, offset in [(0, 0), (101, 0), (True, 0), (10, -1)]:
            with self.assertRaises(LearnError):
                self.client.list_courses(limit=limit, offset=offset)
        self.session.get.assert_not_called()

    def test_unexpected_json_and_unsafe_pagination_fail_closed(self):
        path = PREFIX + "/users/me/courses"
        for value in [{}, {"results": {}}, {"results": ["changed"]}, {"results": [], "paging": {"nextPage": "https://other.invalid/steal?offset=2"}},
                      {"results": [], "paging": {"nextPage": "/learn/api/public/v1/users/me?offset=2"}},
                      {"results": [], "paging": {"nextPage": path + "?offset=no"}}]:
            with self.subTest(value=value), self.assertRaises(LearnError):
                records(value, path)
        with patch.object(self.session, "get", return_value=({"results": [{"course": {"id": COURSE}}]}, {})):
            with self.assertRaises(LearnError):
                self.client.list_courses()
        with patch.object(self.session, "get", return_value=({"results": [], "paging": {"nextPage": path + "?offset=0"}}, {})):
            with self.assertRaisesRegex(LearnError, "pagination loop"):
                self.client.list_courses()

    def test_attachments_preserve_file_metadata(self):
        result = self.client.get_content_attachments(COURSE, "_202_1")
        self.assertEqual(result.attachments[0].file_name, "example.pdf")
        self.assertEqual(result.attachments[0].mime_type, "application/pdf")

import unittest
from unittest.mock import patch

from ntulearn.client.client import LearnClient
from ntulearn.services import people

from .fixtures import COURSE, SECRET, FixtureSession


class PeopleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    async def test_users_groups_and_group_members_are_typed_and_private(self):
        users = await people.list_course_users(self.client, COURSE, limit=1)
        self.assertEqual(users.users[0].name, 'Example Student')
        self.assertEqual(users.next_offset, 1)
        self.assertNotIn(SECRET, users.model_dump_json())
        groups = await people.list_course_groups(self.client, COURSE)
        self.assertIsNone(groups.groups[0].available)
        self.assertEqual(groups.groups[0].description, 'Example tutorial')
        with patch.object(self.session, 'get', wraps=self.session.get) as get:
            members = await people.get_group_members(self.client, COURSE, '_600_1')
        self.assertEqual(members.users[0].role, 'Student')
        self.assertEqual(get.await_args.args[1]['groupId'], '_600_1')

import unittest
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from ntulearn.client.client import LearnClient
from ntulearn.models import LearnError
from ntulearn.services import messages

from .fixtures import COURSE, NOW, RESPONSES, SECRET, USER, FixtureSession


class MessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    async def test_mailbox_inbox_sent_and_read_with_published_recipients(self):
        result = await messages.list_messages(self.client)
        self.assertTrue(result.complete)
        self.assertEqual([row.id for row in result.messages], ['_801_1'])
        self.assertEqual([row.id for row in (await messages.list_messages(self.client, folder='sent')).messages], ['_802_1'])
        self.assertEqual(len((await messages.list_messages(self.client, unread_only=True)).messages), 1)
        self.assertEqual((await messages.list_messages(self.client, since=NOW + timedelta(seconds=1))).messages, [])
        for scope in ({}, {'course_id': COURSE, 'conversation_id': '_800_1'}):
            result = await messages.read_message(self.client, '_801_1', **scope)
            self.assertEqual(result.body, 'Full example message')
            self.assertEqual(result.recipients[0].id, USER)
            self.assertEqual(result.recipients_scope, 'conversation_participants')
            self.assertFalse(result.message.read)
            self.assertNotIn(SECRET, result.model_dump_json())

    async def test_mailbox_budget_partial_conversations_and_unknown_read_status(self):
        self.assertFalse((await messages.list_messages(self.client, max_requests=1)).complete)
        path = f'/learn/api/v1/courses/{COURSE}/conversations'
        preview = deepcopy(RESPONSES[path])
        preview['results'][0]['messages'] = preview['results'][0]['messages'][:1]
        with patch.dict(RESPONSES, {path: preview}):
            self.assertEqual(len((await messages.list_messages(self.client, folder='sent')).messages), 1)
            detail_path = f'/learn/api/v1/courses/{COURSE}/conversations/_800_1'
            with patch.dict(RESPONSES, {detail_path: preview['results'][0]}):
                partial = await messages.list_messages(self.client)
                self.assertFalse(partial.complete)
                self.assertEqual(partial.messages[0].id, '_801_1')
                self.assertEqual((await messages.read_message(self.client, '_801_1', COURSE, '_800_1')).body, 'Full example message')
        with self.assertRaises(LearnError):
            await messages.read_message(self.client, '_801_1', course_id=COURSE)
        with self.assertRaises(LearnError):
            await messages.read_message(self.client, '_missing_1')
        self.assertIsNone((await messages.list_messages(self.client, folder='sent')).messages[0].read)

    async def test_non_advancing_mailbox_cursors_keep_unique_rows_and_stop_safely(self):
        for loop_path in (
            '/learn/api/v1/messages/summary',
            f'/learn/api/v1/courses/{COURSE}/conversations',
        ):
            class RepeatingCursorSession(FixtureSession):
                def __init__(self):
                    super().__init__()
                    self.offsets = []

                async def get(self, path, params=None, refresh=False):
                    params = params or {}
                    if path == loop_path:
                        self.offsets.append(params.get('offset', 0))
                    data, freshness = await super().get(path, params, refresh)
                    if path == loop_path and params.get('offset', 0) == 0:
                        data['paging'] = {'nextPage': f'{path}?limit=100&offset=0'}
                    return data, freshness

            session = RepeatingCursorSession()
            result = await messages.list_messages(LearnClient(session))
            self.assertEqual([row.id for row in result.messages], ['_801_1'])
            self.assertFalse(result.complete)
            self.assertIn('non-advancing mailbox cursor', result.issues[0].message)
            self.assertEqual(session.offsets, [0, 1])

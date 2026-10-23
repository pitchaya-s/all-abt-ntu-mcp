from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch


from ntulearn.services import messages
from ntulearn.client.client import LearnClient
from ntulearn.models import LearnError
from .fixtures import COURSE, FixtureSession, NOW, RESPONSES, SECRET, USER


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    def test_mailbox_inbox_sent_and_read_with_published_recipients(self):
        result = messages.list_messages(self.client)
        self.assertTrue(result.complete)
        self.assertEqual([row.id for row in result.messages], ['_801_1'])
        self.assertEqual([row.id for row in messages.list_messages(self.client, folder='sent').messages], ['_802_1'])
        self.assertEqual(len(messages.list_messages(self.client, unread_only=True).messages), 1)
        self.assertEqual(messages.list_messages(self.client, since=NOW + timedelta(seconds=1)).messages, [])
        for scope in ({}, {'course_id': COURSE, 'conversation_id': '_800_1'}):
            result = messages.read_message(self.client, '_801_1', **scope)
            self.assertEqual(result.body, 'Full example message')
            self.assertEqual(result.recipients[0].id, USER)
            self.assertEqual(result.recipients_scope, 'conversation_participants')
            self.assertFalse(result.message.read)
            self.assertNotIn(SECRET, result.model_dump_json())

    def test_mailbox_budget_partial_conversations_and_unknown_read_status(self):
        self.assertFalse(messages.list_messages(self.client, max_requests=1).complete)
        path = f'/learn/api/v1/courses/{COURSE}/conversations'
        preview = deepcopy(RESPONSES[path])
        preview['results'][0]['messages'] = preview['results'][0]['messages'][:1]
        with patch.dict(RESPONSES, {path: preview}):
            self.assertEqual(len(messages.list_messages(self.client, folder='sent').messages), 1)
            detail_path = f'/learn/api/v1/courses/{COURSE}/conversations/_800_1'
            with patch.dict(RESPONSES, {detail_path: preview['results'][0]}):
                partial = messages.list_messages(self.client)
                self.assertFalse(partial.complete)
                self.assertEqual(partial.messages[0].id, '_801_1')
                self.assertEqual(messages.read_message(self.client, '_801_1', COURSE, '_800_1').body, 'Full example message')
        with self.assertRaises(LearnError):
            messages.read_message(self.client, '_801_1', course_id=COURSE)
        with self.assertRaises(LearnError):
            messages.read_message(self.client, '_missing_1')
        self.assertIsNone(messages.list_messages(self.client, folder='sent').messages[0].read)

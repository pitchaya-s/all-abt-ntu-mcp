import unittest
from datetime import timedelta
from unittest.mock import patch

from ntulearn.client.client import LearnClient
from ntulearn.models import LearnError
from ntulearn.services import overview

from .fixtures import COURSE, NOW, FixtureSession


class OverviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    async def test_upcoming_pagination_filter_and_digest_unknown_change_times(self):
        result = await overview.get_upcoming(self.client, NOW, NOW + timedelta(days=1), [COURSE], 'GradebookColumn')
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 1)
        with patch('ntulearn.services.overview.datetime') as clock:
            clock.now.return_value = NOW
            result = await overview.whats_new(self.client, since=NOW - timedelta(days=1), selected=[COURSE])
        self.assertTrue(result.complete)
        self.assertEqual(len(result.announcements), 1)
        self.assertTrue(result.announcements[0].changed_since)
        self.assertTrue(all(item.changed_since is None for item in result.grades))
        with self.assertRaises(LearnError):
                await overview.get_upcoming(self.client, NOW.replace(tzinfo=None))
        self.assertFalse((await overview.whats_new(self.client, selected=[COURSE], max_requests=1)).complete)

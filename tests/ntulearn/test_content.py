import unittest
from unittest.mock import patch


from ntulearn.services import content
from ntulearn.client.client import LearnClient
from ntulearn.models import LearnError
from .fixtures import CONTENT, COURSE, FixtureSession, PREFIX, RESPONSES


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    def test_tree_depth_node_budget_and_cycles_are_explicit(self):
        result = content.get_content_tree(self.client, COURSE)
        self.assertTrue(result.complete)
        self.assertEqual(result.contents[0].children[0].id, '_202_1')
        self.assertTrue(result.contents[0].children_complete)
        for kwargs in ({'max_depth': 1}, {'max_nodes': 1}, {'max_requests': 1}):
            result = content.get_content_tree(self.client, COURSE, **kwargs)
            self.assertFalse(result.complete)
            self.assertTrue(result.issues)
            self.assertLessEqual(result.requests_used, kwargs.get('max_requests', 100))
        path = f'{PREFIX}/courses/{COURSE}/contents/{CONTENT}/children'
        cycle = {'results': [{'id': CONTENT, 'title': 'Cycle', 'hasChildren': True}]}
        with patch.dict(RESPONSES, {path: cycle}):
            result = content.get_content_tree(self.client, COURSE)
            self.assertFalse(result.complete)
            self.assertIn('cyclic', result.issues[0].message)

    def test_search_recurses_with_breadcrumbs_and_global_limits(self):
        result = content.search(self.client, 'SLIDES', [COURSE])
        self.assertTrue(result.complete)
        self.assertEqual(result.matches[0].breadcrumb, ['Week 1', 'Example slides'])
        self.assertEqual(result.matches[0].course_id, COURSE)
        result = content.search(self.client, 'hello', None)
        self.assertEqual(result.courses_searched, [COURSE])
        self.assertEqual(result.matches[0].content_id, '_201_1')
        self.assertFalse(content.search(self.client, 'e', [COURSE], max_results=1).complete)
        for query in ('', ' ', 'x' * 201):
            with self.assertRaises(LearnError):
                content.search(self.client, query, [COURSE])

    def test_denied_child_retains_other_content_and_reports_partial(self):
        original = self.client.get_course_contents
        def lookup(course_id, parent_id=None, **kwargs):
            if parent_id:
                raise LearnError('NTULearn denied access (HTTP 403).')
            return original(course_id, parent_id, **kwargs)
        with patch.object(self.client, 'get_course_contents', side_effect=lookup):
            result = content.get_content_tree(self.client, COURSE)
        self.assertFalse(result.complete)
        self.assertEqual(len(result.contents), 2)
        self.assertFalse(result.contents[0].children_complete)
        self.assertIn('403', result.issues[0].message)

import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mcp.server.mcpserver.exceptions import ToolError

from faculty import mcp_server, parser
from faculty.client import API, DIRECTORY, FacultyClient
from faculty.models import FacultyError
from shared.public_http import PublicRequestError

from .fixtures import INTEREST_ID, OPTIONS, OTHER_ID, PROFILE, fake_get


class FacultyTests(unittest.TestCase):
    def setUp(self):
        self.client = FacultyClient()
        self.fetch = patch.object(self.client.http, "get", side_effect=fake_get).start()
        self.addCleanup(patch.stopall)

    def test_normalization_preserves_unicode_and_distinguishes_missing_fields(self):
        result = self.client.search("Example")
        person = result.profiles[0]
        self.assertEqual(person.name, "Assoc Prof Example Éclair")
        self.assertEqual(person.school, "School of Example & Testing")
        self.assertEqual(person.appointments, ["Associate Professor, Example School", "Director, Example Centre"])
        self.assertEqual(person.interests, ["Artificial & Augmented Intelligence", "Testing"])
        self.assertEqual(person.summary, "A fictional profile & biography ...")
        absent = parser.profile({"title": "Example", "url": PROFILE["url"]})
        self.assertIsNone(absent.email)
        self.assertIsNone(absent.interests)
        self.assertIsNone(absent.appointments)
        empty = parser.profile({**PROFILE, "interests": "", "appointments": ""})
        self.assertEqual(empty.interests, [])
        self.assertEqual(empty.appointments, [])

    def test_pagination_and_empty_search(self):
        first = self.client.search()
        second = self.client.search(page=first.next_page)
        self.assertEqual(first.total_count, 11)
        self.assertEqual(len(first.profiles), 10)
        self.assertEqual(len(second.profiles), 1)
        self.assertIsNone(second.next_page)
        self.assertFalse({p.profile_url for p in first.profiles} & {p.profile_url for p in second.profiles})
        empty = self.client.search("no matches")
        self.assertEqual(empty.total_count, 0)
        self.assertIsNone(empty.next_page)
        with self.assertRaisesRegex(FacultyError, "Page exceeds"):
            self.client.search(page=3)
        self.assertEqual(parse_qs(urlsplit(self.fetch.call_args.args[0]).query)["page"], ["3"])

    def test_interest_discovery_deduplication_and_filtering(self):
        result = self.client.list_interests(limit=1)
        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.interests[0].interest_id, INTEREST_ID)
        second = self.client.list_interests(limit=1, offset=result.next_offset)
        self.assertEqual(second.interests[0].interest_id, OTHER_ID)
        self.assertIsNone(second.next_offset)
        self.assertEqual(self.client.list_interests("INTELLIGENCE").total_count, 1)
        self.assertEqual(self.client.list_interests("not an interest").interests, [])
        filtered = self.client.search(interest_id=INTEREST_ID, refresh=True)
        self.assertEqual(filtered.total_count, 1)
        url, refresh = self.fetch.call_args.args
        self.assertTrue(refresh)
        self.assertEqual(parse_qs(urlsplit(url).query)["interests"], [INTEREST_ID])

    def test_inputs_are_validated_before_search_requests(self):
        for args in [dict(query="bad\nquery"), dict(query="x" * 201), dict(page=True), dict(page=0),
                     dict(interest_id="not an ID"), dict(interest_id="33333333-3333-4333-8333-333333333333")]:
            with self.subTest(args=args), self.assertRaises(FacultyError):
                self.client.search(**args)
        self.assertTrue(all(call.args[0] == DIRECTORY for call in self.fetch.call_args_list))

    def test_query_is_encoded_without_injecting_parameters(self):
        query = "Example & page=9 + É"
        self.client.search(query)
        params = parse_qs(urlsplit(self.fetch.call_args.args[0]).query)
        self.assertEqual(params["searchFaculty"], [query])
        self.assertEqual(params["page"], ["1"])

    def test_changed_or_partial_responses_fail_without_inventing_profiles(self):
        good = {"items": [PROFILE], "totalItems": 1, "totalPages": 1}
        _, snapshot = fake_get(DIRECTORY)
        cases = [b"<html>Service down</html>", b"{}", b"[]", b'{"items":{},"totalItems":0,"totalPages":0}']
        for update in [{"totalItems": "1"}, {"totalPages": 2}, {"totalItems": 20}, {"items": []},
                       {"items": [PROFILE, PROFILE], "totalItems": 2},
                       {"items": [{**PROFILE, "title": None}]},
                       {"items": [{**PROFILE, "url": "javascript:alert(1)"}]},
                       {"items": [{**PROFILE, "url": "https://evil.example/person"}]}]:
            cases.append(json.dumps({**deepcopy(good), **update}).encode())
        for body in cases:
            with self.subTest(body=body[:120]), self.assertRaises((FacultyError, KeyError, TypeError, ValueError)):
                parser.search_results(body, snapshot, 1)
        for body in [b"<html><body>Unavailable</body></html>", OPTIONS.replace(b"</html>", b""),
                     OPTIONS.replace(b'<label for="energy">Energy</label>', b""),
                     OPTIONS.replace(b'for="mobile">Artificial &amp; Augmented Intelligence', b'for="mobile">Conflicting')]:
            with self.assertRaises(FacultyError):
                parser.interest_options(body)

    def test_shared_cache_refresh_and_failure_handling(self):
        client = FacultyClient()
        url = API + "?interests=all&page=1&searchFaculty=Example"
        body, _ = fake_get(url)
        with patch.object(client.http, "_fetch", return_value=(body, datetime.now(timezone.utc))) as fetch:
            self.assertFalse(client.search("Example").cached)
            self.assertTrue(client.search("Example").cached)
            self.assertFalse(client.search("Example", refresh=True).cached)
            self.assertEqual(fetch.call_count, 2)
        for error in (PublicRequestError("NTU faculty directory returned HTTP 503; try again later."), KeyError("raw provider detail")):
            with patch.object(mcp_server.client, "search", side_effect=error), self.assertRaises(ToolError) as caught:
                mcp_server.search()
            self.assertNotIn("raw provider detail", str(caught.exception))

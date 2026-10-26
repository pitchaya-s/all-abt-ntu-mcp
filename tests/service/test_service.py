import json
import unittest
from datetime import datetime, timezone
from threading import Barrier, Lock
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mcp.server.mcpserver.exceptions import ToolError

from service import mcp_server, parser
from service.client import ServiceClient
from service.models import ServiceError
from shared.public_http import PublicRequestError

from .fixtures import CATEGORY_ID, FORM, ROWS, TYPE_ID, fake_get


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = ServiceClient()
        self.fetch = patch.object(self.client.http, "get", side_effect=fake_get).start()
        self.addCleanup(patch.stopall)

    def test_keyword_search_covers_later_pages_and_location_filter(self):
        result = self.client.search("clinic")
        self.assertEqual((result.total_count, result.directory_count, result.pages_checked), (1, 13, 2))
        self.assertEqual(result.locations[0].name, "Synthetic Café Clinic")
        self.assertEqual(result.locations[0].phone, "0000 0000")
        self.assertEqual(result.locations[0].email, "clinic@example.org")
        self.assertEqual(len(self.client.search(location_contains="SOUTH SPINE").locations), 1)
        self.assertEqual(self.client.search("clinic", location_contains="North").locations, [])
        self.assertFalse(result.cached)
        self.assertEqual(result.retrieved_at, datetime(2025, 12, 31, 23, 59, 30, tzinfo=timezone.utc))

    def test_result_pagination_and_blank_contact_fields(self):
        first = self.client.search(limit=12)
        second = self.client.search(limit=12, offset=first.next_offset)
        self.assertEqual(len(first.locations), 12)
        self.assertEqual(len(second.locations), 1)
        self.assertIsNone(second.next_offset)
        self.assertIsNone(first.locations[0].phone)
        self.assertIsNone(first.locations[0].fax)
        self.assertIn("Closed on holidays", first.locations[0].operating_hours)

    def test_directory_pages_fetch_concurrently_and_preserve_page_order(self):
        barrier = Barrier(2)
        lock = Lock()
        active = 0
        maximum_active = 0

        def read_page(url, refresh=False):
            nonlocal active, maximum_active
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            if page > 1:
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    barrier.wait(timeout=2)
                finally:
                    with lock:
                        active -= 1
            items = [
                {**ROWS[index % len(ROWS)], "title": f"Synthetic location {index}",
                 "location": f"Building {index}", "mapUrl": f"https://maps.ntu.edu.sg/?place={index}"}
                for index in range((page - 1) * 12, page * 12)
            ]
            snapshot = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=url, cached=True)
            return json.dumps({"items": items, "totalItems": 36, "totalPages": 3}).encode(), snapshot

        with patch.object(self.client.http, "get", side_effect=read_page):
            result = self.client.search(limit=100)
        self.assertEqual(maximum_active, 2)
        self.assertEqual([item.name for item in result.locations[:3]], [
            "Synthetic location 0", "Synthetic location 1", "Synthetic location 2",
        ])
        self.assertEqual(result.pages_checked, 3)

    def test_source_filters_can_return_empty_without_hiding_unfiltered_matches(self):
        filters = self.client.list_filters()
        self.assertEqual(filters.types[0].name, "Food & Beverage")
        self.assertEqual(self.client.search(type_id=TYPE_ID).directory_count, 2)
        result = self.client.search(category_id=CATEGORY_ID)
        self.assertEqual(result.directory_count, 0)
        self.assertEqual(result.pages_checked, 1)
        self.assertEqual(self.client.search("clinic").total_count, 1)

    def test_changed_or_partial_directory_is_not_reported_complete(self):
        def changed(url, refresh=False):
            body, snapshot = fake_get(url, refresh)
            if "page=2" in url:
                data = json.loads(body)
                data.update(totalItems=14, items=[ROWS[-1], {**ROWS[-1], "title": "Another"}])
                body = json.dumps(data).encode()
            return body, snapshot
        with patch.object(self.client.http, "get", side_effect=changed), self.assertRaisesRegex(ServiceError, "changed"):
            self.client.search()
        body = json.dumps({"items": ROWS[:12], "totalItems": 601, "totalPages": 51}).encode()
        with patch.object(self.client.http, "get", return_value=(body, {})), self.assertRaisesRegex(ServiceError, "50-page"):
            self.client.search()
        for rows in [[{**ROWS[0], "title": None}], [{**ROWS[0], "mapUrl": "javascript:alert(1)"}], [ROWS[0], ROWS[0]]]:
            body = json.dumps({"items": rows, "totalItems": len(rows), "totalPages": 1}).encode()
            with self.assertRaises((ValueError, TypeError, ServiceError)):
                parser.locations(body, 1)
        with self.assertRaises(ValueError):
            parser.locations(b"<html>Maintenance</html>", 1)

    def test_refresh_invalid_inputs_and_errors(self):
        self.client.search(refresh=True)
        self.assertTrue(all(call.args[1] for call in self.fetch.call_args_list))
        for args in [dict(limit=True), dict(offset=-1), dict(query="bad\nquery"), dict(location_contains="x" * 201),
                     dict(type_id="33333333-3333-4333-8333-333333333333")]:
            with self.assertRaises((ServiceError, ValueError)):
                self.client.search(**args)
        for error in (PublicRequestError("NTU returned HTTP 503; try again later."), KeyError("raw provider detail")):
            with patch.object(mcp_server.client, "search", side_effect=error), self.assertRaises(ToolError) as caught:
                mcp_server.search()
            self.assertNotIn("raw provider detail", str(caught.exception))
        with patch.object(self.client.http, "get", return_value=(FORM.replace(b"</html>", b""), {})), self.assertRaises(ValueError):
            self.client.list_filters()

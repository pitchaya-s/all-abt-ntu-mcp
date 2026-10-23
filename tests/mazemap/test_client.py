from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from mcp.server.mcpserver.exceptions import ToolError

from mazemap.client import API, MapClient
from mazemap.mcp_server import _call
from mazemap.models import MapError
from mazemap import parser
from .fixtures import COLLECTION, POI, ROUTING, SEARCH_POI, fake_get


class ParserTests(unittest.TestCase):
    def test_search_and_detail_agree_with_aliases_entities_and_basements(self):
        detail, search = parser.place(POI), parser.place(SEARCH_POI)
        self.assertEqual(detail.name, search.name)
        self.assertEqual(detail.aliases, ["TR+7"])
        self.assertEqual(detail.description, "A & B")
        self.assertEqual(search.floor_name, "B1")
        self.assertEqual(search.level, -1)
        self.assertEqual(search.building_name, "Example Building")
        self.assertEqual(search.categories, ["Tutorial Room"])
        self.assertEqual(detail.capacity, 0)
        self.assertNotIn("<em>", search.model_dump_json())

    def test_zero_floor_and_absent_fields_are_preserved(self):
        place = parser.place({"poiId": 1, "campusId": 2123, "title": "Ground", "z": 0, "zValue": 9})
        self.assertEqual(place.level, 0)
        self.assertIsNone(place.point)
        self.assertIsNone(place.capacity)

    def test_route_uses_basic_distances_and_provider_duration(self):
        result = parser.route(ROUTING["routes"][0])
        self.assertAlmostEqual(result.distance_metres, 8.3)
        self.assertEqual(result.duration_seconds, 22)
        self.assertTrue(result.accessible)
        self.assertFalse(result.uncertain)
        self.assertEqual(result.instructions, ["Walk forward.", "Turn left."])

    def test_missing_route_information_is_unknown_and_partial_directions_are_explicit(self):
        data = deepcopy(ROUTING["routes"][0])
        data["legs"].append({"basic": {"steps": [{"properties": {}}]}, "instructions": None})
        result = parser.route(data)
        self.assertIsNone(result.distance_metres)
        self.assertIsNone(result.accessible)
        self.assertIsNone(result.uncertain)
        self.assertIsNone(result.instructions)
        self.assertTrue(result.issues)

    def test_bad_shapes_and_deleted_places_fail_instead_of_inventing_data(self):
        cases = [(parser.place, {**POI, "deleted": True}), (parser.place, {"poiId": 1}),
                 (parser.place, {**POI, "point": {"type": "Point", "coordinates": [1000, 500]}}),
                 (parser.route, {"legs": []}), (parser.route, {"legs": [{"basic": {"steps": []}}]})]
        for function, data in cases:
            with self.subTest(function=function.__name__, data=data), self.assertRaises(ToolError):
                _call(function, data)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = MapClient()

    def test_search_pagination_uses_extra_match_without_claiming_total_coverage(self):
        with patch.object(self.client, "_get", side_effect=fake_get) as get:
            first = self.client.search_places(" TR+7 ", limit=1)
            second = self.client.search_places("TR+7", limit=1, offset=first.next_offset)
        self.assertEqual(first.places[0].poi_id, 1001)
        self.assertEqual(first.next_offset, 1)
        self.assertEqual(second.places[0].poi_id, 1002)
        self.assertIsNone(second.next_offset)
        self.assertEqual(get.call_args_list[0].args[2]["rows"], 2)

    def test_campuses_buildings_place_and_directions(self):
        with patch.object(self.client, "_get", side_effect=fake_get):
            self.assertEqual(self.client.list_campuses().campuses[0].campus_id, 2123)
            self.assertEqual(self.client.list_buildings(query="example").buildings[0].floors[1].level, 0)
            self.assertEqual(self.client.list_buildings(query="missing").buildings, [])
            self.assertEqual(self.client.get_place(1001).place.identifier, "EX-B1-07")
            self.assertEqual(self.client.get_directions(1001, 1002).routes[0].duration_seconds, 22)

    def test_invalid_scope_blank_query_and_mismatched_ids(self):
        with patch.object(self.client, "_get", side_effect=fake_get):
            for function, args in [(self.client.list_buildings, (9999,)), (self.client.search_places, (" ",)),
                                   (self.client.list_buildings, (2123, " "))]:
                with self.assertRaises(MapError):
                    function(*args)
        for value in [{**POI, "poiId": 999}, {**POI, "campusId": 999}]:
            def wrong_place(base, path, parameters, refresh=False):
                data, metadata = fake_get(base, path, parameters, refresh)
                return (value if "/pois/" in path else data), metadata
            with patch.object(self.client, "_get", side_effect=wrong_place), self.assertRaises(MapError):
                self.client.get_place(1001)

    def test_empty_routes_and_unsupported_formats_fail_clearly(self):
        for change in [{"routes": []}, {"version": "3"}, {"properties": {"units": "imperial", "mode": "PEDESTRIAN"}},
                       {"properties": {"units": "metric", "mode": "DRIVE"}}]:
            def bad_route(base, path, parameters, refresh=False):
                data, metadata = fake_get(base, path, parameters, refresh)
                return ({**data, **change} if "/routing/" in path else data), metadata
            with patch.object(self.client, "_get", side_effect=bad_route), self.assertRaises(MapError):
                self.client.get_directions(1001, 1002)

    def response(self, data=COLLECTION, content_type="application/json"):
        result = BytesIO(json.dumps(data).encode())
        result.headers = Message()
        result.headers["Content-Type"] = content_type
        return result

    def test_cache_refresh_expiry_and_no_cookie_headers(self):
        with patch("mazemap.client.urlopen", side_effect=lambda *a, **k: self.response()) as fetch, patch("mazemap.client.time.sleep"):
            self.assertFalse(self.client.list_campuses().cached)
            self.assertTrue(self.client.list_campuses().cached)
            self.assertFalse(self.client.list_campuses(refresh=True).cached)
            self.assertEqual(fetch.call_count, 2)
            key = next(iter(self.client._cache))
            stamp, data, retrieved = self.client._cache[key]
            self.client._cache[key] = (stamp - 301, data, retrieved)
            self.assertFalse(self.client.list_campuses().cached)
            self.assertEqual(fetch.call_count, 3)
            self.assertFalse(any(k.lower() in ("cookie", "authorization") for k in fetch.call_args.args[0].headers))

    def test_network_errors_rate_limits_and_http_statuses(self):
        headers = Message()
        headers["Retry-After"] = "1"
        for error, attempts in [(URLError("private detail"), 2),
                                (HTTPError(API, 503, "unavailable", headers, None), 2),
                                (HTTPError(API, 404, "missing", headers, None), 1)]:
            with patch("mazemap.client.urlopen", side_effect=error) as fetch, patch("mazemap.client.time.sleep"):
                with self.assertRaises(MapError) as caught:
                    self.client.list_campuses()
                self.assertEqual(fetch.call_count, attempts)
                self.assertNotIn("private detail", str(caught.exception))
        with patch("mazemap.client.urlopen", side_effect=[HTTPError(API, 429, "limited", headers, None), self.response()]) as fetch, patch("mazemap.client.time.sleep"):
            self.assertEqual(len(self.client.list_campuses().campuses), 1)
            self.assertEqual(fetch.call_count, 2)

    def test_bad_content_and_oversized_response_are_not_cached(self):
        malformed = self.response()
        malformed.seek(0)
        malformed.truncate()
        malformed.write(b"not json")
        malformed.seek(0)
        oversized = self.response()
        oversized.read = lambda n: b" " * n
        for response in [self.response(content_type="text/html"), malformed, oversized]:
            with patch("mazemap.client.urlopen", return_value=response), patch("mazemap.client.time.sleep"):
                with self.assertRaises(MapError):
                    self.client.list_campuses()
                self.assertFalse(self.client._cache)

    def test_long_retry_after_is_respected_without_blocking_the_tool(self):
        for retry_after in ["120", format_datetime(datetime.now(timezone.utc) + timedelta(minutes=5))]:
            headers = Message()
            headers["Retry-After"] = retry_after
            error = HTTPError(API, 429, "limited", headers, None)
            with patch("mazemap.client.urlopen", side_effect=error) as fetch, patch("mazemap.client.time.sleep"):
                with self.assertRaisesRegex(MapError, "429"):
                    self.client.list_campuses()
                self.assertEqual(fetch.call_count, 1)

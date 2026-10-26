import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

from mcp.server.mcpserver.exceptions import ToolError

from mazemap import parser
from mazemap.client import MapClient
from mazemap.mcp_server import _call
from mazemap.models import MapError
from shared.public_http import PublicRequestError

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
        self.addCleanup(self.client.http.close)

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

    def test_route_floor_without_a_building_is_preserved(self):
        def route_with_outdoor_floor(base, path, parameters, refresh=False):
            data, metadata = fake_get(base, path, parameters, refresh)
            if "/routing/" in path:
                data["floors"][0]["buildingId"] = None
            return data, metadata

        with patch.object(self.client, "_get", side_effect=route_with_outdoor_floor):
            result = self.client.get_directions(1001, 1002)
        self.assertIsNone(result.floors[0].building_id)

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

    def test_shared_cache_refresh_and_expiry(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return json.dumps(COLLECTION).encode(), datetime(2026, 1, 1, tzinfo=timezone.utc)

        with patch.object(self.client.http, "_fetch", side_effect=fetch):
            self.assertFalse(self.client.list_campuses().cached)
            self.assertTrue(self.client.list_campuses().cached)
            self.assertFalse(self.client.list_campuses(refresh=True).cached)
            self.assertEqual(len(calls), 2)
            key = next(iter(self.client.http._cache))
            stamp, body, retrieved = self.client.http._cache[key]
            self.client.http._cache[key] = (stamp - 301, body, retrieved)
            self.assertFalse(self.client.list_campuses().cached)
            self.assertEqual(len(calls), 3)

    def test_network_errors_rate_limits_and_http_statuses(self):
        with patch.object(self.client.http, "_fetch", side_effect=PublicRequestError("MazeMap returned HTTP 503; try again later.")):
            with self.assertRaisesRegex(MapError, "HTTP 503") as caught:
                self.client.list_campuses()
        self.assertNotIn("private detail", str(caught.exception))

    def test_invalid_json_is_not_cached(self):
        with patch.object(self.client.http, "_fetch", return_value=(b"not json", datetime.now(timezone.utc))):
            with self.assertRaisesRegex(MapError, "invalid JSON"):
                self.client.list_campuses()
            self.assertFalse(self.client.http._cache)

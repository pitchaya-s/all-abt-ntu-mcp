import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import patch

import httpx
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server import MCPServer

from omnibus import mcp_server, parser
from omnibus.client import (
    _ASSETS,
    _BASE,
    _STOP_CACHE_TTL_SECONDS,
    OmnibusClient,
)
from omnibus.models import OmnibusError
from tests.omnibus.fixtures import RESPONSES, FixtureClient


class ClientTests(unittest.TestCase):
    def test_stop_cache_reuses_routes_across_filters_and_preserves_snapshot_time(self):
        c = FixtureClient()
        first = c.list_stops("", None, 1, 0)
        self.assertFalse(first.cached)
        self.assertEqual(len(c.calls), 8)
        repeated = c.list_stops("gate", "179", 20, 0)
        self.assertTrue(repeated.cached)
        self.assertEqual(len(c.calls), 8)
        self.assertEqual(repeated.total_count, 1)
        self.assertEqual(c.list_stops("", None, 1, 1).retrieved_at, first.retrieved_at)
        self.assertEqual(len(c._stop_cache), 8)
        with self.assertRaises(OmnibusError):
            c.list_stops("", "unknown", 20, 0)
        self.assertEqual(len(c.calls), 8)

    def test_stop_cache_expires_per_route_and_reports_oldest_snapshot(self):
        c = FixtureClient()
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        with patch("omnibus.client.time.monotonic", return_value=100), patch.object(c, "_now", return_value=now):
            first = c.list_stops("", "Blue", 20, 0)
        with patch("omnibus.client.time.monotonic", return_value=101), patch.object(c, "_now", return_value=now + timedelta(seconds=1)):
            mixed = c.list_stops("", None, 20, 0)
        self.assertFalse(mixed.cached)
        self.assertEqual(mixed.retrieved_at, first.retrieved_at)
        with patch("omnibus.client.time.monotonic", return_value=100 + _STOP_CACHE_TTL_SECONDS - 1):
            repeated = c.list_stops("", "Blue", 20, 0)
        self.assertTrue(repeated.cached)
        self.assertEqual(repeated.retrieved_at, first.retrieved_at)
        later = now + timedelta(seconds=_STOP_CACHE_TTL_SECONDS)
        with patch("omnibus.client.time.monotonic", return_value=100 + _STOP_CACHE_TTL_SECONDS), patch.object(c, "_now", return_value=later):
            expired = c.list_stops("", "Blue", 20, 0)
            still_cached = c.list_stops("", "179", 20, 0)
        self.assertFalse(expired.cached)
        self.assertEqual(expired.retrieved_at, later)
        self.assertTrue(still_cached.cached)
        self.assertEqual(len(c.calls), 9)

    def test_stop_cache_does_not_share_mutable_models_with_callers(self):
        c = FixtureClient()
        first = c.list_stops("", "Blue", 20, 0)
        first.stops[0].name = "changed"
        first.stops.clear()
        self.assertEqual(c.list_stops("hall", "Blue", 20, 0).stops[0].name, "Example Hall")

    def test_arrivals_reuse_stop_metadata_but_fetch_each_estimate_live(self):
        c = FixtureClient()
        first = c.get_arrivals("Blue", "hall", "shuttle")
        changed_eta = {"ETA": "8", "NextETA": "15"}
        with patch.dict(RESPONSES, {"GetETAAndNextETA_FMS": changed_eta}):
            repeated = c.get_arrivals("Blue", "hall", "shuttle")
        self.assertEqual(first.shuttle_arrivals[0].eta, "3")
        self.assertEqual(repeated.shuttle_arrivals[0].eta, "8")
        self.assertFalse(first.cached)
        self.assertFalse(repeated.cached)
        self.assertTrue(c.list_stops("hall", "Blue", 20, 0).cached)
        self.assertEqual([call[0] for call in c.calls], [
            "DataActionGetPickupCheckPoints", "GetETAAndNextETA_FMS", "GetETAAndNextETA_FMS"])

    def test_stop_cache_does_not_keep_failed_or_malformed_fetches(self):
        c = FixtureClient()
        for failure in [OmnibusError("offline"), ({}, "https://apps.ntu.edu.sg/example")]:
            kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
            with patch.object(c, "_post", **kwargs):
                with self.assertRaises(OmnibusError):
                    c.list_stops("", "Blue", 20, 0)
            self.assertFalse(c._stop_cache)
        with patch("omnibus.client.time.monotonic", return_value=100):
            c.list_stops("", "Blue", 20, 0)
        with patch("omnibus.client.time.monotonic", return_value=100 + _STOP_CACHE_TTL_SECONDS):
            with patch.object(c, "_post", side_effect=OmnibusError("offline")):
                with self.assertRaises(OmnibusError):
                    c.list_stops("", "Blue", 20, 0)
            self.assertFalse(c.list_stops("", "Blue", 20, 0).cached)
        self.assertEqual(len(c.calls), 2)

    def test_concurrent_stop_requests_share_one_fetch(self):
        c = FixtureClient()
        entered, release = Event(), Event()
        fetch = c._post

        def slow_fetch(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("timed out waiting to release fixture")
            return fetch(*args, **kwargs)

        with patch.object(c, "_post", side_effect=slow_fetch), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(c.list_stops, "", "Blue", 20, 0)
            try:
                self.assertTrue(entered.wait(5))
                second = pool.submit(c.list_stops, "hall", "Blue", 20, 0)
            finally:
                release.set()
            self.assertFalse(first.result(timeout=5).cached)
            self.assertTrue(second.result(timeout=5).cached)
        self.assertEqual(len(c.calls), 1)

    def test_positions_placeholder_timestamp_and_filtered_pagination(self):
        c = FixtureClient()
        buses = c.get_live_buses("Blue")
        self.assertIsNone(buses.source_timestamp)
        self.assertEqual(buses.buses[0].capacity, 40)
        self.assertEqual(c.calls[-1][2]["client_variables"]["SelectedRoute"], "Blue")
        self.assertEqual(c.calls[-1][2]["screen_variables"]["RouteId"], "Blue")
        first = c.list_stops("", None, 1, 0)
        self.assertEqual(first.next_offset, 1)
        self.assertEqual(c.list_stops("", None, 1, 1).stops[0].stop_code, "12345")
        self.assertEqual(c.list_stops("gate", "179", 20, 0).total_count, 1)
        self.assertEqual(c.list_stops("missing", None, 20, 0).total_count, 0)

    def test_arrivals_keep_source_units_and_skip_unrequested_feeds(self):
        c = FixtureClient()
        result = c.get_arrivals("179", "gate", "all")
        self.assertFalse(result.shuttle_arrivals)
        self.assertEqual(result.lta_arrivals[0].eta_minutes, "5")
        self.assertIsNone(result.lta_arrivals[0].eta_seconds)
        self.assertNotIn("GetETAAndNextETA_FMS", [call[0] for call in c.calls])
        c.calls.clear()
        self.assertEqual(c.get_arrivals("Blue", "hall", "shuttle").shuttle_arrivals[0].eta, "3")
        self.assertEqual([call[0] for call in c.calls], ["DataActionGetPickupCheckPoints", "GetETAAndNextETA_FMS"])
        for route, source in [("179", "shuttle"), ("Blue", "lta")]:
            with self.assertRaises(OmnibusError):
                c.get_arrivals(route, "", source)

    def test_status_and_route_color_data(self):
        c = FixtureClient()
        self.assertEqual(c.list_routes().colors[0].display_order, 1)
        result = c.get_service_status("Blue")
        self.assertEqual(result.schedules[0].first_bus, "07:00")
        self.assertFalse(result.is_public_holiday)

    def test_missing_arrival_is_not_a_zero_minute_bus_and_broad_queries_are_bounded(self):
        c = FixtureClient()
        stop = c.list_stops("gate", "179", 20, 0).stops[0]
        missing = parser.stop_arrival({"ETA": "0", "NextETA": "0", "IsETA_NotFound": True}, stop)
        self.assertIsNone(missing.eta_minutes)
        self.assertIsNone(missing.next_eta_minutes)
        with patch.object(c, "_stop_records", return_value=([stop] * 21, [], c._now(), False)):
            with self.assertRaisesRegex(OmnibusError, "More than 20"):
                c.get_arrivals(None, "", "all")
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(OmnibusError):
                parser._number(value, "latitude")
        with self.assertRaises(OmnibusError):
            parser._integer(1.5, "bus count")

    def test_unexpected_source_shapes_are_not_reported_as_empty_data(self):
        for fn, args in [(parser.pickup_stops, ({}, "Blue", False)), (parser.bus_positions, ({},)),
                         (parser.routes, ({"RouteList": {"List": []}}, "[]")),
                         (parser.stop_arrival, ({}, None))]:
            with self.assertRaises(OmnibusError):
                fn(*args)

    def test_metadata_discovers_versions_keeps_public_controller_action_and_caches(self):
        c = OmnibusClient()
        manifest = {"manifest": {"versionToken": "module-version", "urlVersions": {p: "?v=1" for p in _ASSETS}}}
        script = "\n".join('callServerAction("%s", "screenservices/example/%s", "api-version")' % (name, name) for name in RESPONSES)
        script += '\ncallServerAction("GetETAAndNextETA_FMS", "screenservices/app/MainFlow/BusStop/ETA", "screen-version")'
        def get(url):
            if "moduleinfo" in url:return json.dumps(manifest).encode()
            if "/scripts/" in url:return script.encode()
            return b"<html></html>"
        with patch.object(c, "_get_bytes", side_effect=get) as network:
            first = c._metadata()
            self.assertEqual(first["endpoints"]["GetETAAndNextETA_FMS"]["api_version"], "api-version")
            count = network.call_count
            self.assertIs(c._metadata(), first)
            self.assertEqual(count, network.call_count)

    def test_post_uses_discovered_versions_and_retries_csrf_only_once(self):
        c = OmnibusClient()
        metadata = {"module_version": "module-version", "endpoints": {"Read": {
            "type": "callServerAction", "path": "screenservices/example/read", "api_version": "api-version"}}}
        invalid = (403, b'{"exception":{"message":"Invalid Login"}}')
        with patch.object(c, "_metadata", return_value=metadata), patch.object(c, "_csrf_token", side_effect=["old", "new"]), patch.object(c, "_read", side_effect=[invalid, b'{"data":{"ok":true}}']) as network:
            self.assertTrue(c._post("Read", "MainFlow.BusStop", inputs={})[0]["ok"])
            self.assertEqual(network.call_count, 2)
            args = network.call_args.kwargs
            self.assertEqual(args["headers"]["X-CSRFToken"], "new")
            self.assertEqual(json.loads(args["body"])["versionInfo"], {"moduleVersion": "module-version", "apiVersion": "api-version"})

    def test_network_is_bounded_and_refuses_external_hosts(self):
        c = OmnibusClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 8_000_001, request=request)
        ))
        with self.assertRaises(OmnibusError):
            c._read("https://unrelated.invalid/")
        with self.assertRaisesRegex(OmnibusError, "8 MB"):
            c._get_bytes(_BASE)

    def test_http_pool_preserves_same_host_csrf_cookies_and_retries_transient_status(self):
        requests = []

        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    503,
                    headers={"retry-after": "0", "set-cookie": "nr2Users=crf%3Dfixture"},
                    request=request,
                )
            return httpx.Response(200, content=b"{}", request=request)

        c = OmnibusClient(transport=httpx.MockTransport(handle))
        with patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0):
            self.assertEqual(c._get_bytes(_BASE), b"{}")

        self.assertEqual(len(requests), 2)
        self.assertEqual(c._csrf_token(), "fixture")
        self.assertIn("nr2Users=crf%3Dfixture", requests[1].headers.get("cookie", ""))

    def test_redirect_outside_omnibus_host_is_rejected_before_following(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                302,
                headers={"location": "https://attacker.example/collect"},
                request=request,
            )

        c = OmnibusClient(transport=httpx.MockTransport(handle))
        with (
            patch("shared.public_http.REQUEST_INTERVAL_SECONDS", 0),
            self.assertRaisesRegex(OmnibusError, "unexpected redirect"),
        ):
            c._read(_BASE)

        self.assertEqual(len(requests), 1)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_five_public_tools_schemas_calls_and_validation(self):
        server = MCPServer("omnibus-offline")
        mcp_server.register_tools(server)
        with patch.object(mcp_server, "client", FixtureClient()):
            async with Client(server) as client:
                tools = {t.name:t for t in (await client.list_tools()).tools}
                self.assertEqual(len(tools), 5)
                for t in tools.values():
                    self.assertTrue(t.annotations.read_only_hint)
                    Draft202012Validator.check_schema(t.input_schema)
                    Draft202012Validator.check_schema(t.output_schema)
                for name in ["list_routes", "list_stops", "get_live_buses", "get_arrivals", "get_service_status"]:
                    full = "omnibus_" + name
                    r = await client.call_tool(full, {})
                    self.assertFalse(r.is_error)
                    Draft202012Validator(tools[full].output_schema).validate(r.structured_content)
                for name, args in [("list_stops", {"limit":0}), ("get_live_buses", {"route_code":"179"}),
                                   ("get_arrivals", {"route_filter":"179", "source":"shuttle"})]:
                    self.assertTrue((await client.call_tool("omnibus_" + name, args)).is_error)

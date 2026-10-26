import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server import MCPServer

from omnibus import mcp_server, parser
from omnibus.client import OmnibusClient, _ASSETS, _BASE, _ORIGIN
from omnibus.models import OmnibusError
from tests.omnibus.fixtures import FixtureClient, RESPONSES


class ClientTests(unittest.TestCase):
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
        with patch.object(c, "_stop_records", return_value=([stop] * 21, [])):
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
        c = OmnibusClient()
        with self.assertRaises(OmnibusError):
            c._read("https://unrelated.invalid/")
        response = Mock()
        response.geturl.return_value = _BASE
        response.read.return_value = b"x" * 8_000_001
        c._opener = MagicMock()
        c._opener.open.return_value.__enter__.return_value = response
        with self.assertRaisesRegex(OmnibusError, "8 MB"):
            c._get_bytes(_BASE)
        response.read.assert_called_once_with(8_000_001)


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

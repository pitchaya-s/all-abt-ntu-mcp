"""Read public routes, stops and arrival data from NTU Omnibus."""

from datetime import datetime, timezone
from http.client import HTTPException
from http.cookiejar import CookieJar
import json
import re
from threading import RLock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from . import parser
from .models import Arrivals, BusPositions, OmnibusError, Routes, ServiceStatus, Stops


_ORIGIN = "https://apps.ntu.edu.sg"
_BASE = _ORIGIN + "/NTUOmnibus/"
_ALLOWED_HOSTS = frozenset({"apps.ntu.edu.sg"})
_ROUTE_CODES = ("Blue", "Brown", "Green", "Grey", "Red", "179", "179A", "199")
_STOP_CACHE_TTL_SECONDS = 300
_ASSETS = (
    "/NTUOmnibus/scripts/CampusShuttle_MUI.controller.js",
    "/NTUOmnibus/scripts/CampusShuttle_MUI.MainFlow.RenderMap.mvc.js",
)
_CALL_PATTERN = re.compile(
    r'(callDataAction|callServerAction|callAggregateWithStartIndexAndClientVars)'
    r'\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"'
)
_ROUTE_COLORS = (
    "{'data':[{'route_code':'Blue','color_code':'0054A6','Order':'2'},"
    "{'route_code':'Green','color_code':'007C48','Order':'3'},"
    "{'route_code':'Brown','color_code':'866D4B','Order':'4'},"
    "{'route_code':'Red','color_code':'D71440','Order':'1'},"
    "{'route_code':'179','color_code':'944496','Order':'5'},"
    "{'route_code':'179A','color_code':'944496','Order':'6'},"
    "{'route_code':'199','color_code':'944496','Order':'7'},"
    "{'route_code':'default','color_code':'181C62','Order':'8'}]}"
)
_SGH_ROUTE_COLORS = (
    "{'data':[{'route_code':'Carpark H','color_code':'0054A6','Order':'2'},"
    "{'route_code':'Carpark H (Night)','color_code':'32BCAD','Order':'4'},"
    "{'route_code':'SGH-Blue','color_code':'866D4B','Order':'1'},"
    "{'route_code':'SGH-Orange','color_code':'D71440','Order':'3'}]}"
)
class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS or parsed.port not in (None, 443):
            raise OmnibusError("NTU Omnibus returned an unexpected redirect; retrieval stopped.")
        return super().redirect_request(request, response, code, message, headers, new_url)


class OmnibusClient:
    def __init__(self):
        self._cookies = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookies), _Redirects())
        self._lock = RLock()
        self._metadata_cache = None
        self._metadata_cached_at = 0.0
        self._stop_cache = {}
        self._last_request_at = 0.0
        self._bootstrapped = False

    def _pace(self):
        wait = 0.25 - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _read(self, url, *, body=None, headers=None):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS or parsed.port not in (None, 443):
            raise OmnibusError("NTU Omnibus returned an unexpected URL; retrieval stopped.")
        request_headers = {
            "User-Agent": "all-abt-ntu-mcp/0.1 (public NTU shuttle lookup)",
            "Accept": "application/json, text/plain, */*",
            "OutSystems-client-env": "browser",
        }
        if headers:
            request_headers.update(headers)
        request = Request(url, data=body, headers=request_headers, method="POST" if body is not None else "GET")
        self._pace()
        try:
            with self._opener.open(request, timeout=20) as response:
                result_url = urlsplit(response.geturl())
                if result_url.scheme != "https" or result_url.hostname not in _ALLOWED_HOSTS:
                    raise OmnibusError("NTU Omnibus returned an unexpected response URL.")
                data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise OmnibusError("NTU Omnibus response exceeded the 8 MB limit.")
            return data
        except HTTPError as error:
            try:
                payload = error.read(8_000_001)
            finally:
                error.close()
            return error.code, payload
        except (URLError, HTTPException, OSError, TimeoutError):
            raise OmnibusError("Could not reach NTU Omnibus; try again later.") from None

    def _get_bytes(self, url):
        response = self._read(url)
        if isinstance(response, tuple):
            code, _ = response
            raise OmnibusError(f"NTU Omnibus returned HTTP {code} while loading public app data.")
        return response

    def _bootstrap(self):
        if self._bootstrapped:
            return
        self._get_bytes(_BASE)
        self._bootstrapped = True

    def _metadata(self):
        if self._metadata_cache is not None and time.monotonic() - self._metadata_cached_at < 300:
            return self._metadata_cache
        self._bootstrap()
        raw = self._get_bytes(_BASE + "moduleservices/moduleinfo?latest")
        try:
            manifest = json.loads(raw)["manifest"]
            module_version = manifest["versionToken"]
            versions = manifest["urlVersions"]
            if not isinstance(versions, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise OmnibusError("NTU Omnibus returned an unexpected public app manifest.") from None

        endpoints = {}
        for asset in _ASSETS:
            version = versions.get(asset)
            if not isinstance(version, str):
                continue
            script = self._get_bytes(_ORIGIN + asset + version).decode("utf-8", "replace")
            for call_type, name, path, api_version in _CALL_PATTERN.findall(script):
                candidate = {"type": call_type, "path": path, "api_version": api_version}
                previous = endpoints.get(name)
                if previous is None:
                    endpoints[name] = candidate

        required = {
            "DataActionGetRoutesList",
            "DataActionGetActiveBusServicesData",
            "DataActionGetPickupCheckPoints",
            "GetETAAndNextETA_FMS",
            "GetETAAndNextETA_LTA",
            "GetRoutesCodejson",
            "GetRoutesMinMax",
            "CheckPHSpecialDay",
            "GetTempMessages",
        }
        if not required.issubset(endpoints):
            raise OmnibusError("NTU Omnibus changed its public app API; endpoint discovery could not complete.")
        self._metadata_cache = {"module_version": module_version, "endpoints": endpoints}
        self._metadata_cached_at = time.monotonic()
        return self._metadata_cache

    def _csrf_token(self):
        for cookie in self._cookies:
            if cookie.name != "nr2Users":
                continue
            decoded = unquote(cookie.value)
            match = re.search(r"(?:^|[;%])crf=([^;%]+)", decoded)
            if match:
                return match.group(1)
        return None

    def _post(self, name, view_name, *, screen_variables=None, client_variables=None, inputs=None, aggregate=False):
        with self._lock:
            metadata = self._metadata()
            try:
                endpoint = metadata["endpoints"][name]
            except KeyError:
                raise OmnibusError(f"NTU Omnibus does not expose the {name} endpoint.") from None
            payload = {
                "versionInfo": {
                    "moduleVersion": metadata["module_version"],
                    "apiVersion": endpoint["api_version"],
                },
                "viewName": view_name,
            }
            if screen_variables is not None:
                payload["screenData"] = {"variables": screen_variables}
                payload["clientVariables"] = client_variables or {}
            if inputs is not None or endpoint["type"] == "callServerAction":
                payload["inputParameters"] = inputs or {}
            if aggregate:
                payload["inputParameters"] = {"StartIndex": 0, "MaxRecords": 1000}

            request_headers = {
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Referer": _BASE,
                "X-Requested-With": "XMLHttpRequest",
            }
            token = self._csrf_token()
            if token:
                request_headers["X-CSRFToken"] = token
            url = _BASE + endpoint["path"]
            for attempt in range(2):
                response = self._read(url, body=json.dumps(payload, separators=(",", ":")).encode(), headers=request_headers)
                if isinstance(response, tuple):
                    code, raw = response
                    if code == 403 and attempt == 0 and self._is_invalid_login(raw):
                        token = self._csrf_token()
                        if token:
                            request_headers["X-CSRFToken"] = token
                            continue
                    raise OmnibusError(f"NTU Omnibus returned HTTP {code} for {name}.")
                try:
                    envelope = json.loads(response)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise OmnibusError(f"NTU Omnibus returned invalid JSON for {name}.") from None
                exception = envelope.get("exception")
                if exception:
                    message = exception.get("message") if isinstance(exception, dict) else None
                    if message == "Invalid Login" and attempt == 0:
                        token = self._csrf_token()
                        if token:
                            request_headers["X-CSRFToken"] = token
                            continue
                    raise OmnibusError(f"NTU Omnibus could not complete {name}; the app rejected the public request.")
                result = envelope.get("data")
                if not isinstance(result, dict):
                    raise OmnibusError(f"NTU Omnibus returned an unexpected response for {name}.")
                return result, url
        raise OmnibusError(f"NTU Omnibus could not complete {name}.")

    @staticmethod
    def _is_invalid_login(raw):
        try:
            return json.loads(raw).get("exception", {}).get("message") == "Invalid Login"
        except (ValueError, AttributeError, TypeError):
            return False

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _local_now():
        return datetime.now(ZoneInfo("Asia/Singapore")).strftime("%d-%m-%Y %H:%M:%S")

    @staticmethod
    def _empty_map_variables():
        return {
            "MarkerList": {"List": [], "EmptyListItem": {
                "Latitude": "0", "Longitude": "0", "Address": "", "LabelClass": "",
                "LabelPositionX": "", "LabelPositionY": "", "IconURL": "", "UniqueId": "",
                "Code": "", "ShortName": "", "IsFavBusStop": False,
            }},
            "DirectionJson": "",
            "MarkerJson": "",
            "RouteId": "",
            "DirectionList": {"List": [], "EmptyListItem": {"lat": "0", "lng": ""}},
            "SpecialMakerList": {"List": [], "EmptyListItem": {
                "Vehplate": "", "Lat": "0", "Lng": "0", "Speed": "0", "Direction": "0",
                "IconURL": "", "UniqueId": 0,
            }},
            "CounterUniqueId": -1,
            "IsSBS_Route": False,
            "CurrDateTime_Local": OmnibusClient._local_now(),
            "RouteColorCode": "",
            "IsRouteDisabled": False,
            "intervalId": "",
            "RouteName": "",
            "ImageUrl": "",
            "IsPrevBlank": False,
            "HasDifference": False,
            "MsgNoOperations": "",
            "MsgNoActiveBus": "",
            "FavoriteRecord": {
                "Id": "0", "Name": "", "LongName": "", "IsFavorite": False,
                "ArrivalTime": "", "NextArrivalTime": "", "RouteId": "", "BusStopCode": "",
                "IsSBS": False, "ServiceId": "", "BusRouteLongName": "", "ColorCode": "", "Route": "",
            },
            "IsDestroyed": False,
            "NewInterval_Id": "",
            "OldInterval_Id": "",
            "IsShowLocalLoadingView": False,
            "UserCurrLat": "1.2804",
            "_userCurrLatInDataFetchStatus": 1,
            "UserCurrLng": "103.8348",
            "_userCurrLngInDataFetchStatus": 1,
            "CurrDateTime": "1900-01-01T00:00:00",
            "_currDateTimeInDataFetchStatus": 1,
            "CheckIsScreenActive": True,
            "_checkIsScreenActiveInDataFetchStatus": 1,
            "IsRenderMapActive": True,
            "_isRenderMapActiveInDataFetchStatus": 1,
        }

    @staticmethod
    def _client_variables(route_code="Blue"):
        return {
            "SGHO_RouteColorCode": _SGH_ROUTE_COLORS,
            "SelectedRoute": route_code,
            "NTU_RouteColorCode": _ROUTE_COLORS,
        }

    def get_live_buses(self, route_code):
        data, url = self._post(
            "DataActionGetActiveBusServicesData",
            "MainFlow.Shuttle",
            screen_variables=dict(self._empty_map_variables(), RouteId=route_code),
            client_variables=self._client_variables(route_code),
        )
        buses, count, timestamp = parser.bus_positions(data)
        return BusPositions(
            retrieved_at=self._now(),
            source_urls=[url],
            route_code=route_code,
            reported_bus_count=count,
            source_timestamp=timestamp,
            buses=buses,
        )

    def list_routes(self):
        route_data, route_url = self._post(
            "DataActionGetRoutesList",
            "MainFlow.Shuttle",
            screen_variables=self._empty_map_variables(),
            client_variables=self._client_variables(),
        )
        color_data, color_url = self._post("GetRoutesCodejson", "MainFlow.Shuttle", inputs={})
        colors_text = color_data.get("Json")
        if not isinstance(colors_text, str):
            raise OmnibusError("NTU Omnibus returned no route-color data.")
        route_rows, colors = parser.routes(route_data, colors_text)
        return Routes(retrieved_at=self._now(), source_urls=[route_url, color_url], routes=route_rows, colors=colors)

    def _stop_records(self, route_codes=None):
        codes = route_codes or _ROUTE_CODES
        if any(code not in _ROUTE_CODES for code in codes):
            raise OmnibusError("Choose a campus shuttle route or service 179, 179A, or 199.")
        records, urls, retrieved_times = [], [], []
        all_cached = True
        for code in codes:
            # Share stop metadata across lookups without caching live estimates.
            # The fixed route keys bound this cache to eight entries per client.
            with self._lock:
                entry = self._stop_cache.get(code)
                if entry is None or time.monotonic() - entry[0] >= _STOP_CACHE_TTL_SECONDS:
                    is_lta = code in {"179", "179A", "199"}
                    data, url = self._post(
                        "DataActionGetPickupCheckPoints", "MainFlow.Shuttle",
                        screen_variables=dict(self._empty_map_variables(), RouteId=code, IsSBS_Route=is_lta),
                        client_variables=self._client_variables(code),
                    )
                    stops = parser.pickup_stops(data, code, is_lta)
                    entry = (time.monotonic(), self._now(), stops, url)
                    self._stop_cache[code] = entry
                    all_cached = False
                _, retrieved_at, stops, url = entry
                records.extend(stop.model_copy(deep=True) for stop in stops)
                urls.append(url)
                retrieved_times.append(retrieved_at)
        return records, list(dict.fromkeys(urls)), min(retrieved_times), all_cached

    def list_stops(self, query, route_code, limit, offset):
        self._query(query)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise OmnibusError("Use a limit from 1 to 100 and a nonnegative offset.")
        records, urls, retrieved_at, cached = self._stop_records([route_code] if route_code else None)
        folded_query = query.casefold().strip()
        filtered = [stop for stop in records if not folded_query or folded_query in stop.name.casefold()
                    or folded_query in stop.stop_code.casefold()]
        page = filtered[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(filtered) else None
        return Stops(retrieved_at=retrieved_at, source_urls=urls, cached=cached, stops=page,
                     total_count=len(filtered), next_offset=next_offset)

    @staticmethod
    def _query(query):
        if not isinstance(query, str) or len(query) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            raise OmnibusError("Use at most 120 search characters without control characters.")

    def get_arrivals(self, route_filter, stop_query, source):
        self._query(stop_query)
        campus_routes = ("Blue", "Brown", "Green", "Grey", "Red")
        lta_services = ("179", "179A", "199")
        if source not in {"all", "shuttle", "lta"}:
            raise OmnibusError("Choose all, shuttle, or lta arrival sources.")
        codes = list(campus_routes if source == "shuttle" else lta_services if source == "lta" else campus_routes + lta_services)
        if route_filter:
            if route_filter not in codes:
                raise OmnibusError("The selected route does not match the arrival source; choose the matching shuttle or lta source.")
            codes = [route_filter]
        stops, source_urls, _, _ = self._stop_records(codes)
        query = stop_query.strip().casefold()
        stops = [stop for stop in stops if not query or query in stop.name.casefold() or query in stop.stop_code.casefold()]
        if len(stops) > 20:
            raise OmnibusError("More than 20 route-stop matches. Narrow stop_query or route_filter before requesting live arrivals.")
        shuttle_rows, lta_rows = [], []
        for stop in stops:
            name = "GetETAAndNextETA_LTA" if stop.is_lta_service else "GetETAAndNextETA_FMS"
            data, url = self._post(name, "MainFlow.Shuttle",
                                   inputs={"BusStopCode": stop.stop_code, "RouteCode": stop.route_code})
            row = parser.stop_arrival(data, stop)
            (lta_rows if stop.is_lta_service else shuttle_rows).append(row)
            source_urls.append(url)
        return Arrivals(retrieved_at=self._now(), source_urls=list(dict.fromkeys(source_urls)),
                        route_filter=route_filter, stop_query=stop_query,
                        shuttle_arrivals=shuttle_rows, lta_arrivals=lta_rows)

    def get_service_status(self, route_code):
        schedule_data, schedule_url = self._post(
            "GetRoutesMinMax", "MainFlow.Shuttle", inputs={"RouteCode": route_code}
        )
        special_data, special_url = self._post(
            "CheckPHSpecialDay", "MainFlow.Shuttle", inputs={"RouteCode": route_code}
        )
        message_data, message_url = self._post("GetTempMessages", "MainFlow.Shuttle", inputs={})
        try:
            schedules = parser.schedules(schedule_data, route_code)
            result = message_data["Result"]
            if not isinstance(result, dict):
                raise TypeError
            is_local = schedule_data["IsFromLocalDB"]
            is_holiday = special_data["IsTodayPublicHoliday"]
            is_special = special_data["IsTodaySpecialDay"]
            has_message = result["IsShowTemp"]
            for value in (is_local, is_holiday, is_special, has_message):
                if type(value) is not bool:
                    raise TypeError
        except (KeyError, TypeError):
            raise OmnibusError("NTU Omnibus returned an unexpected service-status response.") from None
        return ServiceStatus(
            retrieved_at=self._now(),
            source_urls=[schedule_url, special_url, message_url],
            route_code=route_code,
            schedules=schedules,
            schedule_from_local_db=is_local,
            is_public_holiday=is_holiday,
            is_special_day=is_special,
            special_day_notice=parser.optional_text(special_data.get("SpecialDayTextVal")),
            has_temporary_message=has_message,
            temporary_message=parser.optional_text(result.get("TempMessageContent")),
            no_active_bus_message=parser.optional_text(result.get("MsgNoActiveBus")),
            no_operations_message=parser.optional_text(result.get("MsgNoOperations")),
        )

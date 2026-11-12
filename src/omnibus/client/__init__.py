"""Public NTU Omnibus shuttle client."""

from datetime import datetime, timezone
import weakref
from threading import RLock
from zoneinfo import ZoneInfo

import httpx

from .arrivals import ArrivalMethods
from .constants import (
    _ALLOWED_HOSTS,
    _ASSETS,
    _BASE,
    _CALL_PATTERN,
    _MAX_ATTEMPTS,
    _MAX_REDIRECTS,
    _MAX_RESPONSE_BYTES,
    _MAX_RETRY_DELAY_SECONDS,
    _ORIGIN,
    _REDIRECTS,
    _RETRYABLE,
    _ROUTE_CODES,
    _ROUTE_COLORS,
    _SGH_ROUTE_COLORS,
    _STOP_CACHE_TTL_SECONDS,
)
from .http import HTTPMethods
from .metadata import MetadataMethods
from ..models import Stop
from .routes import RouteMethods
from .stops import StopMethods


class OmnibusClient(
    HTTPMethods, MetadataMethods, RouteMethods, StopMethods, ArrivalMethods
):
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=False,
            transport=transport,
            headers={
                "User-Agent": "all-abt-ntu-mcp/0.1 (public NTU shuttle lookup)",
                "Accept": "application/json, text/plain, */*",
            },
        )
        self._cookies = self._http.cookies.jar
        self._finalizer = weakref.finalize(self, self._http.close)
        self._closed = False
        self._lock = RLock()
        self._metadata_cache = None
        self._metadata_cached_at = 0.0
        self._stop_cache: dict[str, tuple[float, datetime, list[Stop], str]] = {}
        self._bootstrapped = False

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _local_now():
        return datetime.now(ZoneInfo("Asia/Singapore")).strftime("%d-%m-%Y %H:%M:%S")

    @staticmethod
    def _empty_map_variables():
        return {
            "MarkerList": {
                "List": [],
                "EmptyListItem": {
                    "Latitude": "0",
                    "Longitude": "0",
                    "Address": "",
                    "LabelClass": "",
                    "LabelPositionX": "",
                    "LabelPositionY": "",
                    "IconURL": "",
                    "UniqueId": "",
                    "Code": "",
                    "ShortName": "",
                    "IsFavBusStop": False,
                },
            },
            "DirectionJson": "",
            "MarkerJson": "",
            "RouteId": "",
            "DirectionList": {"List": [], "EmptyListItem": {"lat": "0", "lng": ""}},
            "SpecialMakerList": {
                "List": [],
                "EmptyListItem": {
                    "Vehplate": "",
                    "Lat": "0",
                    "Lng": "0",
                    "Speed": "0",
                    "Direction": "0",
                    "IconURL": "",
                    "UniqueId": 0,
                },
            },
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
                "Id": "0",
                "Name": "",
                "LongName": "",
                "IsFavorite": False,
                "ArrivalTime": "",
                "NextArrivalTime": "",
                "RouteId": "",
                "BusStopCode": "",
                "IsSBS": False,
                "ServiceId": "",
                "BusRouteLongName": "",
                "ColorCode": "",
                "Route": "",
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


__all__ = [
    "OmnibusClient",
    "_ALLOWED_HOSTS",
    "_ASSETS",
    "_BASE",
    "_CALL_PATTERN",
    "_MAX_ATTEMPTS",
    "_MAX_REDIRECTS",
    "_MAX_RESPONSE_BYTES",
    "_MAX_RETRY_DELAY_SECONDS",
    "_ORIGIN",
    "_REDIRECTS",
    "_RETRYABLE",
    "_ROUTE_CODES",
    "_ROUTE_COLORS",
    "_SGH_ROUTE_COLORS",
    "_STOP_CACHE_TTL_SECONDS",
]

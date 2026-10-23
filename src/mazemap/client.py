"""Bounded, cached ordinary HTTPS reads. No university login or cookies."""

from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import parser
from .models import Buildings, Campuses, Directions, MapError, PlaceDetails, Places, RouteBuilding, RouteFloor


API = "https://api.mazemap.com"
SEARCH = "https://search.mazemap.com"
ROUTING = "https://routing.mazemap.com"


class MapClient:
    def __init__(self):
        self._lock = Lock()
        self._cache = OrderedDict()
        self._last_request = 0.0

    def _get(self, base, path, parameters, refresh=False):
        url = base + path + "?" + urlencode(parameters)
        # Serializing reads bounds concurrency and avoids duplicate cold requests.
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(url)
            if not refresh and cached is not None and now - cached[0] < 300:
                self._cache.move_to_end(url)
                return cached[1], dict(retrieved_at=cached[2], source_url=url, cached=True)
            request = Request(url, headers={"User-Agent": "all-abt-ntu-mcp/0.1 (NTU campus map lookup)", "Accept": "application/json"})
            for attempt in range(2):
                time.sleep(max(0, 0.25 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
                try:
                    with urlopen(request, timeout=20) as response:
                        if response.headers.get_content_type() != "application/json":
                            raise MapError("MazeMap returned a non-JSON response; try again later.")
                        body = response.read(8_000_001)
                        if len(body) > 8_000_000:
                            raise MapError("MazeMap response exceeded the 8 MB safety limit.")
                        data = json.loads(body)
                    if not isinstance(data, dict):
                        raise MapError("MazeMap returned an unexpected response format.")
                    retrieved = datetime.now(timezone.utc)
                    self._cache[url] = (time.monotonic(), data, retrieved)
                    self._cache.move_to_end(url)
                    while len(self._cache) > 128:
                        self._cache.popitem(last=False)
                    return data, dict(retrieved_at=retrieved, source_url=url, cached=False)
                except HTTPError as error:
                    code = error.code
                    retry_after = error.headers.get("Retry-After", "1")
                    error.close()
                    try:
                        delay = max(0, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            delay = 1
                    if not attempt and (code == 429 or 500 <= code <= 599) and delay <= 10:
                        time.sleep(delay)
                        continue
                    if code == 404:
                        raise MapError("MazeMap could not find this place or route; search again for current IDs.") from None
                    raise MapError(f"MazeMap request failed with HTTP {code}; try again later.") from None
                except (URLError, HTTPException, OSError):
                    if not attempt:
                        continue
                    raise MapError("Could not reach MazeMap after two attempts; check your connection and try again.") from None
                except (ValueError, UnicodeError):
                    raise MapError("MazeMap returned invalid JSON; no map data was inferred.") from None

    def _campuses(self, refresh=False):
        data, metadata = self._get(API, "/api/campuscollection/ntu-sg/", {"withcampuses": "true"}, refresh)
        if data.get("tag") != "ntu-sg":
            raise MapError("MazeMap returned a different campus collection; no data was inferred.")
        campuses = [parser.campus(v) for v in parser.records(data["campuses"])]
        if not campuses or set(data["campusIds"]) != {c.campus_id for c in campuses}:
            raise MapError("MazeMap returned an incomplete campus collection.")
        return Campuses(campuses=campuses, **metadata)

    def _check_campus(self, campus_id):
        if campus_id not in {c.campus_id for c in self._campuses().campuses}:
            raise MapError("campus_id must belong to NTU; use mazemap_list_campuses to find valid IDs.")

    def list_campuses(self, refresh=False) -> Campuses:
        return self._campuses(refresh)

    def list_buildings(self, campus_id=2123, query=None, refresh=False) -> Buildings:
        self._check_campus(campus_id)
        if query is not None and not query.strip():
            raise MapError("query must contain a building name.")
        data, metadata = self._get(API, "/api/buildings/", {"campusid": campus_id, "srid": 4326}, refresh)
        values = parser.records(data["buildings"])
        if any(v.get("campusId") != campus_id for v in values):
            raise MapError("MazeMap returned buildings outside the requested campus.")
        buildings = [parser.building(v) for v in values]
        if query is not None:
            buildings = [b for b in buildings if query.strip().casefold() in (b.name or "").casefold()]
        return Buildings(campus_id=campus_id, buildings=buildings, **metadata)

    def search_places(self, query, campus_id=None, limit=10, offset=0, refresh=False) -> Places:
        query = query.strip()
        if not query:
            raise MapError("query must contain a room code, place name, or category.")
        if campus_id is not None:
            self._check_campus(campus_id)
        parameters = dict(q=query, campuscollectiontag="ntu-sg", rows=limit + 1, start=offset,
                          withpois="true", withbuilding="false", withcampus="false", withtype="false")
        if campus_id is not None:
            parameters["campusid"] = campus_id
        data, metadata = self._get(SEARCH, "/search/equery/", parameters, refresh)
        values = parser.records(data["result"])
        places = [parser.place(v) for v in values]
        ntu_ids = {c.campus_id for c in self._campuses().campuses}
        if any(p.campus_id not in ntu_ids or (campus_id is not None and p.campus_id != campus_id) for p in places):
            raise MapError("MazeMap returned places outside the requested NTU scope.")
        return Places(query=query, places=places[:limit], next_offset=offset + limit if len(places) > limit else None, **metadata)

    def get_place(self, poi_id, refresh=False) -> PlaceDetails:
        data, metadata = self._get(API, f"/api/pois/{poi_id}/", {"srid": 4326}, refresh)
        place = parser.place(data)
        if place.poi_id != poi_id:
            raise MapError("MazeMap returned a different place ID.")
        self._check_campus(place.campus_id)
        return PlaceDetails(place=place, **metadata)

    def get_directions(self, from_poi_id, to_poi_id, constraint="NO_CONSTRAINT", refresh=False) -> Directions:
        self.get_place(from_poi_id, refresh)
        self.get_place(to_poi_id, refresh)
        data, metadata = self._get(ROUTING, "/routing/v2/a-to-b/", dict(
            fromPoiId=from_poi_id, toPoiId=to_poi_id, campusCollectionTag="ntu-sg",
            lang="en", units="metric", mode="PEDESTRIAN", constraint=constraint,
        ), refresh)
        if (data.get("version") != "2" or data["properties"].get("units") != "metric"
                or data["properties"].get("mode") != "PEDESTRIAN"):
            raise MapError("MazeMap returned an unsupported route format, travel mode, or measurement unit.")
        routes = [parser.route(v) for v in parser.records(data["routes"])]
        if not routes:
            raise MapError("MazeMap found no route for these places and accessibility constraint.")
        buildings = [RouteBuilding(building_id=b["id"], name=b.get("buildingName")) for b in parser.records(data["buildings"])]
        floors = [RouteFloor(floor_id=f["id"], building_id=f["buildingId"], name=f.get("floorName"), level=f.get("z"))
                  for f in parser.records(data["floors"])]
        return Directions(from_poi_id=from_poi_id, to_poi_id=to_poi_id, constraint=constraint,
                          routes=routes, buildings=buildings, floors=floors, **metadata)

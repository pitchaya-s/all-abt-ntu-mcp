"""Bounded, cached ordinary HTTPS reads. No university login or cookies."""

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from shared.public_http import PublicHTTPClient, PublicRequestError

from . import parser
from .models import (
    Buildings,
    Campuses,
    Directions,
    MapError,
    PlaceDetails,
    Places,
    RouteBuilding,
    RouteFloor,
)

API = "https://api.mazemap.com"
SEARCH = "https://search.mazemap.com"
ROUTING = "https://routing.mazemap.com"


class MapClient:
    def __init__(self):
        self.http = PublicHTTPClient(
            "MazeMap", ["api.mazemap.com", "search.mazemap.com", "routing.mazemap.com"], {"application/json"}
        )

    def _get(self, base, path, parameters, refresh=False):
        url = base + path + "?" + urlencode(parameters)
        try:
            body, metadata = self.http.get(url, refresh)
        except PublicRequestError as error:
            if error.status == 404:
                if base == ROUTING:
                    raise MapError(
                        "MazeMap could not calculate a walking route for these verified places and constraint; try different NTU POIs or NO_CONSTRAINT."
                    ) from None
                raise MapError("MazeMap could not find this place or route; search again for current IDs.") from None
            raise MapError(str(error)) from None
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            self.http.invalidate(url)
            raise MapError("MazeMap returned invalid JSON; no map data was inferred.") from None
        if not isinstance(data, dict):
            self.http.invalidate(url)
            raise MapError("MazeMap returned an unexpected response format.")
        return data, metadata

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
        self._campuses()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mazemap-place") as pool:
            from_place = pool.submit(self.get_place, from_poi_id, refresh)
            to_place = pool.submit(self.get_place, to_poi_id, refresh)
            from_place.result()
            to_place.result()
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

"""Synthetic payloads matching the verified public MazeMap response shapes."""

from copy import deepcopy
from datetime import datetime, timezone


COLLECTION = {"tag": "ntu-sg", "campusIds": [2123], "campuses": [{
    "campusId": 2123, "name": "NTU - Main Campus",
    "center": {"type": "Point", "coordinates": [103.68, 1.34]},
}]}
BUILDINGS = {"buildings": [{"id": 101, "campusId": 2123, "name": "Example Building", "floors": [
    {"id": 201, "name": "B1", "z": -1}, {"id": 202, "name": "G", "z": 0},
]}]}
POI = {
    "poiId": 1001, "campusId": 2123, "title": "Tutorial Room 7", "identifier": "EX-B1-07",
    "deleted": False, "buildingId": 101, "buildingName": "Example Building", "floorId": 201,
    "floorName": "B1", "z": -1, "peopleCapacity": 0, "description": "A &amp; B",
    "point": {"type": "Point", "coordinates": [103.68, 1.34]},
    "infos": [{"name": "Tutorial Room 7"}, {"name": "TR+7"}], "types": [{"name": "Tutorial Room"}],
}
SEARCH_POI = {**POI, "title": "Tutorial Room <em>7</em>", "z": None, "zValue": -1,
              "floorName": None, "zName": "B1", "buildingName": None,
              "dispBldNames": ["Example Building"], "infos": [], "types": [],
              "poiNames": ["Tutorial Room 7", "TR+7"], "typeNames": ["Tutorial Room"]}
ROUTING = {
    "version": "2", "properties": {"units": "metric", "mode": "PEDESTRIAN"},
    "buildings": [{"id": 101, "campusId": 2123, "buildingName": "Example Building"}],
    "floors": [{"id": 201, "buildingId": 101, "floorName": "B1", "z": -1}],
    "routes": [{"properties": {"timeEstimateSeconds": 22}, "legs": [{
        "basic": {"steps": [{"properties": {"distance": 3.4, "isAccessible": True, "uncertainSegment": False}},
                            {"properties": {"distance": 4.9, "isAccessible": True, "uncertainSegment": False}}]},
        "instructions": {"error": None, "steps": [{"instruction": "Walk forward."}, {"instruction": "Turn left."}]},
    }]}],
}


def fake_get(base, path, parameters, refresh=False):
    metadata = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=base + path, cached=False)
    if path == "/api/campuscollection/ntu-sg/":
        data = COLLECTION
    elif path == "/api/buildings/":
        data = BUILDINGS
    elif path == "/search/equery/":
        matches = [SEARCH_POI, {**SEARCH_POI, "poiId": 1002}]
        start = parameters["start"]
        data = {"result": matches[start:start + parameters["rows"]]}
    elif path.startswith("/api/pois/"):
        poi_id = int(path.split("/")[-2])
        data = {**POI, "poiId": poi_id}
    elif path == "/routing/v2/a-to-b/":
        data = ROUTING
    else:
        raise AssertionError("Unexpected offline MazeMap request")
    return deepcopy(data), metadata

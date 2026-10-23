"""Validate MazeMap payloads and keep navigation fields without polygon data."""

from html.parser import HTMLParser

from .models import Building, Campus, Floor, MapError, Place, Point, Route


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def text(value):
    if not isinstance(value, str):
        raise MapError("MazeMap returned an unexpected text field; no place data was inferred.")
    parser = _Text()
    parser.feed(value)
    return "".join(parser.parts).strip()


def records(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MapError("MazeMap returned an unexpected collection format; try again later.")
    return value


def point(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("type") != "Point":
        raise MapError("MazeMap returned invalid point coordinates.")
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        raise MapError("MazeMap returned invalid point coordinates.")
    return Point(longitude=coordinates[0], latitude=coordinates[1])


def campus(value) -> Campus:
    return Campus(campus_id=value["campusId"], name=text(value["name"]), center=point(value["center"]))


def building(value) -> Building:
    return Building(
        building_id=value["id"], name=text(value["name"]) if value.get("name") else None,
        floors=[Floor(floor_id=f["id"], name=f.get("name"), level=f.get("z")) for f in records(value["floors"])],
    )


def place(value) -> Place:
    if value.get("deleted"):
        raise MapError("This MazeMap place has been deleted; search again for its current location.")
    names = value.get("poiNames")
    if names is None:
        names = [item["name"] for item in records(value.get("infos", []))]
    if not isinstance(names, list):
        raise MapError("MazeMap returned invalid place aliases.")
    name = text(value["title"])
    categories = value.get("typeNames")
    if categories is None:
        categories = [item["name"] for item in records(value.get("types", []))]
    if not isinstance(categories, list):
        raise MapError("MazeMap returned invalid place categories.")
    building_name = value.get("buildingName")
    if building_name is None:
        names_of_building = value.get("dispBldNames", [])
        if not isinstance(names_of_building, list):
            raise MapError("MazeMap returned invalid building names.")
        building_name = ", ".join(text(n) for n in names_of_building) or None
    return Place(
        poi_id=value["poiId"], campus_id=value["campusId"], name=name,
        identifier=value.get("identifier"), aliases=list(dict.fromkeys(text(n) for n in names if text(n) != name)),
        building_id=value.get("buildingId") or value.get("bldId"), building_name=building_name,
        floor_id=value.get("floorId"), floor_name=value.get("floorName") or value.get("zName"),
        level=value.get("z") if value.get("z") is not None else value.get("zValue"),
        categories=list(dict.fromkeys(text(n) for n in categories)), point=point(value.get("point")),
        description=text(value["description"]) if value.get("description") else None,
        capacity=value.get("peopleCapacity"),
        map_url=f"https://use.mazemap.com/?config=ntu-sg&sharepoitype=poi&sharepoi={value['poiId']}",
    )


def route(value) -> Route:
    legs = records(value["legs"])
    if not legs:
        raise MapError("MazeMap returned a route without any legs.")
    steps, instructions, issues = [], [], []
    instructions_available = True
    for leg in legs:
        steps.extend(records(leg["basic"]["steps"]))
        block = leg.get("instructions")
        if block is None or block.get("error") or not block.get("steps"):
            instructions_available = False
            issues.append("Text directions are unavailable for a route leg.")
        else:
            instructions.extend(text(s["instruction"]) for s in records(block["steps"]))
    if not steps:
        raise MapError("MazeMap returned a route without path steps.")
    properties = [step["properties"] for step in steps]
    distances = [item.get("distance") for item in properties]
    accessibility = [item.get("isAccessible") for item in properties]
    uncertainty = [item.get("uncertainSegment") for item in properties]
    if any(v is not None and (type(v) not in (int, float) or v < 0) for v in distances):
        raise MapError("MazeMap returned invalid route distances.")
    if any(v is not None and type(v) is not bool for v in accessibility + uncertainty):
        raise MapError("MazeMap returned invalid route accessibility flags.")
    return Route(
        distance_metres=sum(distances) if all(d is not None for d in distances) else None,
        duration_seconds=value["properties"].get("timeEstimateSeconds"),
        accessible=False if False in accessibility else True if all(v is True for v in accessibility) else None,
        uncertain=True if True in uncertainty else False if all(v is False for v in uncertainty) else None,
        instructions=instructions if instructions_available else None, issues=list(dict.fromkeys(issues)),
    )

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MapError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Point(Model):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class Campus(Model):
    campus_id: int = Field(gt=0, strict=True)
    name: str
    center: Point


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class Campuses(Snapshot):
    campuses: list[Campus]


class Floor(Model):
    floor_id: int = Field(gt=0, strict=True)
    name: str | None
    level: float | None


class Building(Model):
    building_id: int = Field(gt=0, strict=True)
    name: str | None
    floors: list[Floor]


class Buildings(Snapshot):
    campus_id: int
    buildings: list[Building]


class Place(Model):
    poi_id: int = Field(gt=0, strict=True)
    campus_id: int = Field(gt=0, strict=True)
    name: str
    identifier: str | None
    aliases: list[str]
    building_id: int | None
    building_name: str | None
    floor_id: int | None
    floor_name: str | None
    level: float | None
    categories: list[str]
    point: Point | None
    description: str | None
    capacity: int | None = Field(ge=0, strict=True)
    map_url: str


class Places(Snapshot):
    query: str
    places: list[Place]
    next_offset: int | None


class PlaceDetails(Snapshot):
    place: Place


class Route(Model):
    distance_metres: float | None = Field(ge=0)
    duration_seconds: float | None = Field(ge=0)
    accessible: bool | None
    uncertain: bool | None
    instructions: list[str] | None
    issues: list[str]


class RouteFloor(Floor):
    building_id: int | None


class RouteBuilding(Model):
    building_id: int
    name: str | None


class Directions(Snapshot):
    from_poi_id: int
    to_poi_id: int
    constraint: str
    routes: list[Route]
    buildings: list[RouteBuilding]
    floors: list[RouteFloor]

"""Typed results returned by the public NTU Omnibus tools."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OmnibusError(RuntimeError):
    """An upstream response could not be used safely."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_urls: list[str]
    cached: bool = False


class BusPosition(Model):
    vehicle_plate: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed: float | None = None
    direction_degrees: float | None = None
    crowd_level: str | None = None
    occupancy: str | None = None
    capacity: int | None = None
    ridership: int | None = None


class BusPositions(Snapshot):
    route_code: str
    reported_bus_count: int = Field(ge=0)
    source_timestamp: datetime | None = None
    buses: list[BusPosition]


class Route(Model):
    route_code: str = Field(min_length=1)
    description: str | None = None
    long_name: str | None = None
    is_lta_service: bool


class RouteColor(Model):
    route_code: str = Field(min_length=1)
    color_code: str = Field(min_length=1)
    display_order: int | None = None


class Routes(Snapshot):
    routes: list[Route]
    colors: list[RouteColor]


class Stop(Model):
    name: str = Field(min_length=1)
    stop_code: str = Field(min_length=1)
    route_code: str = Field(min_length=1)
    service_id: str | None = None
    is_lta_service: bool
    route_long_name: str | None = None
    color_code: str | None = None


class Stops(Snapshot):
    stops: list[Stop]
    total_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)


class ShuttleArrival(Model):
    route_code: str = Field(min_length=1)
    stop_name: str = Field(min_length=1)
    stop_code: str = Field(min_length=1)
    eta: str | None = None
    next_eta: str | None = None
    color_code: str | None = None


class LtaArrival(Model):
    service_no: str = Field(min_length=1)
    stop_code: str = Field(min_length=1)
    stop_name: str | None = None
    eta_minutes: str | None = None
    eta_seconds: int | None = None
    next_eta_minutes: str | None = None
    next_eta_seconds: int | None = None
    load: str | None = None


class Arrivals(Snapshot):
    route_filter: str | None
    stop_query: str
    shuttle_arrivals: list[ShuttleArrival]
    lta_arrivals: list[LtaArrival]


class RouteSchedule(Model):
    route_code: str = Field(min_length=1)
    first_bus: str | None = None
    last_bus: str | None = None
    schedule_type: str | None = None
    day_type: str | None = None
    display_order: int | None = None


class ServiceStatus(Snapshot):
    route_code: str
    schedules: list[RouteSchedule]
    schedule_from_local_db: bool
    is_public_holiday: bool
    is_special_day: bool
    special_day_notice: str | None = None
    has_temporary_message: bool
    temporary_message: str | None = None
    no_active_bus_message: str | None = None
    no_operations_message: str | None = None

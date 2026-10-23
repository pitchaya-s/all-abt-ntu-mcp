from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class RecordSummary(Model):
    record_id: str
    context: Literal["L", "PC"]
    title: str
    resource_types: list[str]
    authors: list[str]
    publication_dates: list[str]
    open_access: bool | None
    availability_codes: list[str] | None
    availability_label: str | None
    catalogue_url: str


class Link(Model):
    url: str
    label: str | None
    link_type: str | None


class Record(RecordSummary):
    alternate_titles: list[str]
    contributors: list[str]
    publishers: list[str]
    editions: list[str]
    languages: list[str]
    subjects: list[str]
    descriptions: list[str]
    identifiers: dict[str, list[str]]
    links: list[Link]


class SearchResults(Snapshot):
    query: str
    records: list[RecordSummary]
    offset: int = Field(ge=0)
    total_count: int = Field(ge=0)
    local_count: int | None = Field(ge=0)
    central_index_count: int | None = Field(ge=0)
    next_offset: int | None = Field(ge=0)


class RecordDetails(Snapshot):
    record: Record


class Holding(Model):
    library: str | None
    location: str | None
    call_number: str | None
    availability: str | None


class ElectronicService(Model):
    name: str | None
    url: str | None
    notes: str | None


class Availability(Snapshot):
    record_id: str
    context: Literal["L", "PC"]
    holdings: list[Holding]
    electronic_services: list[ElectronicService]
    availability_codes: list[str] | None
    services_source_url: str | None = None


class Facility(Model):
    library: str
    name: str
    url: str
    map_slug: str | None = None
    space_id: int | None = None
    location_id: int | None = None
    group_id: int | None = None


class Facilities(Snapshot):
    facilities: list[Facility]
    notices: list[str]


class SpaceStatus(Model):
    space_id: int
    name: str
    status: Literal["available", "available_later", "unavailable", "unknown"]
    source_status: int


class MapAvailability(Snapshot):
    map_slug: str
    at: datetime
    spaces: list[SpaceStatus]


class TimeSlot(Model):
    start: datetime
    end: datetime
    status: Literal["available", "unavailable"]
    source_classes: str | None


class SpaceSchedule(Model):
    item_id: str
    name: str | None
    slots: list[TimeSlot]


class FacilitySchedule(Snapshot):
    date: str
    timezone: Literal["Asia/Singapore"] = "Asia/Singapore"
    title: str
    description: str | None
    spaces: list[SpaceSchedule]
    window_end: bool | None

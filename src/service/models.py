from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.sitefinity import FilterOption


class ServiceError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class Location(Model):
    name: str = Field(min_length=1)
    address: str | None
    phone: str | None
    fax: str | None
    email: str | None
    operating_hours: str | None
    map_url: str | None


class SearchResults(Snapshot):
    locations: list[Location]
    total_count: int = Field(ge=0)
    directory_count: int = Field(ge=0)
    pages_checked: int = Field(ge=1)
    next_offset: int | None = Field(ge=0)


class Filters(Snapshot):
    types: list[FilterOption]
    categories: list[FilterOption]

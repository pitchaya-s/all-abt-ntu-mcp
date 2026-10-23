from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FacultyError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class Profile(Model):
    name: str = Field(min_length=1)
    school: str | None
    email: str | None
    appointments: list[str] | None
    interests: list[str] | None
    summary: str | None
    profile_url: str


class SearchResults(Snapshot):
    profiles: list[Profile]
    page: int = Field(ge=1)
    total_pages: int = Field(ge=0)
    total_count: int = Field(ge=0)
    next_page: int | None = Field(ge=1)


class Interest(Model):
    interest_id: str
    name: str = Field(min_length=1)


class Interests(Snapshot):
    interests: list[Interest]
    total_count: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)

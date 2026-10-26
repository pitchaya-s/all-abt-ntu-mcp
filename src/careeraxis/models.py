from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CareerAxisError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class AuthStatus(Model):
    credentials_configured: bool | None
    credential_storage: str
    credential_error: str | None
    session_verified: bool
    last_verified_at: datetime | None


class Opportunity(Model):
    title: str = Field(min_length=1, max_length=500)
    url: str
    details: str = Field(max_length=4000)


class SearchResults(Snapshot):
    query: str
    page: int = Field(ge=1)
    opportunities: list[Opportunity]
    has_next_page: bool
    truncated: bool


class OpportunityDetails(Snapshot):
    title: str = Field(min_length=1, max_length=500)
    url: str
    text: str = Field(max_length=20000)
    application_links: list[str]


class PortalItem(Model):
    title: str = Field(min_length=1, max_length=500)
    url: str
    summary: str = Field(max_length=4000)


class PortalResults(Snapshot):
    section: Literal["events", "resources", "organisations", "appointment_topics", "internship_jobs"]
    query: str
    page: int = Field(ge=1)
    items: list[PortalItem]
    has_next_page: bool
    truncated: bool


class PortalDetails(Snapshot):
    title: str = Field(min_length=1, max_length=500)
    url: str
    text: str = Field(max_length=20000)
    links: list[str]

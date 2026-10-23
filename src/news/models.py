from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.sitefinity import FilterOption


class NewsError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class Story(Model):
    title: str = Field(min_length=1)
    url: str
    published_date: str | None
    summary: str | None


class SearchResults(Snapshot):
    stories: list[Story]
    page: int = Field(ge=1)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    next_page: int | None = Field(ge=1)


class Categories(Snapshot):
    categories: list[FilterOption]


class Article(Snapshot):
    title: str = Field(min_length=1)
    published_date: str | None
    text: str
    total_characters: int = Field(ge=1)
    next_offset: int | None = Field(ge=0)

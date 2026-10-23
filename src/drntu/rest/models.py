from typing import Literal

from pydantic import Field

from ..models import MetadataValue, Model, Snapshot


class Page(Model):
    page: int = Field(ge=0)
    page_size: int = Field(gt=0)
    total_elements: int | None = Field(ge=0)
    total_pages: int | None = Field(ge=0)
    next_page: int | None = Field(ge=0)


class SearchFilter(Model):
    field: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
    value: str = Field(min_length=1, max_length=500)
    operator: Literal["equals", "contains", "authority"] = "equals"


class ItemSummary(Model):
    item_id: str
    title: str
    entity_type: str | None
    authors: list[str]
    dates_issued: list[str]
    identifiers: list[str]
    rights: list[str]
    url: str


class SearchResults(Snapshot):
    query: str
    items: list[ItemSummary]
    pagination: Page


class Item(Snapshot):
    item_id: str
    title: str
    entity_type: str | None
    url: str
    last_modified: str | None
    withdrawn: bool | None
    metadata: dict[str, list[MetadataValue]]


class Container(Model):
    container_id: str
    name: str
    description: list[str]
    archived_items_count: int | None = Field(ge=0)
    url: str


class Containers(Snapshot):
    kind: Literal["communities", "collections"]
    containers: list[Container]
    pagination: Page


class FacetDefinition(Model):
    name: str
    facet_type: str


class FacetValue(Model):
    label: str
    count: int = Field(ge=0)
    authority_key: str | None
    filter: SearchFilter | None


class Facets(Snapshot):
    facet: str | None
    definitions: list[FacetDefinition]
    values: list[FacetValue]
    pagination: Page | None


class Bundle(Model):
    bundle_id: str
    name: str


class Bundles(Snapshot):
    item_id: str
    bundles: list[Bundle]
    pagination: Page


class Checksum(Model):
    algorithm: str
    value: str


class File(Model):
    file_id: str
    name: str
    bundle_name: str | None
    size_bytes: int | None = Field(ge=0)
    checksum: Checksum | None
    rights: list[str]
    content_url: str | None


class Files(Snapshot):
    bundle_id: str
    files: list[File]
    pagination: Page


class DatasetFile(Model):
    file_id: int = Field(gt=0)
    name: str
    directory: str | None
    media_type: str | None
    size_bytes: int | None = Field(ge=0)
    restricted: bool | None
    checksum: Checksum | None


class Dataset(Snapshot):
    persistent_id: str
    dataset_id: int = Field(gt=0)
    version: str
    version_state: str
    title: str | None
    authors: list[str]
    descriptions: list[str]
    subjects: list[str]
    publication_date: str | None
    license_name: str | None
    license_url: str | None
    url: str
    files: list[DatasetFile]
    total_files: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)

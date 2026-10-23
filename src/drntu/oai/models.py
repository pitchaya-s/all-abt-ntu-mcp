"""Typed OAI-PMH metadata and provider pagination."""

from typing import Literal

from ..models import MetadataValue, Model, Snapshot


class OAIIdentify(Snapshot):
    response_date: str
    repository_name: str
    base_url: str
    protocol_version: Literal["2.0"]
    admin_emails: list[str]
    earliest_datestamp: str
    deleted_record: Literal["no", "transient", "persistent"]
    granularity: Literal["YYYY-MM-DD", "YYYY-MM-DDThh:mm:ssZ"]
    descriptions_xml: list[str]


class OAIMetadataFormat(Model):
    metadata_prefix: str
    schema_url: str
    metadata_namespace: str


class OAIFormats(Snapshot):
    response_date: str
    formats: list[OAIMetadataFormat]


class OAIPagination(Model):
    offset: int
    page_count: int
    next_offset: int | None
    resumption_token: str | None
    cursor: int | None
    complete_list_size: int | None
    expiration_date: str | None


class OAISet(Model):
    set_spec: str
    name: str
    descriptions_xml: list[str]


class OAISets(Snapshot):
    response_date: str
    sets: list[OAISet]
    pagination: OAIPagination


class OAIRecord(Model):
    identifier: str
    datestamp: str
    set_specs: list[str]
    deleted: bool
    metadata: dict[str, list[MetadataValue]] | None
    metadata_xml: str | None
    about_xml: list[str]


class OAIRecords(Snapshot):
    response_date: str
    headers_only: bool
    records: list[OAIRecord]
    pagination: OAIPagination


class OAIRecordResult(Snapshot):
    response_date: str
    metadata_prefix: str
    record: OAIRecord

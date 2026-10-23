from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Freshness, Model, ScanResult


class Attachment(Model):
    id: str
    file_name: str
    mime_type: str | None = None


class Attachments(Freshness):
    course_id: str
    content_id: str
    attachments: list[Attachment]
    offset: int
    next_offset: int | None


class Download(Model):
    path: str
    bytes_written: int = Field(ge=0)
    downloaded_at: datetime


class FileContent(Model):
    course_id: str
    content_id: str
    attachment_id: str
    file_name: str
    text: str
    truncated: bool
    pages_read: int | None = None
    total_pages: int | None = None
    retrieved_at: datetime


class CourseDownloadFile(Model):
    content_id: str
    attachment_id: str
    path: str
    status: Literal['downloaded', 'skipped_existing', 'failed']
    bytes_written: int | None = None


class CourseDownload(ScanResult):
    course_id: str
    destination: str
    files: list[CourseDownloadFile]
    bytes_written: int

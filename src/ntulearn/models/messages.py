from datetime import datetime
from typing import Literal

from .common import Model, ScanResult
from .people import Person


class MessageSummary(Model):
    id: str
    course_id: str
    conversation_id: str
    subject: str | None = None
    sender: Person
    created: datetime | None = None
    read: bool | None = None
    folder: Literal['inbox', 'sent']


class Messages(ScanResult):
    folder: Literal['inbox', 'sent']
    messages: list[MessageSummary]
    offset: int
    next_offset: int | None


class MessageDetail(ScanResult):
    message: MessageSummary
    body: str | None = None
    recipients: list[Person]
    recipient_categories: list[str]
    includes_all_course_members: bool | None = None
    excluded_participant_ids: list[str]
    recipients_scope: Literal['conversation_participants'] = 'conversation_participants'

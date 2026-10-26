from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class OneStopError(RuntimeError):
    """An error safe to return to an MCP client."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AuthStatus(Model):
    credentials_configured: bool | None
    credential_storage: Literal["os_keyring"] = "os_keyring"
    credential_error: str | None
    session_verified: bool
    last_verified_at: datetime | None
    session_storage: Literal["in_memory_only"] = "in_memory_only"
    cache_ttl_seconds: int = 60


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class Pagination(Model):
    offset: int = Field(ge=0)
    available_count: int = Field(ge=0)
    total_count: int | None = Field(ge=0)
    complete: bool
    next_offset: int | None = Field(ge=0)


class Category(Model):
    category_id: str
    title: str
    parent_id: str | None
    item_count: int
    total_item_count: int


class Categories(Snapshot):
    categories: list[Category]
    root_count: int
    total_root_count: int
    complete: bool


class CatalogItem(Model):
    item_id: str
    title: str
    summary: str | None
    kind: Literal["form", "external", "knowledge", "content"]
    url: str
    form_item_id: str | None


class CatalogItems(Snapshot, Pagination):
    scope: Literal["popular", "category", "search"]
    query: str
    category_id: str | None
    items: list[CatalogItem]


class Choice(Model):
    value: str
    label: str


class FormField(Model):
    name: str
    label: str
    type: str
    mandatory: bool
    read_only: bool
    choices: list[Choice]


class CatalogItemDetails(Snapshot):
    item_id: str
    title: str
    summary: str | None
    description: str
    mandatory_attachment: bool | None
    fields: list[FormField]


class KnowledgeResult(Model):
    article_id: str
    number: str
    title: str
    summary: str | None
    published: str | None
    url: str


class KnowledgeResults(Snapshot, Pagination):
    query: str
    articles: list[KnowledgeResult]


class Link(Model):
    label: str
    url: str


class KnowledgeArticle(Snapshot):
    article_id: str
    number: str
    title: str
    updated_on: str | None
    text: str
    total_characters: int
    offset: int
    next_offset: int | None
    links: list[Link]


class RequestSummary(Model):
    request_id: str
    kind: Literal["case", "request"]
    state_group: Literal["open", "closed"]
    title: str
    number: str | None
    state: str | None
    created_on: str | None
    record_type: str
    url: str
    detail_supported: bool


class ListCoverage(Model):
    kind: Literal["case", "request"]
    state_group: Literal["open", "closed"]
    available_count: int
    source_count: int
    source_count_is_lower_bound: bool
    complete: bool


class Requests(Snapshot, Pagination):
    requests: list[RequestSummary]
    coverage: list[ListCoverage]


class NamedValue(Model):
    name: str
    label: str
    value: str | None


class RequestItemStage(Model):
    item_id: str
    stage: str | None


class RequestRecordDetails(Model):
    record_id: str
    record_type: str
    fields: list[NamedValue]
    variables: list[NamedValue]


class RequestDetails(Snapshot):
    request: RequestSummary
    records: list[RequestRecordDetails]
    requested_items: list[RequestItemStage]


class ActionResult(Model):
    operation: str
    completed_at: datetime
    source_url: str
    resource_id: str | None
    outcome: Literal["completed", "unchanged", "uncertain", "requires_user_action"]
    verified: bool
    message: str | None
    references: list[NamedValue]


class DraftField(FormField):
    value: str | None
    display_value: str | None
    reference: bool


class RequestDraft(Model):
    draft_id: str
    item_id: str
    title: str
    source_url: str
    expires_at: datetime
    state: Literal["prepared", "submitting", "submitted", "uncertain"]
    ready: bool
    missing_fields: list[str]
    invalid_fields: list[str]
    fields: list[DraftField]
    available_actions: list[str]
    receipt_id: str | None = None


class ReferenceChoice(Model):
    value: str
    label: str


class ReferenceChoices(Model):
    draft_id: str
    field_name: str
    query: str
    choices: list[ReferenceChoice]
    complete: bool


class PortalRecord(Model):
    record_id: str | None
    title: str
    url: str | None
    fields: list[NamedValue]


class PortalRecords(Snapshot, Pagination):
    records: list[PortalRecord]


class Dashboard(Snapshot):
    announcements: list[PortalRecord]
    actions: list[PortalRecord]
    appointments: list[PortalRecord]
    popular_links: list[PortalRecord]


class CartItem(Model):
    cart_item_id: str
    item_id: str | None
    title: str
    quantity: int
    quantity_editable: bool
    price_label: str | None


class SavedCart(Model):
    cart_id: str
    name: str


class CartState(Snapshot):
    items: list[CartItem]
    saved_carts: list[SavedCart]
    delivery_address: str | None
    special_instructions: str | None
    two_step_checkout: bool


class CartCheckout(Model):
    checkout_id: str
    source_url: str
    expires_at: datetime
    items: list[CartItem]
    delivery_address: str
    special_instructions: str


class AppointmentConfiguration(Model):
    draft_id: str
    item_id: str
    enabled: bool
    duration_minutes: int | None
    future_bookable_days: int | None
    bookable_weekdays: str | None
    mandatory: bool


class AppointmentSlot(Model):
    slot_id: str
    start: str
    end: str
    start_utc: str | None
    end_utc: str | None
    label: str


class AppointmentSlots(Model):
    draft_id: str
    date: str
    timezone: str | None
    slots: list[AppointmentSlot]
    retrieved_at: datetime


class Favourite(Model):
    favourite_id: str
    item_id: str
    title: str
    pinned: bool


class Favourites(Snapshot):
    items: list[Favourite]
    pinned_count: int
    maximum_pins: int = 4


class ProfileField(Model):
    name: str
    label: str
    value: str | None
    type: str
    read_only: bool
    choices: list[Choice]


class Preference(Model):
    name: str
    label: str
    value: str | None
    enabled: bool
    choices: list[Choice]


class ProfileSettings(Snapshot):
    fields: list[ProfileField]
    preferences: list[Preference]
    notifications_enabled: bool | None
    can_update_picture: bool


class PaymentServiceDetails(Snapshot):
    service_id: str
    title: str
    fixed_amount: str | None


class PaymentHandoff(Model):
    service_id: str
    title: str
    checkout_url: str
    requires_browser_completion: Literal[True] = True


class ArticleFeedback(Snapshot):
    article_id: str
    can_rate: bool
    can_mark_helpful: bool
    can_comment: bool
    can_flag: bool
    can_subscribe: bool
    subscribed: bool
    inherited_subscription: bool
    can_favourite: bool
    favourite: bool
    send_channels: list[str]
    reasons: list[Choice]


class ArticleComment(Model):
    comment_id: str
    parent_id: str | None
    author: str | None
    created_on: str | None
    text: str
    liked: bool
    can_delete: bool
    attachment_ids: list[str]


class ArticleComments(Snapshot, Pagination):
    article_id: str
    comments: list[ArticleComment]


class ActivityEntry(Model):
    entry_id: str
    author: str | None
    created_on: str | None
    kind: Literal["comment", "attachment"]
    text: str
    attachment_id: str | None


class RequestActivity(Snapshot):
    request_id: str
    record_id: str
    entries: list[ActivityEntry]
    available_actions: list[str]
    can_reply: bool
    can_upload_attachment: bool


class Attachment(Model):
    attachment_id: str
    file_name: str
    size_bytes: int | None
    size_label: str | None
    content_type: str | None
    url: str
    can_delete: bool


class RequestAttachmentTarget(Model):
    kind: Literal["request"]
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    record_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class ArticleAttachmentTarget(Model):
    kind: Literal["article"]
    article_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class CommentAttachmentTarget(Model):
    kind: Literal["article_comment"]
    article_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    comment_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class DraftAttachmentTarget(Model):
    kind: Literal["draft"]
    draft_id: str = Field(min_length=16, max_length=100)


class Attachments(Snapshot):
    attachments: list[Attachment]
    can_upload: bool
    max_upload_bytes: int


class FileDownload(Model):
    attachment_id: str
    path: str
    bytes_written: int
    sha256: str
    downloaded_at: datetime


AttachmentTarget = Annotated[
    RequestAttachmentTarget | ArticleAttachmentTarget | CommentAttachmentTarget | DraftAttachmentTarget,
    Field(discriminator="kind"),
]

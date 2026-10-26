"""MCP contracts for the portal's native workflows."""

from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .appointments import AppointmentService
from .attachments import AttachmentService
from .cart import CartService, FavouriteService
from .forms import FormService
from .knowledge import KnowledgeService
from .models import (
    ActionResult, AppointmentConfiguration, AppointmentSlots, ArticleComments, ArticleFeedback,
    Attachments, AttachmentTarget, CartCheckout, CartState, Dashboard, Favourites, FileDownload,
    OneStopError, PaymentHandoff, PaymentServiceDetails, PortalRecords, ProfileSettings,
    ReferenceChoices, RequestActivity, RequestDraft,
)
from .portal import PortalService
from .tickets import TicketService


ID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Token = Annotated[str, Field(min_length=16, max_length=100)]
Limit = Annotated[int, Field(ge=1, le=100, strict=True)]
Offset = Annotated[int, Field(ge=0, strict=True)]
Message = Annotated[str, Field(min_length=1, max_length=20000)]


class WorkflowTools:
    def __init__(self, session, reader):
        self.forms = FormService(session)
        self.knowledge = KnowledgeService(session)
        self.tickets = TicketService(session, reader)
        self.files = AttachmentService(session, self.tickets, self.knowledge)
        self.portal = PortalService(session)
        self.cart = CartService(session)
        self.favourites = FavouriteService(session)
        self.appointments = AppointmentService(session, self.forms)

    def prepare_request(self, item_id: ID, values: dict[str, str] | None = None) -> RequestDraft:
        """Prepare a native catalog form in a private in-memory browser tab. Use form_item_id from catalog results. values maps visible editable question names to strings. Runs native change scripts and reports missing/invalid questions without submitting. Password fields, hidden/read-only values and scripts are refused. Drafts expire after 15 minutes; at most four are open."""
        return self.forms.prepare(item_id, values)

    def get_request_draft(self, draft_id: Token) -> RequestDraft:
        """Inspect a local catalog draft's current visible fields, caller-supplied values, choices, missing requirements, native actions and any submission receipt. Personal defaults are omitted. Does not submit."""
        return self.forms.get(draft_id)

    def update_request_draft(self, draft_id: Token, values: dict[str, str]) -> RequestDraft:
        """Change editable questions on an in-memory draft and rerun native change scripts. Set controlling questions first when conditional questions are hidden. Updating answers invalidates the latest appointment slots; select a slot again before booking."""
        return self.forms.update(draft_id, values)

    def submit_request(self, draft_id: Token,
                       action: Literal["submit", "add_to_cart", "save_favourite"] = "submit") -> ActionResult:
        """Execute a native action on a reviewed local draft: submit a real request, add it to your cart, or save it to favourites when that button is offered. Uses native form validation and one submission attempt. Reusing a completed draft returns its receipt. An uncertain result must be checked in the portal before another submission."""
        return self.forms.submit(draft_id, action)

    def discard_request_draft(self, draft_id: Token) -> ActionResult:
        """Close and discard a local draft. This does not withdraw submitted requests. Previously uploaded server attachments follow ServiceNow retention; use delete_attachment first to remove editable temporary attachments."""
        return self.forms.discard(draft_id)

    def search_form_references(self, draft_id: Token, field_name: str,
                               query: Annotated[str, Field(min_length=1, max_length=100)], limit: Limit = 20) -> ReferenceChoices:
        """Search a visible reference question using its native picker and original reference qualifier. Use returned value IDs in update_request_draft. Supports the portal's leading * wildcard. Encoded-query operators and arbitrary tables/filters are refused."""
        return self.forms.search_references(draft_id, field_name, query, limit)

    def get_dashboard(self) -> Dashboard:
        """Read your One Stop homepage announcements, actions/payment links, upcoming appointments and popular links. Homepage groups may be limited; use the dedicated list tools for their full pages."""
        return self.portal.dashboard()

    def list_announcements(self, limit: Limit = 20, offset: Offset = 0) -> PortalRecords:
        """Read One Stop announcements, summaries and links from the native announcements collection with local pagination."""
        return self.portal.list_announcements(limit, offset)

    def list_my_actions(self, limit: Limit = 20, offset: Offset = 0) -> PortalRecords:
        """Read your One Stop to-do/billing actions and their published due dates and payment links. Source counts can be capped; inspect complete. Does not perform an action or pay a bill."""
        return self.portal.list_actions(limit, offset)

    def list_popular_links(self, limit: Limit = 20, offset: Offset = 0) -> PortalRecords:
        """List links on One Stop's Popular Sites page, preserving native catalog, knowledge and external destinations."""
        return self.portal.list_popular_links(limit, offset)

    def get_profile(self) -> ProfileSettings:
        """Read your own displayed profile fields, editable flags, preferences/choices, notification setting and picture-upload capability. Does not retrieve another user's profile or change identity/security settings."""
        return self.portal.get_profile()

    def update_profile(self, field_name: str, value: Annotated[str, Field(max_length=10000)]) -> ActionResult:
        """Update one displayed editable own-profile field through its native inline editor. Copy field_name from get_profile; bio addresses the live-profile description. Read-only, hidden and password fields are not editable. The server's field validation and permissions apply."""
        return self.portal.update_profile(field_name, value)

    def update_profile_picture(self, file_path: str) -> ActionResult:
        """Upload the explicitly selected local image as your own ServiceNow profile picture using the native file input. Requires an absolute path, a supported image MIME type and a file at most 20 MB. This changes your profile picture."""
        return self.portal.update_picture(file_path)

    def set_notifications(self, enabled: bool) -> ActionResult:
        """Enable or disable your ServiceNow notification preference. Reads the current setting first; an already matching value is unchanged."""
        return self.portal.set_notifications(enabled)

    def set_user_preference(self, name: Literal["accessibility", "voice_input", "analytics", "timezone", "language", "communication_channels"],
                            value: Annotated[str, Field(max_length=500)]) -> ActionResult:
        """Set an enabled own preference returned by get_profile. Use 'true'/'false' for booleans and published choice values for other settings; communication channels are comma-separated choice values. Disabled preferences and identity/MFA/certificate settings are excluded."""
        return self.portal.set_preference(name, value)

    def list_payment_services(self, query: Annotated[str, Field(max_length=100)] = "", limit: Limit = 20,
                              offset: Offset = 0) -> PortalRecords:
        """Search/browse services in the student's native payment directory, preserving its active/category/access filter. Use leading * for substring search. Does not create a payment or charge anything."""
        return self.portal.list_payment_services(query, limit, offset)

    def get_payment_service(self, service_id: ID) -> PaymentServiceDetails:
        """Read a visible payment service's native fixed-amount information. The ID must appear in your payment directory. Variable amounts are completed at the separate payment gateway."""
        return self.portal.get_payment_service(service_id)

    def prepare_payment(self, service_id: ID) -> PaymentHandoff:
        """Ask One Stop to prepare a checkout link for a visible payment service. Returns the native HTTPS gateway URL for the user to open and complete. Does not enter bank/card credentials, authenticate with a bank, or confirm a charge."""
        return self.portal.prepare_payment(service_id)

    def get_article_feedback(self, article_id: ID) -> ArticleFeedback:
        """Read native knowledge capabilities: ratings, helpfulness, comments, flags/reasons, subscription/inheritance, favourites and self-delivery channels. Only controls actually offered for the article can be used."""
        return self.knowledge.get_feedback(article_id)

    def list_article_comments(self, article_id: ID, limit: Limit = 20, offset: Offset = 0) -> ArticleComments:
        """Read visible knowledge comments/replies, author display names, text, dates, reactions, attachment IDs and delete permissions. Pagination covers the retrieved tree; exhaustive coverage is not promised."""
        return self.knowledge.list_comments(article_id, limit, offset)

    def add_article_comment(self, article_id: ID, text: Message, parent_id: ID | None = None) -> ActionResult:
        """Publish plain-text feedback to a knowledge article, or reply to a visible parent comment. This is visible to the article's audience. Use only when the user requests publication; returns the server's comment receipt. Attach files afterward using an article_comment attachment target."""
        return self.knowledge.add_comment(article_id, text, parent_id)

    def delete_article_comment(self, article_id: ID, comment_id: ID) -> ActionResult:
        """Delete a visible article comment only when the native menu permits deletion by the current user. This removes published content; it never accepts an unrelated comment ID."""
        return self.knowledge.delete_comment(article_id, comment_id)

    def set_article_comment_like(self, article_id: ID, comment_id: ID, liked: bool) -> ActionResult:
        """Like or unlike a visible knowledge comment using a desired state. A matching current state is unchanged."""
        return self.knowledge.set_comment_like(article_id, comment_id, liked)

    def rate_article(self, article_id: ID, rating: Annotated[int, Field(ge=1, le=5, strict=True)],
                     reason_id: str | None = None, details: Annotated[str, Field(max_length=10000)] = "") -> ActionResult:
        """Submit a 1–5 star knowledge rating when the native control is enabled. Low ratings can require reason_id from get_article_feedback and optional details; this can create a native feedback task. Does not retry rate-limited or uncertain submissions."""
        return self.knowledge.rate(article_id, rating, reason_id, details)

    def set_article_helpful(self, article_id: ID, helpful: bool, reason_id: str | None = None,
                            details: Annotated[str, Field(max_length=10000)] = "") -> ActionResult:
        """Submit helpful/not-helpful feedback only when the article offers that native control. Negative feedback may require a published reason and create a native feedback task."""
        return self.knowledge.set_helpful(article_id, helpful, reason_id, details)

    def flag_article(self, article_id: ID, text: Annotated[str, Field(min_length=1, max_length=10000)]) -> ActionResult:
        """Flag a knowledge article with the user's explanation when the native flag control is available. Sends feedback to the knowledge owners."""
        return self.knowledge.flag(article_id, text)

    def set_article_subscription(self, article_id: ID, subscribed: bool,
                                 include_knowledge_base: bool = False) -> ActionResult:
        """Subscribe/unsubscribe to article updates. An inherited knowledge-base subscription can only be removed with include_knowledge_base=true, which affects the whole knowledge base. Use that option only when the user explicitly requests that broader change."""
        return self.knowledge.set_subscription(article_id, subscribed, include_knowledge_base)

    def set_article_favourite(self, article_id: ID, favourite: bool) -> ActionResult:
        """Set an article's native favourite state when its Favourite control is enabled. Reads current state and avoids toggling an already matching value."""
        return self.knowledge.set_favourite(article_id, favourite)

    def send_article_to_self(self, article_id: ID, channel: Literal["email", "sms"] = "email") -> ActionResult:
        """Send this article to your registered email/SMS channel using the native Send to myself action. Use only after the user explicitly requests sending; no alternate recipient is accepted. Acknowledgement does not guarantee delivery."""
        return self.knowledge.send_to_self(article_id, channel)

    def get_request_activity(self, request_id: ID, record_id: ID | None = None) -> RequestActivity:
        """Read visible comments and attachment events on a verified own request/item, plus current reply/upload/state-action permissions. Work notes are excluded. Select record_id from get_my_request when it has multiple records."""
        return self.tickets.activity(request_id, record_id)

    def reply_to_request(self, request_id: ID, text: Message, record_id: ID | None = None) -> ActionResult:
        """Post a real additional comment to a verified own ticket/item when its current native state permits replying. Sends only to the comments journal, never work notes. Do not repeat an uncertain reply; inspect activity first."""
        return self.tickets.reply(request_id, text, record_id)

    def take_request_action(self, request_id: ID, action: Literal["close", "reopen", "accept_solution", "reject_solution"],
                            record_id: ID | None = None) -> ActionResult:
        """Execute a state action currently offered by the native own-ticket page. Read get_request_activity.available_actions first. Does not invent unavailable close/reopen/solution actions or accept arbitrary state/table values."""
        return self.tickets.take_action(request_id, action, record_id)

    def list_attachments(self, target: AttachmentTarget) -> Attachments:
        """List attachments on a verified own request/item, a readable knowledge article/comment, or an active local draft. Returns IDs, names, sizes, URLs and upload/delete permissions. Article assets are read-only; comments are editable only when the native menu permits it."""
        return self.files.list(target)

    def upload_attachment(self, target: AttachmentTarget, file_path: str) -> ActionResult:
        """Upload the explicitly selected local file to the verified target when its native upload control permits it. Requires an absolute path and obeys the smaller of the source limit and 20 MB. Article-comment uploads are visible to the article audience. Never chooses files automatically."""
        return self.files.upload(target, file_path)

    def download_attachment(self, target: AttachmentTarget, attachment_id: ID, destination: str) -> FileDownload:
        """Download a listed attachment of the verified target to a new explicit absolute file path, up to 20 MB. Existing files and symbolic-link destinations are refused. Returns file size and SHA-256; does not execute or automatically open files."""
        return self.files.download(target, attachment_id, destination)

    def delete_attachment(self, target: AttachmentTarget, attachment_id: ID) -> ActionResult:
        """Delete an attachment only when it is listed on the verified target and native editing is allowed. Knowledge article assets and closed/read-only ticket attachments cannot be deleted."""
        return self.files.delete(target, attachment_id)

    def rename_attachment(self, target: AttachmentTarget, attachment_id: ID,
                           file_name: Annotated[str, Field(min_length=1, max_length=200)]) -> ActionResult:
        """Rename a listed editable attachment using the native attachment service. The new name cannot contain path separators or control characters."""
        return self.files.rename(target, attachment_id, file_name)

    def get_cart(self) -> CartState:
        """Read your native shopping cart, item quantities/prices, saved-cart IDs/names and checkout defaults. Does not order, load or alter any cart."""
        return self.cart.get()

    def get_saved_cart(self, saved_cart_id: ID) -> PortalRecords:
        """Inspect items in a verified own saved cart before loading it. Does not merge or replace the active cart."""
        return self.cart.get_saved(saved_cart_id)

    def update_cart(self, action: Literal["set_quantity", "remove", "clear", "load_saved", "replace_with_saved", "delete_saved"],
                     item_id: ID | None = None, quantity: Annotated[int, Field(ge=1, le=100, strict=True)] | None = None,
                     saved_cart_id: ID | None = None) -> ActionResult:
        """Change your native cart: set a permitted quantity, remove/clear items, append a saved cart, replace with a saved cart, or delete a saved cart. IDs must appear in get_cart. replace_with_saved replaces current contents; load_saved appends. Does not checkout."""
        return self.cart.update(action, item_id, quantity, saved_cart_id)

    def save_cart(self, name: Annotated[str, Field(min_length=1, max_length=100)],
                   item_ids: list[ID] | None = None) -> ActionResult:
        """Save the current cart, or selected own cart item IDs, as a new named cart using native name/selection validation. Existing saved names are not overwritten. Does not submit an order."""
        return self.cart.save(name, item_ids)

    def prepare_cart_checkout(self, delivery_address: Annotated[str, Field(max_length=10000)] | None = None,
                               special_instructions: Annotated[str, Field(max_length=10000)] | None = None) -> CartCheckout:
        """Create a 15-minute local checkout preview with the current own cart, delivery address and instructions. Does not order anything. submit_cart_checkout rechecks that cart contents have not changed."""
        return self.cart.prepare_checkout(delivery_address, special_instructions)

    def submit_cart_checkout(self, checkout_id: Token) -> ActionResult:
        """Submit a reviewed cart checkout exactly once after checking account identity, expiry and unchanged cart contents. Returns the native request receipt. Accounts requiring an additional two-step form receive a portal handoff. Uncertain submissions must be inspected before another checkout."""
        return self.cart.submit_checkout(checkout_id)

    def list_favourites(self) -> Favourites:
        """Read your saved catalog favourites and which are pinned to the homepage. The native portal permits up to four pins."""
        return self.favourites.list()

    def update_favourite(self, action: Literal["pin", "unpin", "remove", "clear"],
                          favourite_id: ID | None = None) -> ActionResult:
        """Pin/unpin/remove one own saved favourite or clear all favourites. The native four-pin limit and unpin-before-removal rules apply. clear affects every unpinned favourite; it does not clear the shopping cart."""
        return self.favourites.update(action, favourite_id)

    def set_catalog_favourite(self, category_id: ID, item_id: ID, favourite: bool) -> ActionResult:
        """Set a catalog item's favourite state through its category's native control. Both IDs must match a visible category item. Uses the desired state and verifies it against your favourites list."""
        return self.favourites.set_catalog_favourite(category_id, item_id, favourite)

    def list_my_appointments(self, limit: Limit = 20, offset: Offset = 0) -> PortalRecords:
        """Read your native upcoming appointment list with appointment numbers, published dates/times and locations. This listing exposes no cancellation/rescheduling controls; no appointment is changed."""
        return self.appointments.list(limit, offset)

    def get_appointment_configuration(self, draft_id: Token) -> AppointmentConfiguration:
        """Read the native appointment selector's configuration on a local catalog draft: enabled/mandatory flags, duration, booking horizon and weekdays. Use an appointment service's form_item_id to prepare the draft."""
        return self.appointments.configuration(draft_id)

    def get_appointment_slots(self, draft_id: Token, date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]) -> AppointmentSlots:
        """Read available appointment windows for one day using the draft's current native location/contact/reason configuration. Returned slot IDs are bound to this draft's latest lookup. No time is reserved or booked; availability can change until submission."""
        return self.appointments.slots(draft_id, date)

    def select_appointment_slot(self, draft_id: Token, slot_id: Token) -> RequestDraft:
        """Select a slot from this draft's latest availability lookup using the native appointment event. Updates the local form and validation preview only. Changing draft answers requires another availability lookup and selection."""
        return self.appointments.select(draft_id, slot_id)

    def book_appointment(self, draft_id: Token, slot_id: Token | None = None) -> ActionResult:
        """Book an appointment by optionally selecting a verified slot and submitting the reviewed native catalog draft once. All native mandatory questions must be complete. Reusing a completed draft returns its receipt; uncertain bookings are never auto-retried."""
        return self.appointments.book(draft_id, slot_id)


READ_TOOLS = (
    "get_request_draft", "search_form_references", "get_dashboard", "list_announcements", "list_my_actions", "list_popular_links",
    "get_profile", "list_payment_services", "get_payment_service", "get_article_feedback", "list_article_comments",
    "get_request_activity", "list_attachments", "get_cart", "get_saved_cart", "list_favourites", "list_my_appointments",
    "get_appointment_configuration", "get_appointment_slots",
)
LOCAL_TOOLS = ("prepare_request", "update_request_draft", "discard_request_draft", "prepare_cart_checkout", "select_appointment_slot")
WRITE_TOOLS = (
    "submit_request", "update_profile", "update_profile_picture", "set_notifications", "set_user_preference", "prepare_payment",
    "add_article_comment", "delete_article_comment", "set_article_comment_like", "rate_article", "set_article_helpful",
    "flag_article", "set_article_subscription", "set_article_favourite", "send_article_to_self", "reply_to_request",
    "take_request_action", "upload_attachment", "download_attachment", "delete_attachment", "rename_attachment",
    "update_cart", "save_cart", "submit_cart_checkout", "update_favourite", "set_catalog_favourite", "book_appointment",
)
IDEMPOTENT_WRITES = {
    "update_profile", "set_notifications", "set_user_preference", "set_article_comment_like", "set_article_subscription",
    "set_article_favourite", "delete_attachment", "rename_attachment", "set_catalog_favourite", "update_favourite",
}
DESTRUCTIVE_TOOLS = {"delete_article_comment", "delete_attachment", "update_cart", "update_favourite", "take_request_action"}


def register_tools(mcp, session, reader):
    workflows = WorkflowTools(session, reader)
    for name in (*READ_TOOLS, *LOCAL_TOOLS, *WRITE_TOOLS):
        function = getattr(workflows, name)

        def checked(*args, _function=function, _writes=name in WRITE_TOOLS, **kwargs):
            try:
                return _function(*args, **kwargs)
            except OneStopError as error:
                raise ToolError(str(error)) from None
            except (KeyError, TypeError, ValueError, AttributeError):
                if _writes:
                    raise ToolError("The action result could not be verified. It may have completed; check the portal before repeating it.") from None
                raise ToolError("One Stop returned an unexpected workflow format or invalid input; no successful action was inferred.") from None

        # Preserve the actual bound method's contract for MCP schema generation.
        from functools import wraps
        checked = wraps(function)(checked)
        annotations = ToolAnnotations(readOnlyHint=name not in WRITE_TOOLS,
                                      idempotentHint=name in READ_TOOLS or name in IDEMPOTENT_WRITES,
                                      destructiveHint=name in DESTRUCTIVE_TOOLS, openWorldHint=True)
        mcp.tool(name="onestop_" + name, annotations=annotations)(checked)
    return workflows

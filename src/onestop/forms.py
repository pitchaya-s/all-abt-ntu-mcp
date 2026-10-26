"""In-memory native catalog drafts and single-attempt submission."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
import secrets
import time
from urllib.parse import urlsplit

from .browser import action_result, commit, evaluate, picker_query
from .models import DraftField, NamedValue, OneStopError, ReferenceChoice, ReferenceChoices, RequestDraft
from .parser import sys_id
from .session import BASE, page_url


CATALOG_WIDGET = "ntu-widget-sc-cat-item-v2"
LAYOUT_TYPES = ["container_start", "container_end", "container_split", "widget", "macro", "macro_with_label", "label", "rich_text_label"]


@dataclass
class Draft:
    draft_id: str
    item_id: str
    revision: str
    page: object
    expires_at: datetime
    deadline: float
    values: dict = field(default_factory=dict)
    state: str = "prepared"
    preview: RequestDraft | None = None
    receipt: object = None
    slots: dict = field(default_factory=dict)
    appointment_selected: bool = False


def draft_for(session, revision, draft_id, editable=True):
    draft = session._drafts.get(draft_id)
    if draft is None or draft.revision != revision:
        raise OneStopError("This local request draft is unavailable for the current account.")
    if time.monotonic() > draft.deadline:
        session._drafts.pop(draft_id, None)
        draft.page.close()
        raise OneStopError("This local request draft expired; prepare it again.")
    if editable and draft.state != "prepared":
        raise OneStopError("This draft has already been submitted or has an uncertain submission; check its receipt or request list.")
    u = urlsplit(draft.page.url)
    if draft.state == "prepared" and (u.scheme != "https" or u.netloc != urlsplit(BASE).netloc):
        raise OneStopError("The draft left the One Stop portal; prepare it again.")
    return draft


def preview(draft):
    data = evaluate(draft.page, r"""
      const s=scope('ntu-widget-sc-cat-item-v2'), i=s.data.sc_cat_item;
      if(!i || i.sys_id!==args.item_id || !i.can_view) throw new Error('Wrong catalog form');
      const gf=catalogForm();
      const fields=Object.values(i._fields||{}).filter(f=>f.visible===true &&
        !args.layout.includes(f.type) && f.label && f.type!=='password' && f.type!=='password2');
      const missing=[], invalid=[];
      const output=fields.map(f=>{
        const v=gf.getValue(f.name);
        if(f.mandatory && (v==null || String(v).trim()==='' || f.mandatory_filled===false)) missing.push(f.name);
        if(f.isInvalid || f.isRegexInvalid) invalid.push(f.name);
        const supplied=Object.prototype.hasOwnProperty.call(args.values,f.name);
        return {name:f.name,label:f.label,type:f.type,mandatory:f.mandatory===true,
          read_only:f.readonly===true||f.read_only===true,
          choices:(f.choices||[]).map(c=>({value:String(c.value),label:c.label})),
          value:supplied?String(v??''):null,
          display_value:supplied?String(f.displayValue??f.display_value??v??''):null,
          reference:f.type==='reference'||f.type==='glide_list'};
      });
      const appointment=scopes.find(x=>x.widget.id==='sn-appointment-booking-select');
      if(appointment?.c?.isConfigValid && appointment.c.isAppointmentMandatory &&
         (!appointment.isAppointmentMandatoryFilled()||!args.appointment_selected)) missing.push('appointment');
      const actions=[];
      if(s.c.allowOrder() && s.c.showOrderNowButton()) actions.push('submit');
      if(s.data.sys_properties.cartEnabled && s.c.showAddCartBtn()) actions.push('add_to_cart');
      if(s.c.showAddToWishlist()) actions.push('save_favourite');
      if(s.c.showAttachments()) actions.push('upload_attachment');
      return {title:i.name,fields:output,missing,invalid,actions};
    """, {"item_id": draft.item_id, "values": draft.values, "layout": LAYOUT_TYPES,
           "appointment_selected": draft.appointment_selected})
    draft.preview = RequestDraft(draft_id=draft.draft_id, item_id=draft.item_id, title=data["title"],
                                 source_url=page_url("sc_cat_item", {"sys_id": draft.item_id}), expires_at=draft.expires_at,
                                 state=draft.state, ready=not data["missing"] and not data["invalid"],
                                 missing_fields=data["missing"], invalid_fields=data["invalid"],
                                 fields=[DraftField(**f) for f in data["fields"]], available_actions=data["actions"])
    return draft.preview


def apply_values(draft, values):
    if not isinstance(values, dict) or len(values) > 100 or any(
        not isinstance(k, str) or not isinstance(v, str) or len(v) > 50000 or "\0" in v for k, v in values.items()
    ) or sum(len(v) for v in values.values()) > 200000:
        raise OneStopError("Supply at most 100 field values as strings, up to 50,000 characters each and 200,000 total.")
    draft.slots.clear()
    draft.appointment_selected = False
    pending = dict(values)
    while pending:
        progress = False
        for name, value in list(pending.items()):
            state = evaluate(draft.page, r"""
              const s=scope('ntu-widget-sc-cat-item-v2'), i=s.data.sc_cat_item;
              const f=Object.values(i._fields).find(f=>f.name===args.name);
              if(!f) return 'unknown';
              if(args.layout.includes(f.type)||f.type==='password'||f.type==='password2') return 'unsupported';
              if(f.readonly===true||f.read_only===true) return 'readonly';
              if(f.visible!==true) return 'hidden';
              catalogForm().setValue(args.name,args.value);
              s.$evalAsync();
              return 'set';
            """, {"name": name, "value": value, "layout": LAYOUT_TYPES})
            if state == "set":
                draft.values[name] = value
                pending.pop(name)
                progress = True
                draft.page.wait_for_load_state("networkidle", timeout=15000)
            elif state != "hidden":
                raise OneStopError("A supplied question is unknown, read-only, or an unsupported/password field; inspect the draft's visible questions.")
        if not progress:
            raise OneStopError("A supplied question is hidden. Update its controlling questions first, then inspect the draft again.")
    return preview(draft)


class FormService:
    def __init__(self, session):
        self.session = session

    def prepare(self, item_id, values=None):
        return self.session.workflow(self._prepare, sys_id(item_id), values or {})

    def _prepare(self, session, revision, item_id, values):
        for key, draft in list(session._drafts.items()):
            if time.monotonic() > draft.deadline:
                draft.page.close()
                session._drafts.pop(key)
        if len(session._drafts) >= 4:
            raise OneStopError("Four local drafts are already open. Discard a draft before preparing another.")
        page = session._context.new_page()
        try:
            page.goto(page_url("sc_cat_item", {"sys_id": item_id}), wait_until="networkidle", timeout=30000)
            page.wait_for_function("typeof angular!=='undefined' && [...document.querySelectorAll('[form-model][mandatory]')].some(e=>{const s=angular.element(e).isolateScope();return s?.formModel?.sys_id&&s.getGlideForm?.();})", timeout=15000)
            now = datetime.now(timezone.utc)
            draft = Draft(secrets.token_urlsafe(24), item_id, revision, page, now + timedelta(minutes=15), time.monotonic() + 900)
            result = apply_values(draft, values)
            session._drafts[draft.draft_id] = draft
            return result
        except Exception:
            page.close()
            raise

    def get(self, draft_id):
        return self.session.workflow(self._get, draft_id)

    def _get(self, session, revision, draft_id):
        draft = draft_for(session, revision, draft_id, editable=False)
        if draft.state != "prepared":
            return draft.preview.model_copy(update={"state": draft.state,
                                                   "receipt_id": draft.receipt.resource_id if draft.receipt else None})
        return preview(draft)

    def update(self, draft_id, values):
        return self.session.workflow(self._update, draft_id, values)

    def _update(self, session, revision, draft_id, values):
        return apply_values(draft_for(session, revision, draft_id), values)

    def discard(self, draft_id):
        return self.session.workflow(self._discard, draft_id)

    def _discard(self, session, revision, draft_id):
        draft = draft_for(session, revision, draft_id, editable=False)
        draft.page.close()
        session._drafts.pop(draft_id)
        return action_result("discard_request_draft", draft.preview.source_url, draft_id, verified=True,
                             message="The local draft was discarded. Previously uploaded server attachments follow ServiceNow's retention policy.")

    def submit(self, draft_id, action="submit"):
        if action not in {"submit", "add_to_cart", "save_favourite"}:
            raise OneStopError("Unsupported request draft action.")
        return self.session.workflow(self._submit, draft_id, action)

    def _submit(self, session, revision, draft_id, action):
        draft = draft_for(session, revision, draft_id, editable=False)
        if draft.state == "submitted" and draft.receipt:
            return draft.receipt.model_copy(update={"outcome": "unchanged"})
        if draft.state != "prepared":
            raise OneStopError("This draft has an uncertain submission. Check your request list before preparing another submission.")
        info = preview(draft)
        if action not in info.available_actions:
            raise OneStopError("The native portal does not offer this action for this form.")
        if action != "save_favourite" and not info.ready:
            return action_result(action, info.source_url, draft_id, outcome="requires_user_action",
                                 message="Complete the draft's missing or invalid questions before submitting.")
        expected = {"submit": ("submit_producer", "order_now"), "add_to_cart": ("add_to_cart",),
                    "save_favourite": ("add_to_wishlist",)}[action]
        attempts = []

        def matches(request):
            u = urlsplit(request.url)
            return (u.netloc == urlsplit(BASE).netloc and request.method == "POST"
                    and any(u.path.endswith("/items/" + draft.item_id + "/" + suffix) for suffix in expected))

        def record_attempt(request):
            if matches(request):
                attempts.append(True)

        def perform():
            from playwright.sync_api import TimeoutError
            draft.state = "submitting"
            draft.page.on("request", record_attempt)
            try:
                try:
                    with draft.page.expect_response(lambda r: matches(r.request), timeout=30000) as response_info:
                        evaluate(draft.page, "const s=scope('ntu-widget-sc-cat-item-v2'); const methods={submit:'triggerOnSubmit',add_to_cart:'triggerAddToCart',save_favourite:'addToWishlist'}; s[methods[args]](); return true;", action)
                    response = response_info.value
                except TimeoutError:
                    draft.state = "uncertain" if attempts else "prepared"
                    return action_result(action, info.source_url, draft_id,
                                         outcome="uncertain" if attempts else "requires_user_action",
                                         message="Check the portal before repeating the action." if attempts else
                                                 "Native form validation or an additional order confirmation prevented submission. Inspect the draft and portal.")
                if response.status not in {200, 201} or len(response.body()) > 1000000:
                    draft.state = "uncertain"
                    return action_result(action, info.source_url, draft_id, outcome="uncertain",
                                         message="The server did not return a verifiable receipt. Check the portal before retrying.")
                data = response.json().get("result", {})
                resource_id = data.get("sys_id") or data.get("request_id")
                if not resource_id and action != "submit":
                    items = data.get("items") or []
                    resource_id = next((i.get("cart_item_id") for i in items if i.get("catalog_item_id") == draft.item_id), None)
                if not isinstance(resource_id, str) or not re.fullmatch(r"[0-9a-f]{32}", resource_id):
                    draft.state = "uncertain"
                    return action_result(action, info.source_url, draft_id, outcome="uncertain",
                                         message="A submission response arrived without a record receipt. Check the portal before retrying.")
                refs = [NamedValue(name="number", label="Reference number", value=str(data["number"]))] if data.get("number") else []
                draft.receipt = action_result(action, info.source_url, resource_id, verified=True, references=refs,
                                               message="The native portal returned a submission receipt.")
                draft.state = "submitted"
                return draft.receipt
            except Exception:
                draft.state = "uncertain"
                raise
            finally:
                draft.page.remove_listener("request", record_attempt)

        return commit(session, revision, perform)

    def search_references(self, draft_id, field_name, query, limit=20):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100 or any(ord(c) < 32 or ord(c) == 127 for c in query) or type(limit) is not int or not 1 <= limit <= 100:
            raise OneStopError("Use a reference query of 1–100 characters and limit from 1 to 100.")
        return self.session.workflow(self._search_references, draft_id, field_name, query.strip(), limit)

    def _search_references(self, session, revision, draft_id, field_name, query, limit):
        draft = draft_for(session, revision, draft_id)
        status = evaluate(draft.page, r"""
          const s=scope('ntu-widget-sc-cat-item-v2');
          const f=Object.values(s.data.sc_cat_item._fields).find(f=>f.name===args);
          if(!f||f.visible!==true||!['reference','glide_list'].includes(f.type)) return false;
          const e=document.getElementById('sp_formfield_'+args);
          if(!e) return false;
          return !!jQuery(e).data('select2');
        """, field_name)
        if not status:
            raise OneStopError("This visible question does not offer a native reference picker.")
        # Use the configured native picker, preserving its reference qualifier.
        # The field name is supplied as data, never inserted into JavaScript.
        result = picker_query(draft.page, "const element=document.getElementById('sp_formfield_'+args.field);",
                              query, extra_args={"field": field_name})
        choices = result["choices"]
        return ReferenceChoices(draft_id=draft_id, field_name=field_name, query=query,
                                choices=[ReferenceChoice(**c) for c in choices[:limit]], complete=not result["more"] and len(choices) <= limit)

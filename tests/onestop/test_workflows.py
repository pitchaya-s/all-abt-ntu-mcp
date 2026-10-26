"""Native widget contracts exercised in Chromium, with no external requests."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from pathlib import Path
import os
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from onestop.appointments import AppointmentService
from onestop.attachments import AttachmentService, FileContext, upload_file
from onestop.browser import commit
from onestop.cart import CartService, FavouriteService
from onestop.forms import Draft, FormService, apply_values, draft_for, preview
from onestop.knowledge import KnowledgeService
from onestop.models import OneStopError
from onestop.portal import PortalService
from onestop.session import BASE, OneStopSession, PortalPage
from onestop.tickets import TicketContext, TicketService
from tests.credential_fixtures import stored_credentials


ITEM, RECORD, COMMENT = "a" * 32, "b" * 32, "c" * 32


class LocalSession:
    def __init__(self, page=None):
        self._page = page
        self._cache = {"old": "data"}
        self._drafts, self._checkouts = {}, {}
        self.before_write = Mock()
        self.snapshot = PortalPage({"article": {"isValid": True, "knowledgeExists": True,
                                  "article_sys_id": ITEM}}, datetime.now(timezone.utc), BASE + "/ntussp", "revision")

    def workflow(self, fn, *args):
        return fn(self, "revision", *args)

    def read(self, *args, **kwargs):
        return self.snapshot


class SubmissionTests(unittest.TestCase):
    def test_commit_checks_identity_and_sanitizes_uncertain_single_attempt(self):
        s = LocalSession()
        fn = Mock(side_effect=RuntimeError("private-cookie-and-password"))
        with self.assertRaisesRegex(OneStopError, "may have completed") as error:
            commit(s, "revision", fn)
        self.assertNotIn("private-cookie", str(error.exception))
        fn.assert_called_once()
        s.before_write.assert_called_once_with("revision")
        self.assertFalse(s._cache)
        s.before_write.side_effect = OneStopError("account changed")
        with self.assertRaisesRegex(OneStopError, "account changed"):
            commit(s, "revision", fn)
        self.assertEqual(fn.call_count, 1)

    def test_session_nested_workflows_do_not_deadlock_and_rotation_clears_handles(self):
        s = OneStopSession()
        self.addCleanup(s.close)
        with stored_credentials():
            s._run(s._credentials)
            s._verified = True
            result = s.workflow(lambda session, revision: session.workflow(lambda same, rev: rev == revision))
            self.assertTrue(result)
            s._drafts["old"] = object()
            s._checkouts["old"] = object()
            with stored_credentials("other-account"):
                s.status()
            self.assertFalse(s._drafts or s._checkouts or s._verified)

    def form(self):
        page = Mock(url=BASE + "/ntussp")
        s = LocalSession(page)
        d = Draft("draft-token-with-entropy", ITEM, "revision", page, datetime.now(timezone.utc) + timedelta(minutes=15), time.monotonic() + 900)
        s._drafts[d.draft_id] = d
        info = SimpleNamespace(available_actions=["submit"], ready=True, source_url=page.url)
        return s, d, info

    def test_request_receipt_prevents_duplicate_submission_even_after_redirect(self):
        s, d, info = self.form()
        response = Mock(status=201)
        response.body.return_value = b'{}'
        response.json.return_value = {"result": {"sys_id": RECORD, "number": "REQ123"}}
        d.page.expect_response.return_value = nullcontext(SimpleNamespace(value=response))
        with patch("onestop.forms.preview", return_value=info), patch("onestop.forms.evaluate") as native:
            service = FormService(s)
            receipt = service.submit(d.draft_id)
            self.assertEqual(receipt.resource_id, RECORD)
            self.assertTrue(receipt.verified)
            d.page.url = "https://external.invalid/confirmation"
            self.assertEqual(service.submit(d.draft_id).outcome, "unchanged")
            native.assert_called_once()

    def test_uncertain_request_blocks_retry_and_native_required_fields_block_write(self):
        s, d, info = self.form()
        info.ready = False
        with patch("onestop.forms.preview", return_value=info):
            self.assertEqual(FormService(s).submit(d.draft_id).outcome, "requires_user_action")
            s.before_write.assert_not_called()
        info.ready = True
        d.page.expect_response.return_value = nullcontext(SimpleNamespace(value=Mock(status=500)))
        with patch("onestop.forms.preview", return_value=info), patch("onestop.forms.evaluate") as native:
            self.assertEqual(FormService(s).submit(d.draft_id).outcome, "uncertain")
            with self.assertRaisesRegex(OneStopError, "uncertain"):
                FormService(s).submit(d.draft_id)
            native.assert_called_once()

    def test_expired_draft_closes_tab_and_wrong_identity_never_accesses_it(self):
        s, d, _ = self.form()
        with self.assertRaisesRegex(OneStopError, "current account"):
            draft_for(s, "other", d.draft_id)
        d.deadline = 0
        with self.assertRaisesRegex(OneStopError, "expired"):
            draft_for(s, "revision", d.draft_id)
        d.page.close.assert_called_once()
        self.assertFalse(s._drafts)


@unittest.skipUnless(find_spec("playwright"), "Optional personal extra is not installed")
class NativeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            cls.pw.stop()
            raise unittest.SkipTest("Optional Chromium is not installed")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route("**/*", lambda route: route.fulfill(status=200, body="<body></body>", content_type="text/html"))
        self.page = self.context.new_page()
        self.page.goto(BASE + "/ntussp")
        self.session = LocalSession(self.page)
        self.page.evaluate("""() => {
          window.calls=[];window.widgets=[];window.services={};window.extra={};
          window.install=(id,data={},c={},name=id)=>{
            const e=document.createElement('div');e.setAttribute('widget','widget');e.setAttribute('data','data');
            const s={widget:{id,name},data,c,$evalAsync:()=>{},server:{
              get:async payload=>{calls.push(payload);return {data:{response:{sys_id:'c'.repeat(32)},success:true,feedbackSuccess:true,responseMessage:'OK',isFavorite:true}};},
              update:async()=>{calls.push(JSON.parse(JSON.stringify(s.data)));return s.data;}}};
            e.native=s;document.body.appendChild(e);widgets.push(s);return s;
          };
          window.angular={element:e=>({scope:()=>e.native,isolateScope:()=>e.native,
            injector:()=>({get:name=>name==='$sce'?{valueOf:v=>v}:services[name]})})};
        }""")

    def tearDown(self):
        self.context.close()

    def calls(self):
        return self.page.evaluate("calls")

    def knowledge(self):
        self.page.evaluate("""() => {
          const a=install('kb-article-content',{article_sys_id:'a'.repeat(32),isSubscriptionEnabled:true,
            feedback_reasons:[{reason_id:'inaccurate',reason_desc:'Inaccurate'}]}, {showFlagArticle:true});
          install('knowledge-article-helpful',{rating_threshold:2,actionablefeedback_helpful_enabled:true}, {showRatings:true,show_helpful:true});
          install('knowledge-comments',{disabled:false},{isLoggedInUser:true,comments:[{
            sys_id:'c'.repeat(32),comment_text:'<p>Visible text</p>',is_liked:false,user:{name:'Synthetic Student'},
            children:[],attachments:[]}],getMenuItems:()=>true});
          install('ec_favorite',{show_favorite:true,isFavorite:false,table:'kb_knowledge',sys_id:'a'.repeat(32)});
          install('send_to_self_actions',{enableSendEmail:true,emailData:{}},{assignDataForServerCall:channel=>calls.push({channel})});
        }""")
        return KnowledgeService(self.session)

    def test_comments_use_native_ids_escape_text_and_guard_permissions(self):
        k = self.knowledge()
        self.assertEqual(k.list_comments(ITEM).comments[0].text, "Visible text")
        k.add_comment(ITEM, "<script>hello</script>\nnext", COMMENT)
        self.assertEqual(self.calls()[-1], {"action": "reply_comment", "article_id": ITEM,
                         "parent_id": COMMENT, "comment_text": "&lt;script&gt;hello&lt;/script&gt;<br>next"})
        k.set_comment_like(ITEM, COMMENT, True)
        self.assertEqual(self.calls()[-1]["action"], "like_comment")
        self.page.evaluate("widgets.find(s=>s.widget.id==='knowledge-comments').c.comments[0].is_liked=true")
        count = len(self.calls())
        self.assertEqual(k.set_comment_like(ITEM, COMMENT, True).outcome, "unchanged")
        self.assertEqual(count, len(self.calls()))
        self.page.evaluate("widgets.find(s=>s.widget.id==='knowledge-comments').c.getMenuItems=()=>false")
        with self.assertRaisesRegex(OneStopError, "does not allow"):
            k.delete_comment(ITEM, COMMENT)
        with self.assertRaisesRegex(OneStopError, "not visible"):
            k.add_comment(ITEM, "reply", RECORD)
        self.assertEqual(count, len(self.calls()))

    def test_article_feedback_native_actions_and_required_negative_reason(self):
        k = self.knowledge()
        k.rate(ITEM, 5)
        self.assertEqual(self.calls()[-1], {"action": "submit_rating", "article_id": ITEM, "rating": 5})
        with self.assertRaisesRegex(OneStopError, "reason_id"):
            k.rate(ITEM, 1)
        k.rate(ITEM, 1, "inaccurate", "Correction")
        self.assertEqual(self.calls()[-1]["action"], "createFeedbackTask")
        self.assertEqual(self.calls()[-1]["reason"], "inaccurate")
        k.set_helpful(ITEM, True)
        self.assertEqual(self.calls()[-1]["useful"], "useful_yes")
        k.set_helpful(ITEM, False, "inaccurate")
        self.assertEqual(self.calls()[-1]["feedback_action"], "useful_no")
        k.flag(ITEM, "Incorrect directions")
        self.assertEqual(self.calls()[-1]["action"], "saveFlagComment")
        k.set_favourite(ITEM, True)
        self.assertEqual(self.calls()[-1]["recordId"], ITEM)
        k.send_to_self(ITEM, "email")
        self.assertEqual(self.calls()[-2], {"channel": "email"})
        self.assertEqual(self.calls()[-1]["action"], "executeSendEmail")

    def test_inherited_subscription_requires_broader_explicit_scope(self):
        k = self.knowledge()
        self.page.evaluate("Object.assign(widgets[0].data,{isSubscribed:true,isArticleSubscribedAtKB:true,kbSysId:'b'.repeat(32),kbName:'Test KB'})")
        with self.assertRaisesRegex(OneStopError, "whole knowledge base"):
            k.set_subscription(ITEM, False)
        self.assertFalse(self.calls())
        k.set_subscription(ITEM, False, True)
        self.assertEqual(self.calls()[0]["unsubscribeKB"], True)
        self.assertEqual(self.calls()[0]["kbSysId"], RECORD)

    def test_form_changes_respect_visibility_readonly_passwords_and_hide_defaults(self):
        self.page.evaluate("""() => {
          const f=install('ntu-widget-sc-cat-item-v2',{sc_cat_item:{sys_id:'a'.repeat(32),name:'Test',can_view:true,_fields:{
            kind:{name:'kind',label:'Kind',type:'string',visible:true,mandatory:true,value:''},
            detail:{name:'detail',label:'Detail',type:'string',visible:false,value:'private-default'},
            locked:{name:'locked',label:'Locked',type:'string',visible:true,readonly:true,value:'private-default'},
            secret:{name:'secret',label:'Secret',type:'password',visible:true,value:'private-default'}
          }},sys_properties:{cartEnabled:true}},
            {allowOrder:()=>true,showOrderNowButton:()=>true,showAddCartBtn:()=>true,showAddToWishlist:()=>false,showAttachments:()=>true});
          const g={getUniqueValue:()=>f.data.sc_cat_item.sys_id,getValue:n=>f.data.sc_cat_item._fields[n].value,
            setValue:(n,v)=>{f.data.sc_cat_item._fields[n].value=v;if(n==='kind')f.data.sc_cat_item._fields.detail.visible=true;}};
          const e=document.createElement('div');e.setAttribute('form-model','data.sc_cat_item');e.setAttribute('mandatory','c.mandatory');
          e.native={formModel:f.data.sc_cat_item,getGlideForm:()=>g};document.body.appendChild(e);
        }""")
        d = Draft("synthetic-draft-token", ITEM, "revision", self.page, datetime.now(timezone.utc) + timedelta(minutes=15), time.monotonic() + 900)
        info = preview(d)
        self.assertFalse(info.ready)
        self.assertNotIn("private-default", info.model_dump_json())
        self.assertNotIn("secret", [f.name for f in info.fields])
        info = apply_values(d, {"detail": "answer", "kind": "new"})
        self.assertTrue(info.ready)
        self.assertEqual(next(f.value for f in info.fields if f.name == "detail"), "answer")
        for field in ("locked", "secret", "unknown"):
            with self.assertRaises(OneStopError):
                apply_values(d, {field: "forbidden"})

    def cart(self):
        self.page.evaluate("""() => {
          const s=install('sc-shopping-cart-v2',{cartItems:[{sys_id:'b'.repeat(32),item_id:'a'.repeat(32),name:'Example',quantity:1}],
             cart:{delivery_address:'Original',special_instructions:''},sys_properties:{twostep:false}}, {showQuantity:()=>true});
          s.server.get=async p=>{calls.push(p);if(p.action==='update_quantity')s.data.cartItems[0].quantity=p.quantity;return {data:s.data};};
          s.server.update=async()=>{calls.push({action:s.data.action});return {result:{sys_id:'c'.repeat(32),number:'REQ123'}};};
          install('sc-saved-carts',{savedCarts:[{sys_id:'c'.repeat(32),name:'Saved'}]});
        }""")
        return CartService(self.session)

    def test_cart_membership_quantity_and_unchanged_preview_gate_checkout(self):
        cart = self.cart()
        with self.assertRaisesRegex(OneStopError, "not in your"):
            cart.update("remove", ITEM)
        self.assertFalse(self.calls())
        self.assertTrue(cart.update("set_quantity", RECORD, 2).verified)
        checkout = cart.prepare_checkout("New address", "Instructions")
        cart.update("set_quantity", RECORD, 3)
        with self.assertRaisesRegex(OneStopError, "cart changed"):
            cart.submit_checkout(checkout.checkout_id)
        checkout = cart.prepare_checkout()
        result = cart.submit_checkout(checkout.checkout_id)
        self.assertEqual(result.resource_id, COMMENT)
        self.assertEqual(cart.submit_checkout(checkout.checkout_id).outcome, "unchanged")
        self.assertEqual(sum(c.get("action") == "checkout" for c in self.calls()), 1)

    def test_checkout_failure_blocks_retry(self):
        cart = self.cart()
        checkout = cart.prepare_checkout()
        self.page.evaluate("() => {widgets[0].server.update=async()=>{calls.push({action:'checkout'});throw new Error('private-detail')};}")
        with self.assertRaisesRegex(OneStopError, "may have completed"):
            cart.submit_checkout(checkout.checkout_id)
        with self.assertRaisesRegex(OneStopError, "uncertain"):
            cart.submit_checkout(checkout.checkout_id)
        self.assertEqual(len(self.calls()), 1)

    def test_post_write_refresh_failure_reports_uncertain_instead_of_retryable_read_error(self):
        cart = self.cart()
        current = cart.get()
        with patch.object(cart, "_get", side_effect=[current, OneStopError("retry later")]):
            result = cart.update("set_quantity", RECORD, 2)
        self.assertEqual(result.outcome, "uncertain")
        self.assertIn("before repeating", result.message)
        self.assertEqual(len(self.calls()), 1)

    def test_favourite_pin_limit_and_unpin_before_delete(self):
        self.page.evaluate("install('sc-favourite-list',{pinItemCount:4,cartItems:[{sys_id:'b'.repeat(32),item_id:'a'.repeat(32),name:'Test',pin_to_home:0}]})")
        f = FavouriteService(self.session)
        with self.assertRaisesRegex(OneStopError, "four home pins"):
            f.update("pin", RECORD)
        self.page.evaluate("widgets[0].data.cartItems[0].pin_to_home=1")
        for action in ("remove", "clear"):
            with self.assertRaisesRegex(OneStopError, "unpinning"):
                f.update(action, RECORD)
        self.assertFalse(self.calls())

    def test_ticket_activity_omits_work_notes_and_guards_state_actions(self):
        self.page.evaluate("""() => {
          install('ntu_ticket_conversations',{canRead:true,sys_id:'b'.repeat(32),mergedEntries:[
            {sys_id:'c'.repeat(32),element:'comments',value:'<p>Visible</p>'},
            {sys_id:'d'.repeat(32),element:'work_notes',value:'private-internal'}]});
          install('reopen-incident',{});
        }""")
        service = TicketService(self.session, Mock())
        context = TicketContext(self.session.snapshot, RECORD, "incident", {"actions": ["reopen"], "can_reply": False, "can_upload": False})
        with patch.object(service, "context", return_value=context):
            activity = service.activity(RECORD)
            self.assertEqual(len(activity.entries), 1)
            self.assertNotIn("private", activity.model_dump_json())
            for fn in (lambda: service.reply(RECORD, "Reply"), lambda: service.take_action(RECORD, "close")):
                with self.assertRaises(OneStopError):
                    fn()
            self.assertFalse(self.calls())
            service.take_action(RECORD, "reopen")
            self.assertEqual(self.calls()[-1]["action"], "re-open")

    def test_notification_request_uses_native_own_preference_endpoint(self):
        self.page.evaluate("""() => {
          install('user-profile-notification',{isLoggedInUsersProfile:true});
          services['$http']={post:async(url,payload)=>{calls.push({url,payload});return {data:{result:true}};}};
        }""")
        service = PortalService(self.session)
        info = SimpleNamespace(notifications_enabled=False, source_url=self.page.url)
        with patch.object(service, "_get_profile", return_value=info):
            self.assertEqual(service.set_notifications(False).outcome, "unchanged")
            service.set_notifications(True)
        self.assertEqual(self.calls(), [{"url": "/api/now/v1/notification/preference/all", "payload": {"enable_notifications": True}}])

    def test_appointment_slots_are_bound_to_latest_lookup_and_selection_only_fills_form(self):
        self.page.evaluate("""() => {
          const item=install('ntu-widget-sc-cat-item-v2',{sc_cat_item:{sys_id:'a'.repeat(32),name:'Book',can_view:true,_fields:{}},sys_properties:{}},
            {allowOrder:()=>true,showOrderNowButton:()=>true,showAddCartBtn:()=>false,showAddToWishlist:()=>false,showAttachments:()=>false});
          const e=document.createElement('div');e.setAttribute('form-model','data.sc_cat_item');e.setAttribute('mandatory','c.mandatory');
          e.native={formModel:item.data.sc_cat_item,getGlideForm:()=>({getUniqueValue:()=>item.data.sc_cat_item.sys_id})};document.body.appendChild(e);
          const selector=install('sn-appointment-booking-select',{config:{service_config:{appointment_duration:'15',future_bookable_max_days:'14'}}},
            {isConfigValid:true,isAppointmentMandatory:true,cancel:()=>calls.push({action:'close_local_modal'})});
          selector.c.data=selector.data;selector.isAppointmentMandatoryFilled=()=>window.selected===true;
          const calendar=document.createElement('sn-app-booking-availibility');calendar.native={config:{uiRenderTz:'Singapore'}};document.body.appendChild(calendar);
          services.appointmentBookingUtil={getMomentTimeZone:()=> 'Asia/Singapore',localizeSelectedWindow:()=>({start:'09:00',end:'09:15'})};
          services.appointmentBooking={getAppointments:async(start,end,config,next)=>{calls.push({action:'availability',start,end,next});return {
            time_zone:'Singapore',time_zone_display_value:'SGT',availability:[{available:true,start_date:'2030-01-02 09:00:00',
              end_date:'2030-01-02 09:15:00',start_dateUTC:'2030-01-02 01:00:00',end_dateUTC:'2030-01-02 01:15:00'}]};}};
          services['$rootScope']={$broadcast:(name,payload)=>{window.selected=true;calls.push({action:name,payload});}};
          window.moment={tz:()=>({toISOString:()=> '2030-01-02T00:00:00+08:00',clone:()=>({endOf:()=>({toISOString:()=> '2030-01-02T23:59:59+08:00'})})})};
        }""")
        d = Draft("appointment-draft-token", ITEM, "revision", self.page, datetime.now(timezone.utc) + timedelta(minutes=15), time.monotonic() + 900)
        self.session._drafts[d.draft_id] = d
        forms = FormService(self.session)
        service = AppointmentService(self.session, forms)
        first = service.slots(d.draft_id, "2030-01-02")
        latest = service.slots(d.draft_id, "2030-01-02")
        with self.assertRaisesRegex(OneStopError, "latest availability"):
            service.select(d.draft_id, first.slots[0].slot_id)
        self.assertEqual(latest.slots[0].start, "2030-01-02 09:00:00")
        self.assertTrue(service.select(d.draft_id, latest.slots[0].slot_id).ready)
        self.assertTrue(d.appointment_selected)
        self.assertEqual(self.calls()[-2]["action"], "appt.booking.selected.window")
        self.session.before_write.assert_not_called()
        forms.update(d.draft_id, {})
        self.assertFalse(d.slots or d.appointment_selected)
        with self.assertRaisesRegex(OneStopError, "slot"):
            service.book(d.draft_id)

    def profile(self):
        self.page.evaluate("""() => {
          install('user-profile',{isLoggedInUsersProfile:true,userExists:true,sysUserID:'b'.repeat(32),liveProfileID:'c'.repeat(32)});
          const p=install('user-preferences',{isLoggedInUsersProfile:true,userPreferences:{accessibility:{key:'glide.ui.accessibility',value:false}},
            preferencesEnabled:{preferencesPanelEnabled:true},listProperties:{}});
          install('user-profile-notification',{NotificationPreference:true});
          const e=document.createElement('div');e.setAttribute('field-model','field');e.native={editableByUser:true,table:'sys_user',tableId:'b'.repeat(32),
            fieldModel:{name:'company',label:'Company',type:'string',readonly:false,value:'Old'},
            getGlideForm:()=>({setValue:(name,value)=>e.native.fieldModel.value=value}),
            saveForm:()=>fetch('/api/now/v2/table/sys_user/'+e.native.tableId,{method:'PUT',body:JSON.stringify({company:e.native.fieldModel.value})})};
          document.body.appendChild(e);
          services.userPreferences={setPreference:async(key,value)=>{calls.push({key,value});p.data.userPreferences.accessibility.value=value;}};
        }""")
        return PortalService(self.session)

    def test_profile_edit_uses_own_native_editor_and_enabled_preference_key(self):
        service = self.profile()
        self.context.route("**/api/now/v2/table/**", lambda r: r.fulfill(json={"result": {"company": {"value": "Updated", "display_value": "Updated"}}}))
        with self.assertRaisesRegex(OneStopError, "not editable"):
            service.update_profile("password", "blocked")
        self.assertTrue(service.update_profile("company", "Updated").verified)
        self.page.evaluate("document.querySelector('[field-model]').native.tableId='d'.repeat(32)")
        with self.assertRaisesRegex(OneStopError, "verified as yours"):
            service.update_profile("company", "Wrong user")
        self.assertTrue(service.set_preference("accessibility", "true").verified)
        self.assertEqual(self.calls()[-1], {"key": "glide.ui.accessibility", "value": True})
        with self.assertRaisesRegex(OneStopError, "does not offer"):
            service.set_preference("timezone", "UTC")

    def test_payment_selection_is_directory_scoped_and_checkout_is_a_handoff(self):
        self.page.evaluate("""() => {
          const s=install('adhoc-payment',{});s.c.data=s.data;s.service={value:''};
          s.server.update=async()=>{calls.push({action:s.data.action});if(s.data.action==='noupdate'){
            s.data.serviceId=s.data.id;s.data.isFixedAmt=true;s.data.amt='10.00';
          }else{s.data.paymentURL='https://payments.example.edu/checkout';}return s.data;};
          const e=document.createElement('input');e.setAttribute('field','service');document.body.appendChild(e);
          window.jQuery=e=>({data:()=>({opts:{query:({callback})=>callback({results:[{sys_id:'a'.repeat(32),text:'Test fee'}],more:false}),
            id:r=>r.sys_id,formatSelection:r=>r.text}})});
        }""")
        service = PortalService(self.session)
        with self.assertRaisesRegex(OneStopError, "visible payment directory"):
            service.prepare_payment(RECORD)
        self.assertFalse(self.calls())
        self.assertEqual(service.get_payment_service(ITEM).fixed_amount, "10.00")
        self.session.before_write.assert_not_called()
        handoff = service.prepare_payment(ITEM)
        self.assertTrue(handoff.requires_browser_completion)
        self.assertEqual(self.calls()[-1], {"action": "update"})
        self.assertEqual(handoff.checkout_url, "https://payments.example.edu/checkout")

    def test_reference_search_preserves_native_picker_and_refuses_encoded_queries(self):
        self.page.evaluate("""() => {
          install('ntu-widget-sc-cat-item-v2',{sc_cat_item:{_fields:{reason:{name:'reason',visible:true,type:'reference'}}}});
          const e=document.createElement('input');e.id='sp_formfield_reason';document.body.appendChild(e);
          window.jQuery=e=>({data:()=>({opts:{query:({term,page,callback})=>{calls.push({term,page});callback({results:[{sys_id:'b'.repeat(32),text:'<b>Reason</b>'}],more:false});},
            id:r=>r.sys_id,formatSelection:r=>r.text}})});
        }""")
        d = Draft("reference-draft-token", ITEM, "revision", self.page, datetime.now(timezone.utc) + timedelta(minutes=15), time.monotonic() + 900)
        self.session._drafts[d.draft_id] = d
        service = FormService(self.session)
        found = service.search_references(d.draft_id, "reason", "*Help")
        self.assertEqual(found.choices[0].label, "Reason")
        self.assertEqual(self.calls(), [{"term": "*Help", "page": 1}])
        for query in ("x^ORactive=false", "x\n"):
            with self.assertRaises(OneStopError):
                service.search_references(d.draft_id, "reason", query)
        self.assertEqual(len(self.calls()), 1)


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.session = LocalSession(Mock())
        self.service = AttachmentService(self.session, Mock(), Mock())
        self.file = {"sys_id": RECORD, "file_name": "test.txt"}
        self.context = FileContext(self.session._page, BASE, "sc_req_item", ITEM, [self.file], True, True, 1000)

    def test_upload_size_and_absolute_path_are_checked_before_http(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Path(directory) / "example.txt"
            f.write_bytes(b"content")
            with self.assertRaisesRegex(OneStopError, "size limit"):
                upload_file(str(f), 2)
            with self.assertRaisesRegex(OneStopError, "absolute"):
                upload_file("relative.txt")
            self.assertEqual(upload_file(str(f))[2], b"content")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named pipes are not supported")
    def test_upload_named_pipe_is_refused_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipe"
            os.mkfifo(path)
            with self.assertRaisesRegex(OneStopError, "not a regular file"):
                upload_file(str(path))

    def test_delete_rename_require_target_membership_and_edit_permission(self):
        with patch.object(self.service, "context", return_value=self.context), patch("onestop.attachments.evaluate") as native:
            for fn in (lambda: self.service.delete({}, COMMENT), lambda: self.service.rename({}, COMMENT, "new.txt")):
                with self.assertRaisesRegex(OneStopError, "verified resource"):
                    fn()
            native.assert_not_called()
            self.context.can_delete = False
            with self.assertRaises(OneStopError):
                self.service.delete({}, RECORD)
            self.context.can_delete = True
            self.service.rename({}, RECORD, "renamed.txt")
            self.assertEqual(native.call_args.args[2], {"id": RECORD, "name": "renamed.txt"})
        for name in ("../file", "file\tname", "file\x7f"):
            with self.assertRaises(OneStopError):
                self.service.rename({}, RECORD, name)

    def test_download_new_file_digest_and_no_overwrite_or_unlisted_id(self):
        response = Mock(status=200, headers={"content-type": "application/octet-stream"})
        response.body.return_value = b"hello"
        self.session._context = SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response)))
        with tempfile.TemporaryDirectory() as directory, patch.object(self.service, "context", return_value=self.context):
            destination = str(Path(directory) / "new.txt")
            with self.assertRaisesRegex(OneStopError, "not listed"):
                self.service.download({}, COMMENT, destination)
            result = self.service.download({}, RECORD, destination)
            self.assertEqual(result.bytes_written, 5)
            self.assertEqual(result.sha256, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
            with self.assertRaisesRegex(OneStopError, "must be new"):
                self.service.download({}, RECORD, destination)
            self.assertEqual(Path(destination).read_bytes(), b"hello")
            self.assertEqual(self.session._context.request.get.call_count, 1)

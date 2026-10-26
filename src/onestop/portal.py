"""Dashboard, account profile and payment handoffs exposed by the portal."""

from urllib.parse import urlencode

from .browser import action_result, commit, evaluate, picker_query
from .models import (
    Dashboard, NamedValue, OneStopError, PaymentHandoff, PaymentServiceDetails,
    PortalRecord, PortalRecords, Preference, ProfileField, ProfileSettings,
)
from .parser import pagination, safe_url, sys_id
from .session import PORTAL


def record(record_id, title, url=None, **fields):
    return PortalRecord(record_id=record_id, title=str(title), url=safe_url(url) if url else None,
                        fields=[NamedValue(name=k, label=k.replace("_", " ").title(), value=str(v) if v is not None else None)
                                for k, v in fields.items()])


class PortalService:
    def __init__(self, session):
        self.session = session

    def dashboard(self):
        return self.session.workflow(self._dashboard)

    def _dashboard(self, session, revision):
        snapshot = session.read("__home__", refresh=True)
        data = evaluate(session._page, r"""
          const find=id=>scopes.find(s=>s.widget.id===id);
          return {
            announcements:(find('ntu_student_announcement')?.c.announcements||[])
              .map(x=>pick(x,['id','title','summary','targetLink'])),
            actions:(find('ntu_my_action')?.data.gbi||[])
              .map(x=>pick(x,['sys_id','servicetype','short_description','dueD','u_payment_url'])),
            appointments:(find('ntu_upcoming_appointment')?.data.app||[])
              .map(x=>pick(x,['sys_id','number','newstartwindow','location'])),
            links:(find('ntu_student_popular_item_list')?.data.recentItems||[])
              .map(x=>pick(x,['sys_id','name','type','page']))};
        """)
        return Dashboard(**snapshot.metadata(),
            announcements=[record(x.get("id"), x["title"], x.get("targetLink"), summary=x.get("summary")) for x in data["announcements"]],
            actions=[record(x.get("sys_id"), x.get("servicetype") or x.get("short_description") or "Action", x.get("u_payment_url"), due_date=x.get("dueD")) for x in data["actions"]],
            appointments=[record(x.get("sys_id"), x.get("number") or "Appointment", start=x.get("newstartwindow"), location=x.get("location")) for x in data["appointments"]],
            popular_links=[self._popular(x) for x in data["links"]])

    def _popular(self, x):
        url = x.get("page")
        if x.get("type") == "kb_article":
            url = PORTAL + "?" + urlencode({"id": "kb_article_view", "sys_kb_id": sys_id(x["sys_id"])})
        elif x.get("type") == "catalog_item":
            url = PORTAL + "?" + urlencode({"id": x.get("page") or "sc_cat_item", "sys_id": sys_id(x["sys_id"])})
        return record(x.get("sys_id"), x.get("name") or "Portal link", url)

    def list_announcements(self, limit=20, offset=0):
        return self.session.workflow(self._list_announcements, limit, offset)

    def _list_announcements(self, session, revision, limit, offset):
        snapshot = session.read("ntu_announcements", refresh=True)
        raw = evaluate(session._page, r"""
          const s=scopes.find(s=>['ntu_student_announcement','ntu-announcement'].includes(s.widget.id));
          if(!s) throw new Error('Announcements widget missing');
          const service=angular.element(document.body).injector().get('spAnnouncement');
          const result=service.get(service.filterOnType(s.options.type),1000,1);
          return {total:result.totalRecords,items:result.data.map(x=>pick(x,['id','title','summary','targetLink']))};
        """)
        records = [record(x.get("id"), x["title"], x.get("targetLink"), summary=x.get("summary")) for x in raw["items"]]
        return PortalRecords(**snapshot.metadata(), **pagination(len(records), raw["total"], len(records) == raw["total"], offset, limit),
                             records=records[offset:offset + limit])

    def list_actions(self, limit=20, offset=0):
        return self.session.workflow(self._list_actions, limit, offset)

    def _list_actions(self, session, revision, limit, offset):
        snapshot = session.read("ntu_to_do_detail", refresh=True)
        raw = evaluate(session._page, r"""
          const s=scope('ntu_to_do_list');
          return {count:s.data.count,max:s.data.maxCount,items:(s.data.todo||[]).map(x=>pick(x,
            ['sys_id','servicetype','short_description','u_label','dueD','u_payment_url','u_payble_amount']))};
        """)
        records = [record(x.get("sys_id"), x.get("servicetype") or x.get("short_description") or x.get("u_label") or "Action",
                          x.get("u_payment_url"), due_date=x.get("dueD"), amount=x.get("u_payble_amount")) for x in raw["items"]]
        capped = raw["count"] >= raw["max"]
        return PortalRecords(**snapshot.metadata(), **pagination(len(records), None if capped else raw["count"],
                             not capped and len(records) == raw["count"], offset, limit), records=records[offset:offset + limit])

    def list_popular_links(self, limit=20, offset=0):
        return self.session.workflow(self._list_popular_links, limit, offset)

    def _list_popular_links(self, session, revision, limit, offset):
        snapshot = session.read("ntu_popularsites", refresh=True)
        raw = evaluate(session._page, r"""
          const s=scope('ntu-popular-item-list');
          return {count:s.data.count,items:(s.data.recentItems||[]).map(x=>pick(x,['sys_id','name','type','page']))};
        """)
        records = [self._popular(x) for x in raw["items"]]
        return PortalRecords(**snapshot.metadata(), **pagination(len(records), raw["count"], len(records) == raw["count"], offset, limit),
                             records=records[offset:offset + limit])

    def get_profile(self):
        return self.session.workflow(self._get_profile)

    def _get_profile(self, session, revision):
        snapshot = session.read("user_profile", refresh=True)
        raw = evaluate(session._page, r"""
          const s=scope('user-profile'), p=scope('user-preferences');
          if(!s.data.isLoggedInUsersProfile||!s.data.userExists) throw new Error('Own profile unavailable');
          const fields=[];
          for(const element of document.querySelectorAll('[field-model]')) {
            const e=angular.element(element).isolateScope(); const f=e?.fieldModel;
            if(!f||!e.editableByUser||!f.label||['password','password2','user_image'].includes(f.type))continue;
            const name=e.table==='live_profile'?'bio':f.name;
            if(fields.some(x=>x.name===name))continue;
            fields.push({name,label:f.label,value:String(f.displayValue??f.value??''),type:f.type,
              read_only:f.readonly===true,choices:(f.choices||[]).map(c=>({value:String(c.value),label:c.label}))});
          }
          const preferences=[];
          const u=p.data.userPreferences||{}, enabled=p.data.preferencesEnabled||{};
          const add=(name,label,value,allow,choices=[])=>preferences.push({name,label,value:value==null?null:String(value),enabled:allow===true,choices});
          const choices=name=>(p.data.listProperties?.[name]?.list||[]).map(c=>({value:String(c.value),label:c.label}));
          add('accessibility','Accessibility',u.accessibility?.value,enabled.preferencesPanelEnabled);
          add('voice_input','Voice input',u.voiceInput?.value,enabled.voiceInputEnabled);
          add('analytics','Analytics',p.data.userAnalyticsDetails?.tracking_enabled??u.analytics?.value,p.data.showAnalytics);
          add('timezone','Time zone',p.data.listProperties?.timezone?.current?.value,enabled.timezoneEnabled,choices('timezone'));
          add('language','Language',p.data.listProperties?.language?.current?.value,enabled.languageEnabled,choices('language'));
          add('communication_channels','Communication channels',p.data.preferredChannels,p.data.hasChannelValues,
            (p.data.channelList||[]).map(c=>({value:c.value,label:c.display})));
          const n=scope('user-profile-notification');
          return {fields,preferences,notifications_enabled:typeof n.data.NotificationPreference==='boolean'?n.data.NotificationPreference:null,
            can_update_picture:s.data.isLoggedInUsersProfile===true};
        """)
        return ProfileSettings(**snapshot.metadata(), fields=[ProfileField(**f) for f in raw["fields"]],
                               preferences=[Preference(**p) for p in raw["preferences"]],
                               notifications_enabled=raw["notifications_enabled"], can_update_picture=raw["can_update_picture"])

    def update_profile(self, field_name, value):
        if not isinstance(field_name, str) or not isinstance(value, str) or len(value) > 10000 or "\0" in value:
            raise OneStopError("Supply a visible profile field name and a value up to 10,000 characters.")
        return self.session.workflow(self._update_profile, field_name, value)

    def _update_profile(self, session, revision, field_name, value):
        info = self._get_profile(session, revision)
        f = next((f for f in info.fields if f.name == field_name), None)
        if not f or f.read_only:
            raise OneStopError("This field is not editable in your native profile.")
        if f.choices and value not in {choice.value for choice in f.choices}:
            raise OneStopError("Choose one of the field's published choice values.")
        context = evaluate(session._page, r"""
          const p=scope('user-profile');
          for(const element of document.querySelectorAll('[field-model]')) {
            const s=angular.element(element).isolateScope();
            if(!s?.fieldModel)continue;
            const name=s.table==='live_profile'?'bio':s.fieldModel.name;
            if(name===args&&s.editableByUser&&!s.fieldModel.readonly&&
               ((s.table==='sys_user'&&s.tableId===p.data.sysUserID)||
                (s.table==='live_profile'&&s.tableId===p.data.liveProfileID)))
              return {table:s.table,id:s.tableId,name:s.fieldModel.name};
          }
          return null;
        """, field_name)
        if not context:
            raise OneStopError("The editable profile field could not be verified as yours.")

        def perform():
            expected = "/api/now/v2/table/" + context["table"] + "/" + context["id"]
            with session._page.expect_response(lambda r: r.request.method == "PUT" and expected in r.url, timeout=20000) as reply:
                evaluate(session._page, r"""
                  for(const element of document.querySelectorAll('[field-model]')) {
                    const s=angular.element(element).isolateScope();
                    if(s?.table===args.table&&s.tableId===args.id&&s.fieldModel.name===args.name) {
                      s.getGlideForm().setValue(args.name,args.value); s.saveForm(); return true;
                    }
                  }
                  throw new Error('Editable field disappeared');
                """, {**context, "value": value})
            response = reply.value
            if response.status != 200:
                raise OneStopError("One Stop rejected the profile update.")
            result = response.json().get("result", {}).get(context["name"], {})
            return str(result.get("value")) == value

        verified = commit(session, revision, perform)
        return action_result("update_profile", info.source_url, field_name, verified=verified,
                             outcome="completed" if verified else "uncertain")

    def set_notifications(self, enabled):
        if type(enabled) is not bool:
            raise OneStopError("enabled must be a boolean.")
        return self.session.workflow(self._set_notifications, enabled)

    def _set_notifications(self, session, revision, enabled):
        info = self._get_profile(session, revision)
        if info.notifications_enabled is None:
            raise OneStopError("The portal did not expose your notification preference.")
        if info.notifications_enabled == enabled:
            return action_result("set_notifications", info.source_url, verified=True, outcome="unchanged")
        result = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('user-profile-notification');
          if(!s.data.isLoggedInUsersProfile) throw new Error('Not own preference');
          const http=angular.element(document.body).injector().get('$http');
          const r=await http.post('/api/now/v1/notification/preference/all',{enable_notifications:args});
          return !!r.data.result;
        """, enabled, asynchronous=True))
        if not result:
            raise OneStopError("The portal did not acknowledge the notification change.")
        return action_result("set_notifications", info.source_url, verified=True)

    def update_picture(self, file_path):
        return self.session.workflow(self._update_picture, file_path)

    def _update_picture(self, session, revision, file_path):
        from .attachments import upload_file

        info = self._get_profile(session, revision)
        if not info.can_update_picture:
            raise OneStopError("The native portal does not offer an own-profile picture upload.")
        name, mime, data = upload_file(file_path)
        if mime not in {"image/jpeg", "image/png", "image/bmp", "image/x-windows-bmp", "image/gif", "image/x-icon", "image/svg+xml"}:
            raise OneStopError("Choose an image type supported by the native profile picture control.")

        def perform():
            from urllib.parse import parse_qs, urlsplit

            own_id = evaluate(session._page, "return scope('user-profile').data.liveProfileID;")

            def matches(response):
                u = urlsplit(response.url)
                q = parse_qs(u.query)
                return (response.request.method == "POST" and u.path == "/angular.do"
                        and q.get("sysparm_type") == ["ngk_attachments"] and q.get("action") == ["add"]
                        and q.get("sys_id") == [own_id])

            with session._page.expect_response(matches, timeout=60000) as uploaded:
                session._page.locator('div[sn-atf-area="User Profile"] input[type="file"]').set_input_files(
                    {"name": name, "mimeType": mime, "buffer": data})
            response = uploaded.value
            if response.status not in {200, 201} or len(response.body()) > 1000000:
                raise OneStopError("The picture upload did not return a verifiable receipt; inspect the profile before retrying.")
            file_id = sys_id(response.json()["sys_id"])
            session._page.wait_for_function("id=>[...document.querySelectorAll('div[widget][data]')].map(e=>angular.element(e).scope()).some(s=>s?.widget?.id==='user-profile'&&String(s.avatarPicture?.['background-image']||'').includes(id))", arg=file_id, timeout=10000)
            return file_id

        file_id = commit(session, revision, perform)
        return action_result("update_profile_picture", info.source_url, file_id, verified=True)

    def set_preference(self, name, value):
        return self.session.workflow(self._set_preference, name, value)

    def _set_preference(self, session, revision, name, value):
        info = self._get_profile(session, revision)
        preference = next((p for p in info.preferences if p.name == name), None)
        if not preference or not preference.enabled:
            raise OneStopError("The portal does not offer this preference for your account.")
        if not isinstance(value, str) or len(value) > 500:
            raise OneStopError("Preference values must be strings up to 500 characters.")
        if preference.choices:
            values = value.split(",") if name == "communication_channels" else [value]
            if any(v not in {c.value for c in preference.choices} for v in values):
                raise OneStopError("Choose values from this preference's published choices.")
        elif value not in {"true", "false"}:
            raise OneStopError("This preference accepts 'true' or 'false'.")
        if preference.value == value:
            return action_result("set_user_preference", info.source_url, name, verified=True, outcome="unchanged")
        commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('user-preferences'), injector=angular.element(document.body).injector();
          if(!s.data.isLoggedInUsersProfile) throw new Error('Not own preference');
          if(args.name==='analytics') {
            await injector.get('$http').post('/api/now/sp/consent/update',{user_consent:args.value==='true'?'Y':'N'});
          } else if(['timezone','language'].includes(args.name)) {
            await injector.get('$http').put('/api/now/ui/concoursepicker/'+args.name,{current:args.value,id:args.value});
          } else {
            const keys={accessibility:s.data.userPreferences.accessibility?.key,
              voice_input:s.data.userPreferences.voiceInput?.key,analytics:s.data.userPreferences.analytics?.key,
              communication_channels:'sp_preferred_communication_channels'};
            const key=keys[args.name]; if(!key)throw new Error('Unknown preference');
            const value=args.name==='communication_channels'?args.value:args.value==='true';
            await injector.get('userPreferences').setPreference(key,value);
          }
          return true;
        """, {"name": name, "value": value}, asynchronous=True))
        try:
            updated = self._get_profile(session, revision)
        except Exception:
            return action_result("set_user_preference", info.source_url, name, outcome="uncertain",
                                 message="The preference action returned, but the profile could not be refreshed. Check it before repeating the action.")
        after = next(p for p in updated.preferences if p.name == name)
        verified = after.value == value
        return action_result("set_user_preference", info.source_url, name, verified=verified,
                             outcome="completed" if verified else "uncertain")

    def list_payment_services(self, query="", limit=20, offset=0):
        return self.session.workflow(self._list_payment_services, query, limit, offset)

    def _payment_choices(self, session, query):
        choices, page = [], 1
        while page <= 10:
            result = picker_query(session._page, "const element=document.querySelector('[field=\"service\"]');", query, page)
            choices.extend(result["choices"])
            if not result["more"]:
                return choices, True
            page += 1
        return choices, False

    def _list_payment_services(self, session, revision, query, limit, offset):
        snapshot = session.read("ntu_adhoc_payment", refresh=True)
        choices, complete = self._payment_choices(session, query)
        records = [record(sys_id(c["value"]), c["label"]) for c in choices]
        return PortalRecords(**snapshot.metadata(), **pagination(len(records), len(records) if complete else None, complete, offset, limit),
                             records=records[offset:offset + limit])

    def _select_payment(self, session, service_id):
        snapshot = session.read("ntu_adhoc_payment", refresh=True)
        choices, _ = self._payment_choices(session, "")
        choice = next((c for c in choices if c["value"] == service_id), None)
        if choice is None:
            raise OneStopError("This payment service is not in your visible payment directory.")
        data = evaluate(session._page, r"""
          const s=scope('adhoc-payment'); s.service.value=args;
          s.c.data.id=args; s.c.data.action='noupdate'; await s.server.update();
          return {service_id:s.data.serviceId,fixed:s.data.isFixedAmt===true,amount:s.data.amt};
        """, service_id, asynchronous=True)
        if data["service_id"] != service_id:
            raise OneStopError("The portal returned a different payment service.")
        return PaymentServiceDetails(**snapshot.metadata(), service_id=service_id, title=choice["label"],
                                     fixed_amount=str(data["amount"]) if data["fixed"] else None)

    def get_payment_service(self, service_id):
        return self.session.workflow(lambda s, r, i: self._select_payment(s, i), sys_id(service_id))

    def prepare_payment(self, service_id):
        return self.session.workflow(self._prepare_payment, sys_id(service_id))

    def _prepare_payment(self, session, revision, service_id):
        info = self._select_payment(session, service_id)
        url = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('adhoc-payment'); s.c.data.action='update'; await s.server.update();
          return String(s.c.data.paymentURL||'');
        """, asynchronous=True))
        url = safe_url(url)
        if not url or not url.startswith("https://"):
            raise OneStopError("The portal did not provide a valid payment checkout URL. Inspect the payment page before retrying.")
        return PaymentHandoff(service_id=service_id, title=info.title, checkout_url=url)

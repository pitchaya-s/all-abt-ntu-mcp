"""Native appointment availability and catalog-based booking."""

from datetime import date, datetime, timezone
import secrets

from .browser import evaluate
from .forms import draft_for, preview
from .models import AppointmentConfiguration, AppointmentSlot, AppointmentSlots, OneStopError, PortalRecords
from .parser import pagination
from .portal import record


class AppointmentService:
    def __init__(self, session, forms):
        self.session, self.forms = session, forms

    def list(self, limit=20, offset=0):
        return self.session.workflow(self._list, limit, offset)

    def _list(self, session, revision, limit, offset):
        page = session.read("ntu_appointment_list", refresh=True)
        raw = evaluate(session._page, r"""
          const s=scope('ntu-upcoming-appointments');return {count:s.data.count,max:s.data.maxCount,
            items:(s.data.app||[]).map(a=>pick(a,['sys_id','number','newstartwindow','location']))};
        """)
        records = [record(a.get("sys_id"), a.get("number") or "Appointment", start=a.get("newstartwindow"), location=a.get("location")) for a in raw["items"]]
        capped = raw["count"] >= raw["max"]
        return PortalRecords(**page.metadata(), **pagination(len(records), None if capped else raw["count"],
                             not capped and len(records) == raw["count"], offset, limit), records=records[offset:offset + limit])

    def configuration(self, draft_id):
        return self.session.workflow(self._configuration, draft_id)

    def _configuration(self, session, revision, draft_id):
        draft = draft_for(session, revision, draft_id)
        data = evaluate(draft.page, r"""
          const s=scopes.find(s=>s.widget.id==='sn-appointment-booking-select');
          if(!s)return {enabled:false,mandatory:false};
          const d=s.c.data.config?.service_config||{};
          return {enabled:s.c.isConfigValid===true,mandatory:!!s.c.isAppointmentMandatory,
            duration:d.appointment_duration,days:d.future_bookable_max_days,weekdays:d.bookable_days};
        """)
        return AppointmentConfiguration(draft_id=draft_id, item_id=draft.item_id, enabled=data["enabled"],
                                        mandatory=data["mandatory"], duration_minutes=int(data["duration"]) if data.get("duration") else None,
                                        future_bookable_days=int(data["days"]) if data.get("days") else None,
                                        bookable_weekdays=str(data["weekdays"]) if data.get("weekdays") else None)

    def _calendar(self, draft):
        exists = draft.page.locator("sn-app-booking-availibility").count()
        if not exists:
            evaluate(draft.page, "const s=scope('sn-appointment-booking-select'); if(!s.c.isConfigValid)throw new Error('Booking not enabled');s.openAppBookingModal();return true;")
            draft.page.locator("sn-app-booking-availibility").wait_for(state="attached", timeout=20000)
        draft.page.wait_for_load_state("networkidle", timeout=20000)

    def slots(self, draft_id, day):
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except (ValueError, TypeError):
            raise OneStopError("Provide an appointment date as YYYY-MM-DD.") from None
        return self.session.workflow(self._slots, draft_id, day)

    def _slots(self, session, revision, draft_id, day):
        draft = draft_for(session, revision, draft_id)
        if not self._configuration(session, revision, draft_id).enabled:
            raise OneStopError("This draft does not contain an enabled native appointment selector.")
        self._calendar(draft)
        result = evaluate(draft.page, r"""
          const e=document.querySelector('sn-app-booking-availibility');
          const s=angular.element(e).isolateScope(), injector=angular.element(document.body).injector();
          const util=injector.get('appointmentBookingUtil');
          const zone=util.getMomentTimeZone(s.config.uiRenderTz);
          const start=moment.tz(args+' 00:00:00',zone), end=start.clone().endOf('day');
          const response=await injector.get('appointmentBooking').getAppointments(start.toISOString(),end.toISOString(),s.config,false);
          if(!response||!Array.isArray(response.availability))throw new Error('Availability response missing');
          s.config.time_zone=response.time_zone;s.config.time_zone_display_value=response.time_zone_display_value;
          return {timezone:response.time_zone,display_timezone:response.time_zone_display_value,
            slots:response.availability.filter(w=>w.available===true).map(w=>({
              start:w.start_date_display,end:w.end_date_display,available:w.available,
              actualStart:w.start_date,actualEnd:w.end_date,workDuration:w.workDuration,
              averageTravelDuration:w.averageTravelDuration,actualStartUTC:w.start_dateUTC,
              actualEndUTC:w.end_dateUTC,timezone:response.time_zone}))};
        """, day, asynchronous=True)
        draft.slots.clear()
        draft.appointment_selected = False
        slots = []
        for window in result["slots"]:
            token = secrets.token_urlsafe(18)
            draft.slots[token] = {"window": window, "display_timezone": result.get("display_timezone")}
            slots.append(AppointmentSlot(slot_id=token, start=window["actualStart"], end=window["actualEnd"],
                                         start_utc=window.get("actualStartUTC"), end_utc=window.get("actualEndUTC"),
                                         label=str(window.get("start") or window["actualStart"]) + " – " + str(window.get("end") or window["actualEnd"])))
        return AppointmentSlots(draft_id=draft_id, date=day, timezone=result.get("timezone"), slots=slots,
                                retrieved_at=datetime.now(timezone.utc))

    def select(self, draft_id, slot_id):
        return self.session.workflow(self._select, draft_id, slot_id)

    def _select(self, session, revision, draft_id, slot_id):
        draft = draft_for(session, revision, draft_id)
        slot = draft.slots.get(slot_id)
        if slot is None:
            raise OneStopError("This slot is not from the draft's latest availability lookup. Search availability again.")
        self._calendar(draft)
        evaluate(draft.page, r"""
          const element=document.querySelector('sn-app-booking-availibility');
          const a=angular.element(element).isolateScope();
          const injector=angular.element(document.body).injector(), util=injector.get('appointmentBookingUtil');
          const w=args.window;
          w.localizedSelectedWindow={time_zone_display_value:args.display_timezone,
            ...util.localizeSelectedWindow(w,a.config.locale_language,a.config.userDateFormatOptions,a.config.userTimeFormatOptions)};
          injector.get('$rootScope').$broadcast('appt.booking.selected.window',{selectedWindow:w,ruleId:a.config.ruleId});
          const s=scope('sn-appointment-booking-select');s.c.cancel();return true;
        """, slot)
        draft.page.wait_for_load_state("networkidle", timeout=20000)
        draft.appointment_selected = True
        return preview(draft)

    def book(self, draft_id, slot_id=None):
        return self.session.workflow(self._book, draft_id, slot_id)

    def _book(self, session, revision, draft_id, slot_id):
        draft = draft_for(session, revision, draft_id, editable=False)
        if draft.state == "submitted" and draft.receipt:
            return draft.receipt.model_copy(update={"outcome": "unchanged"})
        if slot_id:
            self._select(session, revision, draft_id, slot_id)
        if not draft.appointment_selected:
            raise OneStopError("Select a verified appointment slot on this draft first.")
        return self.forms._submit(session, revision, draft_id, "submit")

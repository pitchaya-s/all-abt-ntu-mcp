"""Own-ticket conversations and state actions; no unrestricted table arguments."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .browser import action_result, commit, evaluate
from .knowledge import message
from .models import ActivityEntry, OneStopError, RequestActivity
from .parser import html_content, sys_id


@dataclass
class TicketContext:
    snapshot: object
    record_id: str
    table: str
    permissions: dict


class TicketService:
    def __init__(self, session, reader):
        self.session = session
        self.reader = reader

    def context(self, session, revision, request_id, record_id=None):
        details = self.reader.get_my_request(sys_id(request_id), refresh=True)
        if record_id is None and len(details.records) != 1:
            raise OneStopError("This request has multiple records. Supply record_id from get_my_request.")
        target = next((r for r in details.records if record_id is None or r.record_id == record_id), None)
        if not target:
            raise OneStopError("This record is not a verified item of your request.")
        q = parse_qs(urlsplit(details.source_url).query)
        page_id = q["id"][0] if target.record_id == request_id else "sc_request"
        snapshot = session.read(page_id, {"sys_id": target.record_id, "table": target.record_type, "view": "ntusp"}, refresh=True)
        if snapshot.revision != revision:
            raise OneStopError("The saved account changed while checking request ownership.")
        fields = snapshot.data.get("ticket_fields", {})
        if fields.get("canRead") is not True or fields.get("sys_id") != target.record_id or fields.get("table") != target.record_type:
            raise OneStopError("One Stop did not verify the requested ticket context.")
        permissions = evaluate(session._page, r"""
          const c=scopes.find(s=>s.widget.id==='ntu_ticket_conversations');
          const a=scopes.find(s=>s.widget.id==='widget-ntu-ticket-attachments');
          const incident=scopes.find(s=>s.widget.id==='reopen-incident');
          const cs=scopes.find(s=>s.widget.name==='NTU Case Ticket Action');
          const actions=[];
          if(incident&&(incident.data.showWidget||incident.data.showWidget2)) {
            if(incident.data.showResolve) actions.push('close');
            if(incident.data.showReopen) actions.push('reopen');
          }
          if(cs?.c.showCaseTable && String(cs.data.state)==='6') actions.push('accept_solution','reject_solution');
          return {actions,can_reply:c?.data.canWrite===true&&c.data.hasWritableJournalField===true&&
              c.data.primaryJournalField?.name==='comments'&&c.data.primaryJournalField.can_write===true&&c.data.notClosedRITM===true,
            can_upload:a?.data.canWrite===true&&a.data.canAttach===true&&a.data.notClosedRITM===true&&a.data.table!=='sc_request',
            can_delete:a?.data.canWrite===true&&a.data.canAttach===true&&a.data.notClosedRITM===true&&a.data.table!=='sc_request',
            attachment_table:a?.data.table,attachment_record_id:a?.data.sys_id,max_attachment_mb:a?.data.maxAttachmentSize};
        """)
        return TicketContext(snapshot, target.record_id, target.record_type, permissions)

    def activity(self, request_id, record_id=None):
        return self.session.workflow(self._activity, sys_id(request_id), sys_id(record_id) if record_id else None)

    def _activity(self, session, revision, request_id, record_id):
        context = self.context(session, revision, request_id, record_id)
        raw = evaluate(session._page, r"""
          const s=scope('ntu_ticket_conversations');
          if(!s.data.canRead||s.data.sys_id!==args) throw new Error('Conversation belongs to another record');
          const sce=angular.element(document.body).injector().get('$sce');
          return (s.data.mergedEntries||s.data.stream?.entries||[])
            .filter(e=>e.element==='comments'||e.element==='attachment')
            .map(e=>({entry_id:e.sys_id,author:e.name??null,created_on:e.sys_created_on??null,
              kind:e.element==='comments'?'comment':'attachment',text:String(sce.valueOf(e.value)||''),
              attachment_id:e.element==='attachment'?e.attachment?.sys_id??null:null}));
        """, context.record_id)
        for entry in raw:
            entry["entry_id"] = sys_id(entry["entry_id"])
            entry["text"] = html_content(entry["text"])[0] if entry["text"].strip() else ""
        return RequestActivity(**context.snapshot.metadata(), request_id=request_id, record_id=context.record_id,
                               entries=[ActivityEntry(**e) for e in raw], available_actions=context.permissions["actions"],
                               can_reply=context.permissions["can_reply"], can_upload_attachment=context.permissions["can_upload"])

    def reply(self, request_id, text, record_id=None):
        return self.session.workflow(self._reply, sys_id(request_id), message(text), sys_id(record_id) if record_id else None)

    def _reply(self, session, revision, request_id, text, record_id):
        context = self.context(session, revision, request_id, record_id)
        if not context.permissions["can_reply"]:
            raise OneStopError("The native portal does not allow replies to this record in its current state.")
        raw = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('ntu_ticket_conversations');
          s.data.journalEntry=args.text; s.data.journalEntryField='comments';
          const r=await s.server.update();
          return (r.stream?.entries||[]).filter(e=>e.element==='comments')
            .map(e=>({id:e.sys_id,value:String(e.value||'')}));
        """, {"text": text}, asynchronous=True))
        entry = next((e for e in raw if html_content(e["value"])[0].strip() == text.strip()), None)
        return action_result("reply_to_request", context.snapshot.source_url, sys_id(entry["id"]) if entry else context.record_id,
                             verified=entry is not None, outcome="completed" if entry else "uncertain",
                             message=None if entry else "A reply response arrived, but the new entry was not identified. Inspect the conversation before replying again.")

    def take_action(self, request_id, action, record_id=None):
        if action not in {"close", "reopen", "accept_solution", "reject_solution"}:
            raise OneStopError("Unsupported native ticket action.")
        return self.session.workflow(self._take_action, sys_id(request_id), action, sys_id(record_id) if record_id else None)

    def _take_action(self, session, revision, request_id, action, record_id):
        context = self.context(session, revision, request_id, record_id)
        if action not in context.permissions["actions"]:
            raise OneStopError("The native portal does not offer this action on the record's current state.")
        raw = commit(session, revision, lambda: evaluate(session._page, r"""
          if(args.action==='close'||args.action==='reopen') {
            const s=scope('reopen-incident'); s.data.action=args.action==='close'?'close':'re-open';
            await s.server.update(); return {acknowledged:true};
          }
          const s=scope('NTU Case Ticket Action');
          s.data.action='update'; s.data.state=args.action==='accept_solution'?'3':'10';
          const r=await s.server.update();
          return {acknowledged:String(r.state)===s.data.state};
        """, {"action": action}, asynchronous=True))
        return action_result(action, context.snapshot.source_url, context.record_id, verified=False,
                             message="The native action returned. Refresh the request to check its resulting state.",
                             outcome="completed" if raw["acknowledged"] else "uncertain")

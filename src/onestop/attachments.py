"""Bounded file operations on verified portal resources."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
import stat
from urllib.parse import urlencode

from pydantic import TypeAdapter

from .browser import action_result, commit, evaluate
from .forms import draft_for
from .models import Attachment, Attachments, AttachmentTarget, FileDownload, OneStopError
from .parser import sys_id
from .session import BASE


MAX_BYTES = 20_000_000


@dataclass
class FileContext:
    page: object
    source_url: str
    table: str
    record_id: str
    files: list
    can_upload: bool
    can_delete: bool
    max_bytes: int
    max_files: int | None = None
    comment: bool = False
    draft: bool = False


def upload_file(path, maximum=MAX_BYTES):
    if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
        raise OneStopError("Choose an explicit absolute path to the file to upload.")
    p = Path(path).expanduser()
    try:
        descriptor = os.open(p, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as f:
            metadata = os.fstat(f.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
                raise OneStopError("The upload is not a regular file or exceeds the portal's size limit.")
            data = f.read(maximum + 1)
    except OSError:
        raise OneStopError("The selected upload file could not be read.") from None
    if len(data) > maximum:
        raise OneStopError("The upload exceeds the portal's size limit.")
    return p.name, mimetypes.guess_type(p.name)[0] or "application/octet-stream", data


def native_files(page, table, record_id):
    return evaluate(page, r"""
      const h=angular.element(document.body).injector().get('snAttachmentHandler').create(args.table,args.id);
      const files=await h.getAttachments();
      return files.map(f=>pick(f,['sys_id','file_name','size_bytes','size','content_type','state']));
    """, {"table": table, "id": record_id}, asynchronous=True)


def attachment(file, can_delete):
    attachment_id = sys_id(file["sys_id"])
    size = file.get("size_bytes")
    if isinstance(size, str) and size.isdigit():
        size = int(size)
    if type(size) is not int:
        size = None
    return Attachment(attachment_id=attachment_id, file_name=str(file["file_name"]), size_bytes=size,
                      size_label=str(file["size"]) if file.get("size") is not None else None,
                      content_type=file.get("content_type"), url=BASE + "/sys_attachment.do?" + urlencode({"sys_id": attachment_id}),
                      can_delete=can_delete)


class AttachmentService:
    def __init__(self, session, tickets, knowledge):
        self.session, self.tickets, self.knowledge = session, tickets, knowledge

    def context(self, session, revision, target):
        target = TypeAdapter(AttachmentTarget).validate_python(target)
        if target.kind == "request":
            ticket = self.tickets.context(session, revision, target.request_id, target.record_id)
            p = ticket.permissions
            if p["attachment_record_id"] != ticket.record_id or p["attachment_table"] != ticket.table:
                raise OneStopError("The portal did not verify this request's attachment container.")
            maximum = min(MAX_BYTES, int(float(p["max_attachment_mb"] or 20) * 1024 * 1024))
            return FileContext(session._page, ticket.snapshot.source_url, ticket.table, ticket.record_id,
                               native_files(session._page, ticket.table, ticket.record_id), p["can_upload"], p["can_delete"], maximum)
        if target.kind == "draft":
            draft = draft_for(session, revision, target.draft_id)
            data = evaluate(draft.page, r"""
              const s=scope('ntu-widget-sc-cat-item-v2');
              return {table:s.data._attachmentTable,id:s.data._generatedItemGUID,
                allowed:s.c.showAttachments(),max_mb:s.data.maxAttachmentSize};
            """)
            table, owner = data["table"], sys_id(data["id"])
            return FileContext(draft.page, draft.preview.source_url, table, owner, native_files(draft.page, table, owner),
                               data["allowed"], data["allowed"], min(MAX_BYTES, int(float(data["max_mb"] or 20) * 1024 * 1024)), draft=True)
        page, article_id = self.knowledge._open(session, target.article_id)
        if target.kind == "article":
            files = evaluate(session._page, "return (scope('kb-article-content').data.attachments||[]).map(f=>pick(f,['sys_id','file_name','size_bytes','size','content_type','state']));")
            return FileContext(session._page, page.source_url, "kb_knowledge", article_id, files, False, False, MAX_BYTES)
        raw = evaluate(session._page, r"""
          const s=scope('knowledge-comments');let found=null;
          function visit(items){for(const c of items||[]){if(c.sys_id===args){found=c;return;}visit(c.children);}}
          visit(s.c.comments);
          if(!found)return null;
          return {files:(found.attachments||[]).map(f=>({sys_id:f.sys_id,file_name:f.file_name,
              size_bytes:typeof f.size==='number'?f.size:null,size:f.size,content_type:f.type,state:f.state})),
            can_write:s.c.getMenuItems(found)===true, max_mb:s.data.maxFileSize,max_files:s.data.maxFiles};
        """, target.comment_id)
        if not raw:
            raise OneStopError("This comment is not visible on the article.")
        return FileContext(session._page, page.source_url, "kb_feedback", sys_id(target.comment_id), raw["files"],
                           raw["can_write"], raw["can_write"], min(MAX_BYTES, int(float(raw["max_mb"] or 20) * 1024 * 1024)),
                           int(raw["max_files"]) if raw.get("max_files") else None, comment=True)

    def list(self, target):
        return self.session.workflow(self._list, target)

    def _list(self, session, revision, target):
        context = self.context(session, revision, target)
        return Attachments(retrieved_at=datetime.now(timezone.utc), source_url=context.source_url, cached=False,
                           attachments=[attachment(f, context.can_delete) for f in context.files],
                           can_upload=context.can_upload, max_upload_bytes=context.max_bytes)

    def upload(self, target, path):
        return self.session.workflow(self._upload, target, path)

    def _upload(self, session, revision, target, path):
        context = self.context(session, revision, target)
        if not context.can_upload:
            raise OneStopError("The native portal does not allow uploading to this resource in its current state.")
        if context.max_files is not None and context.max_files >= 0 and len(context.files) >= context.max_files:
            raise OneStopError("This resource has reached its native attachment count limit.")
        name, mime, data = upload_file(path, context.max_bytes)

        def perform():
            token = context.page.evaluate("window.g_ck")
            if context.comment:
                response = session._context.request.post(BASE + "/api/now/v1/attachment_csm/file",
                    params={"table_name": context.table, "table_sys_id": context.record_id, "file_name": name},
                    data=data, headers={"Content-Type": mime, "Accept": "application/json", "X-UserToken": token},
                    max_redirects=0, timeout=60000)
            else:
                response = session._context.request.post(BASE + "/angular.do",
                    params={"sysparm_type": "ngk_attachments", "sys_id": context.record_id, "table": context.table, "action": "add"},
                    multipart={"attachments_modified": "true", "sysparm_table": context.table,
                               "sysparm_sys_id": context.record_id, "sysparm_nostack": "yes",
                               "sysparm_encryption_context": "", "sysparm_ck": token,
                               "attachFile": {"name": name, "mimeType": mime, "buffer": data}},
                    max_redirects=0, timeout=60000)
            try:
                if response.status not in {200, 201} or len(response.body()) > 1000000:
                    raise OneStopError("The file upload did not return a verifiable receipt; inspect attachments before retrying.")
                payload = response.json()
                file = payload.get("result", payload)
                file_id = sys_id(file["sys_id"])
            finally:
                response.dispose()
            if not context.comment:
                evaluate(context.page, "const s=scopes.find(s=>s.attachmentHandler&&s.data&&(s.data._generatedItemGUID===args||s.data.sys_id===args)); if(s)s.attachmentHandler.getAttachmentList('added'); return true;", context.record_id)
                context.page.wait_for_load_state("networkidle", timeout=15000)
            return file_id

        file_id = commit(session, revision, perform)
        return action_result("upload_attachment", context.source_url, file_id, verified=True)

    def download(self, target, attachment_id, destination):
        return self.session.workflow(self._download, target, sys_id(attachment_id), destination)

    def _download(self, session, revision, target, attachment_id, destination):
        context = self.context(session, revision, target)
        file = next((f for f in context.files if f["sys_id"] == attachment_id), None)
        if not file:
            raise OneStopError("This attachment is not listed on the verified resource.")
        if not isinstance(destination, str) or not Path(destination).expanduser().is_absolute():
            raise OneStopError("Choose an explicit absolute path for the new download file.")
        path = Path(destination).expanduser()
        if path.exists() or path.is_symlink() or not path.parent.is_dir() or any(p.is_symlink() for p in path.parents):
            raise OneStopError("The destination must be new, with an existing directory and no symbolic-link path components.")
        response = session._context.request.get(BASE + "/sys_attachment.do", params={"sys_id": attachment_id}, max_redirects=0, timeout=60000)
        try:
            if response.status != 200 or ("text/html" in response.headers.get("content-type", "") and
                                         "attachment" not in response.headers.get("content-disposition", "")):
                raise OneStopError("The portal did not return the authorized attachment file.")
            body = response.body()
            if len(body) > MAX_BYTES:
                raise OneStopError("The attachment exceeds the 20 MB download limit.")
        finally:
            response.dispose()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(body)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        except OSError:
            raise OneStopError("The new download file could not be written; existing files are never overwritten.") from None
        return FileDownload(attachment_id=attachment_id, path=str(path), bytes_written=len(body),
                            sha256=hashlib.sha256(body).hexdigest(), downloaded_at=datetime.now(timezone.utc))

    def delete(self, target, attachment_id):
        return self.session.workflow(self._delete, target, sys_id(attachment_id))

    def _delete(self, session, revision, target, attachment_id):
        context = self.context(session, revision, target)
        if not context.can_delete or not any(f["sys_id"] == attachment_id for f in context.files):
            raise OneStopError("This attachment is not deletable on the verified resource.")
        commit(session, revision, lambda: evaluate(context.page,
            "await angular.element(document.body).injector().get('snAttachmentHandler').deleteAttachment(args);return true;",
            attachment_id, asynchronous=True))
        return action_result("delete_attachment", context.source_url, attachment_id, verified=False,
                             message="The native deletion returned; refresh the attachment list to verify removal.")

    def rename(self, target, attachment_id, file_name):
        if not isinstance(file_name, str) or not file_name.strip() or len(file_name) > 200 or any(c in '/\\' or ord(c) < 32 or ord(c) == 127 for c in file_name):
            raise OneStopError("Provide a filename of 1–200 characters without path separators or control characters.")
        return self.session.workflow(self._rename, target, sys_id(attachment_id), file_name.strip())

    def _rename(self, session, revision, target, attachment_id, file_name):
        context = self.context(session, revision, target)
        if not context.can_delete or not any(f["sys_id"] == attachment_id for f in context.files):
            raise OneStopError("This attachment is not editable on the verified resource.")
        commit(session, revision, lambda: evaluate(context.page,
            "await angular.element(document.body).injector().get('snAttachmentHandler').renameAttachment(args.id,args.name);return true;",
            {"id": attachment_id, "name": file_name}, asynchronous=True))
        return action_result("rename_attachment", context.source_url, attachment_id, verified=False,
                             message="The native rename returned; refresh the attachment list to verify it.")

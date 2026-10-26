"""Knowledge discussions, feedback, subscriptions and native self-delivery."""

from html import escape

from .browser import action_result, commit, evaluate
from .models import ArticleComment, ArticleComments, ArticleFeedback, OneStopError
from .parser import html_content, pagination, sys_id


def message(value, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\0" in value:
        raise OneStopError(f"Provide nonempty text of at most {maximum} characters without NUL characters.")
    return value.strip()


class KnowledgeService:
    def __init__(self, session):
        self.session = session

    def _open(self, session, article_id):
        page = session.read("kb_article_view", {"sys_kb_id": sys_id(article_id)}, refresh=True)
        data = page.data.get("article", {})
        if data.get("isValid") is not True or data.get("knowledgeExists") is not True:
            raise OneStopError("This knowledge article is unavailable to the signed-in student.")
        return page, sys_id(data["article_sys_id"])

    def _feedback(self, session, snapshot, article_id):
        raw = evaluate(session._page, r"""
          const a=scope('kb-article-content'), h=scope('knowledge-article-helpful');
          const comments=scope('knowledge-comments');
          const fav=scopes.find(s=>s.widget.id==='ec_favorite');
          const send=scopes.find(s=>s.widget.id==='send_to_self_actions');
          return {article_id:a.data.article_sys_id,
            can_rate:h.c.showRatings===true&&!a.data.hideFeedbackOptions,
            can_mark_helpful:h.c.show_helpful===true&&!a.data.hideFeedbackOptions,
            can_comment:comments.data.disabled!==true&&comments.c.isLoggedInUser===true,
            can_flag:a.c.showFlagArticle===true,
            can_subscribe:a.data.isSubscriptionEnabled===true,
            subscribed:a.data.isSubscribed===true,
            inherited_subscription:a.data.isArticleSubscribedAtKB===true,
            can_favourite:fav?.data.show_favorite===true, favourite:fav?.data.isFavorite===true,
            send_channels:!send?[]:['email','sms'].filter(k=>k==='email'?
              send.data.enableSendEmail===true&&!send.data.emailData?.error:
              send.data.enableSendSMS===true&&!send.data.smsData?.error),
            reasons:(a.data.feedback_reasons||[]).map(r=>({value:r.reason_id,label:r.reason_desc}))};
        """)
        if raw["article_id"] != article_id:
            raise OneStopError("One Stop returned feedback controls for a different article.")
        return ArticleFeedback(**snapshot.metadata(), **raw)

    def get_feedback(self, article_id):
        return self.session.workflow(self._get_feedback, sys_id(article_id))

    def _get_feedback(self, session, revision, article_id):
        page, article_id = self._open(session, article_id)
        return self._feedback(session, page, article_id)

    def _comment_data(self, session):
        return evaluate(session._page, r"""
          const s=scope('knowledge-comments'), c=s.c, seen=new Set(), out=[];
          function walk(items,parent,depth) {
            if(depth>10||out.length>1000) throw new Error('Comment tree exceeded limit');
            for(const item of items||[]) {
              if(seen.has(item.sys_id)) continue;
              seen.add(item.sys_id);
              out.push({comment_id:item.sys_id,parent_id:parent,author:item.user?.name??null,
                created_on:item.created_on??null,text:item.comment_text||'',liked:item.is_liked===true,
                can_delete:c.getMenuItems(item)===true,attachment_ids:(item.attachments||[]).map(a=>a.sys_id)});
              walk(item.children,item.sys_id,depth+1);
            }
          }
          walk(c.comments,null,0);
          return out;
        """)

    def list_comments(self, article_id, limit=20, offset=0):
        return self.session.workflow(self._list_comments, sys_id(article_id), limit, offset)

    def _list_comments(self, session, revision, article_id, limit, offset):
        page, article_id = self._open(session, article_id)
        raw = self._comment_data(session)
        comments = []
        for item in raw:
            item["comment_id"] = sys_id(item["comment_id"])
            item["text"] = html_content(item["text"])[0] if item["text"].strip() else ""
            comments.append(ArticleComment(**item))
        return ArticleComments(**page.metadata(), **pagination(len(comments), None, False, offset, limit),
                               article_id=article_id, comments=comments[offset:offset + limit])

    def add_comment(self, article_id, text, parent_id=None):
        return self.session.workflow(self._add_comment, sys_id(article_id), message(text), sys_id(parent_id) if parent_id else None)

    def _add_comment(self, session, revision, article_id, text, parent_id):
        page, article_id = self._open(session, article_id)
        if not self._feedback(session, page, article_id).can_comment:
            raise OneStopError("The portal does not allow comments on this article.")
        if parent_id and parent_id not in {c["comment_id"] for c in self._comment_data(session)}:
            raise OneStopError("The parent comment is not visible on this article.")
        payload = {"action": "reply_comment" if parent_id else "add_comment", "article_id": article_id,
                   "comment_text": escape(text).replace("\n", "<br>"), **({"parent_id": parent_id} if parent_id else {"level": 0})}
        result = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('knowledge-comments').server.get(args); return r.data.response;", payload, asynchronous=True))
        if not isinstance(result, dict) or not result.get("sys_id"):
            raise OneStopError("One Stop did not acknowledge a new comment. Inspect the article before retrying.")
        return action_result("add_article_comment", page.source_url, sys_id(result["sys_id"]), verified=True)

    def delete_comment(self, article_id, comment_id):
        return self.session.workflow(self._change_comment, sys_id(article_id), sys_id(comment_id), "delete", None)

    def set_comment_like(self, article_id, comment_id, liked):
        if type(liked) is not bool:
            raise OneStopError("liked must be a boolean.")
        return self.session.workflow(self._change_comment, sys_id(article_id), sys_id(comment_id), "like", liked)

    def _change_comment(self, session, revision, article_id, comment_id, operation, liked):
        page, article_id = self._open(session, article_id)
        comment = next((c for c in self._comment_data(session) if c["comment_id"] == comment_id), None)
        if not comment:
            raise OneStopError("This comment is not visible on the article.")
        if operation == "delete" and not comment["can_delete"]:
            raise OneStopError("The native portal does not allow you to delete this comment.")
        if operation == "like" and comment["liked"] == liked:
            return action_result("set_article_comment_like", page.source_url, comment_id, verified=True, outcome="unchanged")
        action = "delete_comment" if operation == "delete" else ("like_comment" if liked else "unlike_comment")
        response = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('knowledge-comments').server.get(args); return r.data.response;",
            {"action": action, "article_id": article_id, "feedback_id": comment_id}, asynchronous=True))
        if not response:
            raise OneStopError("The portal did not acknowledge the comment action; inspect the article before retrying.")
        return action_result(action, page.source_url, comment_id, verified=True)

    def rate(self, article_id, rating, reason_id=None, details=""):
        if type(rating) is not int or not 1 <= rating <= 5:
            raise OneStopError("Article ratings must be integers from 1 to 5.")
        return self.session.workflow(self._rate, sys_id(article_id), rating, reason_id, details)

    def _rate(self, session, revision, article_id, rating, reason_id, details):
        page, article_id = self._open(session, article_id)
        flags = self._feedback(session, page, article_id)
        if not flags.can_rate:
            raise OneStopError("The portal does not offer star ratings on this article.")
        threshold = evaluate(session._page, "return scope('knowledge-article-helpful').data.rating_threshold;")
        if threshold not in (None, "") and rating <= int(threshold):
            return self._detailed_feedback(session, revision, page, article_id, "rating", rating, reason_id, details, flags)
        response = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('knowledge-article-helpful').server.get(args); return r.data.response;",
            {"action": "submit_rating", "article_id": article_id, "rating": rating}, asynchronous=True))
        if not response:
            raise OneStopError("The portal rejected the rating or reached its feedback limit.")
        return action_result("rate_article", page.source_url, article_id, verified=True)

    def _detailed_feedback(self, session, revision, page, article_id, action, rating, reason_id, details, flags):
        if reason_id not in {r.value for r in flags.reasons}:
            raise OneStopError("This feedback needs a reason_id from get_article_feedback.")
        details = message(details, 10000) if details else ""
        payload = {"action": "createFeedbackTask", "article_sys_id": article_id, "reason": reason_id,
                   "details": details, "feedback_action": action, "rating": rating}
        result = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('kb-article-content').server.get(args); return {success:r.data.feedbackSuccess===true};",
            payload, asynchronous=True))
        if not result["success"]:
            raise OneStopError("The portal did not acknowledge the detailed article feedback.")
        return action_result("article_feedback", page.source_url, article_id, verified=True)

    def flag(self, article_id, text):
        return self.session.workflow(self._flag, sys_id(article_id), message(text, 10000))

    def _flag(self, session, revision, article_id, text):
        page, article_id = self._open(session, article_id)
        if not self._feedback(session, page, article_id).can_flag:
            raise OneStopError("The native portal does not offer article flagging here.")
        result = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('kb-article-content').server.get(args); return r.data.feedbackSuccess===true;",
            {"action": "saveFlagComment", "article_sys_id": article_id, "comment": text}, asynchronous=True))
        if not result:
            raise OneStopError("The portal did not acknowledge the article flag.")
        return action_result("flag_article", page.source_url, article_id, verified=True)

    def set_helpful(self, article_id, helpful, reason_id=None, details=""):
        if type(helpful) is not bool:
            raise OneStopError("helpful must be a boolean.")
        return self.session.workflow(self._set_helpful, sys_id(article_id), helpful, reason_id, details)

    def _set_helpful(self, session, revision, article_id, helpful, reason_id, details):
        page, article_id = self._open(session, article_id)
        flags = self._feedback(session, page, article_id)
        if not flags.can_mark_helpful:
            raise OneStopError("The portal does not offer helpfulness feedback on this article.")
        actionable = evaluate(session._page, "return scope('knowledge-article-helpful').data.actionablefeedback_helpful_enabled;")
        if not helpful and actionable in (True, "true"):
            return self._detailed_feedback(session, revision, page, article_id, "useful_no", None, reason_id, details, flags)
        response = commit(session, revision, lambda: evaluate(session._page,
            "const r=await scope('knowledge-article-helpful').server.get(args);return r.data.success===true;",
            {"action": "saveHelpful", "article_sys_id": article_id, "useful": "useful_yes" if helpful else "useful_no"}, asynchronous=True))
        if not response:
            raise OneStopError("The portal did not acknowledge helpfulness feedback.")
        return action_result("set_article_helpful", page.source_url, article_id, verified=True)

    def set_subscription(self, article_id, subscribed, include_knowledge_base=False):
        if type(subscribed) is not bool or type(include_knowledge_base) is not bool:
            raise OneStopError("Subscription choices must be booleans.")
        return self.session.workflow(self._set_subscription, sys_id(article_id), subscribed, include_knowledge_base)

    def _set_subscription(self, session, revision, article_id, subscribed, include_knowledge_base):
        page, article_id = self._open(session, article_id)
        flags = self._feedback(session, page, article_id)
        if not flags.can_subscribe:
            raise OneStopError("The native portal does not offer subscriptions to this article.")
        if flags.subscribed == subscribed:
            return action_result("set_article_subscription", page.source_url, article_id, verified=True, outcome="unchanged")
        if not subscribed and flags.inherited_subscription and not include_knowledge_base:
            raise OneStopError("This subscription comes from the whole knowledge base. Removing it requires include_knowledge_base=true and affects that knowledge base.")
        response = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('kb-article-content'), d=s.data;
          const r=await s.server.get({action:args.subscribed?'subscribe':'unsubscribe',
            kbSysId:d.kbSysId,kbName:d.kbName,articleSysId:d.article_sys_id,articleNum:d.number,
            unsubscribeKB:!args.subscribed&&args.include_knowledge_base,
            isArticleSubscribed:d.isArticleSubscribed,isKBSubscribed:d.isArticleSubscribedAtKB});
          return {acknowledged:!!r.data.responseMessage};
        """, {"subscribed": subscribed, "include_knowledge_base": include_knowledge_base}, asynchronous=True))
        if not response["acknowledged"]:
            raise OneStopError("The portal did not acknowledge the subscription change.")
        return action_result("set_article_subscription", page.source_url, article_id, verified=True)

    def set_favourite(self, article_id, favourite):
        if type(favourite) is not bool:
            raise OneStopError("favourite must be a boolean.")
        return self.session.workflow(self._set_favourite, sys_id(article_id), favourite)

    def _set_favourite(self, session, revision, article_id, favourite):
        page, article_id = self._open(session, article_id)
        flags = self._feedback(session, page, article_id)
        if not flags.can_favourite:
            raise OneStopError("The native portal does not offer favourites for this article.")
        if flags.favourite == favourite:
            return action_result("set_article_favourite", page.source_url, article_id, verified=True, outcome="unchanged")
        result = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('ec_favorite'); const r=await s.server.get({action:'toggleFavorite',
            markFavorite:args,table:s.data.table,recordId:s.data.sys_id});
          return r.data.isFavorite;
        """, favourite, asynchronous=True))
        if result is not favourite:
            raise OneStopError("The portal did not verify the requested article favourite state.")
        return action_result("set_article_favourite", page.source_url, article_id, verified=True)

    def send_to_self(self, article_id, channel):
        if channel not in {"email", "sms"}:
            raise OneStopError("Choose email or sms for article self-delivery.")
        return self.session.workflow(self._send_to_self, sys_id(article_id), channel)

    def _send_to_self(self, session, revision, article_id, channel):
        page, article_id = self._open(session, article_id)
        if channel not in self._feedback(session, page, article_id).send_channels:
            raise OneStopError("The portal does not offer this self-delivery channel for the article.")
        result = commit(session, revision, lambda: evaluate(session._page, r"""
          const s=scope('send_to_self_actions'); s.c.assignDataForServerCall(args);
          s.data.action=args==='email'?'executeSendEmail':'executeSendSMS';
          const r=await s.server.update();
          return {acknowledged:args==='email'||!!r.smsId};
        """, channel, asynchronous=True))
        if not result["acknowledged"]:
            raise OneStopError("The portal did not acknowledge article delivery.")
        return action_result("send_article_to_self", page.source_url, article_id, verified=True,
                             message="The portal acknowledged delivery to your registered " + channel + " channel; receipt is not guaranteed.")

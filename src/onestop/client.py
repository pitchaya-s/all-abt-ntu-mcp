"""Typed reads of NTU's student catalog, knowledge and own ticket lists."""

from urllib.parse import parse_qs, urlencode, urlsplit
from html import escape

from .models import (
    CatalogItem, CatalogItemDetails, CatalogItems, Categories, Category, Choice, FormField,
    KnowledgeArticle, KnowledgeResult, KnowledgeResults, Link, ListCoverage, NamedValue,
    OneStopError, RequestDetails, RequestItemStage, RequestRecordDetails, Requests, RequestSummary,
)
from .parser import count, html_content, pagination, safe_url, sys_id, text
from .session import BASE, LIST_PAGES, PORTAL


def _query(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OneStopError("Provide a search query of 1–200 characters without control characters.")
    return value.strip()


def _data(page, key):
    data = page.data.get(key)
    if not isinstance(data, dict):
        raise OneStopError("One Stop did not finish loading the expected widget; retry with refresh=true.")
    return data


def _items(data, key):
    value = data[key]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value) or len(value) > 2000:
        raise OneStopError("One Stop returned an unsupported record list.")
    return value


def _unique(items):
    if len(items) != len(set(items)):
        raise OneStopError("One Stop repeated records; no complete list was inferred.")


def _summary(value):
    value = text(value)
    return html_content(value)[0] if value else None


def _catalog_item(item):
    item_id = sys_id(item["sys_id"])
    item_type = item.get("type")
    content_type = item.get("content_type")
    kind = "form"
    if content_type == "external":
        kind = "external"
        url = safe_url(item.get("url"))
    elif content_type == "kb":
        kind = "knowledge"
        url = PORTAL + "?" + urlencode({"id": "kb_article_view", "sys_kb_id": sys_id(item["kb_article"])})
    else:
        page = item.get("page") or "sc_cat_item"
        if page not in {"sc_cat_item", "sc_cat_item_guide"}:
            raise OneStopError("One Stop returned an unsupported catalog link.")
        if item_type in {"sc_content", "content_item"}:
            kind = "content"
        url = PORTAL + "?" + urlencode({"id": page, "sys_id": item_id})
    if not url:
        raise OneStopError("One Stop returned an invalid catalog URL.")
    u = urlsplit(url)
    q = parse_qs(u.query)
    form_id = None
    if u.scheme == "https" and u.netloc == urlsplit(BASE).netloc and u.path in {"/ntussp", "/ntussp/"} and q.get("id") == ["sc_cat_item"]:
        form_id = sys_id(q["sys_id"][0])
        kind = "form"
    return CatalogItem(item_id=item_id, title=text(item["name"], True), summary=_summary(item.get("short_description")),
                       kind=kind, url=url, form_item_id=form_id)


class OneStopClient:
    def __init__(self, session):
        self.session = session

    def list_categories(self, refresh=False):
        page = self.session.read("sc_home", refresh=refresh)
        data = _data(page, "categories")
        roots = _items(data, "categoriesList")
        total = count(data["total"])
        categories = []

        def collect(items, parent, depth=0):
            if depth > 10 or len(categories) > 500:
                raise OneStopError("One Stop returned an unsupported category hierarchy.")
            for item in items:
                category_id = sys_id(item["sys_id"])
                categories.append(Category(category_id=category_id, title=text(item["title"], True),
                                           parent_id=parent, item_count=count(item["count"]),
                                           total_item_count=count(item["totalCount"])))
                collect(_items(item, "subcategories"), category_id, depth + 1)

        collect(roots, None)
        _unique([item.category_id for item in categories])
        return Categories(**page.metadata(), categories=categories, root_count=len(roots),
                          total_root_count=total, complete=len(roots) == total)

    def list_catalog_items(self, query="", category_id=None, limit=20, offset=0, refresh=False):
        if not isinstance(query, str):
            raise OneStopError("The catalog query must be text.")
        if query and category_id:
            raise OneStopError("Supply either a catalog query or a category_id.")
        if query:
            query = _query(query)
            page = self.session.read("search", {"q": query, "t": "sc"}, refresh=refresh)
            data = _data(page, "search")
            if data["q"] != query or data["t"] != "sc":
                raise OneStopError("One Stop returned a different catalog search.")
            raw = _items(data, "results")
            scope, total, complete = "search", None, False
        elif category_id:
            category_id = sys_id(category_id)
            page = self.session.read("sc_category", {"sys_id": category_id}, refresh=refresh)
            data = _data(page, "category")
            if data["category_id"] != category_id or not isinstance(data.get("category"), dict):
                raise OneStopError("One Stop did not return the requested catalog category.")
            raw = _items(data, "items")
            total = count(data["total_item"])
            scope, complete = "category", len(raw) == total
        else:
            page = self.session.read("sc_home", refresh=refresh)
            raw = _items(_data(page, "popular"), "items")
            scope, total, complete = "popular", None, False
        items = [_catalog_item(item) for item in raw]
        _unique([item.item_id for item in items])
        paging = pagination(len(items), total, complete, offset, limit)
        return CatalogItems(**page.metadata(), **paging, scope=scope, query=query,
                            category_id=category_id, items=items[offset:offset + limit])

    def get_catalog_item(self, item_id, refresh=False):
        item_id = sys_id(item_id)
        page = self.session.read("sc_cat_item", {"sys_id": item_id}, refresh=refresh)
        data = _data(page, "item")
        if data.get("recordFound") is not True or data.get("can_view") is not True:
            raise OneStopError("This catalog form is unavailable to the signed-in student.")
        if data["sys_id"] != item_id:
            raise OneStopError("One Stop returned a different catalog form.")
        fields = [FormField(name=text(f["name"], True), label=text(f["label"], True), type=text(f["type"], True),
                            mandatory=f["mandatory"], read_only=f["read_only"],
                            choices=[Choice(value=c["value"], label=c["label"]) for c in _items(f, "choices")])
                  for f in _items(data, "fields")]
        return CatalogItemDetails(**page.metadata(), item_id=item_id, title=text(data["name"], True),
                                  summary=_summary(data.get("short_description")),
                                  description=_summary(data.get("description")) or "",
                                  mandatory_attachment=data.get("mandatory_attachment"), fields=fields)

    def search_knowledge(self, query, limit=20, offset=0, refresh=False):
        query = _query(query)
        page = self.session.read("search", {"q": query, "t": "kb"}, refresh=refresh)
        data = _data(page, "search")
        if data["q"] != query or data["t"] != "kb":
            raise OneStopError("One Stop returned a different knowledge search.")
        articles = []
        for item in _items(data, "results"):
            if item.get("type") != "kb":
                raise OneStopError("One Stop mixed unsupported records into knowledge results.")
            article_id = sys_id(item["sys_id"])
            articles.append(KnowledgeResult(article_id=article_id, number=text(item["number"], True),
                                            title=text(item["short_description"], True), summary=_summary(item.get("text")),
                                            published=text(item.get("publishedUTC")),
                                            url=PORTAL + "?" + urlencode({"id": "kb_article_view", "sys_kb_id": article_id})))
        _unique([article.article_id for article in articles])
        return KnowledgeResults(**page.metadata(), **pagination(len(articles), None, False, offset, limit),
                                query=query, articles=articles[offset:offset + limit])

    def get_knowledge_article(self, article_id, offset=0, max_chars=12000, refresh=False):
        article_id = sys_id(article_id)
        if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 50000:
            raise OneStopError("Use a nonnegative text offset and max_chars from 1 to 50000.")
        page = self.session.read("kb_article_view", {"sys_kb_id": article_id}, refresh=refresh)
        data = _data(page, "article")
        if data.get("isValid") is not True or data.get("knowledgeExists") is not True:
            raise OneStopError("This knowledge article is unavailable to the signed-in student.")
        if data.get("isTemplate") is True:
            if not isinstance(data.get("template_fields"), list):
                raise OneStopError("This knowledge article uses an unsupported template; open its portal URL to read it.")
            parts = []
            for f in _items(data, "template_fields"):
                label = escape(text(f.get("label")) or "")
                content = text(f.get("content")) or ""
                parts.append("<h2>" + label + "</h2>" + (content if f.get("type") == "html" else escape(content)))
            body, links = html_content("\n".join(parts), page.source_url)
        elif data.get("isTemplate") is False:
            body, links = html_content(data["content"], page.source_url)
        else:
            raise OneStopError("This knowledge article uses an unsupported template; open its portal URL to read it.")
        end = offset + max_chars
        return KnowledgeArticle(**page.metadata(), article_id=sys_id(data["article_sys_id"]),
                                number=text(data["number"], True), title=text(data["shortDesc"], True),
                                updated_on=text(data.get("sys_updated_on")), text=body[offset:end],
                                total_characters=len(body), offset=offset, next_offset=end if end < len(body) else None,
                                links=[Link(**link) for link in links])

    def _request_records(self, status, kind, refresh):
        if status not in {"all", "open", "closed"} or kind not in {"all", "case", "request"}:
            raise OneStopError("Use status=all/open/closed and kind=all/case/request.")
        pages, records, coverage = [], [], []
        for (record_kind, state), page_id in LIST_PAGES.items():
            if status not in {"all", state} or kind not in {"all", record_kind}:
                continue
            page = self.session.read(page_id, refresh=refresh)
            pages.append(page)
            if len({p.revision for p in pages}) != 1:
                raise OneStopError("The saved account changed during the lookup; repeat the request.")
            data = _data(page, "requests")
            if data.get("isValid") is not True:
                raise OneStopError("One Stop did not provide a valid personal request list.")
            raw = _items(data, "list")
            source_count, maximum = count(data["count"]), count(data["maxCount"])
            lower_bound = source_count >= maximum
            coverage.append(ListCoverage(kind=record_kind, state_group=state, available_count=len(raw),
                                         source_count=source_count, source_count_is_lower_bound=lower_bound,
                                         complete=not lower_bound and len(raw) == source_count))
            names = data["secondary_names"]
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                raise OneStopError("One Stop returned unsupported ticket columns.")
            for item in raw:
                request_id = sys_id(item["sys_id"])
                route = item["url"]
                if isinstance(route, str):
                    url = safe_url(route)
                    if not url or urlsplit(url).netloc != urlsplit(BASE).netloc:
                        raise OneStopError("One Stop returned an unsupported personal request link.")
                    values = parse_qs(urlsplit(url).query)
                    route = {k: v[0] for k, v in values.items() if len(v) == 1}
                if not isinstance(route, dict) or route.get("sys_id") != request_id:
                    raise OneStopError("One Stop returned an inconsistent personal request link.")
                record_type = text(item["className"], True)
                secondary = _items(item, "secondary_fields")
                if len(names) != len(secondary):
                    raise OneStopError("One Stop returned inconsistent ticket columns.")
                fields = dict(zip(names, (text(field.get("display_value")) for field in secondary)))
                params = {"sys_id": request_id, "table": record_type, "view": route.get("view") or "ntusp"}
                detail_supported = route.get("id") in {"sc_request", "ticket"} and route.get("table") == record_type and params["view"] == "ntusp"
                url = PORTAL + "?" + urlencode({"id": text(route.get("id"), True), **params})
                record = RequestSummary(request_id=request_id, kind=record_kind, state_group=state,
                                        title=text(item["display_field"]["display_value"], True), number=fields.get("number"),
                                        state=fields.get("state"), created_on=fields.get("sys_created_on"), record_type=record_type,
                                        url=url, detail_supported=detail_supported)
                records.append((record, route["id"], params))
        _unique([record.request_id for record, _, _ in records])
        return records, coverage, pages

    def list_my_requests(self, status="all", kind="all", limit=20, offset=0, refresh=False):
        records, coverage, pages = self._request_records(status, kind, refresh)
        total = None if any(c.source_count_is_lower_bound for c in coverage) else sum(c.source_count for c in coverage)
        return Requests(retrieved_at=min(p.retrieved_at for p in pages), source_url=PORTAL + "?id=tickets",
                        cached=all(p.cached for p in pages), **pagination(len(records), total, all(c.complete for c in coverage), offset, limit),
                        requests=[r for r, _, _ in records[offset:offset + limit]], coverage=coverage)

    def get_my_request(self, request_id, refresh=False):
        request_id = sys_id(request_id)
        records, _, pages = self._request_records("all", "all", refresh)
        match = next((item for item in records if item[0].request_id == request_id), None)
        if match is None:
            raise OneStopError("This ID is not in your retrieved request lists. Older records may require the portal's View all link.")
        record, page_id, params = match
        if not record.detail_supported:
            raise OneStopError("This request uses an unsupported detail page; open its portal URL.")
        page = self.session.read(page_id, params, refresh=refresh)
        if page.revision != pages[0].revision:
            raise OneStopError("The saved account changed during the lookup; repeat the request.")
        def values(items):
            return [NamedValue(name=text(f["name"], True), label=text(f["label"], True), value=text(f.get("display_value")))
                    for f in items]

        def record_details(detail_page, expected_id, expected_table):
            data = _data(detail_page, "ticket_fields")
            if (detail_page.revision != pages[0].revision or data.get("canRead") is not True
                or data.get("sys_id") != expected_id or data.get("table") != expected_table):
                raise OneStopError("One Stop did not verify access to the requested record.")
            return RequestRecordDetails(record_id=expected_id, record_type=expected_table,
                                        fields=values(_items(data, "fields")), variables=values(_items(data, "variables")))

        children = [RequestItemStage(item_id=sys_id(item["sys_id"]), stage=text(item.get("stage")))
                    for item in page.data.get("requested_items", [])]
        _unique([child.item_id for child in children])
        if len(children) > 20:
            raise OneStopError("This request contains more than 20 items; open its portal URL for details.")
        data = _data(page, "ticket_fields")
        records = []
        detail_pages = [page]
        if data.get("sys_id") == request_id:
            records.append(record_details(page, request_id, record.record_type))
        elif record.record_type != "sc_request" or data.get("sys_id") not in {child.item_id for child in children}:
            raise OneStopError("One Stop did not verify access to the requested record.")
        # A ServiceNow request page can show its first requested item's fields.
        # Verify that relationship through the parent's own requested-item list,
        # then read each sibling by its verified child ID, never by a caller table.
        if record.record_type == "sc_request":
            for child in children:
                child_page = page if data.get("sys_id") == child.item_id else self.session.read(
                    "sc_request", {"sys_id": child.item_id, "table": "sc_req_item", "view": "ntusp"}, refresh=refresh)
                detail_pages.append(child_page)
                records.append(record_details(child_page, child.item_id, "sc_req_item"))
        if not records:
            raise OneStopError("One Stop did not return readable request details.")
        sources = [*pages, *detail_pages]
        return RequestDetails(retrieved_at=min(p.retrieved_at for p in sources), source_url=page.source_url,
                              cached=all(p.cached for p in sources), request=record,
                              records=records, requested_items=children)

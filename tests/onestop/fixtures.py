"""Synthetic structures matching hydrated NTU widgets; no real portal records."""

from copy import deepcopy
from datetime import datetime, timezone

from onestop.models import AuthStatus
from onestop.session import LIST_PAGES, PortalPage, page_url


CATEGORY, CHILD, FORM, ARTICLE, REQUEST = (str(i) * 32 for i in range(1, 6))
FORM_ITEM = dict(sys_id=FORM, name="Example form", short_description="Request help", type="sc", page="sc_cat_item")


def list_data(records=None, source_count=None):
    records = records or []
    return dict(isValid=True, count=len(records) if source_count is None else source_count, maxCount=500,
                secondary_names=["number", "state", "sys_created_on"], list=records)


RECORD = dict(sys_id=REQUEST, className="sc_request", display_field=dict(display_value="Example request"),
              secondary_fields=[dict(display_value=v) for v in ["REQ000001", "Closed Complete", "2026-10-01 10:00:00"]],
              url=dict(id="sc_request", sys_id=REQUEST, table="sc_request", view="ntusp"))


class FixtureSession:
    def __init__(self):
        self.calls = []
        self.revision = "fixture-revision"
        self.overrides = {}

    def status(self):
        return AuthStatus(credentials_configured=True, credential_error=None, session_verified=False, last_verified_at=None)

    def read(self, page_id, params=None, refresh=False):
        params = params or {}
        self.calls.append((page_id, params.copy(), refresh))
        if page_id == "sc_home":
            data = {"categories": {"total": 1, "categoriesList": [dict(
                sys_id=CATEGORY, title="Example services", count=2, totalCount=3,
                subcategories=[dict(sys_id=CHILD, title="Child", count=1, totalCount=1, subcategories=[])])]},
                "popular": {"items": [FORM_ITEM], "limit": 9}}
        elif page_id == "sc_category":
            data = {"category": dict(category_id=params["sys_id"], category={"title": "Example services"}, total_item=4,
                                     items=[FORM_ITEM, dict(sys_id="a" * 32, name="External system", type="content_item",
                                                           content_type="external", url="https://wis.ntu.edu.sg/example"),
                                            dict(sys_id="b" * 32, name="Wrapped form", content_type="external",
                                                 url="/ntussp?id=sc_cat_item&sys_id=" + FORM)])}
        elif page_id == "search":
            results = [dict(sys_id=ARTICLE, type="kb", number="KB000001", short_description="Example guide",
                            text="A <b>safe</b> summary", publishedUTC="2026-10-01")] if params["t"] == "kb" else [FORM_ITEM]
            data = {"search": dict(q=params["q"], t=params["t"], limit=15, results=results)}
        elif page_id == "sc_cat_item":
            data = {"item": dict(recordFound=True, can_view=True, sys_id=FORM, name="Example form",
                                 short_description="Help", description="<p>Read the instructions.</p>", mandatory_attachment=False,
                                 fields=[dict(name="purpose", label="Purpose", type="choice", mandatory=True,
                                              read_only=False, choices=[dict(value="help", label="Help")])])}
        elif page_id == "kb_article_view":
            data = {"article": dict(isValid=True, knowledgeExists=True, isTemplate=False, article_sys_id=ARTICLE,
                                    number="KB000001", shortDesc="Example guide", sys_updated_on="2026-10-01 10:00:00",
                                    content='<h2>Guide</h2><p>First paragraph.</p><script>hidden</script>'
                                            '<p>Second paragraph. <a href="?id=sc_home">Catalog</a></p>'
                                            '<a href="javascript:alert(1)">Invalid</a>')}
        elif page_id in LIST_PAGES.values():
            data = {"requests": list_data([RECORD], 2) if page_id == "my_closed_requests" else list_data()}
        elif page_id == "sc_request":
            data = {"ticket_fields": dict(canRead=True, sys_id="6" * 32, table="sc_req_item",
                                          fields=[dict(name="state", label="State", display_value="Closed Complete")],
                                          variables=[dict(name="purpose", label="Purpose", display_value="Help")]),
                    "requested_items": [dict(sys_id="6" * 32, stage="closed_complete")]}
        else:
            raise AssertionError("Unexpected fixture page")
        data = deepcopy(self.overrides.get(page_id, data))
        return PortalPage(data, datetime(2026, 10, 26, tzinfo=timezone.utc), page_url(page_id, params), self.revision)

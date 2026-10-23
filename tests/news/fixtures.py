"""Synthetic news responses and article markup."""

from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

from news.client import DIRECTORY


CATEGORY_ID = "11111111-1111-4111-8111-111111111111"
ARTICLE_URL = "https://www.ntu.edu.sg/news/detail/synthetic-news-4.5g"
FORM = f'''<html><input name="categories" id="all" value="all"><label for="all">All</label>
<input name="categories" id="research" value="{CATEGORY_ID}">
<label for="research">Research &amp; Discovery</label></html>'''.encode()
ARTICLE = '''<html><body><nav>Navigation must be excluded</nav>
<article class="article-detail__article"><header>
<span class="date">21 Oct 2026</span><h1 class="article-detail__title">A fictional &amp; useful story</h1>
</header><div class="article-detail__body"><div class="rte">
<p>First paragraph with <strong>Unicode café</strong>.</p><p>Second paragraph<br/>continues here.</p>
<script>secret script text</script><style>.hidden { display:none }</style>
</div></div></article><aside>Related stories must be excluded</aside></body></html>'''.encode()


def fake_get(url, refresh=False):
    snapshot = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=url, cached=False)
    if url == DIRECTORY:
        return FORM, snapshot
    if url == ARTICLE_URL:
        return ARTICLE, snapshot
    parsed = urlsplit(url)
    if parsed.path != "/news/GetStories/":
        raise AssertionError("Unexpected offline news request")
    params = parse_qs(parsed.query, keep_blank_values=True)
    page = int(params["page"][0])
    rows = [{"title": "Synthetic story " + str(i), "url": ARTICLE_URL + str(i),
             "date": "21 Oct 2026", "description": ""} for i in range(11)]
    rows[0]["url"] = ARTICLE_URL
    if params["listingKeyword"][0] == "no matches":
        rows = []
    elif params["categories"][0] != "all":
        rows = rows[:1]
    if params["sort"][0] == "oldest":
        rows.reverse()
    return json.dumps({"items": rows[(page - 1) * 10:page * 10], "totalItems": len(rows),
                       "totalPages": (len(rows) + 9) // 10}).encode(), snapshot

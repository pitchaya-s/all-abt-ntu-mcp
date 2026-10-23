import re
from urllib.parse import urlencode
from uuid import UUID

from shared.public_http import PublicHTTPClient
from shared.sitefinity import form_options, query_text
from .models import Categories, NewsError
from . import parser


DIRECTORY = "https://www.ntu.edu.sg/news/"
API = DIRECTORY + "GetStories/"
ARTICLE_URL = r"https://www\.ntu\.edu\.sg/news/detail/[A-Za-z0-9][A-Za-z0-9_.-]{0,499}/?"


class NewsClient:
    def __init__(self):
        self.http = PublicHTTPClient("NTU news", ["www.ntu.edu.sg"], {"application/json", "text/html"})

    def list_categories(self, refresh=False):
        body, snapshot = self.http.get(DIRECTORY, refresh)
        return Categories(categories=form_options(body, "categories"), **snapshot)

    def _page(self, query, category_id, sort, page, refresh):
        params = {"categories": category_id or "all", "page": page, "listingKeyword": query, "sort": sort}
        return parser.search_results(*self.http.get(API + "?" + urlencode(params), refresh), page)

    def search(self, query="", category_id=None, sort="latest", page=1, refresh=False):
        query = query_text(query)
        if type(page) is not int or not 1 <= page <= 10000 or sort not in ("latest", "oldest"):
            raise NewsError("Use page 1–10000 and sort latest or oldest.")
        if category_id is not None:
            category_id = str(UUID(category_id))
            if category_id not in {item.id for item in self.list_categories(refresh).categories}:
                raise NewsError("Unknown category_id; use news_list_categories for current IDs.")
        if page > 1:
            first = self._page(query, category_id, sort, 1, refresh)
            if page > first.total_pages:
                raise NewsError(f"This search has {first.total_pages} pages; start at page 1 and follow next_page.")
        return self._page(query, category_id, sort, page, refresh)

    def get_article(self, url, offset=0, max_chars=12000, refresh=False):
        if not isinstance(url, str) or re.fullmatch(ARTICLE_URL, url) is None:
            raise NewsError("Use an https://www.ntu.edu.sg/news/detail/ article URL returned by news_search.")
        if (type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 50000):
            raise NewsError("Use a non-negative offset and max_chars 1–50000.")
        return parser.article(*self.http.get(url, refresh), offset, max_chars)

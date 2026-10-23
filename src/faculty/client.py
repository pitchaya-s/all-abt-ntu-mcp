from urllib.parse import urlencode
from uuid import UUID

from shared.public_http import PublicHTTPClient
from .models import FacultyError, Interests
from . import parser


DIRECTORY = "https://www.ntu.edu.sg/research/faculty-directory/"
API = DIRECTORY + "GetAcademicProfiles/"


def query_text(value):
    if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise FacultyError("query must be at most 200 characters without control characters; omit it to browse.")
    return value.strip()


class FacultyClient:
    def __init__(self):
        self.http = PublicHTTPClient("NTU faculty directory", ["www.ntu.edu.sg"], {"application/json", "text/html"})

    def _interests(self, refresh):
        body, snapshot = self.http.get(DIRECTORY, refresh)
        return parser.interest_options(body), snapshot

    def list_interests(self, query="", limit=50, offset=0, refresh=False):
        query = query_text(query).casefold()
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise FacultyError("Use limit 1–100 and a non-negative offset.")
        options, snapshot = self._interests(refresh)
        options = [item for item in options if query in item.name.casefold()]
        end = offset + limit
        return Interests(interests=options[offset:end], total_count=len(options),
                         next_offset=end if end < len(options) else None, **snapshot)

    def _page(self, query, interest_id, page, refresh):
        url = API + "?" + urlencode({"interests": interest_id or "all", "page": page, "searchFaculty": query})
        return parser.search_results(*self.http.get(url, refresh), page)

    def search(self, query="", interest_id=None, page=1, refresh=False):
        query = query_text(query)
        if type(page) is not int or not 1 <= page <= 10000:
            raise FacultyError("page must be an integer from 1 to 10000; follow next_page.")
        if interest_id is not None:
            try:
                interest_id = str(UUID(interest_id))
            except (ValueError, TypeError, AttributeError):
                raise FacultyError("Use an interest_id returned by faculty_list_interests.") from None
            options, _ = self._interests(refresh)
            if interest_id not in {item.interest_id for item in options}:
                raise FacultyError("Unknown interest_id; use faculty_list_interests to find current filter IDs.")
        if page > 1:
            # NTU reports zero totals for out-of-range pages, even when the query has matches.
            first = self._page(query, interest_id, 1, refresh)
            if page > first.total_pages:
                raise FacultyError(f"Page exceeds this search's {first.total_pages} pages; start at page 1 and follow next_page.")
        return self._page(query, interest_id, page, refresh)

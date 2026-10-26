import re
from urllib.parse import urlsplit

from . import parser
from .models import CareerAxisError
from .session import CareerAxisSession


class CareerAxisClient:
    def __init__(self):
        self.session = CareerAxisSession()

    def search_opportunities(self, query="", page=1, limit=20, refresh=False):
        if (not isinstance(query, str) or len(query) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in query)):
            raise CareerAxisError("query must be at most 200 characters without control characters; omit it to browse.")
        query = query.strip()
        if type(page) is not int or not 1 <= page <= 50:
            raise CareerAxisError("page must be an integer from 1 to 50; follow has_next_page.")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise CareerAxisError("limit must be an integer from 1 to 50.")
        result = self.session.search(query, page, limit, refresh)
        return parser.search_results(result["data"], result["snapshot"], query, page, limit)

    def search_section(self, section, query="", page=1, limit=20, refresh=False, *,
                       current_opportunities_only=False):
        sections = {"events", "resources", "organisations", "appointment_topics", "internship_jobs"}
        if section not in sections:
            raise CareerAxisError("Choose events, resources, organisations, appointment topics, or internship jobs.")
        if (not isinstance(query, str) or len(query) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in query)):
            raise CareerAxisError("query must be at most 200 characters without control characters.")
        query = query.strip()
        if type(page) is not int or not 1 <= page <= 50:
            raise CareerAxisError("page must be an integer from 1 to 50.")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise CareerAxisError("limit must be an integer from 1 to 50.")
        if current_opportunities_only and section != "organisations":
            raise CareerAxisError("current_opportunities_only can only be used with organisations.")
        result = self.session.search_section(
            section, query, page, limit, refresh,
            current_opportunities_only=current_opportunities_only,
        )
        return parser.portal_results(section, result["data"], result["snapshot"], query, page, limit)

    def get_opportunity(self, url, refresh=False):
        if not isinstance(url, str) or len(url) > 1000:
            raise CareerAxisError("Use an opportunity URL returned by careeraxis_search_opportunities.")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "careeraxis.ntu.edu.sg"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or not re.fullmatch(r"/students/jobs/\d+/?", parsed.path)):
            raise CareerAxisError("Use an opportunity URL returned by careeraxis_search_opportunities.")
        url = parser._opportunity_url(url)
        result = self.session.get_opportunity(url, refresh)
        return parser.opportunity_details(result["data"], result["snapshot"], url)

    def get_portal_record(self, url, refresh=False):
        if not isinstance(url, str) or len(url) > 1000:
            raise CareerAxisError("Use a record URL returned by a CareerAxis search tool.")
        parsed = urlsplit(url)
        paths = (
            r"/students/events/detail/\d+/?",
            r"/students/docs/detail/\d+/?",
            r"/students/organisations/detail/\d+/[A-Za-z0-9._-]+/?",
            r"/students/appointments/topics/\d+/?",
            r"/workgroups/internship/Jobs/detail/\d+/?",
        )
        if (parsed.scheme != "https" or parsed.hostname != "careeraxis.ntu.edu.sg"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or not any(re.fullmatch(path, parsed.path) for path in paths)):
            raise CareerAxisError("Use a CareerAxis event, resource, organisation, appointment topic, or internship URL returned by a search tool.")
        url = "https://careeraxis.ntu.edu.sg" + parsed.path
        result = self.session.get_portal_record(url, refresh)
        return parser.portal_details(result["data"], result["snapshot"], url)

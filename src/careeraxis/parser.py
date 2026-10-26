"""Normalize the rendered CareerAxis job search and opportunity pages."""

import re
from urllib.parse import urlsplit

from .models import (
    CareerAxisError, Opportunity, OpportunityDetails, PortalDetails, PortalItem, PortalResults, SearchResults,
)


def _text(value, *, limit):
    if not isinstance(value, str):
        raise CareerAxisError("CareerAxis returned an unexpected page format; no opportunity data was inferred.")
    value = re.sub(r"[\u200B-\u200F\uFEFF\u2060-\u206F]", "", value)
    value = " ".join(value.split())
    return value[:limit]


def _opportunity_url(value):
    if not isinstance(value, str):
        raise CareerAxisError("CareerAxis returned an unsupported opportunity link.")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != "careeraxis.ntu.edu.sg"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not re.fullmatch(r"/students/jobs/\d+/?", parsed.path)):
        raise CareerAxisError("CareerAxis returned an unsupported opportunity link.")
    return "https://careeraxis.ntu.edu.sg" + parsed.path


_PORTAL_ITEM_PATHS = {
    "events": r"/students/events/detail/\d+/?",
    "resources": r"/students/docs/detail/\d+/?",
    "organisations": r"/students/organisations/detail/\d+/[A-Za-z0-9._-]+/?",
    "appointment_topics": r"/students/appointments/topics/\d+/?",
    "internship_jobs": r"/workgroups/internship/Jobs/detail/\d+/?",
}


def _portal_url(value, section):
    if not isinstance(value, str):
        raise CareerAxisError("CareerAxis returned an unsupported record link.")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != "careeraxis.ntu.edu.sg"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or section not in _PORTAL_ITEM_PATHS
            or not re.fullmatch(_PORTAL_ITEM_PATHS[section], parsed.path)):
        raise CareerAxisError("CareerAxis returned an unsupported record link.")
    return "https://careeraxis.ntu.edu.sg" + parsed.path


def search_results(data, snapshot, query, page, limit):
    if not isinstance(data, dict) or not isinstance(data.get("opportunities"), list):
        raise CareerAxisError("CareerAxis changed its job search page; no opportunity list was inferred.")
    items = []
    seen = set()
    for item in data["opportunities"]:
        if not isinstance(item, dict):
            raise CareerAxisError("CareerAxis changed its job search page; no opportunity list was inferred.")
        title = _text(item.get("title"), limit=500)
        if not title:
            continue
        url = _opportunity_url(item.get("url"))
        details = _text(item.get("details", ""), limit=4000)
        if url in seen:
            continue
        seen.add(url)
        items.append(Opportunity(title=title, url=url, details=details))
    if not items and data.get("no_results") is not True:
        raise CareerAxisError("CareerAxis showed no recognizable opportunity links; no results were inferred.")
    offset = (page - 1) * limit
    selected = items[offset:offset + limit]
    if page > 1 and not selected:
        raise CareerAxisError("CareerAxis has no more opportunities at that page.")
    return SearchResults(
        query=query,
        page=page,
        opportunities=selected,
        has_next_page=data.get("has_next_page") is True or len(items) > offset + limit,
        truncated=len(items) > offset + limit,
        **snapshot,
    )


def opportunity_details(data, snapshot, url):
    if not isinstance(data, dict) or not isinstance(data.get("application_links"), list):
        raise CareerAxisError("CareerAxis changed its opportunity page; no detail text was inferred.")
    title = _text(data.get("title"), limit=500)
    text = _text(data.get("text"), limit=20000)
    if not title or not text:
        raise CareerAxisError("CareerAxis returned an incomplete opportunity detail page; no posting content was inferred.")
    links = []
    for value in data["application_links"]:
        if not isinstance(value, str):
            continue
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            links.append(value)
    return OpportunityDetails(
        title=title,
        url=_opportunity_url(url),
        text=text,
        application_links=list(dict.fromkeys(links))[:20],
        **snapshot,
    )


def portal_results(section, data, snapshot, query, page, limit):
    if section not in _PORTAL_ITEM_PATHS or not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CareerAxisError("CareerAxis changed this section; no record list was inferred.")
    items = []
    seen = set()
    for raw in data["items"]:
        if not isinstance(raw, dict):
            raise CareerAxisError("CareerAxis changed this section; no record list was inferred.")
        title = _text(raw.get("title"), limit=500)
        if not title:
            continue
        url = _portal_url(raw.get("url"), section)
        summary = _text(raw.get("summary", ""), limit=4000)
        if url in seen:
            continue
        seen.add(url)
        items.append(PortalItem(title=title, url=url, summary=summary))
    if not items and data.get("no_results") is not True:
        raise CareerAxisError("CareerAxis showed no recognizable records; no results were inferred.")
    offset = (page - 1) * limit
    selected = items[offset:offset + limit]
    if page > 1 and not selected:
        raise CareerAxisError("CareerAxis has no more records at that page.")
    return PortalResults(
        section=section,
        query=query,
        page=page,
        items=selected,
        has_next_page=data.get("has_next_page") is True or len(items) > offset + limit,
        truncated=len(items) > offset + limit,
        **snapshot,
    )


def portal_details(data, snapshot, url):
    if not isinstance(data, dict) or not isinstance(data.get("links"), list):
        raise CareerAxisError("CareerAxis changed this detail page; no record text was inferred.")
    parsed = urlsplit(url)
    section = next((name for name, pattern in _PORTAL_ITEM_PATHS.items()
                    if re.fullmatch(pattern, parsed.path)), None)
    if section is None:
        raise CareerAxisError("Use a CareerAxis record URL returned by a search tool.")
    title = _text(data.get("title"), limit=500)
    text = _text(data.get("text"), limit=20000)
    generic_titles = {"students", "loading...", "be scam-aware", "appointments", "documents", "resources",
                      "search events", "search topics", "search organisations", "internship", "internship opportunities",
                      "opportunity details", "careeraxis", "careeraxis opportunities", "opportunities", "notifications"}
    if not title or title.casefold() in generic_titles or not text or "{{" in title or "}}" in title:
        raise CareerAxisError("CareerAxis returned an empty or incomplete detail page.")
    links = []
    for value in data["links"]:
        if not isinstance(value, str):
            continue
        link = urlsplit(value)
        if (link.scheme == "https" and link.hostname and link.port in (None, 443)
                and not link.username and not link.password):
            links.append(value)
    return PortalDetails(
        title=title,
        url=_portal_url(url, section),
        text=text,
        links=list(dict.fromkeys(links))[:30],
        **snapshot,
    )

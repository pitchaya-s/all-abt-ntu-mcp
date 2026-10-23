from html.parser import HTMLParser
import re
from urllib.parse import urlencode, urlsplit

from .models import LibraryError, Link, Record, RecordSummary


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li"):
            self.parts.append("\n")


def strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise LibraryError("OneSearch returned an unexpected bibliographic field format.")
    return value


def clean(value):
    # $$Q carries a secondary search/index form, not part of the visible label.
    value = value.split("$$Q", 1)[0]
    parser = _Text()
    parser.feed(value)
    return "".join(parser.parts).strip()


def values(block, key):
    return list(dict.fromkeys(clean(v) for v in strings(block.get(key, []))))


def summary(data):
    pnx = data["pnx"]
    display, control, additional = pnx["display"], pnx["control"], pnx.get("addata", {})
    record_ids = strings(control["recordid"])
    titles = values(display, "title")
    if (
        len(record_ids) != 1
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,299}", record_ids[0])
        or not titles
        or not titles[0]
    ):
        raise LibraryError("OneSearch returned a record without a usable canonical ID or title.")
    context = data["context"]
    access = strings(additional.get("openaccess", []))
    if access and (len(set(access)) != 1 or access[0].casefold() not in ("true", "false")):
        raise LibraryError("OneSearch returned ambiguous open-access metadata.")
    delivery = data.get("delivery") or {}
    availability = delivery.get("availability")
    url = "https://ntu-sp.primo.exlibrisgroup.com/discovery/fulldisplay?" + urlencode(
        {
            "docid": record_ids[0],
            "context": context,
            "vid": "65NTU_INST:65NTU_INST",
            "lang": "en",
        }
    )
    return RecordSummary(
        record_id=record_ids[0],
        context=context,
        title=titles[0],
        resource_types=values(display, "type"),
        authors=values(additional, "au") or values(display, "creator"),
        publication_dates=values(display, "creationdate"),
        open_access=access[0].casefold() == "true" if access else None,
        availability_codes=strings(availability) if availability is not None else None,
        availability_label=delivery.get("displayedAvailability"),
        catalogue_url=url,
    )


def record(data):
    brief = summary(data)
    display, additional = data["pnx"]["display"], data["pnx"].get("addata", {})
    links, seen = [], set()
    raw_links = (data.get("delivery") or {}).get("link") or []
    if not isinstance(raw_links, list) or any(not isinstance(v, dict) for v in raw_links):
        raise LibraryError("OneSearch returned invalid delivery links.")
    candidates = [v for v in raw_links if v.get("linkType") != "thumbnail"]
    candidates.extend(
        {"linkURL": url, "linkType": "source", "displayLabel": None}
        for url in strings(additional.get("url", []))
    )
    for value in candidates:
        url = value.get("linkURL")
        if not url:
            continue
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise LibraryError("OneSearch returned an unsupported access link.")
        if url not in seen:
            links.append(Link(url=url, label=value.get("displayLabel"), link_type=value.get("linkType")))
            seen.add(url)
    return Record(
        **brief.model_dump(),
        alternate_titles=values(display, "title")[1:],
        contributors=values(additional, "addau") or values(display, "contributor"),
        publishers=values(display, "publisher"),
        editions=values(display, "edition"),
        languages=values(display, "language"),
        subjects=values(display, "subject"),
        descriptions=values(display, "description"),
        identifiers={
            key: values(additional, key) for key in ("isbn", "issn", "eissn", "doi") if additional.get(key)
        },
        links=links,
    )

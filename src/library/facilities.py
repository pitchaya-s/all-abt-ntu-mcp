"""Public LibFacilities directory and point-in-time map availability."""

from datetime import date, datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from shared.public_http import PublicHTTPClient
from .models import Facilities, Facility, LibraryError, MapAvailability, SpaceStatus

BASE = "https://libcalendar.ntu.edu.sg"
SGT = ZoneInfo("Asia/Singapore")


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.library = ""
        self.heading = None
        self.link = None
        self.notice = None
        self.notices = []
        self.facilities = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h1":
            self.heading = []
        elif tag == "td":
            self.notice = []
        elif tag == "a" and self.heading is None:
            self.link = (attrs.get("href", ""), [])

    def handle_data(self, value):
        for target in (self.heading, self.notice):
            if target is not None:
                target.append(value)
        if self.link is not None:
            self.link[1].append(value)

    def handle_endtag(self, tag):
        if tag == "h1" and self.heading is not None:
            self.library = " ".join("".join(self.heading).split())
            self.heading = None
        elif tag == "td" and self.notice is not None:
            text = " ".join("".join(self.notice).split())
            if text:
                self.notices.append(text)
            self.notice = None
        elif tag == "a" and self.link is not None:
            href, parts = self.link
            self.link = None
            parsed = urlsplit(urljoin(BASE, href))
            if parsed.scheme != "https" or parsed.netloc != "libcalendar.ntu.edu.sg":
                return
            params = parse_qs(parsed.query)
            fields = {}
            if re.fullmatch(r"/map/[a-f0-9]{12}", parsed.path):
                fields["map_slug"] = parsed.path.rsplit("/", 1)[1]
            elif re.fullmatch(r"/space/[1-9][0-9]{0,9}", parsed.path):
                fields["space_id"] = int(parsed.path.rsplit("/", 1)[1])
            elif parsed.path == "/spaces" and all(
                re.fullmatch(r"[1-9][0-9]{0,9}", params.get(k, [""])[0]) for k in ("lid", "gid")
            ):
                fields.update(location_id=int(params["lid"][0]), group_id=int(params["gid"][0]))
            else:
                return
            name = " ".join("".join(parts).split())
            if not name or not self.library:
                raise LibraryError("LibFacilities returned an unlabelled directory entry.")
            self.facilities.append(Facility(library=self.library, name=name, url=parsed.geturl(), **fields))


def directory(body, snapshot):
    parser = DirectoryParser()
    parser.feed(body.decode("utf-8"))
    if not parser.facilities:
        raise LibraryError("LibFacilities returned an unexpected directory; no facilities were inferred.")
    return Facilities(facilities=parser.facilities, notices=parser.notices, **snapshot)


def script_json(html, name):
    match = re.search(r"\b" + re.escape(name) + r"\s*:\s*", html)
    if match is None:
        raise LibraryError("LibFacilities changed its map format; no availability was inferred.")
    return json.JSONDecoder().raw_decode(html, match.end())[0]


def map_availability(body, slug, at, snapshot):
    html = body.decode("utf-8")
    records = script_json(html, "linkModelsByShapeId")
    if not isinstance(records, dict) or not records:
        raise LibraryError("LibFacilities returned an empty or invalid map model.")
    spaces = {}
    for value in records.values():
        if value["type"] != 2:
            continue
        item = SpaceStatus(
            space_id=value["id"],
            name=value["title"],
            source_status=value["status"],
            status={10: "available", 5: "available_later", 1: "unavailable"}.get(value["status"], "unknown"),
        )
        if item.space_id in spaces and spaces[item.space_id] != item:
            raise LibraryError("LibFacilities returned conflicting map statuses.")
        spaces[item.space_id] = item
    if not spaces:
        raise LibraryError("This map returned no identifiable seat or room statuses.")
    return MapAvailability(map_slug=slug, at=at, spaces=list(spaces.values()), **snapshot)


def requested_time(day, time):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", time
        ):
            raise ValueError
        return datetime.combine(date.fromisoformat(day), datetime.strptime(time, "%H:%M").time(), SGT)
    except ValueError:
        raise LibraryError("Use a valid date YYYY-MM-DD and Singapore time HH:MM.") from None


class FacilitiesClient:
    def __init__(self):
        self.http = PublicHTTPClient("NTU LibFacilities", ["libcalendar.ntu.edu.sg"], {"text/html"})

    def list_facilities(self, refresh=False):
        return directory(*self.http.get(BASE + "/", refresh))

    def get_map_availability(self, map_slug, day, time, refresh=False):
        if not re.fullmatch(r"[a-f0-9]{12}", map_slug):
            raise LibraryError("Use map_slug exactly as returned by library_list_facilities.")
        at = requested_time(day, time)
        body, _ = self.http.get(BASE + "/map/" + map_slug, refresh)
        map_id = script_json(body.decode("utf-8"), "mapId")
        if type(map_id) is not int or map_id <= 0:
            raise LibraryError("LibFacilities returned an invalid map ID.")
        url = (
            BASE
            + "/maps/search/spaces?"
            + urlencode(
                {
                    "term": at.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": 3,
                    "map": map_id,
                    "location": 0,
                    "preview": 0,
                }
            )
        )
        body, snapshot = self.http.get(url, refresh)
        if script_json(body.decode("utf-8"), "mapId") != map_id:
            raise LibraryError("LibFacilities returned a different map.")
        return map_availability(body, map_slug, at, snapshot)

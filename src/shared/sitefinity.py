"""Public NTU website text, form options, and listing envelopes."""

from html.parser import HTMLParser
import json
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FilterOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    name: str


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li"):
            self.parts.append("\n")


def lines(value):
    if value is None:
        return None
    parser = Text()
    parser.feed(value)
    return [" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip()]


def text(value):
    parts = lines(value)
    return " ".join(parts) if parts else None


def query_text(value):
    if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("query must contain at most 200 characters without control characters.")
    return value.strip()


def link(value):
    if value is None or value == "":
        return None
    url = urljoin("https://www.ntu.edu.sg/", value)
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443)):
        raise ValueError("Unsupported website link.")
    return url


def page_data(body, page, page_size):
    data = json.loads(body)
    if (not isinstance(data, dict) or not isinstance(data.get("items"), list)
            or type(data.get("totalItems")) is not int or data["totalItems"] < 0
            or type(data.get("totalPages")) is not int or data["totalPages"] < 0):
        raise ValueError("Unexpected website listing envelope.")
    total = data["totalItems"]
    if (data["totalPages"] != (total + page_size - 1) // page_size
            or len(data["items"]) != min(page_size, max(0, total - (page - 1) * page_size))
            or any(not isinstance(item, dict) for item in data["items"])):
        raise ValueError("Inconsistent website pagination.")
    return data


class FormOptions(HTMLParser):
    def __init__(self, field):
        super().__init__(convert_charrefs=True)
        self.field = field
        self.inputs = {}
        self.label = None
        self.options = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == self.field and attrs.get("value") != "all":
            self.inputs[attrs["id"]] = str(UUID(attrs["value"]))
        elif tag == "label" and attrs.get("for") in self.inputs:
            self.label = (self.inputs[attrs["for"]], [])

    def handle_data(self, value):
        if self.label is not None:
            self.label[1].append(value)

    def handle_endtag(self, tag):
        if tag == "label" and self.label is not None:
            identifier, parts = self.label
            self.label = None
            name = " ".join("".join(parts).split())
            if not name or identifier in self.options and self.options[identifier].name != name:
                raise ValueError("Missing or conflicting website filter labels.")
            self.options[identifier] = FilterOption(id=identifier, name=name)


def form_options(body, field):
    html = body.decode("utf-8")
    parser = FormOptions(field)
    parser.feed(html)
    if (not parser.options or set(parser.inputs.values()) != parser.options.keys()
            or parser.label is not None or "</html>" not in html.lower()):
        raise ValueError("Incomplete website filter form.")
    return sorted(parser.options.values(), key=lambda item: item.name.casefold())

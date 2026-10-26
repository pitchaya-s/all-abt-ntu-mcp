from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .models import OneStopError
from .session import PORTAL, SYS_ID


def text(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise OneStopError("One Stop returned a missing or invalid text field.")
    return value.strip()


def sys_id(value):
    if not isinstance(value, str) or not SYS_ID.fullmatch(value):
        raise OneStopError("One Stop returned an invalid record ID.")
    return value


def count(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,8}", value):
        value = int(value)
    if type(value) is not int or value < 0:
        raise OneStopError("One Stop returned an invalid record count.")
    return value


def safe_url(value, base=PORTAL):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000 or any(ord(c) < 32 for c in value):
        return None
    result = urljoin(base, value.strip())
    try:
        u = urlsplit(result)
        if u.scheme not in {"https", "http"} or not u.hostname or u.username or u.password:
            return None
        if u.port not in (None, 80, 443):
            return None
    except ValueError:
        return None
    return result


class _HTML(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts = []
        self.links = []
        self.hidden = 0
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table"}:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            self.parts.append("\t")
        if tag == "a":
            self.anchor = (safe_url(dict(attrs).get("href"), self.base), [])

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"}:
            self.parts.append("\n")
        if tag == "a" and self.anchor:
            url, parts = self.anchor
            if url:
                self.links.append({"label": " ".join("".join(parts).split()), "url": url})
            self.anchor = None

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.anchor:
                self.anchor[1].append(data)


def html_content(value, base=PORTAL):
    parser = _HTML(base)
    parser.feed(text(value, required=True))
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    body = "\n".join(line for line in lines if line)
    links = list({(link["label"], link["url"]): link for link in parser.links}.values())
    return body, links


def pagination(available, total, complete, offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise OneStopError("Use a nonnegative offset and a limit from 1 to 100.")
    return dict(offset=offset, available_count=available, total_count=total, complete=complete,
                next_offset=offset + limit if offset + limit < available else None)

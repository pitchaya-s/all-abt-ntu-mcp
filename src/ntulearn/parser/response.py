"""Only known academic fields leave the local process; raw user/session payloads do not."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from ..models import LearnError


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise LearnError("NTULearn returned an unexpected text field.")
    parser = _Text()
    parser.feed(value)
    return "\n".join(line for raw in "".join(parser.parts).splitlines() if (line := " ".join(raw.split())))


def records(data, path):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list) or any(not isinstance(item, dict) for item in data["results"]):
        raise LearnError("NTULearn returned an unfamiliar result list; no data was inferred.")
    paging = data.get("paging") or {}
    if not isinstance(paging, dict):
        raise LearnError("NTULearn returned unfamiliar pagination metadata.")
    next_page = paging.get("nextPage")
    offset = None
    if next_page:
        if not isinstance(next_page, str):
            raise LearnError("NTULearn returned an invalid next page.")
        url = urlsplit(next_page)
        if url.netloc and (url.scheme != "https" or url.netloc != "ntulearn.ntu.edu.sg"):
            raise LearnError("NTULearn returned a next page outside its own HTTPS origin.")
        if url.path != path:
            raise LearnError("NTULearn returned a next page for a different endpoint.")
        try:
            offset = int(parse_qs(url.query)["offset"][0])
            if offset < 0:
                raise ValueError
        except (KeyError, ValueError, IndexError) as error:
            raise LearnError("NTULearn returned an invalid next-page offset.") from error
    return data["results"], offset


def required(item, key):
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise LearnError("NTULearn returned a record missing a required identifier or title.")
    return value

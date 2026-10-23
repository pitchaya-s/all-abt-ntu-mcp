from html.parser import HTMLParser

from shared.sitefinity import link, page_data, text
from .models import Article, NewsError, SearchResults, Story


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "blockquote", "tr", "br"}


def search_results(body, snapshot, page):
    data = page_data(body, page, 10)
    stories = [Story(title=text(item["title"]), url=link(item["url"]),
                     published_date=text(item.get("date")), summary=text(item.get("description")))
               for item in data["items"]]
    if len({story.url for story in stories}) != len(stories):
        raise NewsError("NTU returned duplicate stories in one result page.")
    return SearchResults(stories=stories, page=page, total_count=data["totalItems"], total_pages=data["totalPages"],
                         next_page=page + 1 if page < data["totalPages"] else None, **snapshot)


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.article_depth = None
        self.active = {}
        self.parts = {"title": [], "date": [], "body": []}
        self.closed = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        depth = len(self.stack)
        if "article-detail__article" in classes:
            if self.article_depth is not None or "article" in self.closed:
                raise NewsError("NTU returned multiple article bodies; retrieval stopped.")
            self.article_depth = depth
        if self.article_depth is not None:
            role = ("body" if "article-detail__body" in classes else "title" if "article-detail__title" in classes
                    else "date" if "date" in classes and "body" not in self.active else None)
            if role:
                if role in self.active or role in self.closed:
                    raise NewsError("NTU returned conflicting article sections.")
                self.active[role] = depth
            if "body" in self.active and tag in BLOCKS:
                self.parts["body"].append("\n")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, value):
        if not any(tag in ("script", "style", "template", "noscript") for tag in self.stack):
            for role in self.active:
                self.parts[role].append(value)

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        depth = len(self.stack) - 1 - self.stack[::-1].index(tag)
        if "body" in self.active and tag in BLOCKS:
            self.parts["body"].append("\n")
        for role, start in list(self.active.items()):
            if start >= depth:
                if start != depth:
                    raise NewsError("NTU returned an incomplete article section.")
                self.closed.add(role)
                del self.active[role]
        if self.article_depth is not None and depth <= self.article_depth:
            if depth != self.article_depth:
                raise NewsError("NTU returned an incomplete article element.")
            self.article_depth = None
            self.closed.add("article")
        del self.stack[depth:]


def article(body, snapshot, offset, max_chars):
    html = body.decode("utf-8")
    parser = ArticleParser()
    parser.feed(html)
    title = " ".join("".join(parser.parts["title"]).split())
    content = "\n".join(" ".join(line.split()) for line in "".join(parser.parts["body"]).splitlines() if line.strip())
    if not {"article", "title", "body"} <= parser.closed or not title or not content or "</html>" not in html.lower():
        raise NewsError("NTU changed its news article format; no article text was inferred.")
    end = offset + max_chars
    return Article(title=title, published_date=" ".join("".join(parser.parts["date"]).split()) or None,
                   text=content[offset:end], total_characters=len(content),
                   next_offset=end if end < len(content) else None, **snapshot)

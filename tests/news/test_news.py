import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from news import mcp_server, parser
from news.client import NewsClient
from news.models import NewsError
from shared.public_http import PublicRequestError
from mcp.server.mcpserver.exceptions import ToolError
from .fixtures import ARTICLE, ARTICLE_URL, CATEGORY_ID, FORM, fake_get


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.client = NewsClient()
        self.fetch = patch.object(self.client.http, "get", side_effect=fake_get).start()
        self.addCleanup(patch.stopall)

    def test_search_pagination_sort_empty_and_category(self):
        first = self.client.search()
        second = self.client.search(page=first.next_page)
        self.assertEqual((first.total_count, len(first.stories), len(second.stories)), (11, 10, 1))
        self.assertIsNone(second.next_page)
        self.assertNotIn(first.stories[0].url, {item.url for item in second.stories})
        self.assertEqual(self.client.search(sort="oldest").stories[0].url, second.stories[0].url)
        self.assertEqual(self.client.search("no matches").stories, [])
        categories = self.client.list_categories()
        self.assertEqual(categories.categories[0].name, "Research & Discovery")
        self.assertEqual(self.client.search(category_id=CATEGORY_ID).total_count, 1)
        with self.assertRaisesRegex(NewsError, "pages"):
            self.client.search(page=3)

    def test_query_encoding_and_refresh(self):
        self.client.search("quantum & sort=oldest", refresh=True)
        url, refresh = self.fetch.call_args.args
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["listingKeyword"], ["quantum & sort=oldest"])
        self.assertEqual(params["sort"], ["latest"])
        self.assertTrue(refresh)

    def test_article_excludes_boilerplate_and_supports_lossless_chunks(self):
        full = self.client.get_article(ARTICLE_URL)
        self.assertEqual(full.title, "A fictional & useful story")
        self.assertEqual(full.published_date, "21 Oct 2026")
        self.assertIn("Unicode café", full.text)
        for unwanted in ("Navigation", "Related", "secret script", "display:none"):
            self.assertNotIn(unwanted, full.text)
        first = self.client.get_article(ARTICLE_URL, max_chars=15)
        second = self.client.get_article(ARTICLE_URL, offset=first.next_offset)
        self.assertEqual(first.text + second.text, full.text)
        self.assertIsNone(second.next_offset)
        self.assertEqual(full.total_characters, len(full.text))

    def test_unexpected_pages_and_unsafe_urls_fail(self):
        for url in ["https://evil.example/news/detail/example", "http://www.ntu.edu.sg/news/detail/example",
                    "https://www.ntu.edu.sg/news/detail/../GetStories", "https://www.ntu.edu.sg/news/detail/example?x=y"]:
            with self.assertRaises(NewsError):
                self.client.get_article(url)
        self.fetch.assert_not_called()
        for body in [b"<html><body>Maintenance</body></html>", ARTICLE.replace(b"</html>", b""),
                     ARTICLE.replace(b"article-detail__body", b"changed-body"),
                     ARTICLE.replace(b"</article>", b""), ARTICLE.replace(b"</div></div>", b"")]:
            with self.subTest(body=body[:40]), self.assertRaises(NewsError):
                parser.article(body, fake_get(ARTICLE_URL)[1], 0, 1000)
        for data in [{}, {"items": {}, "totalItems": 0, "totalPages": 0},
                     {"items": [], "totalItems": 1, "totalPages": 1},
                     {"items": [], "totalItems": "0", "totalPages": 0}]:
            with self.assertRaises((ValueError, KeyError, TypeError)):
                parser.search_results(json.dumps(data).encode(), fake_get(ARTICLE_URL)[1], 1)

    def test_invalid_queries_filters_and_errors(self):
        for args in [dict(query="bad\nquery"), dict(query="x" * 201), dict(page=True), dict(sort="unsupported"),
                     dict(category_id="33333333-3333-4333-8333-333333333333")]:
            with self.assertRaises((NewsError, ValueError)):
                self.client.search(**args)
        for error in (PublicRequestError("NTU news returned HTTP 503; try again later."), KeyError("raw provider detail")):
            with patch.object(mcp_server.client, "search", side_effect=error), self.assertRaises(ToolError) as caught:
                mcp_server.search()
            self.assertNotIn("raw provider detail", str(caught.exception))
        with patch.object(self.client.http, "get", return_value=(FORM.replace(b"</html>", b""), {})):
            with self.assertRaises(ValueError):
                self.client.list_categories()

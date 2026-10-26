import time
import unittest
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server import MCPServer

from onestop import mcp_server
from onestop.client import OneStopClient
from onestop.models import OneStopError
from onestop.session import OneStopSession, page_url
from shared.credentials import delete_credentials, read_credentials, save_credentials
from tests.credential_fixtures import stored_credentials
from tests.onestop.fixtures import ARTICLE, CATEGORY, FORM, REQUEST, FixtureSession, list_data


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = OneStopClient(self.session)

    def test_catalog_hierarchy_external_links_and_partial_category_results(self):
        categories = self.client.list_categories()
        self.assertTrue(categories.complete)
        self.assertEqual(categories.categories[1].parent_id, CATEGORY)
        popular = self.client.list_catalog_items()
        self.assertEqual(popular.scope, "popular")
        self.assertFalse(popular.complete)
        self.assertIsNone(popular.total_count)
        items = self.client.list_catalog_items(category_id=CATEGORY, limit=2)
        self.assertFalse(items.complete)
        self.assertEqual((items.available_count, items.total_count, items.next_offset), (3, 4, 2))
        self.assertEqual(items.items[0].form_item_id, FORM)
        self.assertEqual(items.items[1].kind, "external")
        self.assertIsNone(items.items[1].form_item_id)
        rest = self.client.list_catalog_items(category_id=CATEGORY, offset=2)
        self.assertEqual(rest.items[0].form_item_id, FORM)
        self.assertEqual(self.client.get_catalog_item(FORM).fields[0].choices[0].label, "Help")
        with self.assertRaises(OneStopError):
            self.client.list_catalog_items(query="help", category_id=CATEGORY)

    def test_knowledge_text_pagination_links_and_nonexhaustive_search(self):
        results = self.client.search_knowledge(" VPN ")
        self.assertEqual(results.query, "VPN")
        self.assertFalse(results.complete)
        self.assertIsNone(results.total_count)
        self.assertEqual(results.articles[0].summary, "A safe summary")
        first = self.client.get_knowledge_article(ARTICLE, max_chars=10)
        rest = self.client.get_knowledge_article(ARTICLE, offset=first.next_offset, max_chars=50000)
        self.assertEqual(first.total_characters, len(first.text + rest.text))
        self.assertNotIn("hidden", first.text + rest.text)
        self.assertEqual(len(first.links), 1)
        self.assertTrue(first.links[0].url.startswith("https://ntuadminonestop.service-now.com/ntussp?"))

    def test_personal_list_coverage_and_ownership_check_before_detail(self):
        results = self.client.list_my_requests()
        self.assertEqual((results.available_count, results.total_count), (1, 2))
        self.assertFalse(results.complete)
        self.assertIsNone(results.next_offset)
        self.assertEqual(len(results.coverage), 4)
        self.assertEqual(results.requests[0].state, "Closed Complete")
        details = self.client.get_my_request(REQUEST)
        self.assertEqual(details.records[0].fields[0].value, "Closed Complete")
        self.assertEqual(details.records[0].record_id, "6" * 32)
        self.assertEqual(details.requested_items[0].stage, "closed_complete")
        self.session.calls.clear()
        with self.assertRaisesRegex(OneStopError, "not in your retrieved"):
            self.client.get_my_request("f" * 32)
        self.assertFalse(any(page == "sc_request" for page, _, _ in self.session.calls))

    def test_count_cap_is_not_an_exact_total_and_missing_widgets_are_not_empty_lists(self):
        self.session.overrides["my_closed_requests"] = {"requests": list_data(source_count=500)}
        result = self.client.list_my_requests(status="closed", kind="request")
        self.assertIsNone(result.total_count)
        self.assertFalse(result.complete)
        self.assertTrue(result.coverage[0].source_count_is_lower_bound)
        self.session.overrides["my_closed_requests"] = {}
        with self.assertRaisesRegex(OneStopError, "did not finish loading"):
            self.client.list_my_requests(status="closed", kind="request")

    def test_wrong_record_or_account_change_does_not_return_request_data(self):
        self.session.overrides["sc_request"] = {"ticket_fields": dict(canRead=True, sys_id="f" * 32, table="sc_request")}
        with self.assertRaisesRegex(OneStopError, "did not verify access"):
            self.client.get_my_request(REQUEST)
        self.session.overrides.clear()
        original = self.session.read

        def rotate(*args, **kwargs):
            page = original(*args, **kwargs)
            if args[0] == "sc_request":
                page.revision = "changed-account"
            return page

        with patch.object(self.session, "read", side_effect=rotate):
            with self.assertRaisesRegex(OneStopError, "account changed"):
                self.client.get_my_request(REQUEST)

    def test_sibling_items_are_read_only_through_verified_parent_relationships(self):
        original = self.session.read

        def siblings(page_id, params=None, refresh=False):
            page = original(page_id, params, refresh)
            if page_id == "sc_request":
                if params["table"] == "sc_request":
                    page.data["requested_items"].append(dict(sys_id="7" * 32, stage="requested"))
                else:
                    page.data["ticket_fields"]["sys_id"] = params["sys_id"]
            return page

        with patch.object(self.session, "read", side_effect=siblings):
            result = self.client.get_my_request(REQUEST)
        self.assertEqual([r.record_id for r in result.records], ["6" * 32, "7" * 32])
        child_calls = [(page, params) for page, params, _ in self.session.calls
                       if params.get("table") == "sc_req_item"]
        self.assertEqual(child_calls, [("sc_request", {"sys_id": "7" * 32, "table": "sc_req_item", "view": "ntusp"})])

    def test_invalid_queries_and_unavailable_articles_are_explicit(self):
        for query in (" ", "x\nprivate", "x\x7f", "x" * 201):
            with self.assertRaises(OneStopError):
                self.client.search_knowledge(query)
        self.session.overrides["kb_article_view"] = {"article": {"isValid": False}}
        with self.assertRaisesRegex(OneStopError, "unavailable"):
            self.client.get_knowledge_article(ARTICLE)
        self.session.overrides["kb_article_view"] = {"article": {"isValid": True, "knowledgeExists": True, "isTemplate": True}}
        with self.assertRaisesRegex(OneStopError, "unsupported template"):
            self.client.get_knowledge_article(ARTICLE)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.session = OneStopSession()
        self.addCleanup(self.session.close)

    def test_revoked_credentials_block_cached_reads_and_clear_status(self):
        with stored_credentials():
            credentials = read_credentials()
            self.session._revision = credentials.revision
            self.session._verified = True
            url = page_url("sc_home", {})
            fixture = FixtureSession().read("sc_home")
            fixture.revision = credentials.revision
            self.session._cache[url] = (time.monotonic(), fixture)
            self.assertTrue(self.session.read("sc_home").cached)
            delete_credentials()
            with self.assertRaisesRegex(OneStopError, "auth save"):
                self.session.read("sc_home")
            self.assertFalse(self.session._cache)
            self.assertFalse(self.session.status().session_verified)

    def test_rotation_and_locked_storage_invalidate_session_without_logging_in(self):
        with stored_credentials() as backend:
            self.session._run(self.session._credentials)
            self.session._verified = True
            self.session._cache["private"] = "old-account-record"
            save_credentials("other001", "new-test-secret")
            with patch.object(self.session, "_open") as browser:
                self.assertTrue(self.session.status().credentials_configured)
                browser.assert_not_called()
            self.assertFalse(self.session._verified or self.session._cache)
            with patch.object(backend, "get_password", side_effect=RuntimeError("secret-backend-detail")):
                status = self.session.status()
            self.assertIsNone(status.credentials_configured)
            self.assertNotIn("secret-backend-detail", status.model_dump_json())

    def test_unsafe_routes_and_raw_browser_errors_are_not_exposed(self):
        for page, params in [("form", {}), ("search", {"q": "x", "t": "all"}),
                             ("sc_cat_item", {"sys_id": "../escape"}),
                             ("sc_home", {"action": "submit"})]:
            with self.assertRaises(OneStopError):
                self.session.read(page, params)

        def fail():
            raise RuntimeError("password=private-test-secret cookie=session-secret")

        with self.assertRaises(OneStopError) as error:
            self.session._run(fail)
        self.assertNotIn("private-test-secret", str(error.exception))
        self.assertNotIn("session-secret", str(error.exception))

    def test_unsupported_login_host_receives_no_password(self):
        with stored_credentials():
            self.session._page = Mock(url="https://unexpected.invalid/adfs/ls/")
            with patch.object(self.session, "_open"):
                with self.assertRaisesRegex(OneStopError, "unsupported login host"):
                    self.session._login(read_credentials())
            self.session._page.locator.assert_not_called()


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_schemas_read_calls_and_sanitized_errors(self):
        fixture = FixtureSession()
        server = MCPServer("onestop-offline")
        mcp_server.register_tools(server)
        with patch.object(mcp_server, "client", OneStopClient(fixture)), patch.object(mcp_server, "session", fixture):
            async with Client(server) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                self.assertEqual(len(tools), 59)
                from onestop.workflow_tools import READ_TOOLS, LOCAL_TOOLS, WRITE_TOOLS
                for tool in tools.values():
                    name = tool.name.removeprefix("onestop_")
                    self.assertEqual(tool.annotations.read_only_hint, name not in WRITE_TOOLS)
                    if name in READ_TOOLS:
                        self.assertTrue(tool.annotations.idempotent_hint)
                    if name in LOCAL_TOOLS:
                        self.assertFalse(tool.annotations.idempotent_hint)
                    Draft202012Validator.check_schema(tool.input_schema)
                    Draft202012Validator.check_schema(tool.output_schema)
                for name, args in [
                    ("onestop_auth_status", {}), ("onestop_list_catalog_categories", {}),
                    ("onestop_list_catalog_items", {"category_id": CATEGORY}),
                    ("onestop_get_catalog_item", {"item_id": FORM}),
                    ("onestop_search_knowledge", {"query": "VPN"}),
                    ("onestop_get_knowledge_article", {"article_id": ARTICLE}),
                    ("onestop_list_my_requests", {}), ("onestop_get_my_request", {"request_id": REQUEST}),
                ]:
                    result = await client.call_tool(name, args)
                    self.assertFalse(result.is_error, name)
                    Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
                for name, args in [
                    ("onestop_get_catalog_item", {"item_id": "../escape"}),
                    ("onestop_list_my_requests", {"status": "other"}),
                    ("onestop_search_knowledge", {"query": " "}),
                    ("onestop_get_my_request", {"request_id": "f" * 32}),
                    ("onestop_list_catalog_items", {"limit": 101}),
                ]:
                    result = await client.call_tool(name, args)
                    self.assertTrue(result.is_error, name)
                    self.assertIsNone(result.structured_content)
                malformed = fixture.read("sc_cat_item", {"sys_id": FORM}).data
                malformed["item"]["mandatory_attachment"] = "private-validation-secret"
                fixture.overrides["sc_cat_item"] = malformed
                result = await client.call_tool("onestop_get_catalog_item", {"item_id": FORM})
                self.assertTrue(result.is_error)
                self.assertNotIn("private-validation-secret", result.model_dump_json())

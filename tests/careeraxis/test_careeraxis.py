from datetime import datetime, timezone
from importlib.util import find_spec
import unittest
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server import MCPServer

from careeraxis import mcp_server, parser
from careeraxis.client import CareerAxisClient
from careeraxis.models import CareerAxisError
from careeraxis.session import CareerAxisSession, _PORTAL_SNAPSHOT, _SEARCH_SNAPSHOT
from shared.credentials import read_credentials, delete_credentials, save_credentials
from tests.credential_fixtures import stored_credentials
from tests.careeraxis.fixtures import BASE, SNAPSHOT, FixtureSession, records


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CareerAxisClient()
        self.client.session.close()
        self.client.session = FixtureSession()

    def test_local_pagination_preserves_records_and_exact_end(self):
        first = self.client.search_section("resources", page=1, limit=3)
        second = self.client.search_section("resources", page=2, limit=3)
        self.assertEqual([i.url for i in first.items] + [i.url for i in second.items], [i["url"] for i in records("resources")])
        self.assertTrue(first.has_next_page)
        self.assertFalse(second.has_next_page)
        with self.assertRaisesRegex(CareerAxisError, "no more"):
            self.client.search_section("resources", page=3, limit=3)

    def test_detail_urls_are_canonical_read_routes_and_external_links_are_filtered(self):
        with patch.object(self.client.session, "get_opportunity", wraps=self.client.session.get_opportunity) as native:
            detail = self.client.get_opportunity(BASE + "/students/jobs/1?action=apply#save")
            self.assertEqual(native.call_args.args[0], BASE + "/students/jobs/1")
            self.assertEqual(detail.application_links, ["https://employer.example/apply"])
        detail = self.client.get_portal_record(BASE + "/students/events/detail/1?action=register")
        self.assertEqual(detail.url, BASE + "/students/events/detail/1")
        for url in ["https://external.invalid/students/jobs/1", BASE + "/students/jobs/1/apply",
                    "https://user:secret@careeraxis.ntu.edu.sg/students/jobs/1", BASE + ":bad/students/jobs/1"]:
            with self.assertRaises((CareerAxisError, ValueError)):
                self.client.get_opportunity(url)

    def test_invalid_searches_and_malformed_empty_sources_fail_explicitly(self):
        for query in ("x\n", "x" * 201):
            with self.assertRaises(CareerAxisError):
                self.client.search_opportunities(query)
        with self.assertRaises(CareerAxisError):
            self.client.search_section("events", current_opportunities_only=True)
        with self.assertRaises(CareerAxisError):
            parser.search_results({"opportunities": [], "no_results": False}, SNAPSHOT, "", 1, 20)
        empty = parser.search_results({"opportunities": [], "no_results": True}, SNAPSHOT, "", 1, 20)
        self.assertFalse(empty.opportunities)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.session = CareerAxisSession()
        self.addCleanup(self.session.close)

    def test_status_detects_rotation_and_deletion_without_logging_in(self):
        s = self.session
        with stored_credentials():
            s._run(s._credentials)
            s._verified, s._last_verified = True, datetime.now(timezone.utc)
            s._cache["private"] = "old identity"
            save_credentials("other-student", "other-secret")
            with patch.object(s, "_open") as browser:
                status = s.status()
                browser.assert_not_called()
            self.assertTrue(status.credentials_configured)
            self.assertFalse(status.session_verified or s._cache)
            self.assertIsNone(status.last_verified_at)
            s._cache["private"] = "old identity"
            delete_credentials()
            self.assertFalse(s.status().credentials_configured)
            self.assertFalse(s._cache)

    def test_keyring_failure_blocks_cached_data_and_browser_errors_hide_secrets(self):
        s = self.session
        with stored_credentials() as backend:
            s._run(s._credentials)
            s._cache["private"] = "old data"
            with patch.object(backend, "get_password", side_effect=RuntimeError("private keyring data")):
                self.assertIsNone(s.status().credentials_configured)
                self.assertFalse(s._cache)
                with self.assertRaises(CareerAxisError) as error:
                    s.search("", 1, 20, False)
                self.assertNotIn("private", str(error.exception))
        with self.assertRaises(CareerAxisError) as error:
            s._run(Mock(side_effect=RuntimeError("password=private-secret")))
        self.assertNotIn("private-secret", str(error.exception))

    def test_unsupported_login_host_receives_no_credentials(self):
        s = self.session
        s._page = Mock(url="https://unexpected.invalid/adfs/ls/")
        s._page.goto.return_value.status = 200
        s._page.locator.return_value.inner_text.return_value = "Sign in"
        with patch.object(s, "_open"), patch.object(s, "_pace"):
            with self.assertRaisesRegex(CareerAxisError, "unsupported login host"):
                s._navigate("/students/jobs/search", Mock())
        s._page.locator.return_value.fill.assert_not_called()


@unittest.skipUnless(find_spec("playwright"), "Optional personal extra is not installed")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            cls.pw.stop()
            raise unittest.SkipTest("Optional Chromium is not installed")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route("**/*", lambda r: r.fulfill(body="<body></body>", content_type="text/html"))
        self.page = self.context.new_page()
        self.page.goto(BASE + "/students/jobs/search")
        self.session = CareerAxisSession()
        self.addCleanup(self.session.close)

    def tearDown(self):
        self.context.close()

    def listing(self, section=None, append=False):
        self.page.evaluate("""({section,append}) => {
          const paths={resources:'/students/docs/detail/',internship_jobs:'/workgroups/internship/Jobs/detail/'};
          window.nativePage=1;
          window.render=()=>{
            const start=append?0:(nativePage-1)*3,end=nativePage*3;
            let html='<main>';
            for(let i=start;i<end;i++)html+=`<article><h3><a href="${paths[section]||'/students/jobs/'}${i+1}">Role ${i}</a></h3><p>${i===7?'Wanted internship':'Fictional role'}</p></article>`;
            html+=`<button id="next" aria-label="Next page" ${nativePage===3?'disabled':''}>Next</button></main>`;
            document.body.innerHTML=html;
            document.getElementById('next').onclick=()=>{nativePage++;render();};
          };render();
        }""", {"section": section, "append": append})

    def test_job_pagination_handles_append_and_replace_views_without_skipping(self):
        for append in (False, True):
            self.listing(append=append)
            data = self.session._collect_pages(self.page, _SEARCH_SNAPSHOT, "opportunities", 4)
            result = parser.search_results(data, SNAPSHOT, "", 2, 2)
            self.assertEqual([r.url.rsplit("/",1)[-1] for r in result.opportunities], ["3", "4"])
            self.assertTrue(result.has_next_page)

    def test_section_pagination_respects_local_limit_and_internship_keyword(self):
        self.listing(section="resources")
        data = self.session._collect_pages(self.page, _PORTAL_SNAPSHOT, "items", 4, section="resources")
        result = parser.portal_results("resources", data, SNAPSHOT, "", 2, 2)
        self.assertEqual([r.url.rsplit("/",1)[-1] for r in result.items], ["3", "4"])
        self.listing(section="internship_jobs")
        data = self.session._collect_pages(self.page, _PORTAL_SNAPSHOT, "items", 1, section="internship_jobs", accept=lambda item: "Wanted" in item["summary"])
        self.assertEqual(len(data["items"]), 1)
        self.assertTrue(data["items"][0]["url"].endswith("/8"))

    def test_disabled_or_hidden_next_controls_do_not_claim_another_page(self):
        self.page.set_content('<a href="/students/jobs/1">Role</a><button aria-label="Next page" disabled>Next</button><button style="display:none">Next</button>')
        self.assertFalse(self.page.evaluate(_SEARCH_SNAPSHOT)["has_next_page"])
        self.page.set_content('<a href="/students/docs/detail/1">Guide</a><ul class="pagination"><li class="active">1</li><li class="disabled"><a href="#">Next</a></li></ul>')
        self.assertFalse(self.page.evaluate(_PORTAL_SNAPSHOT, "resources")["has_next_page"])

    def test_job_text_about_mfa_is_not_a_login_challenge(self):
        self.context.route("**/students/jobs/1", lambda r: r.fulfill(body='<a href="/students/logout">Logout</a><main>Security role using multi-factor authentication</main>', content_type="text/html"))
        self.session._page = self.page
        with stored_credentials():
            credentials = read_credentials()
        with patch.object(self.session, "_open"), patch.object(self.session, "_pace"):
            self.session._navigate("/students/jobs/1", credentials)
        self.assertTrue(self.session._verified)

    def test_missing_requested_employer_filter_fails_before_search(self):
        self.session._page = self.page
        with patch.object(self.session, "_credentials", return_value=Mock()), patch.object(self.session, "_navigate"), patch.object(self.session, "_click_search") as search:
            with self.assertRaisesRegex(CareerAxisError, "did not expose"):
                self.session._search_section("organisations", "", 1, 20, True, True)
            search.assert_not_called()


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_nine_read_tools_schemas_calls_and_sanitized_errors(self):
        server = MCPServer("careeraxis-offline")
        mcp_server.register_tools(server)
        client_impl = CareerAxisClient()
        client_impl.session.close()
        client_impl.session = FixtureSession()
        with patch.object(mcp_server, "client", client_impl):
            async with Client(server) as client:
                tools = {t.name:t for t in (await client.list_tools()).tools}
                self.assertEqual(len(tools), 9)
                for t in tools.values():
                    self.assertTrue(t.annotations.read_only_hint)
                    Draft202012Validator.check_schema(t.input_schema)
                    Draft202012Validator.check_schema(t.output_schema)
                calls = [(n,{}) for n in tools if n not in {"careeraxis_get_opportunity", "careeraxis_get_record"}]
                calls += [("careeraxis_get_opportunity", {"url":BASE+"/students/jobs/1"}), ("careeraxis_get_record", {"url":BASE+"/students/events/detail/1"})]
                for name,args in calls:
                    r = await client.call_tool(name,args)
                    self.assertFalse(r.is_error, name)
                    Draft202012Validator(tools[name].output_schema).validate(r.structured_content)
                self.assertTrue((await client.call_tool("careeraxis_search_events", {"page":0})).is_error)
                with patch.object(client_impl.session, "search", side_effect=RuntimeError("cookie=private-secret")):
                    r = await client.call_tool("careeraxis_search_opportunities", {})
                    self.assertTrue(r.is_error)
                    self.assertNotIn("private-secret", r.model_dump_json())

import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx2
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.http import create_app
from tests.faculty.fixtures import fake_get as faculty_get
from tests.library.fixtures import fake_get as library_get
from tests.mazemap.fixtures import fake_get as map_get
from tests.news.fixtures import ARTICLE_URL, fake_get as news_get
from tests.repository.fixtures import fake_get as repository_get
from tests.service.fixtures import fake_get as service_get
from tests.stars.mcp_fixtures import COURSE


HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
COUNTS = {"stars": 10, "mazemap": 5, "drntu": 7, "library": 5, "faculty": 2, "news": 3, "service": 2}


def payload(method="tools/list", params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params is not None else {})}


def http_client(app=None):
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app or create_app()), base_url="http://localhost")


class PublicHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_clients_discovery_calls_schemas_and_resources(self):
        with ExitStack() as stack:
            for target, data in [
                ("faculty.mcp_server.client.http.get", faculty_get), ("library.mcp_server.client.http.get", library_get),
                ("mazemap.mcp_server.client._get", map_get), ("news.mcp_server.client.http.get", news_get),
                ("drntu.mcp_server.client.get", repository_get), ("service.mcp_server.client.http.get", service_get),
            ]:
                stack.enter_context(patch(target, side_effect=data))
            stack.enter_context(patch("stars.mcp_server.fetch_course", return_value=COURSE))
            async with http_client() as http:
                for mode in ("auto", "legacy"):
                    transport = streamable_http_client("http://localhost/mcp", http_client=http)
                    async with Client(transport, mode=mode, cache=None) as client:
                        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                        self.assertEqual(len(tools), sum(COUNTS.values()))
                        for prefix, count in COUNTS.items():
                            self.assertEqual(len([name for name in tools if name.startswith(prefix + "_")]), count)
                        for tool in tools.values():
                            self.assertTrue(tool.annotations.read_only_hint)
                            Draft202012Validator.check_schema(tool.output_schema)
                        for name, arguments in [
                            ("stars_get_course_metadata", {"course_code": "ZZ0001", "academic_year": 2026, "semester": 1}),
                            ("mazemap_list_campuses", {}), ("drntu_search", {"query": "learning"}),
                            ("library_search", {"query": "algorithms"}), ("faculty_search", {"query": "Example"}),
                            ("news_get_article", {"url": ARTICLE_URL}), ("service_search", {"query": "clinic"}),
                        ]:
                            result = await client.call_tool(name, arguments)
                            self.assertFalse(result.is_error, result)
                            Draft202012Validator(tools[name].output_schema).validate(result.structured_content)
                        self.assertEqual((await client.list_resources()).resources, [])
                        self.assertEqual((await client.list_resource_templates()).resource_templates, [])

    async def test_personal_requests_are_rejected_before_any_handler_runs(self):
        async with http_client() as http:
            for name in ("stars_auth_status", "stars_get_stars_planner", "stars_save_stars_plan",
                         "stars_get_degree_audit", "ntulearn_list_courses", "library_get_facility_schedule"):
                response = await http.post("/mcp", headers=HEADERS,
                                           json=payload("tools/call", {"name": name, "arguments": {}}))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["result"]["isError"])
                self.assertNotIn("structuredContent", response.json()["result"])

    async def test_requests_need_no_session_or_lifespan_and_can_run_concurrently(self):
        async with http_client() as http:
            responses = await asyncio.gather(*(http.post("/mcp", headers=HEADERS, json=payload()) for _ in range(3)))
            for response in responses:
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("mcp-session-id", response.headers)
                self.assertEqual(len(response.json()["result"]["tools"]), 34)
            for method in ("GET", "DELETE"):
                response = await http.request(method, "/mcp")
                self.assertEqual(response.status_code, 405)
            self.assertEqual((await http.get("/health")).json()["mode"], "public")
            self.assertEqual((await http.get("/")).status_code, 200)

    async def test_host_and_origin_validation_uses_vercel_domains(self):
        with patch.dict(os.environ, {"VERCEL_URL": "preview.example.org", "MCP_ALLOWED_HOSTS": "mcp.example.org"}):
            app = create_app()
        async with http_client(app) as http:
            for host in ("preview.example.org", "mcp.example.org"):
                response = await http.post("/mcp", headers={**HEADERS, "Host": host, "Origin": "https://" + host}, json=payload())
                self.assertEqual(response.status_code, 200)
            response = await http.post("/mcp", headers={**HEADERS, "Host": "evil.example"}, json=payload())
            self.assertEqual(response.status_code, 421)
            response = await http.post("/mcp", headers={**HEADERS, "Origin": "https://evil.example"}, json=payload())
            self.assertEqual(response.status_code, 403)

    async def test_malformed_and_oversized_requests_fail(self):
        async with http_client() as http:
            malformed = await http.post("/mcp", headers={**HEADERS, "Content-Type": "application/json"}, content=b"not JSON")
            self.assertEqual(malformed.status_code, 400)
            oversized = await http.post("/mcp", headers={**HEADERS, "Content-Type": "application/json"}, content=b" " * 1_000_001)
            self.assertEqual(oversized.status_code, 413)


class ImportIsolationTests(unittest.TestCase):
    def test_deployment_imports_no_personal_modules(self):
        code = '''
import importlib.abc
import sys
class RejectPersonal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"keyring", "shared.credentials", "shared.server", "stars.personal_tools", "library.personal_tools", "library.session"} or fullname.startswith(("ntulearn", "stars.wish", "playwright")):
            raise AssertionError("Hosted entrypoint imported a personal module: " + fullname)
sys.meta_path.insert(0, RejectPersonal())
import app
assert app.app
print("Public entrypoint imports no credential or personal-service modules.")
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_app_can_serve_independent_event_loops(self):
        app = create_app()
        async def request():
            async with http_client(app) as client:
                response = await client.post("/mcp", headers=HEADERS, json=payload())
                self.assertEqual(response.status_code, 200)
        asyncio.run(request())
        asyncio.run(request())

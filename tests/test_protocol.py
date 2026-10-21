import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from mcp import Client, ClientSession
from mcp.types import CallToolResult
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
SERVER = Path(__file__).with_name("protocol_server.py")
ARGS = {"course_code": "SC2001", "academic_year": 2026, "semester": 1}


def environment():
    return {"PYTHONPATH": str(ROOT / "src"), "NTU_WISH_USERNAME": "", "NTU_WISH_PASSWORD": ""}


def validate_result(tools, name, result):
    schema = next(tool.output_schema for tool in tools if tool.name == name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.structured_content)


class SDKProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_level_client_stdio_schemas_calls_and_discovery(self):
        with tempfile.TemporaryDirectory() as cwd:
            async with Client(StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=cwd, env=environment())) as client:
                listing = await client.list_tools()
                self.assertEqual(len(listing.tools), 12)
                for tool in listing.tools:
                    self.assertIsNotNone(tool.output_schema, tool.name)
                    self.assertEqual(tool.output_schema["type"], "object", tool.name)
                    self.assertTrue(tool.output_schema.get("properties"), tool.name)
                    Draft202012Validator.check_schema(tool.output_schema)
                calls = [
                    ("get_course_metadata", ARGS), ("get_course_indexes", ARGS),
                    ("get_index", {**ARGS, "index": "10143"}),
                    ("compare_indexes", {**ARGS, "indexes": ["10143", "10144"], "against_sessions": [
                        {"day": "TUE", "start_time": "16:30", "end_time": "17:20", "teaching_weeks": [2]}
                    ]}),
                    ("find_matching_indexes", {**ARGS, "constraints": {"avoid_days": ["FRI"]}}),
                    ("get_graduate_course_schedule", {"course_code": "EE6102"}),
                    ("get_undergraduate_exam_schedule", {"course_code": "SC2001"}), ("ntu_auth_status", {}),
                ]
                for name, arguments in calls:
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, name)
                    validate_result(listing.tools, name, result)
                    self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                    self.assertNotIn("result", result.structured_content)
                self.assertEqual((await client.list_resources()).resources, [])
                self.assertEqual((await client.list_resource_templates()).resource_templates, [])

    async def test_low_level_python_session_and_tool_errors(self):
        with tempfile.TemporaryDirectory() as cwd:
            async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=cwd, env=environment())) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    initialized = await client.initialize()
                    self.assertEqual(initialized.server_info.name, "ntu-stars-mcp")
                    tools = (await client.list_tools()).tools
                    result = await client.call_tool("get_index", {**ARGS, "index": "10143"})
                    self.assertFalse(result.is_error)
                    validate_result(tools, "get_index", result)
                    invalid = CallToolResult(content=[], structured_content={**result.structured_content, "sessions": "not-a-list"})
                    with self.assertRaisesRegex(RuntimeError, "Invalid structured content"):
                        await client.validate_tool_result("get_index", invalid)
                    for name, args in (
                        ("get_course_indexes", {**ARGS, "semester": 3}),
                        ("get_index", {**ARGS, "index": "missing"}),
                        ("get_course_metadata", {**ARGS, "course_code": "ZZ9999"}),
                        ("compare_indexes", {**ARGS, "indexes": ["10143"]}),
                        ("unknown_tool", {}),
                    ):
                        error = await client.call_tool(name, args)
                        self.assertTrue(error.is_error, name)
                        self.assertTrue(error.content[0].text)
                        self.assertIsNone(error.structured_content)


@asynccontextmanager
async def raw_client(version):
    """Independent newline-delimited JSON-RPC client, without SDK serializers."""
    with tempfile.TemporaryDirectory() as cwd:
        env = {**os.environ, **environment()}
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(SERVER), cwd=cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=2_000_000,
        )
        stderr = asyncio.create_task(process.stderr.read())
        request_id = 0

        async def request(method, params=None):
            nonlocal request_id
            request_id += 1
            message = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                message["params"] = params
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=15)
                if not line:
                    raise AssertionError("MCP server closed stdout unexpectedly")
                response = json.loads(line)
                if response.get("id") == request_id:
                    return response

        try:
            initialized = await request("initialize", {
                "protocolVersion": version, "capabilities": {},
                "clientInfo": {"name": "raw-json-rpc-test", "version": "1.0"},
            })
            assert initialized["result"]["protocolVersion"] == version
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            await process.stdin.drain()
            yield request
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            await stderr


class RawProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_protocol_versions_and_wire_field_names(self):
        for version in ("2025-06-18", "2025-11-25"):
            async with raw_client(version) as request:
                listing = await request("tools/list", {})
                tools = listing["result"]["tools"]
                self.assertEqual(len(tools), 12)
                self.assertEqual(tools, (await request("tools/list", {}))["result"]["tools"])
                tool = next(tool for tool in tools if tool["name"] == "get_course_indexes")
                self.assertIn("inputSchema", tool)
                self.assertIn("outputSchema", tool)
                self.assertNotIn("output_schema", tool)
                result = await request("tools/call", {"name": "get_course_indexes", "arguments": ARGS})
                self.assertNotIn("error", result)
                payload = result["result"]
                self.assertFalse(payload.get("isError", False))
                self.assertEqual(payload["structuredContent"]["index_count"], 36)
                self.assertEqual(json.loads(payload["content"][0]["text"]), payload["structuredContent"])
                Draft202012Validator(tool["outputSchema"]).validate(payload["structuredContent"])
                self.assertEqual((await request("resources/list", {}))["result"]["resources"], [])
                self.assertEqual((await request("resources/templates/list", {}))["result"]["resourceTemplates"], [])

    async def test_protocol_errors_are_distinct_from_tool_failures(self):
        async with raw_client("2025-11-25") as request:
            error = await request("tools/call", {"name": "get_course_indexes", "arguments": {**ARGS, "semester": 3}})
            self.assertNotIn("error", error)
            self.assertTrue(error["result"]["isError"])
            self.assertNotIn("structuredContent", error["result"])
            malformed = await request("tools/call", {"arguments": {}})
            self.assertEqual(malformed["error"]["code"], -32602)
            missing = await request("unsupported/method", {})
            self.assertEqual(missing["error"]["code"], -32601)
            resource = await request("resources/read", {"uri": "ntu://missing"})
            self.assertEqual(resource["error"]["code"], -32602)

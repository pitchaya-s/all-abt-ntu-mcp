import unittest
from unittest.mock import Mock

from mcp import Client
from mcp.server import MCPServer
from mcp.types import ElicitResult
from mcp.shared.exceptions import MCPError

from shared.confirmation import confirmed_tool


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_must_confirm_before_side_effect(self):
        server = MCPServer("confirmation-test")
        action = Mock()

        def write(value: str) -> dict[str, str]:
            action(value)
            return {"value": value}

        server.tool(name="write")(confirmed_tool(write, "write"))
        async with Client(server) as client:
            tool = (await client.list_tools()).tools[0]
            self.assertNotIn("confirmation_result", tool.input_schema["properties"])
            with self.assertRaises(MCPError):
                await client.call_tool("write", {"value": "example"})
            with self.assertRaises(MCPError):
                await client.call_tool("write", {"value": "example", "confirmation_result": {"confirm": True}})
            action.assert_not_called()

        async def decline(context, params):
            return ElicitResult(action="decline")

        async with Client(server, elicitation_callback=decline) as client:
            result = await client.call_tool("write", {"value": "example"})
            self.assertTrue(result.is_error)
            action.assert_not_called()

        async def approve(context, params):
            self.assertIn('"value": "example"', params.message)
            return ElicitResult(action="accept", content={"confirm": True})

        async with Client(server, elicitation_callback=approve) as client:
            result = await client.call_tool("write", {"value": "example"})
            self.assertFalse(result.is_error)
            action.assert_called_once_with("example")

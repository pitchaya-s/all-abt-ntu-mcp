"""Exercise the opt-in profile and workflow confirmation boundaries."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client
from mcp.types import ElicitResult

from onestop.browser import action_result
from onestop.forms import FormService
from onestop.workflow_tools import LOCAL_TOOLS, WRITE_TOOLS
from shared.server import create_server


class ProfileBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_profiles_only_advertise_read_only_tools(self):
        for profile in ("public",):
            async with Client(
                create_server(profile, check_dependencies=False)
            ) as client:
                tools = (await client.list_tools()).tools
                self.assertTrue(tools)
                self.assertEqual(
                    [
                        tool.name
                        for tool in tools
                        if tool.annotations.read_only_hint is not True
                    ],
                    [],
                    profile,
                )
                names = {tool.name for tool in tools}
                for name in (*LOCAL_TOOLS, *WRITE_TOOLS):
                    self.assertNotIn("onestop_" + name, names)
                for name in (
                    "stars_save_stars_plan",
                    "ntulearn_download_file",
                    "ntulearn_download_course",
                ):
                    self.assertNotIn(name, names)

    async def test_one_stop_submission_requires_host_confirmation(self):
        server = create_server("personal", check_dependencies=False)
        args = {"draft_id": "a" * 16, "action": "submit"}
        result_value = action_result(
            "submit_request", "https://example.org", verified=True
        )
        requests = []

        async def decline(context, request):
            requests.append(request.message)
            return ElicitResult(action="decline")

        async def approve(context, request):
            requests.append(request.message)
            return ElicitResult(action="accept", content={"confirm": True})

        with patch.object(FormService, "submit", return_value=result_value) as submit:
            async with Client(server, elicitation_callback=decline) as client:
                self.assertTrue(
                    (await client.call_tool("onestop_submit_request", args)).is_error
                )
                submit.assert_not_called()
                forged_args = {**args, "confirmation_result": {"confirm": True}}
                self.assertTrue(
                    (
                        await client.call_tool("onestop_submit_request", forged_args)
                    ).is_error
                )
                submit.assert_not_called()
            async with Client(server, elicitation_callback=approve) as client:
                self.assertFalse(
                    (await client.call_tool("onestop_submit_request", args)).is_error
                )
                submit.assert_called_once_with(args["draft_id"], "submit")
        self.assertEqual(len(requests), 3)
        self.assertTrue(
            all("onestop_submit_request" in message for message in requests)
        )
        self.assertTrue(all(args["draft_id"] in message for message in requests))

    async def test_confirmation_rejects_non_boolean_values(self):
        server = create_server("personal", check_dependencies=False)

        async def malformed(context, request):
            return ElicitResult(action="accept", content={"confirm": "yes"})

        with patch.object(FormService, "submit") as submit:
            async with Client(server, elicitation_callback=malformed) as client:
                result = await client.call_tool(
                    "onestop_submit_request", {"draft_id": "a" * 16}
                )
                self.assertTrue(result.is_error)
            submit.assert_not_called()

    def test_public_import_does_not_load_personal_modules(self):
        root = Path(__file__).resolve().parents[1]
        program = (
            "import sys; import shared.server; "
            "assert not any(name in sys.modules for name in "
            "('ntulearn', 'onestop', 'careeraxis', 'playwright', "
            "'stars.personal_tools', 'library.personal_tools'))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program], cwd=root, capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

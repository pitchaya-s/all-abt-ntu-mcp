import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from cli.cli import main
from cli.config import config_path, load_config, save_config


class ToolConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": self.directory.name, "APPDATA": self.directory.name},
        )
        environment.start()
        self.addCleanup(environment.stop)

    def seed(self, profile, disabled, *, enabled=()):
        config = load_config()
        config["profile"] = profile
        config["tools"]["disabled"] = sorted(disabled)
        config["tools"]["enabled"] = sorted(enabled)
        save_config(config)

    def call(self, *args):
        out, err = StringIO(), StringIO()
        out.isatty = lambda: True
        err.isatty = lambda: True
        with (
            patch("sys.argv", ["all-abt-ntu", *args]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            main()
        return out.getvalue()

    def test_enable_disable_and_list_persist(self):
        self.call("tools", "disable", "mazemap_list_campuses", "news_search")
        self.assertEqual(
            set(load_config()["tools"]["disabled"]),
            {"mazemap_list_campuses", "news_search"},
        )
        self.assertIn("[ ] mazemap_list_campuses", self.call("tools", "list", "--all"))
        self.call("tools", "enable", "mazemap_list_campuses")
        self.assertEqual(load_config()["tools"]["disabled"], ["news_search"])
        self.assertIn("[x] mazemap_list_campuses", self.call("tools", "list", "--all"))

    def test_invalid_name_does_not_modify_config(self):
        self.seed("public", {"news_search"})
        before = config_path().read_text()
        with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
            self.call("tools", "disable", "not_a_real_tool")
        self.assertEqual(config_path().read_text(), before)

    def test_saved_profile_and_explicit_override_are_used(self):
        self.seed("personal", {"news_search"})
        with patch("shared.server.main") as run:
            with patch("cli.tools.commands.action_names", return_value=set()):
                self.call()
                run.assert_called_once_with("personal", disabled_tools=["news_search"])
        with patch("shared.server.main") as run:
            self.call("--profile", "public")
            run.assert_called_once_with("public", disabled_tools=["news_search"])

    def test_corrupt_config_fails_closed(self):
        path = config_path()
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        with patch("shared.server.main") as run, self.assertRaises(SystemExit):
            self.call()
        run.assert_not_called()

    def test_setup_saves_and_cancel_preserves_previous_config(self):
        from unittest.mock import Mock

        self.seed("public", {"news_search"})
        radio = Mock()
        radio.return_value.unsafe_ask.return_value = "public"
        checkbox = Mock()
        checkbox.return_value.unsafe_ask.return_value = ["news"]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch(
                "cli.tools.commands.tool_names",
                return_value=["news_search", "mazemap_list_campuses"],
            ),
        ):
            self.call("setup")
            self.assertEqual(
                {choice.value for choice in checkbox.call_args.kwargs["choices"]},
                {"news", "mazemap"},
            )
            profile_style = radio.call_args.kwargs["style"]
            for name in (
                "qmark",
                "answer",
                "pointer",
                "selected",
                "highlighted",
                "text",
            ):
                self.assertEqual(
                    profile_style.get_attrs_for_style_str(f"class:{name}").color,
                    "default",
                )
            family_style = checkbox.call_args.kwargs["style"]
            for name in ("text", "highlighted"):
                self.assertEqual(
                    family_style.get_attrs_for_style_str(f"class:{name}").color,
                    "a0a0a0",
                )
            selected = family_style.get_attrs_for_style_str("class:selected")
            self.assertEqual(selected.color, "ansigreen")
            self.assertTrue(selected.bold)
            self.assertFalse(selected.reverse)
            self.assertEqual(
                load_config()["tools"]["families"]["disabled"], ["mazemap"]
            )
            self.assertEqual(load_config()["tools"]["disabled"], ["news_search"])
            checkbox.return_value.unsafe_ask.return_value = None
            with self.assertRaises(SystemExit):
                self.call("setup")
            self.assertEqual(
                load_config()["tools"]["families"]["disabled"], ["mazemap"]
            )

    def test_disabled_tool_cannot_be_listed_or_called(self):
        from shared import server

        instance = server.create_server("public")

        async def serve():
            async with Client(instance) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertNotIn("mazemap_list_campuses", names)
                self.assertIn("news_search", names)
                result = await client.call_tool("mazemap_list_campuses", {})
                self.assertTrue(result.is_error)

        with (
            patch.object(server, "create_server", return_value=instance),
            patch.object(instance, "run_stdio_async", side_effect=serve),
        ):
            server.main(
                "public", disabled_tools=["mazemap_list_campuses", "obsolete_tool"]
            )

    def test_unchecked_family_clears_its_explicit_tool_exceptions(self):
        from unittest.mock import Mock

        config = load_config()
        config["tools"]["enabled"] = ["news_search"]
        config["tools"]["families"]["disabled"] = ["news"]
        save_config(config)
        radio, checkbox = Mock(), Mock()
        radio.return_value.unsafe_ask.return_value = "public"
        checkbox.return_value.unsafe_ask.return_value = ["mazemap"]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch(
                "cli.tools.commands.tool_names",
                return_value=["news_search", "mazemap_get_place"],
            ),
        ):
            self.call("setup")
        self.assertEqual(load_config()["tools"]["enabled"], [])
        self.assertIn("news", load_config()["tools"]["families"]["disabled"])

    def test_setup_reenables_family_disabled_by_cli(self):
        from unittest.mock import Mock

        self.call("tools", "disable", "news")
        radio, checkbox = Mock(), Mock()
        radio.return_value.unsafe_ask.return_value = "public"
        checkbox.return_value.unsafe_ask.return_value = ["news"]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
        ):
            self.call("setup")
        output = self.call("tools", "list", "--all")
        self.assertIn("[x] news_search", output)
        self.assertNotIn("news", load_config()["tools"]["families"]["disabled"])

    def test_personal_selection_offers_keyring_authentication(self):
        from unittest.mock import Mock

        radio = Mock()
        radio.return_value.unsafe_ask.return_value = "personal"
        checkbox = Mock()
        checkbox.return_value.unsafe_ask.return_value = [
            "news",
            "ntulearn",
        ]
        auth_dialog = Mock()
        auth_dialog.return_value.unsafe_ask.return_value = True
        names = lambda profile: (
            ["news_search"]
            if profile == "public"
            else ["news_search", "ntulearn_list_courses"]
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch("questionary.confirm", auth_dialog),
            patch("cli.tools.commands.tool_names", side_effect=names),
            patch("cli.tools.commands.ensure_chromium"),
            patch(
                "shared.credentials.credential_status",
                return_value={
                    "credential_error": None,
                    "credentials_configured": False,
                },
            ),
            patch("builtins.input", return_value="student001"),
            patch("cli.cli.getpass", return_value="test-password"),
            patch("cli.cli.save_credentials") as save,
        ):
            output = self.call("setup")
            auth_dialog.assert_called_once()
            save.assert_called_once_with("student001", "test-password")
            self.assertNotIn("test-password", output)
            self.assertEqual(load_config()["profile"], "personal")
            save.reset_mock()
            auth_dialog.return_value.unsafe_ask.return_value = False
            self.call("setup")
            save.assert_not_called()
            self.assertEqual(load_config()["profile"], "personal")

    def test_setup_does_not_prompt_when_credentials_exist_or_status_is_unknown(self):
        from unittest.mock import Mock

        radio, checkbox = Mock(), Mock()
        radio.return_value.unsafe_ask.return_value = "personal"
        checkbox.return_value.unsafe_ask.return_value = ["ntulearn"]
        names = lambda profile: [] if profile == "public" else ["ntulearn_list_courses"]
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch("questionary.confirm") as auth_dialog,
            patch("cli.tools.commands.tool_names", side_effect=names),
            patch("cli.tools.commands.ensure_chromium"),
            patch("shared.credentials.credential_status") as status,
        ):
            status.return_value = {
                "credential_error": None,
                "credentials_configured": True,
            }
            self.assertIn("credentials are already saved", self.call("setup"))
            auth_dialog.assert_not_called()
            status.return_value = {
                "credential_error": "Keyring unavailable",
                "credentials_configured": None,
            }
            self.call("setup")
            auth_dialog.assert_not_called()

    def test_personal_profile_with_only_public_tools_does_not_offer_auth(self):
        from unittest.mock import Mock

        radio = Mock()
        radio.return_value.unsafe_ask.return_value = "personal"
        checkbox = Mock()
        checkbox.return_value.unsafe_ask.return_value = ["news"]
        names = lambda profile: (
            ["news_search"]
            if profile == "public"
            else ["news_search", "ntulearn_list_courses"]
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch("questionary.confirm") as auth_dialog,
            patch("cli.tools.commands.tool_names", side_effect=names),
            patch("cli.tools.commands.ensure_chromium"),
        ):
            self.call("setup")
            auth_dialog.assert_not_called()

    def test_setup_creates_default_upload_directory_when_selected(self):
        from unittest.mock import Mock

        radio, checkbox, auth = Mock(), Mock(), Mock()
        radio.return_value.unsafe_ask.return_value = "personal"
        checkbox.return_value.unsafe_ask.return_value = ["onestop"]
        auth.return_value.unsafe_ask.return_value = False
        self.seed("public", set(), enabled={"onestop_upload_attachment"})
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select", radio),
            patch("questionary.checkbox", checkbox),
            patch("questionary.confirm", auth),
            patch(
                "cli.tools.commands.tool_names",
                side_effect=lambda profile: (
                    [] if profile == "public" else ["onestop_upload_attachment"]
                ),
            ),
            patch("cli.tools.commands.ensure_chromium"),
        ):
            os.environ.pop("NTU_ONESTOP_UPLOAD_DIR", None)
            output = self.call("setup")
            directory = config_path().parent / "onestop-uploads"
            self.assertTrue(directory.is_dir())
            self.assertIn(str(directory), output)

    def test_personal_actions_default_off_and_can_be_enabled(self):
        output = self.call("--profile", "personal", "tools", "list", "--all")
        self.assertIn("[x] ntulearn_list_courses", output)
        self.assertIn("[ ] onestop_upload_attachment", output)
        self.call(
            "--profile", "personal", "tools", "enable", "onestop_upload_attachment"
        )
        config = load_config()
        self.assertEqual(config["profile"], "public")
        self.assertIn("onestop_upload_attachment", config["tools"]["enabled"])
        self.assertNotIn("onestop_upload_attachment", config["tools"]["disabled"])
        self.assertNotIn("stars_save_stars_plan", config["tools"]["enabled"])
        output = self.call("--profile", "personal", "tools", "list", "--all")
        self.assertIn("[x] onestop_upload_attachment", output)
        self.assertIn("[ ] stars_save_stars_plan", output)

    def test_family_commands_and_future_family_tools(self):
        self.call("tools", "disable", "news")
        self.assertIn("[ ] news ", self.call("tools", "list"))
        self.assertIn("[ ] news_search", self.call("tools", "list", "--all"))
        with patch("shared.server.main") as run:
            self.call()
            self.assertIn("news_search", run.call_args.kwargs["disabled_tools"])
        from cli.tools.commands import effective_disabled

        with patch(
            "cli.tools.commands.tool_names", return_value=["news_search", "news_new"]
        ):
            self.assertTrue(
                {"news_search", "news_new"}.issubset(
                    effective_disabled(load_config(), "public")
                )
            )
        self.call("tools", "enable", "news_search")
        self.assertIn("[x] news_search", self.call("tools", "list", "--all"))
        self.call("tools", "enable", "news")
        self.assertIn("[x] news_search", self.call("tools", "list", "--all"))

    def test_explicitly_enabling_personal_family_includes_its_actions(self):
        with patch("cli.tools.commands.prepare_upload_directory") as prepare:
            self.call("--profile", "personal", "tools", "enable", "onestop")
            prepare.assert_called_once()
        self.assertIn("onestop_upload_attachment", load_config()["tools"]["enabled"])
        self.assertIn(
            "[x] onestop_upload_attachment",
            self.call("--profile", "personal", "tools", "list", "--all"),
        )

    def test_new_action_stays_disabled_until_explicitly_enabled(self):
        from cli.tools.commands import effective_disabled

        config = {
            "tools": {
                "enabled": ["existing_action"],
                "disabled": [],
                "families": {"enabled": [], "disabled": []},
            }
        }
        with patch(
            "cli.tools.commands.action_names",
            return_value={"existing_action", "new_action"},
        ):
            self.assertEqual(effective_disabled(config, "personal"), {"new_action"})

    def test_service_settings_are_typed_and_survive_tool_changes(self):
        self.call("config", "set", "ntulearn.headless", "false")
        self.call("config", "set", "stars.cache_ttl_seconds", "120")
        self.call("config", "set", "onestop.upload_dir", self.directory.name)
        self.call("config", "set", "other.EXAMPLE_SETTING", "value")
        self.call("tools", "disable", "news")
        env = load_config()["env"]
        self.assertIs(env["ntulearn"]["headless"], False)
        self.assertEqual(env["stars"]["cache_ttl_seconds"], 120)
        self.assertEqual(env["onestop"]["upload_dir"], self.directory.name)
        self.assertEqual(env["other"]["EXAMPLE_SETTING"], "value")
        with self.assertRaises(SystemExit):
            self.call("config", "set", "ntulearn.headless", "no")
        with self.assertRaises(SystemExit):
            self.call("config", "set", "onestop.upload_dir", "relative")
        with self.assertRaises(SystemExit):
            self.call("config", "set", "public_http.concurrency", "999")
        with self.assertRaises(SystemExit):
            self.call("config", "set", "other.XDG_CONFIG_HOME", "elsewhere")
        self.call("config", "unset", "ntulearn.headless")
        self.assertNotIn("ntulearn", load_config()["env"])

    def test_minimal_handwritten_settings_keep_public_defaults(self):
        path = config_path()
        path.parent.mkdir(parents=True)
        path.write_text('{"env":{"stars":{"cache_ttl_seconds":120}}}', encoding="utf-8")
        config = load_config()
        self.assertEqual(config["profile"], "public")
        self.assertEqual(config["tools"]["enabled"], [])
        self.assertEqual(config["tools"]["families"]["disabled"], [])
        self.assertEqual(config["env"]["stars"]["cache_ttl_seconds"], 120)

    def test_settings_apply_before_import_and_process_environment_wins(self):
        import subprocess
        import sys

        config = load_config()
        config["env"] = {"stars": {"cache_ttl_seconds": 123}}
        save_config(config)
        command = [
            sys.executable,
            "-c",
            "from cli.cli import main; main(); from stars.client.cache import CACHE_TTL_SECONDS; print('TTL:', CACHE_TTL_SECONDS)",
            "tools",
            "list",
        ]
        env = {**os.environ}
        env.pop("NTU_CACHE_TTL_SECONDS", None)
        result = subprocess.run(
            command, env=env, text=True, capture_output=True, check=True
        )
        self.assertIn("TTL: 123", result.stdout)
        result = subprocess.run(
            command,
            env={**env, "NTU_CACHE_TTL_SECONDS": "42"},
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("TTL: 42", result.stdout)

    def test_duplicate_environment_setting_is_rejected_without_saving(self):
        self.call("config", "set", "ntulearn.headless", "false")
        before = config_path().read_text()
        with self.assertRaises(SystemExit):
            self.call("config", "set", "other.NTULEARN_HEADLESS", "true")
        self.assertEqual(config_path().read_text(), before)

    def test_chromium_install_asks_and_respects_answer(self):
        from cli.tools.commands import ensure_chromium
        from unittest.mock import Mock
        import sys

        with (
            patch("shared.server._chromium_installed", side_effect=[False, True]),
            patch("builtins.input", side_effect=["invalid", ""]),
            patch(
                "cli.tools.commands.subprocess.run", return_value=Mock(returncode=0)
            ) as install,
            redirect_stdout(StringIO()),
        ):
            ensure_chromium()
            install.assert_called_once_with(
                [sys.executable, "-m", "playwright", "install", "chromium"], check=False
            )
        with (
            patch("shared.server._chromium_installed", return_value=False),
            patch("builtins.input", return_value="n"),
            patch("cli.tools.commands.subprocess.run") as install,
            redirect_stdout(StringIO()),
        ):
            ensure_chromium()
            install.assert_not_called()
        with (
            patch("shared.server._chromium_installed", return_value=True),
            patch("builtins.input") as prompt,
            patch("cli.tools.commands.subprocess.run") as install,
        ):
            ensure_chromium()
            prompt.assert_not_called()
            install.assert_not_called()
        with (
            patch("shared.server._chromium_installed", return_value=False),
            patch("builtins.input", return_value="y"),
            patch("cli.tools.commands.subprocess.run", return_value=Mock(returncode=1)),
            redirect_stdout(StringIO()),
        ):
            from cli.config import ConfigError

            with self.assertRaisesRegex(ConfigError, "choices were saved"):
                ensure_chromium()


class FamilyProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_family_is_not_exposed_over_stdio(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "XDG_CONFIG_HOME": directory, "APPDATA": directory}
            command = [sys.executable, "-c", "from cli.cli import main; main()"]
            subprocess.run(
                [*command, "tools", "disable", "news"],
                env=env,
                check=True,
                capture_output=True,
            )
            async with Client(
                StdioServerParameters(command=command[0], args=command[1:], env=env)
            ) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertTrue(names)
                self.assertFalse(any(name.startswith("news_") for name in names))
                self.assertIn("mazemap_list_campuses", names)
                result = await client.call_tool("news_search", {"query": "example"})
                self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()

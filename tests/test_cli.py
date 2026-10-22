from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch
import warnings
from getpass import GetPassWarning

from shared.cli import main
from shared.credentials import credential_status, read_credentials
from tests.credential_fixtures import stored_credentials


class CredentialCLITests(unittest.TestCase):
    def call(self, *arguments):
        output, errors = StringIO(), StringIO()
        errors.isatty = lambda: True
        with patch("sys.argv", ["all-abt-ntu-mcp", *arguments]), redirect_stdout(output), redirect_stderr(errors):
            main()
        return output.getvalue() + errors.getvalue()

    def test_hidden_terminal_save_update_status_and_management(self):
        with stored_credentials(), patch("sys.stdin.isatty", return_value=True), patch("sys.stderr.isatty", return_value=True), patch("shared.cli.getpass", side_effect=["student001", "hidden-test-secret"]):
            output = self.call("auth", "save")
            self.assertEqual(read_credentials().password, "hidden-test-secret")
            for arguments in [("status",), ("delete",)]:
                output += self.call("auth", *arguments)
            self.assertFalse(credential_status()["credentials_configured"])
            self.assertNotIn("hidden-test-secret", output)
            self.assertNotIn("student001", output)

    def test_piped_setup_and_echo_fallback_are_refused_without_prompting(self):
        with patch("sys.stdin.isatty", return_value=False), patch("shared.cli.getpass") as prompt:
            with self.assertRaises(SystemExit):
                self.call("auth", "save")
            prompt.assert_not_called()

    def test_echo_fallback_is_rejected_and_never_saves(self):
        def insecure_prompt(*args):
            warnings.warn("Secret input would echo", GetPassWarning)
        with patch("sys.stdin.isatty", return_value=True), patch("shared.cli.getpass", side_effect=insecure_prompt), patch("shared.cli.save_credentials") as save:
            with self.assertRaises(SystemExit):
                self.call("auth", "save")
            save.assert_not_called()

    def test_invalid_arguments_are_not_echoed_to_logs(self):
        output, errors = StringIO(), StringIO()
        with patch("sys.argv", ["all-abt-ntu-mcp", "auth", "save", "--password", "secret-in-invalid-argument"]), redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaises(SystemExit):
                main()
        self.assertNotIn("secret-in-invalid-argument", output.getvalue() + errors.getvalue())

    def test_no_command_runs_stdio_server_without_credential_prompts(self):
        with patch("shared.server.main") as server, patch("shared.cli.getpass") as prompt:
            self.assertEqual(self.call(), "")
            server.assert_called_once()
            prompt.assert_not_called()

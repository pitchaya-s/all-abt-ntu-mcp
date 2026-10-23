from contextlib import redirect_stderr, redirect_stdout
from getpass import GetPassWarning
from io import StringIO
import unittest
from unittest.mock import patch
import warnings

from shared.cli import main
from shared.credentials import credential_status, read_credentials
from tests.credential_fixtures import stored_credentials


class CredentialCLITests(unittest.TestCase):
    def call(self, *arguments):
        output, errors = StringIO(), StringIO()
        errors.isatty = lambda: True
        with patch("sys.argv", ["all-abt-ntu", *arguments]), redirect_stdout(output), redirect_stderr(errors):
            main()
        return output.getvalue() + errors.getvalue()

    def test_hidden_password_save_status_and_management(self):
        with stored_credentials(), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="student001") as prompt, patch("shared.cli.getpass", return_value="hidden-test-secret") as password:
            output = self.call("auth", "save")
            self.assertEqual(read_credentials().password, "hidden-test-secret")
            prompt.assert_called_once_with("NTU network username or email: ")
            password.assert_called_once_with("NTU password: ")
            for arguments in [("status",), ("delete",)]:
                output += self.call("auth", *arguments)
            self.assertFalse(credential_status()["credentials_configured"])
            self.assertNotIn("hidden-test-secret", output)
            self.assertNotIn("student001", output)

    def test_piped_setup_is_refused_without_prompting(self):
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as prompt, patch("shared.cli.getpass") as password:
            with self.assertRaises(SystemExit):
                self.call("auth", "save")
            prompt.assert_not_called()
            password.assert_not_called()

    def test_cancelled_input_never_saves_partial_credentials(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="student001"), patch("shared.cli.getpass", side_effect=EOFError), patch("shared.cli.save_credentials") as save:
            with self.assertRaises(SystemExit):
                self.call("auth", "save")
            save.assert_not_called()

    def test_password_echo_fallback_is_refused_without_saving(self):
        def echo_fallback(prompt):
            warnings.warn("Password input may be echoed.", GetPassWarning)
            return "must-not-be-saved"

        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="student001"), patch("shared.cli.getpass", side_effect=echo_fallback), patch("shared.cli.save_credentials") as save:
            with self.assertRaises(SystemExit):
                self.call("auth", "save")
            save.assert_not_called()

    def test_invalid_arguments_are_not_echoed_to_logs(self):
        output, errors = StringIO(), StringIO()
        with patch("sys.argv", ["all-abt-ntu", "auth", "save", "--password", "secret-in-invalid-argument"]), redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaises(SystemExit):
                main()
        self.assertNotIn("secret-in-invalid-argument", output.getvalue() + errors.getvalue())

    def test_no_command_runs_stdio_server_without_credential_prompts(self):
        with patch("shared.server.main") as server, patch("builtins.input") as prompt, patch("shared.cli.getpass") as password:
            self.assertEqual(self.call(), "")
            server.assert_called_once()
            prompt.assert_not_called()
            password.assert_not_called()

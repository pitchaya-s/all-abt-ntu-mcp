"""Local credential commands; no secret inputs are exposed through MCP."""

import argparse
from getpass import GetPassWarning, getpass
import sys
import warnings

from .credentials import CredentialError, credential_status, delete_credentials, save_credentials


class LocalParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command. Use --help; enter credentials only at the local hidden prompts.\n")


def main() -> None:
    parser = LocalParser(description="NTU MCP server and opt-in local keyring credentials.")
    commands = parser.add_subparsers(dest="command")
    auth = commands.add_parser("auth", help="Manage shared credentials in your native OS keyring")
    auth.add_argument("action", choices=("save", "status", "delete"))
    args = parser.parse_args()
    if args.command is None:
        from .server import main as run_server
        run_server()
        return
    try:
        if args.action == "save":
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise CredentialError("Credential setup requires your own interactive terminal; piped input is refused.")
            print("Save/update your NTU account in the native OS keyring and enable automatic login for STARS and NTULearn.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                username = getpass("NTU network username or email (hidden): ")
                password = getpass("NTU password (hidden): ")
            save_credentials(username, password)
            print("Credentials saved in the OS keyring. Automatic login enabled.")
        elif args.action == "status":
            status = credential_status()
            if status["credential_error"]:
                raise CredentialError(status["credential_error"])
            print("Credentials stored: " + ("yes" if status["credentials_configured"] else "no"))
        elif args.action == "delete":
            delete_credentials()
            print("Stored credentials deleted. Automatic login disabled.")
    except (CredentialError, GetPassWarning) as error:
        message = str(error) if isinstance(error, CredentialError) else "Secure hidden input is unavailable; credentials were not saved."
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
    except (EOFError, KeyboardInterrupt):
        print("Credential setup cancelled; no credentials were saved.", file=sys.stderr)
        raise SystemExit(1) from None

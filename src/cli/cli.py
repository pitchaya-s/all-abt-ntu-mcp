"""Local credential commands; no secret inputs are exposed through MCP."""

import argparse
from getpass import GetPassWarning, getpass
import json
import sys
import warnings

from shared.credentials import (
    CredentialError,
    credential_status,
    delete_credentials,
    save_credentials,
)
from .config import (
    SETTINGS,
    ConfigError,
    apply_config_env,
    load_config,
    save_config,
    setting_entry,
)


class LocalParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(
            2,
            "Invalid command. Use --help; enter credentials only at the local prompts.\n",
        )


def main() -> None:
    parser = LocalParser(
        description="NTU MCP server and opt-in local keyring credentials."
    )
    parser.add_argument(
        "--profile",
        choices=("public", "personal"),
        default=None,
        help="Override the saved profile (default: public)",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "setup", help="Choose a profile and enabled tools interactively"
    )
    tools = commands.add_parser(
        "tools", help="List, enable, or disable individual tools"
    )
    tool_actions = tools.add_subparsers(dest="tool_action", required=True)
    list_command = tool_actions.add_parser(
        "list", help="List tool families and their status"
    )
    list_command.add_argument(
        "--all", action="store_true", help="List individual tools"
    )
    for action in ("enable", "disable"):
        command = tool_actions.add_parser(
            action, help=f"{action.capitalize()} one or more tools"
        )
        command.add_argument("names", nargs="+", help="Family IDs or exact tool names")
    settings = commands.add_parser("config", help="Manage saved environment settings")
    setting_actions = settings.add_subparsers(dest="setting_action", required=True)
    setting_actions.add_parser("list", help="List saved settings")
    setting_set = setting_actions.add_parser("set", help="Save an environment setting")
    setting_set.add_argument("name", help="Setting such as ntulearn.headless")
    setting_set.add_argument("value")
    setting_unset = setting_actions.add_parser("unset", help="Remove a saved setting")
    setting_unset.add_argument("name")
    auth = commands.add_parser(
        "auth", help="Manage shared credentials in your native OS keyring"
    )
    auth.add_argument("action", choices=("save", "status", "delete"))
    args = parser.parse_args()
    try:
        config = load_config()
        apply_config_env(config)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    if args.command != "auth":
        try:
            if args.command == "config":
                if args.setting_action == "list":
                    print(json.dumps(config["env"], indent=2, sort_keys=True))
                else:
                    section, separator, name = args.name.partition(".")
                    if not separator or not section or not name:
                        raise ConfigError(
                            "Use a setting name such as ntulearn.headless."
                        )
                    if args.setting_action == "set":
                        _, rendered = setting_entry(
                            section, name, args.value, parse=True
                        )
                        kind = SETTINGS[section][name][1] if section != "other" else str
                        value = rendered == "true" if kind is bool else kind(rendered)
                        config["env"].setdefault(section, {})[name] = value
                    else:
                        values = config["env"].get(section, {})
                        values.pop(name, None)
                        if not values:
                            config["env"].pop(section, None)
                    path = save_config(config)
                    print(f"Updated setting in {path}. Restart the server to apply.")
            elif args.command == "setup":
                from .tools.commands import setup

                if setup(args.profile):
                    args.command = "auth"
                    args.action = "save"
            elif args.command == "tools":
                from .tools.commands import tools_command

                tools_command(
                    args.tool_action,
                    getattr(args, "names", []),
                    args.profile,
                    all_tools=getattr(args, "all", False),
                )
            else:
                from shared.server import main as run_server

                profile = args.profile or config["profile"]
                from .tools.commands import effective_disabled

                disabled = sorted(effective_disabled(config, profile))
                if disabled:
                    run_server(profile, disabled_tools=disabled)
                else:
                    run_server(profile)
        except (ConfigError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        except (EOFError, KeyboardInterrupt):
            print(
                "Cancelled. Any settings already saved remain in place.",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        if args.command != "auth":
            return
    try:
        if args.action == "save":
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise CredentialError(
                    "Credential setup requires your own interactive terminal; piped input is refused."
                )
            print(
                "Save/update your NTU account in the native OS keyring and enable automatic login for STARS, NTULearn and LibFacilities."
            )
            username = input("NTU network username or email: ")
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                password = getpass("NTU password: ")
            save_credentials(username, password)
            print("Credentials saved in the OS keyring. Automatic login enabled.")
        elif args.action == "status":
            status = credential_status()
            if status["credential_error"]:
                raise CredentialError(status["credential_error"])
            print(
                "Credentials stored: "
                + ("yes" if status["credentials_configured"] else "no")
            )
        elif args.action == "delete":
            delete_credentials()
            print("Stored credentials deleted. Automatic login disabled.")
    except GetPassWarning:
        print(
            "Cannot hide password input. Use an interactive terminal that supports hidden input; no credentials were saved.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except CredentialError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (EOFError, KeyboardInterrupt):
        print("Credential setup cancelled; no credentials were saved.", file=sys.stderr)
        raise SystemExit(1) from None

"""Interactive setup and local tool-selection commands."""

import asyncio
import subprocess
import sys

from ..config import ConfigError, load_config, save_config

FAMILY_LABELS = {
    "careeraxis": "CareerAxis",
    "drntu": "DR-NTU",
    "faculty": "Faculty",
    "library": "Library",
    "mazemap": "MazeMap",
    "news": "NTU News",
    "ntulearn": "NTULearn",
    "omnibus": "NTU Omnibus",
    "onestop": "One Stop @ SAC",
    "service": "Campus services",
    "stars": "STARS",
}


def tool_families(names: list[str]) -> dict[str, set[str]]:
    families: dict[str, set[str]] = {}
    for name in names:
        families.setdefault(name.split("_", 1)[0], set()).add(name)
    return families


def registered_tools(profile: str):
    try:
        from server import create_server

        server = create_server(profile, check_dependencies=False)
        return asyncio.run(server.list_tools())
    except ModuleNotFoundError as error:
        if profile != "public" and error.name and error.name.startswith("playwright"):
            raise ConfigError(
                "Personal tools require the personal extra. Install all-abt-ntu-mcp[personal] and run setup again."
            ) from error
        raise


def tool_names(profile: str) -> list[str]:
    return sorted(tool.name for tool in registered_tools(profile))


def ensure_chromium() -> None:
    from server import _chromium_installed

    if _chromium_installed():
        return
    while True:
        answer = (
            input("Personal profiles need Playwright Chromium. Install it now? [Y/n] ")
            .strip()
            .lower()
        )
        if answer in ("", "y", "yes"):
            break
        if answer in ("n", "no"):
            print(
                "Skipped Chromium. Install it before starting a personal profile; rerun setup to retry."
            )
            return
        print("Enter y or n.")
    print("Installing Playwright Chromium for the personal profile...", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=False
        )
    except OSError as error:
        raise ConfigError(
            f"Could not start the Chromium installer: {error}. Your tool choices were saved; rerun setup to retry."
        ) from error
    if result.returncode or not _chromium_installed():
        raise ConfigError(
            "Chromium installation failed or the browser is unavailable. Your tool choices were saved; rerun setup to retry."
        )
    print("Playwright Chromium is ready.")


def action_names() -> set[str]:
    return {
        tool.name
        for tool in registered_tools("personal")
        if not tool.annotations or tool.annotations.read_only_hint is not True
    }


def effective_disabled(config: dict, profile: str) -> set[str]:
    tools = config["tools"]
    enabled = set(tools["enabled"])
    disabled = set(tools["disabled"])
    disabled_families = set(tools["families"]["disabled"])
    if disabled_families:
        disabled.update(
            name
            for name in tool_names(profile)
            if name.split("_", 1)[0] in disabled_families and name not in enabled
        )
    if profile == "personal":
        disabled.update(action_names() - enabled)
    return disabled


def prepare_upload_directory() -> None:
    from onestop.attachments import upload_directory
    from onestop.models import OneStopError

    try:
        directory = upload_directory()
    except OneStopError as error:
        raise ConfigError(
            f"Tool choices were saved, but the upload directory is unavailable: {error}"
        ) from error
    print(f"One Stop upload directory: {directory}")


def setup(profile_override: str | None = None) -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ConfigError(
            "Setup requires an interactive terminal. Use tools enable/disable for scripts."
        )
    import questionary

    config = load_config()
    neutral_style = questionary.Style(
        [
            (name, "fg:default noreverse")
            for name in (
                "qmark",
                "answer",
                "pointer",
                "selected",
                "highlighted",
                "text",
            )
        ]
    )
    family_style = questionary.Style(
        [
            ("selected", "noreverse fg:ansigreen bold"),
            ("text", "fg:#a0a0a0"),
            ("highlighted", "noreverse fg:#a0a0a0"),
            ("pointer", "fg:ansicyan"),
        ]
    )
    print("All About NTU setup")
    profile = questionary.select(
        "Which tools would you like to use?",
        choices=[
            questionary.Choice("Public information", value="public"),
            questionary.Choice("Public and personal tools", value="personal"),
        ],
        default="public"
        if (profile_override or config["profile"]) == "public"
        else "personal",
        style=neutral_style,
    ).unsafe_ask()
    if profile is None:
        raise ConfigError("Setup cancelled; configuration was not changed.")
    names = tool_names(profile)
    families = tool_families(names)
    tools = config["tools"]
    disabled_families = set(tools["families"]["disabled"])
    previously_disabled = set(disabled_families)
    selected = questionary.checkbox(
        "Choose tool families",
        instruction="(arrows to move, space to toggle, enter to confirm)",
        choices=[
            questionary.Choice(
                FAMILY_LABELS.get(name, name),
                value=name,
                checked=name not in disabled_families,
            )
            for name in sorted(families)
        ],
        style=family_style,
    ).unsafe_ask()
    if selected is None:
        raise ConfigError("Setup cancelled; configuration was not changed.")
    disabled_families.difference_update(families)
    disabled_families.update(set(families) - set(selected))
    enabled_families = set(tools["families"]["enabled"])
    enabled_families.difference_update(families)
    enabled_families.update(selected)
    enabled_tools = set(tools["enabled"])
    disabled_tools = set(tools["disabled"])
    for family in set(selected) & previously_disabled:
        disabled_tools.difference_update(families[family])
    for family in set(families) - set(selected):
        enabled_tools.difference_update(families[family])
    tools["enabled"] = sorted(enabled_tools)
    tools["disabled"] = sorted(disabled_tools)
    tools["families"] = {
        "enabled": sorted(enabled_families),
        "disabled": sorted(disabled_families),
    }
    config["profile"] = profile
    path = save_config(config)
    print(
        f"Saved {len(selected)} enabled families for {profile} to {path}. Restart the server to apply."
    )
    enabled = set(names) - effective_disabled(config, profile)
    if "onestop_upload_attachment" in enabled:
        prepare_upload_directory()
    if profile != "public":
        ensure_chromium()
    if profile != "public" and enabled.difference(tool_names("public")):
        from shared.credentials import credential_status

        status = credential_status()
        if status["credential_error"]:
            print(
                f"Could not check saved NTU credentials: {status['credential_error']}",
                file=sys.stderr,
            )
            return False
        if status["credentials_configured"]:
            print("NTU credentials are already saved in the OS keyring.")
            return False
        return bool(
            questionary.confirm(
                "Set up NTU account credentials now? You can also run auth save later.",
                default=True,
            ).unsafe_ask()
        )
    return False


def tools_command(
    action: str,
    names: list[str],
    profile_override: str | None,
    *,
    all_tools: bool = False,
) -> None:
    config = load_config()
    profile = profile_override or config["profile"]
    available = tool_names(profile)
    families = tool_families(available)
    disabled = effective_disabled(config, profile)
    if action == "list":
        print(f"Profile: {profile}")
        if all_tools:
            for name in available:
                print(f"[{' ' if name in disabled else 'x'}] {name}")
        else:
            for family, members in sorted(families.items()):
                count = len(members - disabled)
                state = " " if count == 0 else "x" if count == len(members) else "~"
                print(
                    f"[{state}] {family} ({FAMILY_LABELS.get(family, family)}; {count}/{len(members)} tools)"
                )
        return
    unknown = sorted(set(names) - set(available) - set(families))
    if unknown:
        raise ConfigError(
            f"Tool not available in profile {profile}: {', '.join(unknown)}"
        )
    tools = config["tools"]
    disabled = set(tools["disabled"])
    enabled = set(tools["enabled"])
    disabled_families = set(tools["families"]["disabled"])
    enabled_families = set(tools["families"]["enabled"])
    family_names = set(names) & set(families)
    individual_names = set(names) - family_names
    if action == "enable":
        expanded = individual_names | set().union(
            *(families[name] for name in family_names)
        )
        disabled_families.difference_update(family_names)
        enabled_families.update(family_names)
        disabled.difference_update(expanded)
        enabled.update(expanded)
    else:
        expanded = individual_names | set().union(
            *(families[name] for name in family_names)
        )
        disabled_families.update(family_names)
        enabled_families.difference_update(family_names)
        disabled.update(expanded)
        enabled.difference_update(expanded)
    tools["enabled"], tools["disabled"] = sorted(enabled), sorted(disabled)
    tools["families"] = {
        "enabled": sorted(enabled_families),
        "disabled": sorted(disabled_families),
    }
    path = save_config(config)
    print(
        f"Updated {len(set(names))} selection(s) in {path}. Restart the server to apply."
    )
    if action == "enable" and "onestop_upload_attachment" in expanded:
        prepare_upload_directory()

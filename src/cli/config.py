"""Machine-local tool selection and service settings."""

import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from shared.paths import config_dir

PROFILES = ("public", "personal")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_CONFIG_LOCATION_VARS = {"XDG_CONFIG_HOME", "APPDATA", "HOME", "USERPROFILE"}
# Each entry maps a friendly key to its existing environment variable, type and limits.
SETTINGS: dict[
    str, dict[str, tuple[str, type, int | float | None, int | float | None]]
] = {
    "stars": {
        "cache_ttl_seconds": ("NTU_CACHE_TTL_SECONDS", int, 0, None),
        "personal_cache_ttl_seconds": ("NTU_PERSONAL_CACHE_TTL_SECONDS", int, 0, 86400),
    },
    "ntulearn": {
        "cache_ttl_seconds": ("NTULEARN_CACHE_TTL_SECONDS", int, 0, 86400),
        "headless": ("NTULEARN_HEADLESS", bool, None, None),
        "browser_cookies": ("NTULEARN_BROWSER_COOKIES", bool, None, None),
        "request_concurrency": ("NTULEARN_REQUEST_CONCURRENCY", int, 1, 8),
        "request_interval_seconds": ("NTULEARN_REQUEST_INTERVAL_SECONDS", float, 0, 5),
        "timeout_seconds": ("NTULEARN_TIMEOUT_SECONDS", float, 1, 120),
    },
    "careeraxis": {
        "cache_ttl_seconds": ("CAREERAXIS_CACHE_TTL_SECONDS", int, 0, 3600),
        "headless": ("CAREERAXIS_HEADLESS", bool, None, None),
    },
    "onestop": {"upload_dir": ("NTU_ONESTOP_UPLOAD_DIR", str, None, None)},
    "public_http": {
        "concurrency": ("NTU_PUBLIC_HTTP_CONCURRENCY", int, 1, 8),
        "interval_seconds": ("NTU_PUBLIC_HTTP_INTERVAL_SECONDS", float, 0, 10),
        "timeout_seconds": ("NTU_PUBLIC_HTTP_TIMEOUT_SECONDS", float, 1, 120),
        "max_retry_delay_seconds": (
            "NTU_PUBLIC_HTTP_MAX_RETRY_DELAY_SECONDS",
            float,
            0,
            30,
        ),
    },
    "browser": {"browsers_path": ("PLAYWRIGHT_BROWSERS_PATH", str, None, None)},
}


class ConfigError(Exception):
    pass


def config_path() -> Path:
    return config_dir() / "tools.json"


def setting_entry(section: str, name: str, value, *, parse: bool = False):
    if section == "other":
        if (
            not _ENV_NAME.fullmatch(name)
            or name in _CONFIG_LOCATION_VARS
            or not isinstance(value, str)
            or "\0" in value
        ):
            raise ConfigError(
                "Invalid environment name or value; configuration-location variables must be set outside this file."
            )
        return name, value
    setting = SETTINGS.get(section, {}).get(name)
    if setting is None:
        raise ConfigError(f"Unknown setting {section}.{name}.")
    variable, kind, minimum, maximum = setting
    if parse:
        try:
            if kind is bool:
                if value.lower() not in ("true", "false"):
                    raise ValueError
                value = value.lower() == "true"
            else:
                value = kind(value)
        except (ValueError, TypeError):
            raise ConfigError(f"Invalid value for {section}.{name}.") from None
    valid = type(value) is kind or (kind is float and type(value) is int)
    if valid and kind in (int, float):
        valid = (
            (kind is int or math.isfinite(value))
            and (minimum is None or value >= minimum)
            and (maximum is None or value <= maximum)
        )
    if valid and kind is str:
        valid = "\0" not in value
        if section == "onestop" and name == "upload_dir" and value:
            valid = Path(value).expanduser().is_absolute()
    if not valid:
        raise ConfigError(f"Invalid value for {section}.{name}.")
    return variable, str(value).lower() if kind is bool else str(value)


def validate_env_settings(env: dict) -> None:
    variables = set()
    for section, values in env.items():
        if section != "other" and section not in SETTINGS:
            raise ConfigError(f"Unknown settings group {section}.")
        for name, value in values.items():
            if not isinstance(name, str):
                raise ConfigError("Invalid setting name.")
            variable, _ = setting_entry(section, name, value)
            if variable in variables:
                raise ConfigError(
                    f"Environment variable {variable} is configured more than once."
                )
            variables.add(variable)


def load_config() -> dict:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "profile": "public",
            "tools": {
                "enabled": [],
                "disabled": [],
                "families": {"enabled": [], "disabled": []},
            },
            "env": {},
        }
    except (OSError, ValueError) as error:
        raise ConfigError(f"Cannot read configuration at {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid configuration at {path}; fix or remove the file.")
    data.setdefault("profile", "public")
    tools: Any = data.setdefault("tools", {})
    if isinstance(tools, dict):
        tools.setdefault("enabled", [])
        tools.setdefault("disabled", [])
        tools.setdefault("families", {})
    families = tools.get("families") if isinstance(tools, dict) else None
    if isinstance(families, dict):
        families.setdefault("enabled", [])
        families.setdefault("disabled", [])
    env = data.get("env", {})
    if (
        data.get("profile") not in PROFILES
        or not isinstance(tools, dict)
        or not all(isinstance(tools.get(key), list) for key in ("enabled", "disabled"))
        or not all(
            isinstance(name, str) and name
            for key in ("enabled", "disabled")
            for name in tools[key]
        )
        or set(tools["enabled"]) & set(tools["disabled"])
        or not isinstance(families, dict)
        or not all(
            isinstance(families.get(key), list) for key in ("enabled", "disabled")
        )
        or not all(
            isinstance(name, str) and name
            for key in ("enabled", "disabled")
            for name in families[key]
        )
        or set(families["enabled"]) & set(families["disabled"])
        or not isinstance(env, dict)
        or not all(
            isinstance(section, str) and isinstance(values, dict)
            for section, values in env.items()
        )
    ):
        raise ConfigError(f"Invalid configuration at {path}; fix or remove the file.")
    validate_env_settings(env)
    data.setdefault("env", {})
    return data


def apply_config_env(config: dict) -> None:
    """Inherit explicit process environment values ahead of saved defaults."""
    for section, settings in config["env"].items():
        for name, value in settings.items():
            variable, rendered = setting_entry(section, name, value)
            os.environ.setdefault(variable, rendered)


def save_config(config: dict) -> Path:
    validate_env_settings(config["env"])
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            try:
                json.dump(config, file, indent=2, sort_keys=True)
                file.write("\n")
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as error:
        raise ConfigError(f"Cannot save configuration at {path}: {error}") from error
    return path

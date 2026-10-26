"""NTULearn HTTP and authentication settings."""

import math
import os
from dataclasses import dataclass

from ..models import LearnError


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.environ.get(name, str(default))
    try:
        parsed = int(value)
    except ValueError:
        raise LearnError(f"{name} must be an integer from {minimum} to {maximum}.") from None
    if not minimum <= parsed <= maximum:
        raise LearnError(f"{name} must be an integer from {minimum} to {maximum}.")
    return parsed


def _seconds(name: str, default: float, minimum: float, maximum: float) -> float:
    value = os.environ.get(name, str(default))
    try:
        parsed = float(value)
    except ValueError:
        raise LearnError(f"{name} must be a number from {minimum:g} to {maximum:g}.") from None
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise LearnError(f"{name} must be a number from {minimum:g} to {maximum:g}.")
    return parsed


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name, "true" if default else "false").lower()
    if value not in {"true", "false"}:
        raise LearnError(f"{name} must be true or false.")
    return value == "true"


@dataclass(frozen=True)
class SessionConfig:
    cache_ttl_seconds: int
    headless: bool
    browser_cookies: bool
    request_concurrency: int
    request_interval_seconds: float
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "SessionConfig":
        return cls(
            cache_ttl_seconds=_integer("NTULEARN_CACHE_TTL_SECONDS", 300, 0, 86400),
            headless=_boolean("NTULEARN_HEADLESS", True),
            browser_cookies=_boolean("NTULEARN_BROWSER_COOKIES", False),
            request_concurrency=_integer("NTULEARN_REQUEST_CONCURRENCY", 4, 1, 8),
            request_interval_seconds=_seconds("NTULEARN_REQUEST_INTERVAL_SECONDS", 0.1, 0, 5),
            timeout_seconds=_seconds("NTULEARN_TIMEOUT_SECONDS", 30, 1, 120),
        )

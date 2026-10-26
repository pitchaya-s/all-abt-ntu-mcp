"""Synthetic comparison of legacy serialized HTTP pacing and the async client.

This does not contact NTU. The legacy model reproduces the former one-worker,
500 ms request-start pacing and response cache. Authentication and network
latency are deterministic local delays, so these numbers compare scheduling
behavior rather than real SSO, NTU, or browser performance.
"""

import asyncio
import logging
import os
import statistics
import sys
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ntulearn.client.browser_cookies import SessionCookie  # noqa: E402
from ntulearn.client.client import LearnClient  # noqa: E402
from ntulearn.client.session import Session  # noqa: E402
from ntulearn.services.overview import whats_new  # noqa: E402
from shared.credentials import Credentials  # noqa: E402

PREFIX = "/learn/api/public/v1"
COURSES = PREFIX + "/users/me/courses"
USER = PREFIX + "/users/me"
LATENCY = float(os.environ.get("NTULEARN_BENCH_LATENCY_MS", "50")) / 1000
ITERATIONS = int(os.environ.get("NTULEARN_BENCH_ITERATIONS", "3"))
LOGIN_LATENCY = LATENCY
COOKIES = (
    SessionCookie("BbRouter", "expires:1,id:synthetic", ".ntu.edu.sg", secure=True, domain_specified=True),
)
LOGIN_CREDENTIALS = Credentials(
    "student001", "student001@e.ntu.edu.sg", "synthetic-password", "synthetic-revision"
)


def response_data(path: str):
    if path == USER:
        return {"id": "_900_1"}
    return {"results": []}


class LegacySession:
    """Small timing model for the old serial executor and its cache."""

    def __init__(self, *, authenticated=True, login_delay=LOGIN_LATENCY):
        self.authenticated = authenticated
        self.auth = SimpleNamespace(generation=0)
        self.login_delay = login_delay
        self._lock = asyncio.Lock()
        self._next_start = 0.0
        self._cache = {}

    @asynccontextmanager
    async def operation(self):
        yield

    async def get(self, path, params=None, refresh=False):
        params = params or {}
        key = (path, tuple(sorted(params.items())))
        if not refresh and key in self._cache:
            return deepcopy(self._cache[key]), {
                "retrieved_at": datetime.now(timezone.utc),
                "from_cache": True,
                "cache_age_seconds": 0,
            }
        async with self._lock:
            if not refresh and key in self._cache:
                return deepcopy(self._cache[key]), {
                    "retrieved_at": datetime.now(timezone.utc),
                    "from_cache": True,
                    "cache_age_seconds": 0,
                }
            now = time.monotonic()
            await asyncio.sleep(max(0.0, self._next_start - now))
            started = time.monotonic()
            self._next_start = started + 0.5
            if not self.authenticated:
                await asyncio.sleep(self.login_delay)
                self.authenticated = True
            await asyncio.sleep(LATENCY)
            data = response_data(path)
            self._cache[key] = deepcopy(data)
            return data, {
                "retrieved_at": datetime.now(timezone.utc),
                "from_cache": False,
                "cache_age_seconds": 0,
            }


def synthetic_handler(*, delay=LATENCY, expiry=False):
    expired_once = False

    async def handle(request):
        nonlocal expired_once
        await asyncio.sleep(delay)
        if expiry and request.url.path == COURSES and not expired_once:
            expired_once = True
            return httpx.Response(401, request=request)
        if request.url.path == USER and not request.headers.get("cookie"):
            return httpx.Response(401, request=request)
        return httpx.Response(200, json=response_data(request.url.path), request=request)

    return handle


def new_session(*, browser=False, expiry=False):
    cookie_sets = iter([COOKIES, (SessionCookie(
        "BbRouter", "expires:1,id:rotated", ".ntu.edu.sg", secure=True, domain_specified=True
    ),)])
    with patch.dict(os.environ, {"NTULEARN_BROWSER_COOKIES": str(browser).lower()}):
        return Session(
            browser_cookie_reader=lambda: [next(cookie_sets)] if expiry else [COOKIES],
            sso_login=synthetic_sso,
            transport=httpx.MockTransport(synthetic_handler(expiry=expiry)),
        )


async def synthetic_sso(credentials, *, headless):
    await asyncio.sleep(LOGIN_LATENCY)
    return COOKIES


async def with_new_session(action, *, browser=False, expiry=False, warm_auth=False):
    session = new_session(browser=browser, expiry=expiry)
    try:
        client = LearnClient(session)
        if warm_auth:
            await session.auth.ensure()
            await asyncio.sleep(session.config.request_interval_seconds)
        started = time.perf_counter()
        async with session.operation():
            result = await action(session, client)
        if warm_auth:
            return time.perf_counter() - started
        return result
    finally:
        await session.close()


async def with_legacy_session(action, *, authenticated=True):
    session = LegacySession(authenticated=authenticated)
    client = LearnClient(session)
    async with session.operation():
        return await action(session, client)


async def benchmark_case(name, new_action, legacy_action=None):
    new_samples, legacy_samples = [], []
    for _ in range(ITERATIONS):
        if legacy_action is not None:
            started = time.perf_counter()
            measured = await legacy_action()
            legacy_samples.append(measured if type(measured) is float else time.perf_counter() - started)
        started = time.perf_counter()
        measured = await new_action()
        new_samples.append(measured if type(measured) is float else time.perf_counter() - started)
    old_text = format_seconds(statistics.median(legacy_samples)) if legacy_samples else "unsupported"
    print(f"{name:<34} {old_text:>14} {format_seconds(statistics.median(new_samples)):>14}")


def format_seconds(value):
    return f"{value * 1000:.1f} ms" if value < 1 else f"{value:.2f} s"


async def cold_sso_new():
    session = new_session()
    try:
        async with session.operation():
            await LearnClient(session).list_courses()
    finally:
        await session.close()


async def cold_sso_legacy():
    session = LegacySession(authenticated=False)
    await session.get(COURSES)


async def cold_browser_new():
    session = new_session(browser=True)
    try:
        async with session.operation():
            await LearnClient(session).list_courses()
        assert session.auth.state.method == "browser_cookie"
    finally:
        await session.close()


async def warm_new_single():
    session = new_session()
    try:
        await session.auth.ensure()
        # Exclude the pacing interval left by the authentication validation;
        # this case represents a steady-state request on an active session.
        await asyncio.sleep(session.config.request_interval_seconds)
        started = time.perf_counter()
        async with session.operation():
            await LearnClient(session).list_courses(refresh=True)
        return time.perf_counter() - started
    finally:
        await session.close()


async def warm_legacy_single():
    await with_legacy_session(lambda session, client: client.list_courses(refresh=True))


async def repeated_cached_new():
    session = new_session()
    try:
        await session.auth.ensure()
        client = LearnClient(session)
        await client.list_courses()
        started = time.perf_counter()
        async with session.operation():
            for _ in range(10):
                await client.list_courses()
        return time.perf_counter() - started
    finally:
        await session.close()


async def repeated_cached_legacy():
    session = LegacySession()
    client = LearnClient(session)
    await client.list_courses()
    started = time.perf_counter()
    for _ in range(10):
        await client.list_courses()
    return time.perf_counter() - started


async def parallel_reads(session, _client):
    await asyncio.gather(*(
        session.get(COURSES, {"offset": offset}, refresh=True)
        for offset in range(8)
    ))


async def multi_course(session, client):
    now = datetime.now(timezone.utc)
    return await whats_new(
        client,
        since=now - timedelta(days=7),
        until=now + timedelta(days=14),
        selected=[f"_{index}_1" for index in range(1, 9)],
        max_requests=40,
        refresh=True,
    )


async def recovery_new():
    session = new_session(browser=True, expiry=True)
    try:
        await session.auth.ensure()
        await asyncio.sleep(session.config.request_interval_seconds)
        started = time.perf_counter()
        async with session.operation():
            await session.get(COURSES, refresh=True)
        return time.perf_counter() - started
    finally:
        await session.close()


async def recovery_legacy():
    session = LegacySession(authenticated=True)
    async with session._lock:
        now = time.monotonic()
        await asyncio.sleep(max(0.0, session._next_start - now))
        started = time.monotonic()
        session._next_start = started + 0.5
        await asyncio.sleep(LATENCY)  # first request receives the simulated 401
        await asyncio.sleep(LOGIN_LATENCY)
        now = time.monotonic()
        await asyncio.sleep(max(0.0, session._next_start - now))
        started = time.monotonic()
        session._next_start = started + 0.5
        await asyncio.sleep(LATENCY)  # request after the simulated SSO recovery


async def run():
    if ITERATIONS < 1:
        raise ValueError("NTULEARN_BENCH_ITERATIONS must be at least 1")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    env = {
        "NTULEARN_BROWSER_COOKIES": "false",
        "NTULEARN_HEADLESS": "true",
        "NTULEARN_CACHE_TTL_SECONDS": "300",
        "NTULEARN_REQUEST_CONCURRENCY": "4",
        "NTULEARN_REQUEST_INTERVAL_SECONDS": "0.1",
        "NTULEARN_TIMEOUT_SECONDS": "30",
    }
    with patch.dict(os.environ, env), patch(
        "ntulearn.client.auth.read_credentials", return_value=LOGIN_CREDENTIALS
    ):
        print(f"Synthetic benchmark; {ITERATIONS} iteration(s), {LATENCY * 1000:.0f} ms local HTTP latency")
        print(f"{'Scenario':<34} {'legacy model':>14} {'async client':>14}")
        print("-" * 64)
        await benchmark_case("Cold, no authenticated session", cold_sso_new, cold_sso_legacy)
        await benchmark_case("Cold, existing browser cookie", cold_browser_new)
        await benchmark_case("Warm single API request", warm_new_single, warm_legacy_single)
        await benchmark_case("10 repeated cached requests", repeated_cached_new, repeated_cached_legacy)
        await benchmark_case(
            "8 independent API requests",
            lambda: with_new_session(parallel_reads, warm_auth=True),
            lambda: with_legacy_session(parallel_reads),
        )
        await benchmark_case(
            "8-course activity aggregation",
            lambda: with_new_session(multi_course, warm_auth=True),
            lambda: with_legacy_session(multi_course),
        )
        await benchmark_case("Session expiry and recovery", recovery_new, recovery_legacy)
    print("\nLegacy values model one-worker 500 ms pacing; browser-cookie import was unsupported.")
    print("SSO, HTTP latency, and recovery are simulated; no NTU or browser processes were contacted.")


if __name__ == "__main__":
    asyncio.run(run())

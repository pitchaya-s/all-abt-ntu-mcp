"""Lazy hybrid authentication and single-flight session recovery."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from shared.credentials import CredentialError, read_credentials

from ..models import LearnError
from .browser_cookies import SessionCookie, read_browser_cookie_sets
from .config import SessionConfig
from .http import LearnHTTP, json_body
from .sso import login


@dataclass(frozen=True, slots=True)
class AuthState:
    method: Literal["browser_cookie", "sso"]
    generation: int
    verified_at: datetime
    credential_revision: str | None = field(default=None, repr=False)


class SessionExpired(Exception):
    """An authenticated NTULearn request received a login/expired response."""


class Authenticator:
    def __init__(
        self,
        transport: LearnHTTP,
        config: SessionConfig,
        *,
        browser_cookie_reader: Callable[[], list[tuple[SessionCookie, ...]]] = read_browser_cookie_sets,
        sso_login: Callable[..., Awaitable[tuple[SessionCookie, ...]]] = login,
    ):
        self.transport = transport
        self.config = config
        self.browser_cookie_reader = browser_cookie_reader
        self.sso_login = sso_login
        self._state: AuthState | None = None
        self._generation = 0
        self._lock = asyncio.Lock()
        self._flight: asyncio.Task[AuthState] | None = None
        self._flight_failed_at: float | None = None
        self._login_not_before = 0.0

    @property
    def state(self) -> AuthState | None:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    async def ensure(self, *, check_credentials: bool = True) -> AuthState:
        state = self._state
        if state is not None and state.method == "browser_cookie":
            return state
        if state is not None and check_credentials:
            try:
                credentials = await asyncio.to_thread(read_credentials)
            except CredentialError:
                await self._invalidate_if(state.generation)
            else:
                if self._state is state and credentials.revision == state.credential_revision:
                    return state
                await self._invalidate_if(state.generation)
        return await self._resolve_once()

    async def recover(self, expired_generation: int) -> AuthState:
        async with self._lock:
            state = self._state
            if state is not None and state.generation != expired_generation:
                return state
            if self._generation == expired_generation and state is not None:
                self._state = None
                self._generation += 1
                self.transport.clear_cookies(self._generation)
        return await self._resolve_once()

    async def invalidate(self) -> None:
        """Drop this process's validated authentication state."""
        async with self._lock:
            if self._state is not None:
                self._state = None
                self._generation += 1
                self.transport.clear_cookies(self._generation)

    async def _invalidate_if(self, generation: int) -> None:
        async with self._lock:
            if self._state is not None and self._state.generation == generation:
                self._state = None
                self._generation += 1
                self.transport.clear_cookies(self._generation)

    async def _resolve_once(self) -> AuthState:
        async with self._lock:
            if self._state is not None:
                return self._state
            task = self._flight
            if task is not None and task.done() and self._flight_failed_at is not None:
                elapsed = time.monotonic() - self._flight_failed_at
                if elapsed < 2.0 and self._login_not_before > time.monotonic():
                    raise LearnError(
                        "A recent login did not complete. Wait one minute before retrying to avoid repeated password attempts."
                    )
                if elapsed >= 2.0:
                    self._flight = None
                    self._flight_failed_at = None
                    task = None
            if task is None:
                task = asyncio.create_task(self._resolve())
                self._flight = task
                self._flight_failed_at = None

        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._flight is task:
                        if task.cancelled() or task.exception() is not None:
                            self._flight_failed_at = time.monotonic()
                        else:
                            self._flight = None
                            self._flight_failed_at = None

    async def _resolve(self) -> AuthState:
        generation = self._generation
        try:
            if self.config.browser_cookies:
                try:
                    cookie_sets = await asyncio.to_thread(self.browser_cookie_reader)
                except Exception:  # noqa: BLE001 - browser profiles may fail for platform-specific reasons.
                    cookie_sets = []
                for cookies in cookie_sets:
                    self.transport.set_cookies(cookies, generation)
                    if await self._validate():
                        return self._activate("browser_cookie", generation, None)
                    self.transport.clear_cookies(generation)

            try:
                credentials = await asyncio.to_thread(read_credentials)
                credentials.require_login()
            except CredentialError as error:
                raise LearnError(str(error)) from None

            if time.monotonic() < self._login_not_before:
                raise LearnError(
                    "A recent login did not complete. Wait one minute before retrying to avoid repeated password attempts."
                )
            self._login_not_before = time.monotonic() + 60
            cookies = await self.sso_login(credentials, headless=self.config.headless)
            self.transport.set_cookies(cookies, generation)
            if not await self._validate():
                self.transport.clear_cookies(generation)
                raise LearnError("NTULearn did not verify the authenticated session.")
            self._login_not_before = 0.0
            return self._activate("sso", generation, credentials.revision)
        except asyncio.CancelledError:
            self.transport.clear_cookies(self._generation)
            raise
        except LearnError:
            self.transport.clear_cookies(self._generation)
            raise
        except Exception:  # noqa: BLE001 - provider exceptions may contain credentials or page data.
            self.transport.clear_cookies(self._generation)
            raise LearnError("NTULearn authentication failed; no credentials or session data were included.") from None

    async def _validate(self) -> bool:
        response = await self.transport.get("/learn/api/public/v1/users/me")
        try:
            if response.status_code == 200:
                try:
                    data = json_body(response)
                except LearnError:
                    return False
                return isinstance(data, dict) and isinstance(data.get("id"), str) and bool(data["id"])
            if response.status_code in {401, 403, 404, 301, 302, 303, 307, 308}:
                return False
            if response.status_code in {429, 500, 502, 503, 504}:
                raise LearnError(
                    f"NTULearn could not verify the session after retrying (HTTP {response.status_code})."
                )
            return False
        finally:
            await response.aclose()

    def _activate(
        self,
        method: Literal["browser_cookie", "sso"],
        generation: int,
        credential_revision: str | None,
    ) -> AuthState:
        if generation != self._generation:
            raise LearnError("NTULearn authentication changed while the session was being established; retry the request.")
        state = AuthState(
            method=method,
            generation=generation,
            verified_at=datetime.now(timezone.utc),
            credential_revision=credential_revision,
        )
        self._state = state
        return state

    async def close(self) -> None:
        async with self._lock:
            task = self._flight
            self._flight = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            self._state = None
            self.transport.clear_cookies()

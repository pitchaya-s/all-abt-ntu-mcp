"""Lifecycle coordinator for authenticated, read-only NTULearn operations."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.credentials import credential_status

from ..models import AuthStatus, Download, LearnError
from .auth import Authenticator, SessionExpired
from .browser_cookies import BASE_URL, read_browser_cookie_sets
from .cache import ResponseCache
from .config import SessionConfig
from .http import AuthGenerationChanged, MAX_FILE_BYTES, LearnHTTP, allowed_read_path, json_body
from .sso import login


class _Operation:
    def __init__(self):
        self.credential_check_lock = asyncio.Lock()
        self.credential_checked = False


class Session:
    def __init__(
        self,
        *,
        browser_cookie_reader=read_browser_cookie_sets,
        sso_login=login,
        transport=None,
        external_transport=None,
    ):
        self.config = SessionConfig.from_env()
        self.http = LearnHTTP(
            self.config,
            transport=transport,
            external_transport=external_transport,
        )
        self.cache = ResponseCache(self.config.cache_ttl_seconds)
        self.auth = Authenticator(
            self.http,
            self.config,
            browser_cookie_reader=browser_cookie_reader,
            sso_login=sso_login,
        )
        self._cache_generation = self.auth.generation
        self._operation: ContextVar[_Operation | None] = ContextVar(
            f"ntulearn-operation-{id(self)}", default=None
        )
        self._lifecycle = asyncio.Condition()
        self._active_operations = 0
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    async def status(self) -> AuthStatus:
        credentials = await asyncio.to_thread(credential_status)
        state = self.auth.state
        return AuthStatus(
            **credentials,
            session_verified=state is not None,
            authentication_method=state.method if state else None,
            last_verified_at=state.verified_at if state else None,
            cache_ttl_seconds=self.config.cache_ttl_seconds,
        )

    @asynccontextmanager
    async def operation(self):
        """Share one keyring revision check across a multi-request MCP tool call."""
        await self._begin_operation()
        token = self._operation.set(_Operation())
        try:
            yield
        finally:
            self._operation.reset(token)
            await self._end_operation()

    async def get(self, path: str, params: dict[str, Any] | None = None, refresh: bool = False):
        await self._begin_operation()
        try:
            return await self._get(path, params or {}, refresh)
        finally:
            await self._end_operation()

    async def _get(self, path: str, params: dict[str, Any], refresh: bool):
        if not allowed_read_path(path) or path.endswith("/download"):
            raise LearnError("This NTULearn endpoint is not an academic JSON read endpoint.")
        state = await self._ensure_authenticated()
        key = (path, tuple(sorted(params.items())))
        cached = self.cache.get(key, refresh=refresh)
        if cached is not None:
            return cached

        reauthenticated = False
        generation_changes = 0
        while True:
            try:
                response = await self.http.get(
                    path,
                    params,
                    expected_generation=state.generation,
                )
            except AuthGenerationChanged:
                generation_changes += 1
                if generation_changes > 2:
                    raise LearnError("NTULearn authentication changed repeatedly; retry the request.") from None
                state = await self._ensure_authenticated()
                continue
            try:
                status = response.status_code
                content_type = response.headers.get("content-type", "").lower()
                expired = (
                    status == 401
                    or status in {301, 302, 303, 307, 308}
                    or (status == 200 and "text/html" in content_type)
                )
                if expired:
                    await response.aclose()
                    if reauthenticated:
                        raise LearnError("NTULearn's session expired again after reauthentication; retry later.")
                    state = await self.auth.recover(state.generation)
                    self._sync_cache_generation()
                    reauthenticated = True
                    continue
                if status == 403:
                    raise LearnError("NTULearn denied access to this resource (HTTP 403); no alternate access was attempted.")
                if status == 404:
                    raise LearnError("NTULearn did not find this resource, or it is not visible to your account (HTTP 404).")
                if status == 429:
                    raise LearnError("NTULearn is rate limited (HTTP 429); retry this read later.")
                if status != 200:
                    raise LearnError(f"NTULearn could not complete this read request (HTTP {status}).")
                data = json_body(response)
                now = datetime.now(timezone.utc)
                # An account change can clear the cache while this request is
                # in flight. Do not let the old account repopulate it.
                if self.auth.generation == state.generation:
                    self.cache.put(key, data, now)
                return data, {"retrieved_at": now, "from_cache": False, "cache_age_seconds": 0}
            finally:
                await response.aclose()
        raise LearnError("NTULearn is temporarily unavailable.")

    async def download(self, path: str, destination: str, max_bytes: int = MAX_FILE_BYTES) -> Download:
        await self._begin_operation()
        try:
            return await self._download(path, destination, max_bytes)
        finally:
            await self._end_operation()

    async def _download(self, path: str, destination: str, max_bytes: int) -> Download:
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_FILE_BYTES:
            raise LearnError("The remaining per-file byte limit must be between 1 and 20000000.")
        if not allowed_read_path(path) or not path.endswith("/download"):
            raise LearnError("Use a Blackboard attachment download endpoint.")
        target = Path(destination).expanduser().absolute()
        if target.exists() or not target.parent.is_dir():
            raise LearnError("Choose a new file path in an existing directory; existing files are never overwritten.")

        state = await self._ensure_authenticated()
        reauthenticated = False
        generation_changes = 0
        for _ in range(4):
            try:
                body = await self.http.download_bytes(
                    path,
                    max_bytes,
                    expected_generation=state.generation,
                )
                break
            except AuthGenerationChanged:
                generation_changes += 1
                if generation_changes > 2:
                    raise LearnError("NTULearn authentication changed repeatedly; retry the download.") from None
                state = await self._ensure_authenticated()
            except SessionExpired:
                if reauthenticated:
                    raise LearnError("NTULearn's session expired again during the download; retry later.") from None
                state = await self.auth.recover(state.generation)
                self._sync_cache_generation()
                reauthenticated = True
        else:
            raise LearnError("NTULearn could not complete the attachment download; retry later.")

        try:
            await asyncio.to_thread(self._write_new_file, target, body)
        except OSError:
            raise LearnError("Could not save the download. Check the destination and available space; existing files were not overwritten.") from None
        return Download(
            path=str(target),
            bytes_written=len(body),
            downloaded_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _write_new_file(target: Path, body: bytes) -> None:
        created = False
        try:
            with target.open("xb") as output:
                created = True
                output.write(body)
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            raise

    async def _ensure_authenticated(self):
        try:
            operation = self._operation.get()
            if operation is None:
                return await self.auth.ensure()
            async with operation.credential_check_lock:
                check_credentials = not operation.credential_checked
                state = await self.auth.ensure(check_credentials=check_credentials)
                operation.credential_checked = True
                return state
        finally:
            self._sync_cache_generation()

    def _sync_cache_generation(self) -> None:
        if self._cache_generation != self.auth.generation:
            self.cache.clear()
            self._cache_generation = self.auth.generation

    async def _begin_operation(self) -> None:
        async with self._lifecycle:
            if self._closing and self._operation.get() is None:
                raise LearnError("The NTULearn session is closed; restart the MCP server.")
            self._active_operations += 1

    async def _end_operation(self) -> None:
        async with self._lifecycle:
            self._active_operations -= 1
            if self._active_operations == 0:
                self._lifecycle.notify_all()

    async def close(self) -> None:
        async with self._lifecycle:
            if self._close_task is None:
                self._closing = True
                self._close_task = asyncio.create_task(self._close_resources())
            task = self._close_task
        await asyncio.shield(task)

    async def _close_resources(self) -> None:
        async with self._lifecycle:
            await self._lifecycle.wait_for(lambda: self._active_operations == 0)
        try:
            await self.auth.close()
        finally:
            await self.http.aclose()
            self.cache.clear()


BASE = BASE_URL

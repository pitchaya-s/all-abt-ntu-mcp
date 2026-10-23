"""Opt-in NTU credentials stored only in a native OS keyring."""

from dataclasses import dataclass, field
import json
import re
import sys
from uuid import uuid4

import keyring
from typing_extensions import TypedDict


SERVICE = "all-abt-ntu-mcp"
ACCOUNT = "ntu-account"
_NATIVE_BACKENDS = {
    "linux": {("keyring.backends.SecretService", "Keyring"),
              ("keyring.backends.kwallet", "DBusKeyring"),
              ("keyring.backends.kwallet", "DBusKeyringKWallet4")},
    "darwin": {("keyring.backends.macOS", "Keyring")},
    "win32": {("keyring.backends.Windows", "WinVaultKeyring")},
}
_UNAVAILABLE = (
    "The native OS keyring is unavailable or locked. Unlock/configure Secret Service or KWallet "
    "on Linux, Keychain on macOS, or Credential Manager on Windows. No plaintext fallback is used."
)
SETUP_MESSAGE = "No NTU credentials are stored. Run `all-abt-ntu auth save` in your own terminal."


class CredentialError(RuntimeError):
    """A credential failure with a message safe for logs and tool results."""


@dataclass(frozen=True)
class Credentials:
    username: str = field(default="", repr=False)
    email: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    revision: str = ""

    def require_login(self) -> None:
        if not self.username or not self.password:
            raise CredentialError(SETUP_MESSAGE)


class CredentialStatus(TypedDict):
    credentials_configured: bool | None
    credential_storage: str
    credential_error: str | None


def _backend():
    try:
        backend = keyring.get_keyring()
        if (type(backend).__module__, type(backend).__name__) == ("keyring.backends.chainer", "ChainerBackend"):
            backend = next(candidate for candidate in backend.backends
                           if (type(candidate).__module__, type(candidate).__name__) in _NATIVE_BACKENDS.get(sys.platform, set()))
        if (type(backend).__module__, type(backend).__name__) not in _NATIVE_BACKENDS.get(sys.platform, set()):
            raise CredentialError(_UNAVAILABLE)
        return backend
    except Exception:
        raise CredentialError(_UNAVAILABLE) from None


def _read(backend) -> dict | None:
    try:
        secret = backend.get_password(SERVICE, ACCOUNT)
    except Exception:
        raise CredentialError(_UNAVAILABLE) from None
    if secret is None:
        return None
    try:
        record = json.loads(secret)
        if not isinstance(record, dict) or set(record) != {"username", "password", "revision"}:
            raise ValueError
        _validate(record["username"], record["password"])
        if not isinstance(record["revision"], str) or not re.fullmatch(r"[0-9a-f]{32}", record["revision"]):
            raise ValueError
        return record
    except (ValueError, TypeError, CredentialError):
        raise CredentialError("The NTU keyring entry is invalid. Run `all-abt-ntu auth save` to replace it, or `auth delete` to remove it.") from None


def _validate(username: str, password: str) -> None:
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:@(?:e\.)?ntu\.edu\.sg)?", username, re.I):
        raise CredentialError("Enter your NTU network username or NTU email address.")
    if not isinstance(password, str) or not password or len(password) > 4096 or any(char in password for char in "\r\n\0"):
        raise CredentialError("Enter a nonempty NTU password without line breaks, up to 4096 characters.")


def _write(backend, record: dict) -> None:
    secret = json.dumps(record)
    try:
        backend.set_password(SERVICE, ACCOUNT, secret)
        if backend.get_password(SERVICE, ACCOUNT) != secret:
            raise CredentialError(_UNAVAILABLE)
    except Exception:
        raise CredentialError("The OS keyring did not confirm the update. Check/unlock it and retry; no plaintext copy was saved.") from None


def read_credentials() -> Credentials:
    record = _read(_backend())
    if record is None:
        return Credentials()
    username = record["username"]
    email = username if "@" in username else username + "@e.ntu.edu.sg"
    return Credentials(username.partition("@")[0], email, record["password"], record["revision"])


def credential_status() -> CredentialStatus:
    try:
        credentials = read_credentials()
    except CredentialError as error:
        return {"credentials_configured": None,
                "credential_storage": "os_keyring", "credential_error": str(error)}
    return {"credentials_configured": bool(credentials.username and credentials.password),
            "credential_storage": "os_keyring", "credential_error": None}


def save_credentials(username: str, password: str) -> None:
    username = username.strip()
    _validate(username, password)
    _write(_backend(), {"username": username, "password": password, "revision": uuid4().hex})


def delete_credentials() -> None:
    backend = _backend()
    try:
        if backend.get_password(SERVICE, ACCOUNT) is not None:
            backend.delete_password(SERVICE, ACCOUNT)
        if backend.get_password(SERVICE, ACCOUNT) is not None:
            raise CredentialError(_UNAVAILABLE)
    except Exception:
        raise CredentialError("The OS keyring did not confirm deletion. Unlock it and retry; credentials may still be stored.") from None

"""Shared NTU credentials for WISH and NTULearn."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path.cwd() / ".env", override=False)


@dataclass(frozen=True)
class Credentials:
    username: str
    email: str
    password: str = field(repr=False)


def read_credentials() -> Credentials:
    username = os.environ.get("NTU_USERNAME", "").strip()
    password = os.environ.get("NTU_PASSWORD", "")
    email = username if not username or "@" in username else username + "@e.ntu.edu.sg"
    return Credentials(username=username.partition("@")[0], email=email, password=password)

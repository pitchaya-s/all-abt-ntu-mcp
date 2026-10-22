"""In-memory keyring for tests; never touches the user's credential store."""

from contextlib import contextmanager
from unittest.mock import patch

from shared.credentials import save_credentials


class MemoryKeyring:
    def __init__(self):
        self.entries = {}

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def set_password(self, service, account, password):
        self.entries[service, account] = password

    def delete_password(self, service, account):
        self.entries.pop((service, account), None)


@contextmanager
def stored_credentials(username="test-user", password="test-secret"):
    backend = MemoryKeyring()
    with patch("shared.credentials._backend", return_value=backend):
        save_credentials(username, password)
        yield backend

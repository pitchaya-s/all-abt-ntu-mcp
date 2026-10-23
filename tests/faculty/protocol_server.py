"""Offline faculty directory server for stdio client checks."""

from unittest.mock import patch

from shared.server import main
from tests.faculty.fixtures import fake_get


if __name__ == "__main__":
    with patch("faculty.mcp_server.client.http.get", side_effect=fake_get):
        main()

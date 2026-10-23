"""Synthetic public map data for stdio interoperability checks."""

from unittest.mock import patch

from tests.mazemap.fixtures import fake_get
from shared.server import main


if __name__ == "__main__":
    with patch("mazemap.mcp_server.client._get", side_effect=fake_get):
        main()

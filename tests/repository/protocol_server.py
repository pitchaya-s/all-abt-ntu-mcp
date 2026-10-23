"""Offline DR-NTU fixtures for shared MCP interoperability checks."""

from unittest.mock import patch

from tests.repository.fixtures import fake_get
from tests.repository.oai_fixtures import fake_get as oai_get
from shared.server import main


if __name__ == "__main__":
    with patch("drntu.mcp_server.client.get", side_effect=fake_get), patch("drntu.mcp_server.oai_client.get", side_effect=oai_get):
        main()

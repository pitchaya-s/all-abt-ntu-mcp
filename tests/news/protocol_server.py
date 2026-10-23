from unittest.mock import patch

from shared.server import main
from tests.news.fixtures import fake_get


if __name__ == "__main__":
    with patch("news.mcp_server.client.http.get", side_effect=fake_get):
        main()

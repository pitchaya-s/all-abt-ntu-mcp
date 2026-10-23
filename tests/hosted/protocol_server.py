"""Offline public HTTP app; the same ASGI entrypoint as Vercel with synthetic data."""

from unittest.mock import patch

from shared.http import create_app
from tests.faculty.fixtures import fake_get as faculty_get
from tests.library.fixtures import fake_get as library_get
from tests.mazemap.fixtures import fake_get as map_get
from tests.news.fixtures import fake_get as news_get
from tests.repository.fixtures import fake_get as repository_get
from tests.repository.oai_fixtures import fake_get as oai_get
from tests.service.fixtures import fake_get as service_get
from tests.stars.mcp_fixtures import COURSE


PATCHES = [
    patch("stars.mcp_server.fetch_course", return_value=COURSE),
    patch("faculty.mcp_server.client.http.get", side_effect=faculty_get),
    patch("library.mcp_server.client.http.get", side_effect=library_get),
    patch("mazemap.mcp_server.client._get", side_effect=map_get),
    patch("news.mcp_server.client.http.get", side_effect=news_get),
    patch("drntu.mcp_server.client.get", side_effect=repository_get),
    patch("drntu.mcp_server.oai_client.get", side_effect=oai_get),
    patch("service.mcp_server.client.http.get", side_effect=service_get),
]
for replacement in PATCHES:
    replacement.start()
app = create_app()

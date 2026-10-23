from unittest.mock import patch

from tests.library.fixtures import fake_get
from tests.library.facility_fixtures import fake_facility_get, fake_schedule
from shared.server import main


if __name__ == "__main__":
    with (
        patch("library.mcp_server.client.http.get", side_effect=fake_get),
        patch("library.mcp_server.facilities.http.get", side_effect=fake_facility_get),
        patch("library.personal_tools.session.get_schedule", side_effect=fake_schedule),
    ):
        main()

"""A malformed successful response must not poison subsequent service reads."""

from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from drntu.models import RepositoryError
from drntu.oai import service as oai_service
from drntu.oai.client import OAIClient
from drntu.rest import repository
from drntu.rest.client import RepositoryClient
from library.client import LibraryClient
from tests.library.fixtures import LOCAL
from tests.repository.fixtures import ITEM, ITEM_ID
from tests.repository.oai_fixtures import envelope, fake_get as oai_fixture


class CacheValidationTests(unittest.TestCase):
    def test_repository_evicts_structurally_invalid_item(self):
        client = RepositoryClient()
        self.addCleanup(client.http.close)
        now = datetime.now(timezone.utc)
        with patch.object(
            client.http,
            "_fetch",
            side_effect=[
                (b"{}", now),
                (json.dumps(ITEM).encode(), now + timedelta(seconds=1)),
            ],
        ) as fetch:
            with self.assertRaises((KeyError, RepositoryError)):
                repository.get_item(client, ITEM_ID)
            self.assertEqual(repository.get_item(client, ITEM_ID).item_id, ITEM_ID)
            self.assertEqual(fetch.call_count, 2)

    def test_library_evicts_structurally_invalid_record(self):
        client = LibraryClient()
        self.addCleanup(client.http.close)
        now = datetime.now(timezone.utc)
        with patch.object(
            client.http,
            "_fetch",
            side_effect=[
                (b"{}", now),
                (json.dumps(LOCAL).encode(), now + timedelta(seconds=1)),
            ],
        ) as fetch:
            with self.assertRaises((KeyError, ValueError)):
                client.get_record("almaExample001")
            self.assertEqual(
                client.get_record("almaExample001").record.record_id, "almaExample001"
            )
            self.assertEqual(fetch.call_count, 2)

    def test_oai_evicts_valid_xml_missing_required_fields(self):
        client = OAIClient()
        self.addCleanup(client.close)
        now = datetime.now(timezone.utc)
        good, _ = oai_fixture("https://dr.ntu.edu.sg/server/oai/request?verb=Identify")
        with patch.object(
            client,
            "_fetch",
            side_effect=[
                (envelope("Identify"), now),
                (good, now + timedelta(seconds=1)),
            ],
        ) as fetch:
            with self.assertRaises(RepositoryError):
                oai_service.identify(client)
            self.assertEqual(
                oai_service.identify(client).repository_name, "Synthetic NTU repository"
            )
            self.assertEqual(fetch.call_count, 2)

"""Concurrent refreshes must not lose newer cache data to older requests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
import unittest
from unittest.mock import patch

import httpx

from drntu.models import RepositoryError
from drntu.oai.client import BASE, OAIClient
from drntu.rest.client import API, RepositoryClient
from shared.public_http import PublicHTTPClient

URL = "https://example.org/feed"


class CacheRaceTests(unittest.TestCase):
    def _run_overlapping_reads(self, invalidate_refresh):
        entered, release = Event(), Event()
        now = datetime.now(timezone.utc)
        fetches = []

        def fetch(url):
            fetches.append(url)
            number = len(fetches)
            if number == 1:
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("The old response was not released")
                return b"old", now
            if number == 2:
                return b"fresh", now + timedelta(seconds=1)
            return b"replacement", now + timedelta(seconds=2)

        client = PublicHTTPClient(
            "test",
            ["example.org"],
            {"application/json"},
            transport=httpx.MockTransport(lambda request: None),
        )
        self.addCleanup(client.close)
        with (
            patch.object(client, "_fetch", side_effect=fetch),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            old = pool.submit(client.get, URL)
            try:
                self.assertTrue(entered.wait(timeout=5))
                if invalidate_refresh:
                    with self.assertRaises(ValueError):
                        with client.parsed_response(URL, refresh=True):
                            raise ValueError("malformed fresh response")
                else:
                    self.assertEqual(client.get(URL, refresh=True)[0], b"fresh")
            finally:
                release.set()
            self.assertEqual(old.result(timeout=5)[0], b"old")
            actual, metadata = client.get(URL)
        self.assertEqual(actual, b"replacement" if invalidate_refresh else b"fresh")
        self.assertEqual(len(fetches), 3 if invalidate_refresh else 2)
        self.assertEqual(metadata["cached"], not invalidate_refresh)

    def test_slow_old_request_does_not_replace_refresh(self):
        self._run_overlapping_reads(False)

    def test_slow_old_request_does_not_revive_invalidated_refresh(self):
        self._run_overlapping_reads(True)

    def test_invalid_old_repository_json_cannot_evict_new_refresh(self):
        client = RepositoryClient()
        self.addCleanup(client.http.close)
        url = API + "/example"
        now = datetime.now(timezone.utc)
        with patch.object(
            client.http,
            "_fetch",
            side_effect=[(b"old", now), (b"fresh", now + timedelta(seconds=1))],
        ) as fetch:

            def parse(body):
                self.assertEqual(body, b"old")
                client.http.get(url, refresh=True)
                raise ValueError("invalid JSON")

            with (
                patch("drntu.rest.client.json.loads", side_effect=parse),
                self.assertRaises(RepositoryError),
            ):
                client.get("/example")
            self.assertEqual(client.http.get(url)[0], b"fresh")
            self.assertEqual(fetch.call_count, 2)

    def test_invalid_old_oai_envelope_cannot_evict_new_refresh(self):
        client = OAIClient()
        self.addCleanup(client.close)
        url = BASE + "?verb=Identify"
        now = datetime.now(timezone.utc)
        with patch.object(
            client,
            "_fetch",
            side_effect=[(b"old", now), (b"fresh", now + timedelta(seconds=1))],
        ) as fetch:

            def parse(body, verb):
                self.assertEqual(body, b"old")
                client.get(url, refresh=True)
                raise RepositoryError("invalid OAI envelope")

            with (
                patch("drntu.oai.client.envelope", side_effect=parse),
                self.assertRaises(RepositoryError),
            ):
                client.request("Identify")
            self.assertEqual(client.get(url)[0], b"fresh")
            self.assertEqual(fetch.call_count, 2)

from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from library import parser
from library.client import LibraryClient
from library.models import LibraryError
from .fixtures import LOCAL, fake_get


class LibraryTests(unittest.TestCase):
    def test_availability_keeps_holdings_and_institutional_access_separate(self):
        client = LibraryClient()
        with patch.object(client.http, "get", side_effect=fake_get):
            result = client.get_availability("almaExample001")
        self.assertEqual(result.holdings[0].call_number, "QA1.EX")
        self.assertEqual(result.holdings[0].availability, "available")
        self.assertEqual(result.electronic_services, [])
        electronic = deepcopy(LOCAL)
        electronic["delivery"].update(holding=[], deliveryCategory=["Alma-E"])
        with patch.object(
            client.http,
            "get",
            side_effect=[
                (json.dumps(electronic).encode(), fake_get("https://example.org/pnxs?q=x")[1]),
                fake_get("https://example.org/edelivery/x"),
            ],
        ):
            result = client.get_availability("almaExample001")
        self.assertEqual(result.holdings, [])
        self.assertEqual(result.electronic_services[0].notes, "Current students only.")
        self.assertTrue(
            result.electronic_services[0].url.startswith("https://ntu-sp.primo.exlibrisgroup.com/")
        )

    def test_record_normalization_keeps_source_signals_separate(self):
        result = parser.record(LOCAL)
        self.assertEqual(result.record_id, "almaExample001")
        self.assertEqual(result.title, "Example algorithms")
        self.assertEqual(result.authors, ["Example, Author"])
        self.assertTrue(result.open_access)
        self.assertEqual(result.availability_label, "Not available")
        self.assertEqual(result.availability_codes, ["not_restricted"])
        self.assertEqual(result.subjects, ["Algorithms"])
        self.assertIn("First paragraph.\n\nSecond paragraph.", result.descriptions[0])
        self.assertEqual(result.identifiers["isbn"], ["9780000000001"])
        self.assertEqual(result.links[0].url, "https://example.org/book")

    def test_search_pagination_and_query_parameters(self):
        client = LibraryClient()
        with patch.object(client.http, "get", side_effect=fake_get) as get:
            first = client.search("algorithms", limit=1, resource_type="books")
            second = client.search("algorithms", limit=1, offset=first.next_offset)
            self.assertEqual(first.total_count, 2)
            self.assertEqual(second.records[0].context, "PC")
            self.assertIsNone(second.next_offset)
            self.assertEqual(client.search("no matches").records, [])
        params = parse_qs(urlsplit(get.call_args_list[0].args[0]).query)
        self.assertEqual(params["qInclude"], ["facet_rtype,exact,books"])
        self.assertEqual(params["vid"], ["65NTU_INST:65NTU_INST"])

    def test_canonical_record_lookup_and_central_adaptor(self):
        client = LibraryClient()
        with patch.object(client.http, "get", side_effect=fake_get):
            self.assertEqual(client.get_record("almaExample001").record.record_id, "almaExample001")
            self.assertEqual(client.get_record("cdi_example_article", "PC").record.context, "PC")
            with self.assertRaisesRegex(LibraryError, "could not find"):
                client.get_record("missing")

    def test_invalid_queries_fail_before_network_access(self):
        client = LibraryClient()
        with patch.object(client.http, "get") as get:
            for query in [" ", "term;other", "term\nother", "term\0other", "term\tother"]:
                with self.assertRaises(LibraryError):
                    client.search(query)
            get.assert_not_called()

    def test_missing_optional_fields_remain_unknown(self):
        value = deepcopy(LOCAL)
        value.pop("delivery")
        value["pnx"]["addata"].pop("openaccess")
        summary = parser.summary(value)
        self.assertIsNone(summary.open_access)
        self.assertIsNone(summary.availability_codes)
        self.assertIsNone(summary.availability_label)

    def test_mismatched_paging_and_record_ids_fail(self):
        client = LibraryClient()
        snapshot = fake_get("https://example.org/pnxs?q=x")[1]
        data = {"info": {"total": 2, "first": 1, "last": 1}, "docs": [LOCAL]}
        with patch.object(client.http, "get", return_value=(json.dumps(data).encode(), snapshot)):
            with self.assertRaises(LibraryError):
                client.search("algorithms", offset=1)
        with patch.object(client.http, "get", return_value=(json.dumps(LOCAL).encode(), snapshot)):
            with self.assertRaises(LibraryError):
                client.get_record("different")

    def test_invalid_access_flags_and_delivery_links_are_rejected(self):
        value = deepcopy(LOCAL)
        value["pnx"]["addata"]["openaccess"] = ["maybe"]
        with self.assertRaises(LibraryError):
            parser.summary(value)
        value = deepcopy(LOCAL)
        value["delivery"]["link"] = [{"linkURL": "javascript:alert(1)", "linkType": "viewit"}]
        with self.assertRaises(LibraryError):
            parser.record(value)

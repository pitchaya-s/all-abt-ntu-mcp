from copy import deepcopy
import unittest
from unittest.mock import patch

from mcp.server.mcpserver.exceptions import ToolError

from drntu import datasets, mcp_server, parser, repository
from drntu.models import RepositoryError, SearchFilter
from .fixtures import CONTAINER_ID, DOI, ITEM, ITEM_ID, VERSION, fake_get, hal


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client = mcp_server.client
        self.mock = patch.object(self.client, "get", side_effect=fake_get)
        self.get = self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_publication_default_filters_scope_and_search_pagination(self):
        results = repository.search(self.client, " learning ", scope_id=CONTAINER_ID,
                                    filters=[SearchFilter(field="dateIssued", value="[2020 TO 2026]")], page_size=1)
        self.assertEqual(results.query, "learning")
        self.assertEqual(results.pagination.next_page, 1)
        self.assertEqual(results.items[0].authors, ["Example, Author"])
        self.assertEqual(results.items[0].rights, ["restricted"])
        params = self.get.call_args.args[1]
        self.assertEqual(params["f.entityType"], ["Publication,equals"])
        self.assertEqual(params["f.dateIssued"], ["[2020 TO 2026],equals"])
        self.assertEqual(params["scope"], CONTAINER_ID)
        self.assertEqual(params["dsoType"], "item")
        self.assertEqual(len(repository.search(self.client, "no matches").items), 0)

    def test_all_entities_do_not_force_publication_filter(self):
        repository.search(self.client, "learning", entity_type="all")
        self.assertNotIn("f.entityType", self.get.call_args.args[1])

    def test_item_metadata_keeps_abstract_language_and_unknown_fields(self):
        item = repository.get_item(self.client, ITEM_ID)
        self.assertNotIn("dc.title", item.metadata)
        self.assertEqual(item.metadata["dc.description.abstract"][0].language, "en")
        self.assertFalse(item.withdrawn)
        self.assertEqual(item.metadata["datacite.rights"][0].value, "restricted")
        value = deepcopy(ITEM)
        value["metadata"]["dc.title"][0]["language"] = "en"
        value["metadata"]["example.custom"] = [{"value": "unknown but retained", "language": None}]
        snapshot = fake_get("/core/items/" + ITEM_ID)[1]
        self.get.return_value = (value, snapshot)
        self.get.side_effect = None
        result = repository.get_item(self.client, ITEM_ID)
        self.assertIn("dc.title", result.metadata)
        self.assertIn("example.custom", result.metadata)

    def test_browse_nested_collections_and_unknown_counts(self):
        result = repository.browse(self.client, "collections", CONTAINER_ID)
        self.assertIsNone(result.containers[0].archived_items_count)
        self.assertEqual(self.get.call_args.args[0], f"/core/communities/{CONTAINER_ID}/collections")
        communities = repository.browse(self.client)
        self.assertEqual(communities.kind, "communities")
        self.assertEqual(communities.containers[0].url, f"https://dr.ntu.edu.sg/communities/{CONTAINER_ID}")
        self.assertEqual(len(repository.browse(self.client, "communities", CONTAINER_ID).containers), 1)

    def test_facets_return_the_actual_date_filter_instead_of_display_label(self):
        self.assertEqual(repository.get_facets(self.client).definitions[0].name, "dateIssued")
        result = repository.get_facets(self.client, "dateIssued", "learning")
        value = result.values[0]
        self.assertEqual(value.label, "2020 - 2026")
        self.assertEqual(value.filter.value, "[2020 TO 2026]")
        self.assertEqual(value.filter.operator, "equals")
        self.assertIsNone(result.pagination.total_elements)

    def test_bundles_and_files_preserve_restrictions_without_claiming_access(self):
        bundles = repository.list_bundles(self.client, ITEM_ID)
        self.assertEqual(bundles.bundles[0].name, "ORIGINAL")
        files = repository.list_files(self.client, bundles.bundles[0].bundle_id)
        file = files.files[0]
        self.assertEqual(file.rights, ["restricted"])
        self.assertEqual(file.size_bytes, 123)
        self.assertEqual(file.checksum.algorithm, "MD5")
        self.assertTrue(file.content_url.endswith("/content"))
        self.assertNotIn("downloadable", file.model_dump())

    def test_blank_search_and_filter_values_are_rejected(self):
        for fn, args in [(repository.search, (self.client, " ")),
                         (repository.search, (self.client, "learning", None, "Publication", [SearchFilter(field="subject", value=" ")]))]:
            with self.assertRaises(RepositoryError):
                fn(*args)
        self.get.assert_not_called()

    def test_missing_or_mismatched_records_and_pages_fail(self):
        for data in [{}, {**ITEM, "uuid": CONTAINER_ID}, {**ITEM, "type": "collection"}]:
            self.get.side_effect = None
            self.get.return_value = (data, fake_get("/core/items/" + ITEM_ID)[1])
            with self.assertRaises(ToolError):
                mcp_server.get_item(ITEM_ID)
        with self.assertRaises(RepositoryError):
            parser.pagination(hal("items", [ITEM]), 0, 0, 20)
        with self.assertRaises(RepositoryError):
            parser.pagination(hal("items", [ITEM]), 1, 1, 20)
        with self.assertRaises(RepositoryError):
            parser.embedded({"page": {"totalElements": 1}}, "items")
        self.assertEqual(parser.embedded({"page": {"totalElements": 0}}, "items"), [])


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.client = mcp_server.client

    def test_latest_version_citation_fields_and_file_pagination(self):
        with patch.object(self.client, "get", side_effect=fake_get):
            first = datasets.get_dataset(self.client, DOI, limit=1)
            second = datasets.get_dataset(self.client, DOI, version="1.0", limit=1, offset=first.next_offset)
        self.assertEqual(first.title, "Synthetic dataset")
        self.assertEqual(first.authors, ["Example, Author"])
        self.assertEqual(first.total_files, 2)
        self.assertTrue(first.files[0].restricted)
        self.assertIsNone(second.files[0].restricted)
        self.assertIsNone(second.next_offset)
        self.assertNotEqual(first.files[0].file_id, second.files[0].file_id)

    def test_draft_wrong_identifier_and_wrong_version_are_rejected(self):
        for patch_value in [{"versionState": "DRAFT"}, {"datasetPersistentId": "doi:10.21979/WRONG"}, {"versionNumber": 2}]:
            data = {**deepcopy(VERSION), **patch_value}
            with patch.object(self.client, "get", return_value=({"status": "OK", "data": data}, fake_get("/", dataset=True)[1])):
                with self.assertRaises(RepositoryError):
                    datasets.get_dataset(self.client, DOI, "1.0")

    def test_missing_optional_citation_fields_remain_unknown(self):
        data = deepcopy(VERSION)
        data["metadataBlocks"]["citation"]["fields"] = []
        data.pop("license")
        with patch.object(self.client, "get", return_value=({"status": "OK", "data": data}, fake_get("/", dataset=True)[1])):
            result = datasets.get_dataset(self.client, DOI, "1.0")
        self.assertIsNone(result.title)
        self.assertIsNone(result.license_name)
        self.assertEqual(result.authors, [])

from email.message import Message
from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from mcp.server.mcpserver.exceptions import ToolError

from drntu import mcp_server, oai
from drntu.oai import parser
from drntu.models import RepositoryError
from .oai_fixtures import DELETED, IDENTIFIER, STAMP, TOKEN, envelope, fake_get, record


class OAITests(unittest.TestCase):
    def setUp(self):
        self.client = oai.OAIClient()
        self.get = patch.object(self.client, 'get', side_effect=fake_get).start()
        self.addCleanup(patch.stopall)

    def test_discovery_formats_and_extension_xml(self):
        info = oai.identify(self.client)
        self.assertEqual(info.repository_name, 'Synthetic NTU repository')
        self.assertEqual(info.deleted_record, 'transient')
        self.assertIn('urn:example:repository', info.descriptions_xml[0])
        formats = oai.formats(self.client, IDENTIFIER)
        self.assertEqual([value.metadata_prefix for value in formats.formats], ['oai_dc', 'qdc'])
        self.assertEqual(parse_qs(urlsplit(self.get.call_args.args[0]).query)['identifier'], [IDENTIFIER])

    def test_set_slices_then_opaque_provider_continuation(self):
        first = oai.sets(self.client, limit=2)
        self.assertEqual(len(first.sets), 2)
        self.assertEqual(first.pagination.next_offset, 2)
        self.assertIsNone(first.pagination.resumption_token)
        self.assertEqual(first.pagination.complete_list_size, 4)
        self.assertIn('urn:example:set', first.sets[0].descriptions_xml[0])
        last = oai.sets(self.client, limit=2, offset=2)
        self.assertEqual(last.pagination.resumption_token, TOKEN)
        self.assertIsNone(last.pagination.next_offset)
        final = oai.sets(self.client, resumption_token=TOKEN)
        self.assertEqual(final.sets[0].set_spec, 'col_example4')
        self.assertIsNone(final.pagination.resumption_token)
        self.assertEqual(parse_qs(urlsplit(self.get.call_args.args[0]).query), {'verb': ['ListSets'], 'resumptionToken': [TOKEN]})
        with self.assertRaisesRegex(RepositoryError, 'offset'):
            oai.sets(self.client, offset=10)

    def test_dc_repetitions_languages_deleted_headers_and_provenance(self):
        result = oai.records(self.client, from_date='2026-01-01', until_date='2026-01-02', set_spec='col_example')
        first, deleted = result.records[:2]
        self.assertEqual(first.metadata['dc.title'][0].value, 'Synthetic research & methods')
        self.assertEqual(first.metadata['dc.title'][0].language, 'en')
        self.assertEqual(len(first.metadata['dc.creator']), 2)
        self.assertEqual(first.metadata['dc.rights'][0].value, 'restricted')
        self.assertIn('urn:example:provenance', first.about_xml[0])
        self.assertTrue(deleted.deleted)
        self.assertIsNone(deleted.metadata)
        self.assertEqual(deleted.set_specs, ['col_example'])
        query = parse_qs(urlsplit(self.get.call_args.args[0]).query)
        self.assertEqual(query['from'], ['2026-01-01'])
        self.assertEqual(query['metadataPrefix'], ['oai_dc'])
        self.assertEqual(query['set'], ['col_example'])
        self.assertEqual(oai.get_record(self.client, DELETED).record.identifier, DELETED)

    def test_identifier_mode_and_non_dc_formats_preserve_structure(self):
        result = oai.records(self.client, headers_only=True)
        self.assertTrue(result.headers_only)
        self.assertTrue(all(value.metadata is None and value.metadata_xml is None for value in result.records))
        self.assertEqual(parse_qs(urlsplit(self.get.call_args.args[0]).query)['verb'], ['ListIdentifiers'])
        detailed = oai.get_record(self.client, IDENTIFIER, 'qdc').record
        self.assertIsNone(detailed.metadata)
        self.assertIn('code="retained"', detailed.metadata_xml)
        self.assertIn('nested', detailed.metadata_xml)

    def test_record_slicing_and_token_exclusivity(self):
        first = oai.records(self.client, limit=1)
        self.assertEqual(first.pagination.next_offset, 1)
        self.assertIsNone(first.pagination.resumption_token)
        last = oai.records(self.client, limit=1, offset=2)
        self.assertEqual(last.pagination.resumption_token, TOKEN)
        next_page = oai.records(self.client, resumption_token=TOKEN)
        self.assertIsNone(next_page.pagination.resumption_token)
        query = parse_qs(urlsplit(self.get.call_args.args[0]).query)
        self.assertEqual(query, {'verb': ['ListRecords'], 'resumptionToken': [TOKEN]})
        for argument in ('metadata_prefix', 'set_spec', 'from_date', 'until_date'):
            with self.subTest(argument=argument), self.assertRaisesRegex(RepositoryError, 'used alone'):
                oai.records(self.client, resumption_token=TOKEN, **{argument: 'x'})

    def test_valid_utc_bounds_and_invalid_dates_fail_before_http(self):
        for bounds in [dict(from_date='2026-02-30'), dict(until_date='2026-01-01T25:00:00Z'),
                       dict(from_date='2026-01-01T12:00:00+08:00'),
                       dict(from_date='2026-01-02', until_date='2026-01-01'),
                       dict(from_date='2026-01-01', until_date='2026-01-01T01:00:00Z')]:
            with self.subTest(bounds=bounds), self.assertRaises(RepositoryError):
                oai.records(self.client, **bounds)
        self.get.assert_not_called()
        oai.records(self.client, from_date='2026-01-01T00:00:00Z', until_date='2026-01-02T00:00:00Z')

    def test_empty_matches_are_successful_but_protocol_errors_are_actionable(self):
        result = oai.records(self.client, from_date='1900-01-01')
        self.assertEqual(result.records, [])
        self.assertEqual(result.pagination.page_count, 0)
        self.assertIsNone(result.pagination.resumption_token)
        for code, message in [('badResumptionToken', 'expired'), ('cannotDisseminateFormat', 'format'),
                              ('idDoesNotExist', 'identifier'), ('noSetHierarchy', 'sets'),
                              ('badArgument', 'arguments'), ('noMetadataFormats', 'formats')]:
            with self.subTest(code=code), patch.object(self.client, 'get', return_value=(envelope('ListRecords', error=code), {})):
                with self.assertRaisesRegex(RepositoryError, message):
                    oai.records(self.client)

    def test_wrong_identifier_active_record_shape_and_malformed_pages_fail(self):
        snapshot = fake_get(oai.BASE + '?verb=GetRecord&identifier=' + IDENTIFIER + '&metadataPrefix=oai_dc')[1]
        wrong = record().replace(IDENTIFIER, 'oai:dr.ntu.edu.sg:10356/WRONG')
        for body in [envelope('GetRecord', wrong), envelope('GetRecord', '<record/>'),
                     envelope('GetRecord', record().replace('<metadata>', '<header/><metadata>')),
                     envelope('GetRecord', record().replace('</header>', '<setSpec/> </header>')),
                     envelope('GetRecord', record().replace('<metadata>', '<notMetadata>').replace('</metadata>', '</notMetadata>'))]:
            with patch.object(self.client, 'get', return_value=(body, snapshot)), self.assertRaises(RepositoryError):
                oai.get_record(self.client, IDENTIFIER)
        for body in [b'<html>Maintenance</html>', b'<broken', envelope('Identify', '').replace(b'Identify', b'Other'),
                     envelope('ListRecords', ''), envelope('ListRecords', record()).replace(STAMP.encode(), b'not-a-date', 1),
                     envelope('ListRecords', record() + '<resumptionToken cursor="-1"/>')]:
            with patch.object(self.client, 'get', return_value=(body, snapshot)), self.assertRaises((RepositoryError, ValueError)):
                oai.records(self.client)

    def test_dtd_entities_and_excessive_depth_are_rejected(self):
        dtd = '<!DOCTYPE OAI-PMH [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        for encoding in ('utf-8', 'utf-16'):
            body = envelope('ListRecords', record()).decode().split('?>', 1)[1]
            with self.assertRaisesRegex(RepositoryError, 'DTD'):
                parser.envelope((dtd + body).encode(encoding), 'ListRecords')
        deep = '<x>' * 70 + '</x>' * 70
        with self.assertRaisesRegex(RepositoryError, 'nesting'):
            parser.envelope(envelope('ListRecords', deep), 'ListRecords')


class OAIHTTPTests(unittest.TestCase):
    def response(self, request, content_type='text/xml', body=None, **kwargs):
        response = BytesIO(body if body is not None else fake_get(request.full_url)[0])
        response.headers = Message()
        response.headers['Content-Type'] = content_type
        response.geturl = lambda: request.full_url
        return response

    def test_cache_refresh_no_credentials_and_protocol_errors_not_cached(self):
        client = oai.OAIClient()
        with patch('shared.public_http.time.sleep'), patch.object(client.opener, 'open', side_effect=self.response) as fetch:
            first = oai.identify(client)
            self.assertFalse(first.cached)
            self.assertTrue(oai.identify(client).cached)
            self.assertEqual(fetch.call_count, 1)
            oai.identify(client, refresh=True)
            self.assertEqual(fetch.call_count, 2)
            request = fetch.call_args.args[0]
            self.assertNotIn('Cookie', request.headers)
            self.assertNotIn('Authorization', request.headers)
            for _ in range(2):
                with self.assertRaisesRegex(RepositoryError, 'badResumptionToken'):
                    oai.records(client, resumption_token='expired')
            self.assertEqual(fetch.call_count, 4)
        with patch('shared.public_http.time.sleep'), patch.object(client.opener, 'open', side_effect=lambda request, **kwargs: self.response(request, body=b'<html/>')):
            with self.assertRaises(RepositoryError):
                oai.identify(client, refresh=True)
            self.assertFalse(client._cache)

    def test_access_denials_network_failures_and_html_stop_retrieval(self):
        for error, calls in [(HTTPError(oai.BASE, 403, 'Forbidden', Message(), None), 1), (URLError('private-detail'), 2)]:
            client = oai.OAIClient()
            with patch('shared.public_http.time.sleep'), patch.object(client.opener, 'open', side_effect=error) as fetch:
                with self.assertRaises(RepositoryError) as caught:
                    oai.identify(client)
                self.assertEqual(fetch.call_count, calls)
                self.assertNotIn('private-detail', str(caught.exception))
        client = oai.OAIClient()
        with patch('shared.public_http.time.sleep'), patch.object(client.opener, 'open', side_effect=lambda request, **kwargs: self.response(request, content_type='text/html')):
            with self.assertRaisesRegex(RepositoryError, 'content type'):
                oai.identify(client)

    def test_tool_wrapper_sanitizes_unexpected_data(self):
        with patch.object(mcp_server.oai_client, 'get', return_value=(b'not XML', {})):
            with self.assertRaisesRegex(ToolError, 'unexpected OAI'):
                mcp_server.oai_identify()

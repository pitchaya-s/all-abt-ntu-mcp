from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ntulearn_mcp.services import files
from ntulearn_mcp.ntu_client.client import LearnClient
from ntulearn_mcp.parser.documents import extract
from ntulearn_mcp.models import Download, LearnError
from .fixtures import COURSE, FixtureSession, NOW, PREFIX, RESPONSES


class FileTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        self.client = LearnClient(self.session)

    def test_inline_text_and_pdf_extraction_bounds_and_office(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'example.txt'
            path.write_text('Example text')
            result = extract(path, max_chars=7)
            self.assertEqual(result['text'], 'Example')
            self.assertTrue(result['truncated'])
            pdf = Path(directory) / 'example.pdf'
            writer = PdfWriter()
            page = writer.add_blank_page(200, 200)
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf 10 100 Td (Example PDF) Tj ET')
            page[NameObject('/Contents')] = stream
            writer.add_blank_page(200, 200)
            writer.write(pdf)
            result = extract(pdf, max_pages=1)
            self.assertIn('Example PDF', result['text'])
            self.assertEqual(result['pages_read'], 1)
            self.assertTrue(result['truncated'])
            for suffix, name, xml in (
                ('docx', 'word/document.xml', '<w:document xmlns:w="urn:test"><w:t>Example doc</w:t></w:document>'),
                ('pptx', 'ppt/slides/slide1.xml', '<a:slide xmlns:a="urn:test"><a:t>Example slide</a:t></a:slide>'),
                ('xlsx', 'xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><row><c><v>42</v></c></row></worksheet>'),
            ):
                office = Path(directory) / ('example.' + suffix)
                with ZipFile(office, 'w') as archive:
                    archive.writestr(name, xml)
                self.assertTrue(extract(office)['text'])
            with self.assertRaises(LearnError):
                extract(Path(directory) / 'unknown.zip')
            path.write_bytes(b'\x00not text')
            with self.assertRaises(LearnError):
                extract(path)

    def test_inline_read_uses_attachment_metadata_and_cleans_temporary_files(self):
        path = f'{PREFIX}/courses/{COURSE}/contents/_202_1/attachments'
        seen = []
        def download(course, content_id, attachment, destination, **kwargs):
            seen.append(Path(destination))
            Path(destination).write_text('Inline example')
            return Download(path=destination, bytes_written=14, downloaded_at=NOW)
        with patch.dict(RESPONSES, {path: {'results': [{'id': '_500_1', 'fileName': '../../example.txt'}]}}), patch.object(self.client, 'download_file', side_effect=download):
            result = files.read_file_content(self.client, COURSE, '_202_1', '_500_1')
        self.assertEqual(result.text, 'Inline example')
        self.assertFalse(seen[0].exists())

    def test_course_download_preserves_folders_skips_existing_and_bounds_files(self):
        def download(course, content_id, attachment, destination, **kwargs):
            Path(destination).write_bytes(b'example')
            return Download(path=destination, bytes_written=7, downloaded_at=NOW)
        with tempfile.TemporaryDirectory() as directory, patch.object(self.client, 'download_file', side_effect=download) as get:
            result = files.download_course(self.client, COURSE, directory)
            self.assertTrue(result.complete)
            self.assertEqual(result.bytes_written, 7)
            self.assertTrue(Path(result.files[0].path).is_relative_to(Path(directory)))
            self.assertIn('Week 1', result.files[0].path)
            result = files.download_course(self.client, COURSE, directory)
            self.assertEqual(result.files[0].status, 'skipped_existing')
            self.assertEqual(get.call_count, 1)
            other = Path(directory) / 'bounded'
            result = files.download_course(self.client, COURSE, str(other), max_requests=3)
            self.assertFalse(result.complete)
            self.assertLessEqual(result.requests_used, 3)
            streamed = files.download_course(self.client, COURSE, str(Path(directory) / 'streamed'), max_requests=8)
            self.assertEqual(streamed.bytes_written, 7)
            self.assertFalse(streamed.complete)
            self.assertLessEqual(streamed.requests_used, 8)

    def test_download_rejects_symlink_directory_and_reports_failed_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'link'
            link.symlink_to(Path(directory), target_is_directory=True)
            with self.assertRaisesRegex(LearnError, 'symbolic'):
                files.download_course(self.client, COURSE, str(link))
            with patch.object(self.client, 'download_file', side_effect=LearnError('Download denied (HTTP 403).')):
                result = files.download_course(self.client, COURSE, directory)
            self.assertFalse(result.complete)
            self.assertEqual(result.files[0].status, 'failed')
            self.assertEqual(result.bytes_written, 0)

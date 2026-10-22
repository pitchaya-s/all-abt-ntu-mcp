"""Extract text in a short-lived worker with time and memory limits."""

import json
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile
from xml.etree import ElementTree

from ..models import LearnError


TEXT_EXTENSIONS = {'.txt', '.md', '.csv', '.tsv', '.xml', '.py', '.java', '.c', '.cpp', '.h', '.r', '.sql', '.log', '.tex'}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {'.pdf', '.docx', '.pptx', '.xlsx'}


def _extract(path, max_chars, max_pages):
    extension = path.suffix.lower()
    pages_read = total_pages = None
    truncated = False
    if extension == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('Encrypted documents are not supported.')
        total_pages = len(reader.pages)
        parts = []
        size = 0
        pages_read = 0
        for page in reader.pages[:max_pages]:
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 10_000_000:
                raise ValueError('PDF page is too large to extract safely.')
            part = page.extract_text() or ''
            parts.append(part)
            size += len(part) + 1
            pages_read += 1
            if size > max_chars:
                truncated = True
                break
        value = '\n'.join(parts)
        truncated = truncated or pages_read < total_pages
    elif extension in {'.docx', '.pptx', '.xlsx'}:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 40_000_000:
                raise ValueError('Office document exceeds the extraction limit.')
            def order(entry):
                return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', entry.filename)]
            selected = [entry for entry in sorted(entries, key=order) if (
                entry.filename == 'word/document.xml' or
                entry.filename.startswith(('ppt/slides/slide', 'ppt/notesSlides/notesSlide', 'xl/sharedStrings', 'xl/worksheets/sheet'))
                and entry.filename.endswith('.xml'))]
            shared = []
            parts = []
            for entry in selected:
                raw = archive.read(entry)
                if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
                    raise ValueError('Office document contains unsupported XML declarations.')
                root = ElementTree.fromstring(raw)
                if entry.filename.startswith('xl/sharedStrings'):
                    shared = [''.join(node.itertext()) for node in root]
                    continue
                if entry.filename.startswith('xl/worksheets/'):
                    for row in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                        cells = []
                        for cell in row:
                            value = ''.join(cell.itertext())
                            if cell.get('t') == 's':
                                value = shared[int(value)]
                            cells.append(value)
                        parts.append('\t'.join(cells))
                else:
                    parts.extend(node.text or '' for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 't')
            value = '\n'.join(parts)
    else:
        raw = path.read_bytes()
        if b'\0' in raw and not raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            raise ValueError('The attachment is not a supported text document.')
        value = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    return dict(text=value[:max_chars], truncated=truncated or len(value) > max_chars, pages_read=pages_read, total_pages=total_pages)


def extract(path, max_chars=20000, max_pages=20):
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise LearnError('Unsupported inline format. Use PDF, DOCX, PPTX, XLSX, or a UTF-8/UTF-16 text file; otherwise use ntulearn_download_file.')
    if type(max_chars) is not int or not 1 <= max_chars <= 100000 or type(max_pages) is not int or not 1 <= max_pages <= 50:
        raise LearnError('max_chars must be 1–100000 and max_pages must be 1–50.')
    try:
        result = subprocess.run([sys.executable, '-m', 'ntulearn_mcp.parser.documents', str(path), str(max_chars), str(max_pages)],
                                capture_output=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise LearnError('The document could not be extracted within the format, memory, or 30-second time limit. Download it to read locally.') from None


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512_000_000, 512_000_000))
    except ImportError:
        pass
    try:
        print(json.dumps(_extract(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))))
    except Exception:
        sys.exit(1)

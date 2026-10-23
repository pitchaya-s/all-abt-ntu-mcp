"""Inline document reads and bounded course downloads without overwrites."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory

from ..client.client import identifier, model
from .content import bounds, walk
from ..parser.documents import SUPPORTED_EXTENSIONS, extract
from ..models import CourseDownload, CourseDownloadFile, FileContent
from ..models import LearnError
from .scan import LimitReached, Scan, pages


def read_file_content(client, course_id, content_id, attachment_id, max_chars=20000, max_pages=20):
    course_id, content_id, attachment_id = map(identifier, (course_id, content_id, attachment_id))
    if type(max_chars) is not int or not 1 <= max_chars <= 100000 or type(max_pages) is not int or not 1 <= max_pages <= 50:
        raise LearnError('max_chars must be 1–100000 and max_pages must be 1–50.')
    scan = Scan(20)
    attachment = next((item for item in pages(scan, client.get_content_attachments, 'attachments', course_id, content_id)
                       if item.id == attachment_id), None)
    if attachment is None:
        raise LearnError('Attachment not found on this content item.')
    extension = Path(attachment.file_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise LearnError('Unsupported inline file format; use ntulearn_download_file for this attachment.')
    with TemporaryDirectory(prefix='ntulearn-read-') as directory:
        path = Path(directory) / ('attachment' + extension)
        download = client.download_file(course_id, content_id, attachment_id, str(path))
        result = extract(path, max_chars, max_pages)
    return model(FileContent, course_id=course_id, content_id=content_id, attachment_id=attachment_id,
                 file_name=attachment.file_name, retrieved_at=download.downloaded_at, **result)


def _component(value):
    return re.sub(r'[^\w. -]', '_', value).strip(' .')[:70] or 'item'


def _directory(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise LearnError('Download directories must not contain symbolic links.')
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise LearnError('Choose a directory for course downloads.')


def download_course(client, course_id, destination, max_depth=5, max_nodes=1000, max_files=100,
                    max_total_mb=200, max_requests=200, refresh=False):
    course_id = identifier(course_id)
    bounds(max_depth, max_nodes)
    if type(max_files) is not int or not 1 <= max_files <= 500 or type(max_total_mb) is not int or not 1 <= max_total_mb <= 500:
        raise LearnError('max_files and max_total_mb must be between 1 and 500.')
    root = Path(destination).expanduser().absolute() / course_id
    try:
        _directory(root)
    except OSError:
        raise LearnError('Could not create the course download directory.') from None
    scan = Scan(max_requests)
    files, written = [], 0
    try:
        for node, breadcrumb in walk(client, scan, course_id, max_depth, max_nodes, refresh):
            if node.has_children:
                continue
            try:
                for attachment in pages(scan, client.get_content_attachments, 'attachments', course_id, node.id, refresh=refresh):
                    identifier(node.id)
                    identifier(attachment.id)
                    if len(files) >= max_files or written >= max_total_mb * 1_000_000:
                        raise LimitReached('Course file or batch byte limit reached; remaining files were not downloaded.')
                    directory = root.joinpath(*(_component(title) for title in breadcrumb[:-1]))
                    filename = f'{node.id}-{attachment.id}-{_component(attachment.file_name)}'
                    path = directory / filename
                    try:
                        _directory(directory)
                        if path.is_symlink():
                            raise LearnError('A download destination is a symbolic link.')
                        if path.exists():
                            if not path.is_file():
                                raise LearnError('A download destination is not a regular file.')
                            files.append(CourseDownloadFile(content_id=node.id, attachment_id=attachment.id,
                                                            path=str(path), status='skipped_existing'))
                            continue
                        result = scan.call(client.download_file, course_id, node.id, attachment.id, str(path), cost=5,
                                           max_bytes=min(20_000_000, max_total_mb * 1_000_000 - written))
                        written += result.bytes_written
                        files.append(CourseDownloadFile(content_id=node.id, attachment_id=attachment.id, path=str(path),
                                                        status='downloaded', bytes_written=result.bytes_written))
                    except OSError:
                        raise LearnError('Could not write a course attachment; check the destination permissions and disk space.') from None
                    except LearnError as error:
                        scan.issue('download', error, course_id, node.id)
                        files.append(CourseDownloadFile(content_id=node.id, attachment_id=attachment.id, path=str(path), status='failed'))
                        if isinstance(error, LimitReached):
                            raise
            except LearnError as error:
                scan.issue('attachments', error, course_id, node.id)
                if isinstance(error, LimitReached):
                    break
    except LearnError as error:
        scan.issue('download', error, course_id)
    return model(CourseDownload, course_id=course_id, destination=str(root), files=files, bytes_written=written, **scan.metadata())

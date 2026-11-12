"""Safe selection and reading of local upload files."""

import mimetypes
import os
from pathlib import Path
import stat

from shared.paths import config_dir
from ..models import OneStopError

MAX_BYTES = 20_000_000


def upload_directory() -> Path:
    configured = os.environ.get("NTU_ONESTOP_UPLOAD_DIR")
    directory = (
        config_dir() / "onestop-uploads"
        if configured is None
        else Path(configured).expanduser()
    )
    if configured == "" or not directory.is_absolute():
        raise OneStopError(
            "Uploads are disabled. Set NTU_ONESTOP_UPLOAD_DIR to an approved absolute directory."
        )
    if configured is None:
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if directory.is_symlink():
                raise OneStopError(
                    "The approved upload directory cannot be a symbolic link."
                )
        except OSError:
            raise OneStopError(
                "The default upload directory could not be created."
            ) from None
    return directory


def upload_file(path, maximum=MAX_BYTES):
    if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
        raise OneStopError("Choose an explicit absolute path to the file to upload.")
    p = Path(path).expanduser()
    configured = upload_directory()
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise OneStopError(
            "Safe upload directory enforcement is unavailable on this platform; upload through the portal instead."
        )
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
        dirfd = os.open(configured, flags)
        try:
            parentfd = os.open(p.parent, flags)
            try:
                approved, requested = os.fstat(dirfd), os.fstat(parentfd)
                if (
                    not stat.S_ISDIR(approved.st_mode)
                    or not stat.S_ISDIR(requested.st_mode)
                    or (approved.st_dev, approved.st_ino)
                    != (requested.st_dev, requested.st_ino)
                ):
                    raise OneStopError(
                        "The upload must be a direct child of the approved upload directory."
                    )
            finally:
                os.close(parentfd)
            descriptor = os.open(
                p.name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                dir_fd=dirfd,
            )
        finally:
            os.close(dirfd)
        with os.fdopen(descriptor, "rb") as f:
            metadata = os.fstat(f.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
                raise OneStopError(
                    "The upload is not a regular file or exceeds the portal's size limit."
                )
            data = f.read(maximum + 1)
    except OSError:
        raise OneStopError("The selected upload file could not be read.") from None
    if len(data) > maximum:
        raise OneStopError("The upload exceeds the portal's size limit.")
    return p.name, mimetypes.guess_type(p.name)[0] or "application/octet-stream", data

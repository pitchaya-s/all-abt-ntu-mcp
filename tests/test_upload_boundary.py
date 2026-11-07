"""Validate the local directory boundary for One Stop uploads."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onestop.attachments import upload_directory, upload_file
from onestop.models import OneStopError


@unittest.skipUnless(
    hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd,
    "Safe directory-relative open is not available",
)
class UploadBoundaryTests(unittest.TestCase):
    def test_default_directory_is_dedicated_and_can_read_selected_file(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": root, "APPDATA": root}):
                os.environ.pop("NTU_ONESTOP_UPLOAD_DIR", None)
                directory = upload_directory()
                self.assertEqual(
                    directory, Path(root) / "all-abt-ntu" / "onestop-uploads"
                )
                self.assertTrue(directory.is_dir())
                (directory / "file.txt").write_text("permitted")
                self.assertEqual(
                    upload_file(str(directory / "file.txt"))[2], b"permitted"
                )
                secret = directory.parent / "tools.json"
                secret.write_text("not uploadable")
                with self.assertRaisesRegex(OneStopError, "approved"):
                    upload_file(str(secret))

    def test_default_directory_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / "all-abt-ntu"
            parent.mkdir()
            (parent / "onestop-uploads").symlink_to(root, target_is_directory=True)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": root, "APPDATA": root}):
                os.environ.pop("NTU_ONESTOP_UPLOAD_DIR", None)
                with self.assertRaisesRegex(OneStopError, "symbolic link"):
                    upload_directory()

    def test_replaced_approved_directory_cannot_redirect_upload(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            approved, moved, outside = (
                root / "approved",
                root / "moved",
                root / "outside",
            )
            approved.mkdir()
            outside.mkdir()
            (approved / "file.txt").write_text("permitted")
            (outside / "file.txt").write_text("outside-secret")
            original_open = os.open
            switched = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal switched
                if not switched and dir_fd is None and Path(path) == approved:
                    switched = True
                    approved.rename(moved)
                    approved.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch.dict(os.environ, {"NTU_ONESTOP_UPLOAD_DIR": str(approved)}):
                with patch(
                    "onestop.attachments.os.open", side_effect=swap_before_open
                ) as mocked_open:
                    with patch.object(os, "supports_dir_fd", {mocked_open}):
                        with self.assertRaises(OneStopError):
                            upload_file(str(approved / "file.txt"))
            self.assertTrue(switched)

    def test_directory_replacement_after_open_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            approved, moved, outside = (
                root / "approved",
                root / "moved",
                root / "outside",
            )
            approved.mkdir()
            outside.mkdir()
            (approved / "file.txt").write_text("permitted")
            (outside / "file.txt").write_text("outside-secret")
            original_open = os.open
            switched = False

            def swap_after_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal switched
                fd = original_open(path, flags, mode, dir_fd=dir_fd)
                if not switched and dir_fd is None and Path(path) == approved:
                    switched = True
                    approved.rename(moved)
                    outside.rename(approved)
                return fd

            with patch.dict(os.environ, {"NTU_ONESTOP_UPLOAD_DIR": str(approved)}):
                with patch(
                    "onestop.attachments.os.open", side_effect=swap_after_open
                ) as mocked_open:
                    with patch.object(os, "supports_dir_fd", {mocked_open}):
                        with self.assertRaisesRegex(OneStopError, "approved"):
                            upload_file(str(approved / "file.txt"))
            self.assertTrue(switched)

    def test_approved_directory_must_not_be_a_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            actual, link = root / "actual", root / "link"
            actual.mkdir()
            (actual / "file.txt").write_text("content")
            link.symlink_to(actual, target_is_directory=True)
            with patch.dict(os.environ, {"NTU_ONESTOP_UPLOAD_DIR": str(link)}):
                with self.assertRaises(OneStopError):
                    upload_file(str(link / "file.txt"))

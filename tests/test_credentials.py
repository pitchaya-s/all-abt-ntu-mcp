import json
import sys
import unittest
from unittest.mock import Mock, patch

from keyring.backends.chainer import ChainerBackend
from keyring.backends.null import Keyring as NullKeyring
from keyring.backends.SecretService import Keyring as SecretService
from mcp import Client

from shared.credentials import (
    ACCOUNT, SERVICE, CredentialError, _backend, credential_status,
    delete_credentials, read_credentials, save_credentials,
)
from ntulearn_mcp.ntu_client.session import Session
from ntulearn_mcp.models import LearnError
from ntu_stars_mcp.wish.models import NTUAuthError
from ntu_stars_mcp.wish.session import WishSessionManager
from tests.credential_fixtures import MemoryKeyring, stored_credentials


class KeyringTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryKeyring()
        self.patch = patch("shared.credentials._backend", return_value=self.backend)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_opt_in_save_update_and_delete(self):
        self.assertFalse(credential_status()["credentials_configured"])
        save_credentials("student001", "first-test-secret")
        first = read_credentials()
        first.require_login()
        self.assertEqual(first.email, "student001@e.ntu.edu.sg")
        self.assertEqual(set(self.backend.entries), {(SERVICE, ACCOUNT)})
        save_credentials("staff001@ntu.edu.sg", "updated-test-secret")
        updated = read_credentials()
        self.assertNotEqual(first.revision, updated.revision)
        self.assertEqual(updated.password, "updated-test-secret")
        self.assertEqual(updated.email, "staff001@ntu.edu.sg")
        delete_credentials()
        delete_credentials()
        self.assertEqual(self.backend.entries, {})
        with self.assertRaisesRegex(CredentialError, "auth save"):
            read_credentials().require_login()

    def test_invalid_inputs_and_corrupt_records_never_return_secrets(self):
        for user, password in [("", "secret"), ("student@other.invalid", "secret"), ("user\nname", "secret"), ("student001", "")]:
            with self.assertRaises(CredentialError):
                save_credentials(user, password)
        self.assertEqual(self.backend.entries, {})
        for raw in ("secret-not-json", "[]", json.dumps({"password": "test-secret"})):
            self.backend.set_password(SERVICE, ACCOUNT, raw)
            with self.assertRaises(CredentialError) as error:
                read_credentials()
            self.assertNotIn(raw, str(error.exception))
            self.assertNotIn("test-secret", json.dumps(credential_status()))
        delete_credentials()  # Corrupt entries can still be removed.

    def test_locked_keyring_and_unconfirmed_changes_fail_without_secret_details(self):
        with patch.object(self.backend, "get_password", side_effect=RuntimeError("secret-backend-detail")):
            status = credential_status()
            self.assertFalse(status["credentials_configured"])
            self.assertNotIn("secret-backend-detail", json.dumps(status))
        with patch.object(self.backend, "set_password"):
            with self.assertRaisesRegex(CredentialError, "did not confirm"):
                save_credentials("student001", "test-secret")
        save_credentials("student001", "test-secret")
        with patch.object(self.backend, "delete_password"):
            with self.assertRaisesRegex(CredentialError, "may still be stored"):
                delete_credentials()


class BackendSelectionTests(unittest.TestCase):
    def test_only_native_backend_selected_from_chain(self):
        native, unsafe = SecretService(), Mock()
        chain = ChainerBackend()
        with patch.object(sys, "platform", "linux"), patch.object(type(chain), "backends", [unsafe, native]), patch("shared.credentials.keyring.get_keyring", return_value=chain):
            self.assertIs(_backend(), native)
            unsafe.get_password.assert_not_called()

    def test_plaintext_null_custom_and_unavailable_backends_are_rejected(self):
        for backend in (NullKeyring(), MemoryKeyring(), Mock()):
            with patch("shared.credentials.keyring.get_keyring", return_value=backend):
                with self.assertRaisesRegex(CredentialError, "No plaintext fallback"):
                    _backend()
        with patch("shared.credentials.keyring.get_keyring", side_effect=RuntimeError("secret-detail")):
            with self.assertRaises(CredentialError) as error:
                _backend()
            self.assertNotIn("secret-detail", str(error.exception))


class SessionCredentialTests(unittest.TestCase):
    def test_deleting_credentials_blocks_both_services_even_with_cached_data(self):
        with stored_credentials():
            wish, learn = WishSessionManager(), Session()
            try:
                wish._credential_revision = learn._credential_revision = read_credentials().revision
                wish._authenticated = learn._verified = True
                wish._cache["private"] = learn._cache["private"] = "private-data"
                delete_credentials()
                with self.assertRaises(NTUAuthError), patch.object(wish, "_browser_page") as wish_browser:
                    wish.get_degree_audit()
                with self.assertRaises(LearnError), patch.object(learn, "_open") as learn_browser:
                    learn.get("/learn/api/public/v1/users/me")
                wish_browser.assert_not_called()
                learn_browser.assert_not_called()
                self.assertEqual(wish._cache, {})
                self.assertEqual(learn._cache, {})
                self.assertFalse(wish.status()["session_verified"])
                self.assertFalse(learn.status().session_verified)
            finally:
                wish.close()
                learn.close()


    def test_rotated_credentials_clear_previous_account_sessions(self):
        with stored_credentials():
            wish, learn = WishSessionManager(), Session()
            try:
                wish._check_credentials()
                learn.run(learn._check_credentials)
                wish._authenticated = learn._verified = True
                wish._cache["private"] = learn._cache["private"] = "private-data"
                save_credentials("other001", "replacement-secret")
                self.assertEqual(wish._check_credentials().username, "other001")
                self.assertEqual(learn.run(learn._check_credentials).email, "other001@e.ntu.edu.sg")
                self.assertFalse(wish._authenticated or learn._verified)
                self.assertFalse(wish._cache or learn._cache)
            finally:
                wish.close()
                learn.close()


class MCPCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_and_credential_errors_never_expose_keyring_secrets(self):
        from ntu_stars_mcp.mcp_server import mcp
        with stored_credentials("example001", "mcp-test-secret"):
            async with Client(mcp) as client:
                for name in ("stars_auth_status", "ntulearn_auth_status"):
                    result = await client.call_tool(name, {})
                    self.assertFalse(result.is_error)
                    self.assertTrue(result.structured_content["credentials_configured"])
                    self.assertEqual(result.structured_content["credential_storage"], "os_keyring")
                    self.assertNotIn("mcp-test-secret", result.model_dump_json())
                    self.assertNotIn("example001", result.model_dump_json())
                delete_credentials()
                for name in ("stars_get_degree_audit", "ntulearn_list_courses"):
                    result = await client.call_tool(name, {})
                    self.assertTrue(result.is_error)
                    self.assertIn("auth save", result.content[0].text)
                    self.assertNotIn("mcp-test-secret", result.model_dump_json())

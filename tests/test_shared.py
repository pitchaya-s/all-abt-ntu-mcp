import os
import unittest
from unittest.mock import patch

from shared.credentials import read_credentials
from ntulearn.client.session import Session
from stars.wish.session import WishSessionManager
from tests.credential_fixtures import MemoryKeyring, stored_credentials


class CredentialTests(unittest.TestCase):
    def test_network_username_derives_student_email(self):
        with stored_credentials("student001", "shared-test-secret"):
            credentials = read_credentials()
            self.assertEqual(credentials.username, "student001")
            self.assertEqual(credentials.email, "student001@e.ntu.edu.sg")
            self.assertEqual(credentials.password, "shared-test-secret")
            self.assertNotIn(credentials.password, repr(credentials))
            self.assertNotIn(credentials.username, repr(credentials))

    def test_full_email_preserves_domain_and_normalizes_wish_username(self):
        for email in ["student001@e.ntu.edu.sg", "staff001@ntu.edu.sg"]:
            with stored_credentials(email, "shared-test-secret"):
                credentials = read_credentials()
                self.assertEqual(credentials.username, email.split("@")[0])
                self.assertEqual(credentials.email, email)

    def test_plaintext_environment_is_never_a_credential_source(self):
        with patch.dict(os.environ, {"NTU_USERNAME": "student001", "NTU_PASSWORD": "ignored-secret"}), patch("shared.credentials._backend", return_value=MemoryKeyring()):
            credentials = read_credentials()
            self.assertFalse(credentials.username or credentials.email or credentials.password)

    def test_both_services_share_opt_in_keyring_without_login(self):
        with stored_credentials():
            wish, learn = WishSessionManager(), Session()
            try:
                self.assertTrue(wish.status()["credentials_configured"])
                self.assertTrue(learn.status().credentials_configured)
                self.assertFalse(wish.status()["session_verified"])
                self.assertFalse(learn.status().session_verified)
                self.assertNotIn("test-secret", str(wish.status()) + learn.status().model_dump_json())
            finally:
                wish.close()
                learn.close()

    def test_server_closes_all_sessions_even_if_one_cleanup_fails(self):
        from shared import server
        from stars.wish.session import wish_session
        with patch.object(server.mcp, "run"), patch.object(wish_session, "close", side_effect=RuntimeError("test cleanup")) as wish, patch.object(server.mcp_server.session, "close") as learn, patch.object(server.library_personal.session, "close") as library, patch.object(server.onestop.session, "close") as onestop, patch.object(server.careeraxis_personal.client.session, "close") as careeraxis:
            with self.assertRaisesRegex(RuntimeError, "test cleanup"):
                server.main()
            wish.assert_called_once()
            learn.assert_called_once()
            library.assert_called_once()
            onestop.assert_called_once()
            careeraxis.assert_called_once()

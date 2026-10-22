import os
import unittest
from unittest.mock import patch

from shared.credentials import read_credentials
from ntulearn_mcp.auth import Session
from ntu_stars_mcp.wish.session import WishSessionManager


class CredentialTests(unittest.TestCase):
    def test_network_username_derives_student_email(self):
        with patch.dict(os.environ, {"NTU_USERNAME": " student001 ", "NTU_PASSWORD": "shared-test-secret"}, clear=True):
            credentials = read_credentials()
            self.assertEqual(credentials.username, "student001")
            self.assertEqual(credentials.email, "student001@e.ntu.edu.sg")
            self.assertEqual(credentials.password, "shared-test-secret")
            self.assertNotIn(credentials.password, repr(credentials))

    def test_full_email_preserves_domain_and_normalizes_wish_username(self):
        for email in ["student001@e.ntu.edu.sg", "staff001@ntu.edu.sg"]:
            with patch.dict(os.environ, {"NTU_USERNAME": email, "NTU_PASSWORD": "shared-test-secret"}, clear=True):
                credentials = read_credentials()
                self.assertEqual(credentials.username, email.split("@")[0])
                self.assertEqual(credentials.email, email)

    def test_only_shared_credential_variables_are_used(self):
        with patch.dict(os.environ, {"NTU_WISH_USERNAME": "student001", "NTU_WISH_PASSWORD": "old-secret"}, clear=True):
            self.assertEqual(read_credentials().username, "")
            self.assertEqual(read_credentials().email, "")
            self.assertEqual(read_credentials().password, "")
            os.environ.update(NTU_USERNAME="new001", NTU_PASSWORD="new-secret")
            self.assertEqual(read_credentials().username, "new001")
            self.assertEqual(read_credentials().password, "new-secret")
            os.environ.update(NTU_USERNAME="", NTU_PASSWORD="")
            self.assertEqual(read_credentials().username, "")
            self.assertEqual(read_credentials().email, "")
            self.assertEqual(read_credentials().password, "")

    def test_both_services_use_one_configuration_without_login(self):
        with patch.dict(os.environ, {"NTU_USERNAME": "student001", "NTU_PASSWORD": "shared-test-secret"}, clear=True):
            wish, learn = WishSessionManager(), Session()
        try:
            self.assertEqual(wish.username, "student001")
            self.assertEqual(learn._username, "student001@e.ntu.edu.sg")
            self.assertEqual(wish.password, learn._password)
            self.assertTrue(wish.status()["credentials_configured"])
            self.assertTrue(learn.status().credentials_configured)
            self.assertFalse(wish.status()["session_verified"])
            self.assertFalse(learn.status().session_verified)
        finally:
            wish.close()
            learn.close()

    def test_server_closes_both_sessions_even_if_one_cleanup_fails(self):
        from shared import server
        from ntu_stars_mcp.wish.session import wish_session
        with patch.object(server.mcp, "run"), patch.object(wish_session, "close", side_effect=RuntimeError("test cleanup")) as wish, patch.object(server.tools.session, "close") as learn:
            with self.assertRaisesRegex(RuntimeError, "test cleanup"):
                server.main()
            wish.assert_called_once()
            learn.assert_called_once()

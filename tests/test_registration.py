from dataclasses import replace
import os
from threading import get_ident
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

from mcp import Client

from ntu_stars_mcp.mcp_server import mcp
from ntu_stars_mcp.wish import registration as reg
from ntu_stars_mcp.wish.models import NTUPersonalDataError
from ntu_stars_mcp.wish.session import WishSessionManager


COURSES = [{"course_code": "ZZ0001", "index": "00001"}]
FIELDS = [("p1", "private-session-token"), ("p2", "private-session-token-2"), ("subj_code", "ZZ0001"),
          ("index_nmbr", "00001"), ("subj_code", ""), ("index_nmbr", ""), ("tchar2", "native-field"), ("boption", "native-action")]


def snapshot(records=(), semester=2):
    return {"academic_year": 2026, "semester": semester, "registered_courses": list(records),
            "registered_courses_status": "parsed" if records else "empty"}


class RegistrationFormTests(unittest.TestCase):
    def test_exact_native_form_is_accepted_without_submitting(self):
        page = Mock()
        page.evaluate.return_value = {"action": "AUS_STARS_REG.reg_sub", "method": "post", "disabled": False, "fields": FIELDS}
        self.assertEqual(reg._registration_form(page, "native-html", COURSES), FIELDS)
        page.context.request.post.assert_not_called()

    def test_changed_external_or_mismatched_forms_are_rejected(self):
        base = {"action": "AUS_STARS_REG.reg_sub", "method": "post", "disabled": False, "fields": FIELDS}
        for changed in (
            None, {**base, "action": "https://other.example/register"},
            {**base, "action": "AUS_STARS_REG.drop_sub"}, {**base, "method": "get"}, {**base, "disabled": True},
            {**base, "fields": FIELDS + [("proficiency_declaration", "yes")]},
            {**base, "fields": [(k, v) for k, v in FIELDS if k != "p2"]},
            {**base, "fields": [(k, "00002" if k == "index_nmbr" and v else v) for k, v in FIELDS]},
            {**base, "fields": FIELDS + [("subj_code", "ZZ0001"), ("index_nmbr", "00001")]},
            {**base, "fields": FIELDS + [("subj_code", ""), ("index_nmbr", "00001")]},
        ):
            page = Mock()
            page.evaluate.return_value = changed
            with self.assertRaises(NTUPersonalDataError):
                reg._registration_form(page, "html", COURSES)
            page.context.request.post.assert_not_called()

    def test_request_uses_fixed_endpoint_no_redirects_and_disposes_response(self):
        response = Mock(status=200, headers={"content-type": "text/html; charset=windows-1252"})
        response.body.return_value = b"<p>Response</p>"
        page = Mock()
        page.context.request.post.return_value = response
        with patch.object(reg, "_wait_for_request_slot"):
            reg._submit_registration(page, FIELDS)
        request = page.context.request.post.call_args
        self.assertEqual(request.args[0], reg.REGISTRATION_URL)
        self.assertEqual(request.kwargs["max_redirects"], 0)
        self.assertEqual(parse_qs(request.kwargs["data"])["index_nmbr"], ["00001"])
        response.dispose.assert_called_once()

    def test_waitlists_and_other_indexes_are_not_confirmed_registrations(self):
        self.assertTrue(reg._registered_as_requested([{"course_code": "ZZ0001", "Index No": "00001"}], COURSES))
        for record in (
            {"course_code": "ZZ0001", "Index No": "00002"},
            {"course_code": "ZZ0001", "Index No": "00001", "Status": "Waitlisted"},
            {"course_code": "ZZ0001", "Index No": "00001", "Status": "Pending"},
            {"course_code": "ZZ0001"},
        ):
            self.assertFalse(reg._registered_as_requested([record], COURSES))


class RegistrationGuardTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"NTU_WISH_USERNAME": "test-user", "NTU_WISH_PASSWORD": "test-secret"}):
            self.manager = WishSessionManager()
        self.addCleanup(self.manager.close)
        self.manager._page = Mock()
        self.read = patch.object(self.manager, "_get_personal_data", return_value=snapshot()).start()
        self.prepare = patch.object(reg, "_prepare_registration", return_value=FIELDS).start()
        self.submit = patch.object(reg, "_submit_registration").start()
        self.addCleanup(patch.stopall)

    def preview(self):
        result = self.manager.register_courses(COURSES, 2026, 2)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertIn("Are you sure?", result["confirmation_question"])
        self.assertIn("VERY DANGEROUS", result["warning"])
        self.assertIn("ZZ0001 index 00001", result["confirmation_question"])
        self.submit.assert_not_called()
        return result["confirmation_token"]

    def test_preview_is_non_submitting_and_refreshes_live_data(self):
        token = self.preview()
        self.assertTrue(token)
        self.assertNotIn("private-session-token", token)
        self.assertTrue(self.read.call_args.kwargs["refresh"])
        self.prepare.assert_called_once()

    def test_no_confirmation_or_token_can_submit_without_an_issued_preview(self):
        for token in (None, "unissued-token"):
            with self.assertRaisesRegex(NTUPersonalDataError, "confirmation"):
                self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.read.assert_not_called()
        self.submit.assert_not_called()

    def test_token_alone_is_not_confirmation(self):
        token = self.preview()
        with self.assertRaisesRegex(NTUPersonalDataError, "affirmative"):
            self.manager.register_courses(COURSES, 2026, 2, token, False)
        self.submit.assert_not_called()

    def test_changed_payload_and_expired_tokens_cannot_submit(self):
        token = self.preview()
        for courses, year, semester in (([{"course_code": "ZZ0001", "index": "00002"}], 2026, 2),
                                       (COURSES, 2025, 2), (COURSES, 2026, 1)):
            with self.assertRaises(NTUPersonalDataError):
                self.manager.register_courses(courses, year, semester, token, True)
        self.manager._pending_registration = replace(self.manager._pending_registration, deadline=0)
        with self.assertRaisesRegex(NTUPersonalDataError, "expired"):
            self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.submit.assert_not_called()

    def test_new_preview_invalidates_the_old_preview(self):
        old = self.preview()
        new = self.preview()
        self.assertNotEqual(old, new)
        with self.assertRaises(NTUPersonalDataError):
            self.manager.register_courses(COURSES, 2026, 2, old, True)
        self.submit.assert_not_called()

    def test_confirmation_is_single_use_and_invalidates_personal_caches(self):
        token = self.preview()
        self.manager._cache = {name: (0, {}) for name in ("stars_planner", "degree_audit")}
        def submit(*_args):
            self.assertIsNone(self.manager._pending_registration)
            self.assertNotIn("stars_planner", self.manager._cache)
            self.assertNotIn("degree_audit", self.manager._cache)
        self.submit.side_effect = submit
        self.read.side_effect = [snapshot(), snapshot([{"course_code": "ZZ0001", "Index No": "00001"}])]
        result = self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.assertEqual(result["status"], "registered")
        self.assertIsNone(result["confirmation_token"])
        with self.assertRaises(NTUPersonalDataError):
            self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.submit.assert_called_once()

    def test_registration_or_term_changes_require_a_new_preview(self):
        for changed in (snapshot([{"course_code": "ZZ0002", "Index No": "00002"}]), snapshot(semester=1)):
            token = self.preview()
            self.read.return_value = changed
            with self.assertRaises(NTUPersonalDataError):
                self.manager.register_courses(COURSES, 2026, 2, token, True)
            self.assertIsNone(self.manager._pending_registration)
            self.read.return_value = snapshot()
        self.submit.assert_not_called()

    def test_registered_courses_are_not_submitted_for_index_changes(self):
        self.read.return_value = snapshot([{"course_code": "ZZ0001", "Index No": "00002"}])
        with self.assertRaisesRegex(NTUPersonalDataError, "already registered"):
            self.manager.register_courses(COURSES, 2026, 2)
        self.prepare.assert_not_called()
        self.submit.assert_not_called()

    def test_expiry_during_preparation_is_rejected(self):
        token = self.preview()
        def expire(*_args):
            self.assertIsNone(self.manager._pending_registration)
            return FIELDS
        pending = replace(self.manager._pending_registration, deadline=100)
        self.manager._pending_registration = pending
        self.prepare.side_effect = expire
        with patch.object(reg.time, "monotonic", side_effect=[0, 100]):
            with self.assertRaisesRegex(NTUPersonalDataError, "expired during"):
                self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.submit.assert_not_called()

    def test_timeouts_and_unverified_outcomes_never_repeat_registration(self):
        for after in (snapshot(), RuntimeError("private-session-token"), snapshot(semester=1),
                      snapshot([{"course_code": "ZZ0001", "Index No": "00001", "Status": "Waitlisted"}])):
            self.read.side_effect = None
            token = self.preview()
            self.read.side_effect = [snapshot(), after]
            self.submit.side_effect = TimeoutError("private-session-token")
            result = self.manager.register_courses(COURSES, 2026, 2, token, True)
            self.assertEqual(result["status"], "unverified")
            self.assertNotIn("private-session-token", str(result))
            self.assertIsNone(self.manager._pending_registration)
            self.submit.assert_called_once()
            self.submit.reset_mock()

    def test_close_discards_pending_confirmation(self):
        self.preview()
        self.manager.close()
        self.assertIsNone(self.manager._pending_registration)

    def test_preview_and_confirmation_use_the_shared_browser_thread(self):
        threads = []
        def prepare(*_args):
            threads.append(get_ident())
            return FIELDS
        self.prepare.side_effect = prepare
        token = self.preview()
        self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.assertEqual(len(threads), 2)
        self.assertEqual(len(set(threads)), 1)
        self.assertNotEqual(threads[0], get_ident())

    def test_prepare_errors_do_not_submit_or_leak_private_data(self):
        token = self.preview()
        self.prepare.side_effect = RuntimeError("private-session-token")
        with self.assertRaises(NTUPersonalDataError) as error:
            self.manager.register_courses(COURSES, 2026, 2, token, True)
        self.assertNotIn("private-session-token", str(error.exception))
        self.assertIsNone(self.manager._pending_registration)
        self.submit.assert_not_called()


class RegistrationMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_warning_annotations_defaults_and_structured_preview(self):
        result = {"status": "confirmation_required", "academic_year": 2026, "semester": 2, "courses": COURSES,
                  "warning": reg.DANGER_WARNING, "confirmation_question": "Are you sure?", "confirmation_token": "preview-token",
                  "confirmation_expires_at": "2026-10-21T04:00:00+00:00", "registered_courses": [],
                  "registered_courses_status": "empty", "message": "Preview only", "verified_at": None, "source_url": reg.REGISTRATION_URL}
        with patch("ntu_stars_mcp.mcp_server.submit_course_registration", return_value=result) as submit:
            async with Client(mcp) as client:
                tool = next(t for t in (await client.list_tools()).tools if t.name == "register_courses")
                self.assertFalse(tool.annotations.read_only_hint)
                self.assertTrue(tool.annotations.destructive_hint)
                self.assertFalse(tool.annotations.idempotent_hint)
                self.assertIn("VERY DANGEROUS", tool.description)
                self.assertIn("Are you sure?", tool.description)
                reply = await client.call_tool("register_courses", {"courses": COURSES, "academic_year": 2026, "semester": 2})
                self.assertFalse(reply.is_error)
                self.assertEqual(reply.structured_content["status"], "confirmation_required")
                submit.assert_called_once_with(COURSES, 2026, 2, None, False)

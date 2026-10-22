import os
from threading import get_ident
import unittest
from unittest.mock import Mock, patch

from mcp import Client

from ntu_stars_mcp.mcp_server import mcp
from ntu_stars_mcp.parser import NTUPageError
from ntu_stars_mcp.wish import plan_editor as editor
from ntu_stars_mcp.wish.models import NTUAuthError, NTUPersonalDataError
from ntu_stars_mcp.wish.planner import PLANNER_VIEW_URL, SAVE_PLAN_URL, _post
from ntu_stars_mcp.wish.session import WishSessionManager


COURSES = [{"course_code": "ZZ0001", "index": "00001"}]


def state(codes=(), indexes=()):
    codes = list(codes) + [""] * (3 - len(codes))
    indexes = list(indexes) + [""] * (3 - len(indexes))
    fields = [("p1", "private-session-token"), ("p2", "private-session-token-2"),
              ("acad", "2026"), ("semester", "2"), ("plan_no", "1"), ("r_subj", ""), ("boption", "")]
    for name, values in (("subj_code", codes), ("index_nmbr", indexes), ("subj_type", ["C" if c else "" for c in codes])):
        fields.extend((name, value) for value in values)
    return {
        "action": "AUS_STARS_PLANNER.planner", "method": "post",
        "handler": "if (fcheckform(this.form)) {this.form.action='AUS_STARS_PLANNER.save_time_table';submit()}",
        "fields": fields,
        "indexes": [{"options": ["null", "00001", "00002"] if code else None} for code in codes],
    }


def saved_plan(courses=None, number=1):
    return {"plan_number": number, "status": "loaded", "courses": [{**course, "course_type": "C"} for course in (courses if courses is not None else COURSES)],
            "sessions": [], "unparsed_sessions": [], "timetable_status": "empty"}


def snapshot(courses=None):
    return {"academic_year": 2026, "semester": 2, "saved_plans": [saved_plan(courses)]}


class PlanEditorTests(unittest.TestCase):
    def test_request_validation_precedes_any_network(self):
        self.assertEqual(editor.validate_plan_request(1, [{"course_code": " zz0001 ", "index": "00001"}], 2026, 2), COURSES)
        for number, courses, year, semester in (
            (0, COURSES, 2026, 2), (True, COURSES, 2026, 2), (1, [], 2026, 2),
            (1, COURSES * 14, 2026, 2), (1, COURSES * 2, 2026, 2),
            (1, [{"course_code": "ZZ0001?x", "index": "00001"}], 2026, 2),
            (1, [{"course_code": "ZZ0001", "index": "bad"}], 2026, 2),
            (1, COURSES, 1999, 2), (1, COURSES, 2026, "S"),
        ):
            with self.subTest(number=number, year=year, semester=semester):
                with self.assertRaises(ValueError):
                    editor.validate_plan_request(number, courses, year, semester)

    def test_native_scratch_updates_do_not_save_or_register(self):
        page = Mock()
        page.evaluate.side_effect = [state(["ZZ0002"], ["00002"]), state(), state(["ZZ0001"], ["null"]), state(["ZZ0001"], ["00001"])]
        with patch.object(editor, "_post", side_effect=["clear", "add", "select"]) as post:
            fields = editor.prepare_stars_plan(page, COURSES, 2026, 2)
        self.assertTrue(all(call.args[1] == PLANNER_VIEW_URL and not call.kwargs for call in post.call_args_list))
        self.assertTrue(all(value == "" for key, value in post.call_args_list[0].args[2] if key == "subj_code"))
        self.assertIn(("r_subj", "ZZ0001"), post.call_args_list[1].args[2])
        self.assertIn(("index_nmbr", "00001"), fields)
        self.assertIn(("boption", ""), fields)

    def test_changed_save_forms_or_terms_are_not_used(self):
        for update in (
            {"action": "https://other.example/save"}, {"action": "AUS_STARS_REG.reg_sub"},
            {"method": "get"}, {"handler": "this.form.action='AUS_STARS_REG.reg_sub';submit()"},
            {"fields": [(k, v) for k, v in state()["fields"] if k != "p2"]},
            {"fields": [(k, "2025" if k == "acad" else v) for k, v in state()["fields"]]},
            {"indexes": []},
        ):
            page = Mock()
            page.evaluate.return_value = {**state(), **update}
            with patch.object(editor, "_post") as post:
                with self.assertRaises(NTUPageError):
                    editor.prepare_stars_plan(page, COURSES, 2026, 2)
                post.assert_not_called()

    def test_multiple_courses_keep_index_assignments_when_ntu_reorders_rows(self):
        requested = [{"course_code": "ZZ0002", "index": "00002"}, *COURSES]
        page = Mock()
        page.evaluate.side_effect = [state(), state(), state(["ZZ0002"], ["null"]),
                                    state(["ZZ0001", "ZZ0002"], ["null", "00002"]),
                                    state(["ZZ0001", "ZZ0002"], ["00001", "00002"])]
        with patch.object(editor, "_post", return_value="display") as post:
            fields = editor.prepare_stars_plan(page, requested, 2026, 2)
        codes = [v for k, v in fields if k == "subj_code"]
        indexes = [v for k, v in fields if k == "index_nmbr"]
        self.assertEqual({c: i for c, i in zip(codes, indexes) if c}, editor.course_assignments(requested))
        self.assertEqual(post.call_count, 4)

    def test_failed_clear_and_unretained_indexes_are_rejected(self):
        for states in (
            [state(), state(["ZZ0002"], ["00002"])],
            [state(), state(), state(["ZZ0001"], ["null"]), state(["ZZ0001"], ["null"])],
        ):
            page = Mock()
            page.evaluate.side_effect = states
            with patch.object(editor, "_post", return_value="display") as post:
                with self.assertRaises((NTUPageError, NTUPersonalDataError)):
                    editor.prepare_stars_plan(page, COURSES, 2026, 2)
            self.assertTrue(all(call.args[1] == PLANNER_VIEW_URL for call in post.call_args_list))

    def test_unoffered_courses_and_indexes_cannot_be_saved(self):
        for added in (state(), state(["ZZ0001"], ["null"])):
            if added["indexes"][0]["options"]:
                added["indexes"][0]["options"] = ["null", "00002"]
            page = Mock()
            page.evaluate.side_effect = [state(), state(), added]
            with patch.object(editor, "_post", return_value="display") as post:
                with self.assertRaisesRegex(NTUPersonalDataError, "no plan was saved"):
                    editor.prepare_stars_plan(page, COURSES, 2026, 2)
                self.assertEqual(post.call_count, 2)

    def test_expiry_during_preparation_never_saves(self):
        page = Mock()
        page.evaluate.return_value = state()
        with patch.object(editor, "_post", return_value=None) as post:
            with self.assertRaisesRegex(NTUAuthError, "no save was submitted"):
                editor.prepare_stars_plan(page, COURSES, 2026, 2)
            post.assert_called_once()

    def test_only_fixed_save_endpoint_and_selected_plan_are_submitted(self):
        with patch.object(editor, "_post", return_value="<script>alert('Plan saved successfully.')</script>") as post:
            editor.submit_stars_plan(Mock(), [("plan_no", "1"), ("p1", "private-session-token")], 3)
        self.assertEqual(post.call_args.args[1], SAVE_PLAN_URL)
        self.assertEqual([v for k, v in post.call_args.args[2] if k == "plan_no"], ["3"])
        self.assertEqual(post.call_args.kwargs, {"save": True})

    def test_uncertain_saves_are_not_retried_and_do_not_expose_private_details(self):
        for reply in (None, "<p>Service unavailable</p>", TimeoutError("private-session-token")):
            with patch.object(editor, "_post", **({"side_effect": reply} if isinstance(reply, Exception) else {"return_value": reply})) as post:
                with self.assertRaises(NTUPersonalDataError) as error:
                    editor.submit_stars_plan(Mock(), [], 1)
                self.assertNotIn("private-session-token", str(error.exception))
                post.assert_called_once()

    def test_request_allowlist_blocks_registration_and_save_via_read_path(self):
        page = Mock()
        for url, saving in ((SAVE_PLAN_URL, False), (PLANNER_VIEW_URL, True),
                            (PLANNER_VIEW_URL.replace('AUS_STARS_PLANNER.planner', 'AUS_STARS_REG.reg_sub'), False),
                            (PLANNER_VIEW_URL.replace('AUS_STARS_PLANNER.planner', 'AUS_STARS_REG.reg_sub'), True)):
            with self.assertRaises(NTUPersonalDataError):
                _post(page, url, [], save=saving)
        page.context.request.post.assert_not_called()


class PlanSessionTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"NTU_USERNAME": "test-user", "NTU_PASSWORD": "test-secret"}):
            self.manager = WishSessionManager()
        self.addCleanup(self.manager.close)
        self.manager._page = Mock()

    def test_live_read_save_read_back_runs_on_one_browser_thread(self):
        threads = []
        def read(*_args, **kwargs):
            self.assertTrue(kwargs["refresh"])
            threads.append(get_ident())
            return snapshot([]) if len(threads) == 1 else snapshot()
        self.manager._cache["stars_planner"] = (0, snapshot([]))
        def save(*_args):
            threads.append(get_ident())
            self.assertNotIn("stars_planner", self.manager._cache)
        with (
            patch.object(self.manager, "_get_personal_data", side_effect=read) as fetch,
            patch("ntu_stars_mcp.wish.session.prepare_stars_plan", return_value=[]) as prepare,
            patch("ntu_stars_mcp.wish.session.submit_stars_plan", side_effect=save) as submit,
        ):
            result = self.manager.save_stars_plan(1, COURSES, 2026, 2)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(editor.course_assignments(result["saved_plan"]["courses"]), editor.course_assignments(COURSES))
        self.assertEqual(fetch.call_count, 2)
        prepare.assert_called_once()
        submit.assert_called_once()
        self.assertEqual(len(set(threads)), 1)
        self.assertNotEqual(threads[0], get_ident())

    def test_identical_contents_do_not_submit_a_save(self):
        with patch.object(self.manager, "_get_personal_data", return_value=snapshot()), patch("ntu_stars_mcp.wish.session.submit_stars_plan") as submit:
            self.assertEqual(self.manager.save_stars_plan(1, COURSES, 2026, 2)["status"], "unchanged")
        submit.assert_not_called()

    def test_term_mismatch_fails_before_preparation(self):
        with patch.object(self.manager, "_get_personal_data", return_value=snapshot()), patch("ntu_stars_mcp.wish.session.prepare_stars_plan") as prepare:
            with self.assertRaisesRegex(NTUPersonalDataError, "current Planner term"):
                self.manager.save_stars_plan(1, COURSES, 2026, 1)
        prepare.assert_not_called()

    def test_failed_read_back_does_not_repeat_save(self):
        for after in (snapshot([]), NTUAuthError("session expired"), {**snapshot(), "semester": 1}):
            with (
                patch.object(self.manager, "_get_personal_data", side_effect=[snapshot([]), after]),
                patch("ntu_stars_mcp.wish.session.prepare_stars_plan", return_value=[]),
                patch("ntu_stars_mcp.wish.session.submit_stars_plan") as submit,
            ):
                with self.assertRaises(NTUPersonalDataError):
                    self.manager.save_stars_plan(1, COURSES, 2026, 2)
            submit.assert_called_once()
            self.assertNotIn("stars_planner", self.manager._cache)

    def test_missing_credentials_invalid_inputs_and_closed_manager(self):
        with self.assertRaises(ValueError):
            self.manager.save_stars_plan(1, [], 2026, 2)
        self.assertIsNone(self.manager._executor)
        self.manager.username = ""
        with self.assertRaises(NTUAuthError):
            self.manager.save_stars_plan(1, COURSES, 2026, 2)
        self.manager.close()
        with self.assertRaisesRegex(NTUAuthError, "closed"):
            self.manager.save_stars_plan(1, COURSES, 2026, 2)

    def test_unknown_browser_errors_are_sanitized_and_saves_are_not_repeated(self):
        with (
            patch.object(self.manager, "_get_personal_data", return_value=snapshot([])),
            patch("ntu_stars_mcp.wish.session.prepare_stars_plan", side_effect=RuntimeError("private-session-token")),
            patch("ntu_stars_mcp.wish.session.submit_stars_plan") as submit,
        ):
            with self.assertRaises(NTUPersonalDataError) as error:
                self.manager.save_stars_plan(1, COURSES, 2026, 2)
        self.assertNotIn("private-session-token", str(error.exception))
        submit.assert_not_called()
        self.manager._cache["stars_planner"] = (0, snapshot([]))
        with (
            patch.object(self.manager, "_get_personal_data", return_value=snapshot([])),
            patch("ntu_stars_mcp.wish.session.prepare_stars_plan", return_value=[]),
            patch("ntu_stars_mcp.wish.session.submit_stars_plan", side_effect=NTUPersonalDataError("uncertain")) as submit,
        ):
            with self.assertRaises(NTUPersonalDataError):
                self.manager.save_stars_plan(1, COURSES, 2026, 2)
        submit.assert_called_once()
        self.assertNotIn("stars_planner", self.manager._cache)


class PlanMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_schema_annotations_and_call(self):
        reply = {"status": "saved", "academic_year": 2026, "semester": 2, "saved_plan": saved_plan(),
                 "verified_at": "2026-10-21T00:00:00+00:00", "source_url": SAVE_PLAN_URL}
        with patch("ntu_stars_mcp.mcp_server.persist_stars_plan", return_value=reply) as save:
            async with Client(mcp) as client:
                tool = next(t for t in (await client.list_tools()).tools if t.name == "save_stars_plan")
                self.assertFalse(tool.annotations.read_only_hint)
                self.assertTrue(tool.annotations.destructive_hint)
                result = await client.call_tool("save_stars_plan", {"plan_number": 1, "courses": COURSES, "academic_year": 2026, "semester": 2})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["saved_plan"]["courses"][0]["index"], "00001")
                save.assert_called_once_with(1, COURSES, 2026, 2)

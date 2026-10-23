from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import MagicMock, patch

from shared.credentials import CredentialError, Credentials
from library.facilities import FacilitiesClient, map_availability, requested_time, script_json
from library.models import LibraryError
from library.session import FacilitySession
from library.schedule import parse_slots, schedule_path
from .facility_fixtures import GRID, MAP, fake_facility_get, fake_schedule, snapshot


class FacilityTests(unittest.TestCase):
    def test_directory_and_map_statuses(self):
        client = FacilitiesClient()
        with patch.object(client.http, "get", side_effect=fake_facility_get):
            directory = client.list_facilities()
            self.assertEqual(len(directory.facilities), 3)
            self.assertEqual(directory.facilities[0].map_slug, "abcdef123456")
            self.assertEqual(directory.facilities[1].space_id, 100)
            self.assertEqual(directory.facilities[2].group_id, 20)
            self.assertEqual(directory.notices, ["Example closure notice."])
            result = client.get_map_availability("abcdef123456", "2026-10-24", "14:00")
        self.assertEqual(
            [v.status for v in result.spaces], ["available", "available_later", "unavailable", "unknown"]
        )
        self.assertEqual(result.at.utcoffset(), timedelta(hours=8))
        self.assertEqual(result.spaces[-1].source_status, 88)

    def test_invalid_dates_and_missing_map_data_fail_closed(self):
        for day, time in [("2026-02-30", "12:00"), ("2026-10-24", "25:00")]:
            with self.assertRaises(LibraryError):
                requested_time(day, time)
        for html in ["<html>Login</html>", "mapId: null"]:
            with self.assertRaises((LibraryError, ValueError, TypeError)):
                script_json(html, "linkModelsByShapeId")
        altered = MAP.replace(b'"id":101', b'"id":100')
        with self.assertRaises(LibraryError):
            map_availability(
                altered,
                "abcdef123456",
                requested_time("2026-10-24", "14:00"),
                snapshot("https://example.org"),
            )

    def test_grid_is_lossless_compact_and_excludes_booking_secrets(self):
        result = parse_slots(GRID, {100: "Example Room"}, "2026-10-24")
        self.assertEqual(len(result[0].slots), 2)
        self.assertEqual(result[0].slots[0].end.minute, 30)
        self.assertEqual(result[0].slots[-1].source_classes, "future-source-state")
        self.assertEqual(result[0].slots[-1].status, "unavailable")
        self.assertNotIn("never-output", result[0].model_dump_json())
        self.assertEqual(result[0].slots[0].start.utcoffset(), timedelta(hours=8))
        self.assertEqual(parse_slots({**GRID, "slots": []}, {100: "Room"}, "2026-10-24")[0].slots, [])
        available = deepcopy(GRID)
        for row in available["slots"]:
            row.pop("className", None)
        self.assertEqual(parse_slots(available, {}, "2026-10-24")[0].slots[0].status, "available")
        self.assertIsNone(parse_slots(available, {}, "2026-10-24")[0].slots[0].source_classes)

    def test_grid_wrong_day_overlap_and_unexpected_booking_fail(self):
        cases = []
        value = deepcopy(GRID)
        value["slots"][0]["start"] = "2026-10-23 10:00:00"
        cases.append(value)
        value = deepcopy(GRID)
        value["slots"][1]["start"] = "2026-10-24 10:10:00"
        cases.append(value)
        cases.append({**GRID, "isPreCreatedBooking": True})
        cases.append({"slots": {}, "isPreCreatedBooking": False})
        for value in cases:
            with self.assertRaises(LibraryError):
                parse_slots(value, {}, "2026-10-24")

    def test_read_paths_and_credentials_are_checked_before_cache(self):
        self.assertEqual(schedule_path(100, None, None), "/space/100")
        self.assertEqual(schedule_path(None, 10, 20), "/spaces?lid=10&gid=20")
        for ids in [(None, None, None), (100, 10, 20), (-1, None, None), (True, None, None)]:
            with self.assertRaises(LibraryError):
                schedule_path(*ids)
        session = FacilitySession()
        self.addCleanup(session.close)
        with patch("library.session.read_credentials", side_effect=CredentialError("Keyring locked")):
            with self.assertRaisesRegex(LibraryError, "Keyring locked"):
                session.get_schedule("2026-10-24", 100)
        self.assertIsNone(session._browser)

    def test_cached_personal_results_require_current_credentials_and_are_copied(self):
        session = FacilitySession()
        self.addCleanup(session.close)
        credentials = Credentials(username="example", password="synthetic", revision="a" * 32)
        session._revision = credentials.revision
        import time

        session._cache[("/space/100", "2026-10-24")] = (time.monotonic(), fake_schedule("2026-10-24", 100))
        with patch("library.session.read_credentials", return_value=credentials):
            first = session.get_schedule("2026-10-24", 100)
            first.spaces.clear()
            self.assertTrue(session.get_schedule("2026-10-24", 100).spaces)
            self.assertTrue(first.cached)
        with patch("library.session.read_credentials", return_value=Credentials()):
            with self.assertRaises(LibraryError):
                session.get_schedule("2026-10-24", 100)
        self.assertFalse(session._cache)

    def test_browser_errors_do_not_leak_details(self):
        session = FacilitySession()
        self.addCleanup(session.close)
        with patch.object(session, "_get_schedule", side_effect=RuntimeError("private-password-and-cookie")):
            with self.assertRaises(LibraryError) as error:
                session.get_schedule("2026-10-24", 100)
        self.assertNotIn("private-password", str(error.exception))

    def test_expired_grid_reauthenticates_once_and_permission_errors_do_not(self):
        credentials = Credentials(username="example", password="synthetic", revision="a" * 32)
        settings = dict(lid=10, gid=20, eid=100, seat=0, seatId=0, zone=0, pageSize=18, count=1)
        for status in (302, 403):
            with self.subTest(status=status):
                session = FacilitySession()
                self.addCleanup(session.close)
                session._revision = credentials.revision
                session._context = MagicMock()
                session._page = MagicMock()
                session._page.evaluate.side_effect = [
                    settings,
                    [["100", "Example Room"]],
                    settings,
                    [["100", "Example Room"]],
                ]
                session._page.locator.return_value.inner_text.return_value = "Example Room"
                session._page.locator.return_value.first.inner_text.return_value = "Example Room"
                first = MagicMock(status=status, headers={})
                second = MagicMock(status=200, headers={"content-type": "application/json"})
                second.body.return_value = b"{}"
                second.json.return_value = GRID
                session._context.request.post.side_effect = [first, second]
                context = session._context
                with (
                    patch("library.session.read_credentials", return_value=credentials),
                    patch.object(session, "_navigate") as login,
                    patch.object(session, "_pace"),
                ):
                    if status == 302:
                        result = session.get_schedule("2026-10-24", 100)
                        self.assertEqual(result.spaces[0].name, "Example Room")
                        self.assertEqual(login.call_count, 2)
                        context.clear_cookies.assert_called_once()
                        self.assertTrue(
                            all(
                                call.args[0].endswith("/spaces/availability/grid")
                                for call in context.request.post.call_args_list
                            )
                        )
                    else:
                        with self.assertRaisesRegex(LibraryError, "HTTP 403"):
                            session.get_schedule("2026-10-24", 100)
                        self.assertEqual(login.call_count, 1)
                        context.clear_cookies.assert_not_called()

    def test_mfa_and_wrong_password_stop_without_repeated_submission(self):
        credentials = Credentials(username="example", password="synthetic", revision="a" * 32)
        for body in (["Verify your identity"], ["Sign in", "Incorrect password"]):
            with self.subTest(body=body):
                session = FacilitySession()
                self.addCleanup(session.close)
                page = session._page = MagicMock()
                page.url = "https://loginfs.ntu.edu.sg/adfs/ls/"
                page.goto.return_value = None
                page.locator.return_value.inner_text.side_effect = body
                page.locator.return_value.count.return_value = 1
                with patch.object(session, "_open"), patch.object(session, "_pace"):
                    with self.assertRaises(LibraryError):
                        session._navigate("/space/100", credentials)
                self.assertEqual(page.locator.return_value.fill.call_count, 0 if len(body) == 1 else 2)

    def test_category_session_recognizes_configuration_without_room_heading(self):
        session = FacilitySession()
        self.addCleanup(session.close)
        page = session._page = MagicMock()
        page.goto.return_value = None
        page.url = "https://libcalendar.ntu.edu.sg/spaces?lid=10&gid=20"
        page.locator.return_value.inner_text.return_value = "Space Availability"
        page.evaluate.return_value = True
        with patch.object(session, "_open"), patch.object(session, "_pace"):
            session._navigate("/spaces?lid=10&gid=20", Credentials())
        page.locator.return_value.fill.assert_not_called()

    def test_category_all_resources_sentinel_matches_the_official_grid_query(self):
        credentials = Credentials(username="example", password="synthetic", revision="a" * 32)
        session = FacilitySession()
        self.addCleanup(session.close)
        session._revision = credentials.revision
        session._context = MagicMock()
        context = session._context
        session._page = MagicMock()
        session._page.locator.return_value.first.inner_text.return_value = "Example Library"
        session._page.locator.return_value.inner_text.return_value = "Example rooms."
        session._page.evaluate.side_effect = [
            dict(lid=10, gid=20, eid=-1, seat=0, seatId=0, zone=0, pageSize=18, count=1),
            [["100", "Example Room"]],
        ]
        response = MagicMock(status=200, headers={"content-type": "application/json"})
        response.body.return_value = b"{}"
        response.json.return_value = GRID
        context.request.post.return_value = response
        with (
            patch("library.session.read_credentials", return_value=credentials),
            patch.object(session, "_navigate"),
            patch.object(session, "_pace"),
        ):
            result = session.get_schedule("2026-10-24", location_id=10, group_id=20)
        self.assertEqual(result.spaces[0].item_id, "100")
        self.assertEqual(context.request.post.call_args.kwargs["form"]["eid"], -1)

    def test_wrong_facility_metadata_is_rejected_before_grid_query(self):
        credentials = Credentials(username="example", password="synthetic", revision="a" * 32)
        session = FacilitySession()
        self.addCleanup(session.close)
        session._revision = credentials.revision
        session._context = MagicMock()
        context = session._context
        session._page = MagicMock()
        session._page.evaluate.return_value = dict(
            lid=10, gid=20, eid=101, seat=0, seatId=0, zone=0, pageSize=18, count=1
        )
        with (
            patch("library.session.read_credentials", return_value=credentials),
            patch.object(session, "_navigate"),
        ):
            with self.assertRaisesRegex(LibraryError, "different facility"):
                session.get_schedule("2026-10-24", 100)
        context.request.post.assert_not_called()

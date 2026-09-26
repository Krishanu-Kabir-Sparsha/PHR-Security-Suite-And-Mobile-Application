# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One definition of "am I checked in", and what happens when somebody forgets.

The bug these were written against: ``_today_state`` derived the answer from
today's rows while ``toggle`` read ``employee.attendance_state``. A row left
open overnight made the first say "checked out" and the second say "checked
in", so the app drew a Check In button, the user pressed it, and Odoo refused
with a constraint error naming a date two days earlier.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceState(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Checkin = self.env["perfecthr.mobile.checkin"]
        self.Attendance = self.env["hr.attendance"]
        self.company = self.env["res.company"].create({"name": "State Co"})
        self.user = self.env["res.users"].create(
            {
                "name": "State Tester",
                "login": "state.tester@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.company.id,
                "company_ids": [(6, 0, [self.company.id])],
            }
        )
        self.employee = self.env["hr.employee"].create(
            {
                "name": "State Tester",
                "user_id": self.user.id,
                "company_id": self.company.id,
            }
        )

    def _row(self, check_in, check_out=None):
        return self.Attendance.create(
            {
                "employee_id": self.employee.id,
                "check_in": check_in,
                "check_out": check_out,
            }
        )

    # -- the open session ----------------------------------------------
    def test_no_rows_is_not_checked_in(self):
        self.assertFalse(self.Checkin.open_session(self.employee))
        self.assertEqual(
            self.Checkin.day_state(self.employee)["state"], "not_checked_in"
        )

    def test_an_open_row_today_is_checked_in(self):
        self._row(fields.Datetime.now() - timedelta(hours=1))
        self.assertEqual(
            self.Checkin.day_state(self.employee)["state"], "checked_in"
        )

    def test_a_closed_day_is_checked_out(self):
        now = fields.Datetime.now()
        self._row(now - timedelta(hours=3), now - timedelta(hours=1))
        self.assertEqual(
            self.Checkin.day_state(self.employee)["state"], "checked_out"
        )

    def test_a_row_open_since_last_week_is_stale(self):
        """THE case from 2026-09-26. Reported as its own state, not as an error.

        Until it is closed, hr.attendance's own constraint refuses every new
        check-in -- so the app has to be able to say so before the user presses
        a button that cannot work.
        """
        session = self._row(fields.Datetime.now() - timedelta(days=3))
        self.assertTrue(self.Checkin.is_stale(session))
        self.assertEqual(
            self.Checkin.day_state(self.employee)["state"], "checked_in_stale"
        )

    def test_a_night_shift_across_midnight_is_not_stale(self):
        """Crossing midnight is a night shift, not a mistake.

        The cutoff is the start of yesterday for exactly this reason. Treating
        any pre-today row as stale would flag every night-shift worker every
        morning.
        """
        session = self._row(fields.Datetime.now() - timedelta(hours=10))
        self.assertFalse(self.Checkin.is_stale(session))

    # -- ordering --------------------------------------------------------
    def test_sessions_come_back_in_chronological_order(self):
        """The app renders "first check-in -> last check-out".

        Built from a descending search, a two-session day printed its range
        backwards -- "5:57 AM -> 5:53 AM" -- which reads as corrupt data.
        """
        now = fields.Datetime.now()
        self._row(now - timedelta(hours=6), now - timedelta(hours=4))
        self._row(now - timedelta(hours=3), now - timedelta(hours=1))

        sessions = self.Checkin.day_state(self.employee)["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertLess(
            sessions[0]["check_in"],
            sessions[1]["check_in"],
            "sessions must be chronological or the day range renders backwards",
        )
        self.assertLess(sessions[0]["check_in"], sessions[-1]["check_out"])

    # -- resolving -------------------------------------------------------
    def test_resolving_closes_at_the_end_of_that_day_not_now(self):
        """The whole point of the resolver.

        Closing a Thursday session on Saturday at ``now`` records a 48-hour
        shift, and worked_hours and overtime consume that without complaint.
        """
        started = fields.Datetime.now() - timedelta(days=3)
        session = self._row(started)

        closed = self.Checkin.resolve_stale(self.employee)
        self.assertTrue(closed)
        self.assertEqual(closed, session)
        self.assertTrue(session.check_out)

        hours = (session.check_out - session.check_in).total_seconds() / 3600
        self.assertLess(
            hours, 24, "a resolved session must not span whole days"
        )
        self.assertGreater(hours, 0)
        self.assertEqual(session.out_mode, "auto_check_out")

    def test_resolving_is_idempotent(self):
        """Two taps on a slow connection must not fail the second time."""
        self._row(fields.Datetime.now() - timedelta(days=3))
        self.assertTrue(self.Checkin.resolve_stale(self.employee))
        self.assertFalse(self.Checkin.resolve_stale(self.employee))

    def test_resolving_leaves_a_healthy_session_alone(self):
        """Somebody at work right now must not be checked out from under them."""
        session = self._row(fields.Datetime.now() - timedelta(hours=1))
        self.assertFalse(self.Checkin.resolve_stale(self.employee))
        self.assertFalse(session.check_out)

    def test_a_resolved_session_frees_the_next_check_in(self):
        """The reason any of this matters.

        While the row is open the constraint refuses every new row, so the
        employee cannot start work.
        """
        self._row(fields.Datetime.now() - timedelta(days=3))
        self.Checkin.resolve_stale(self.employee)

        self.employee.invalidate_recordset(["attendance_state"])
        result = self.Checkin.record_sign_in(self.user, company=self.company)
        self.assertIn(result["status"], ("recorded", "already_today"))

# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Breaks, and the hour they must not charge twice.

The trap these exist for: ``hr_attendance``'s own ``_compute_worked_hours``
already subtracts the *scheduled* lunch from the resource calendar for any
non-flexible employee. Subtracting recorded breaks on top of that bills the
same hour twice, and the only symptom is somebody's pay being quietly short.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceBreak(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({"name": "Break Co"})
        self.user = self.env["res.users"].create(
            {
                "name": "Break Tester",
                "login": "break.tester@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.company.id,
                "company_ids": [(6, 0, [self.company.id])],
            }
        )
        # A flexible calendar, so Odoo's own lunch deduction is out of the
        # picture and these tests measure only what this module does. The
        # interaction with a scheduled lunch has its own test below.
        self.calendar = self.env["resource.calendar"].create(
            {
                "name": "Break Co Flexible",
                "company_id": self.company.id,
                "flexible_hours": True,
            }
        )
        self.employee = self.env["hr.employee"].create(
            {
                "name": "Break Tester",
                "user_id": self.user.id,
                "company_id": self.company.id,
                "resource_calendar_id": self.calendar.id,
            }
        )

    def _session(self, hours=8):
        """A closed session of `hours` length, ending now."""
        end = fields.Datetime.now()
        return self.env["hr.attendance"].create(
            {
                "employee_id": self.employee.id,
                "check_in": end - timedelta(hours=hours),
                "check_out": end,
            }
        )

    # -- the arithmetic --------------------------------------------------
    def test_a_session_with_no_breaks_is_untouched(self):
        """Every existing record, and every deployment not using this."""
        session = self._session(hours=8)
        self.assertAlmostEqual(session.worked_hours, 8.0, places=2)
        self.assertAlmostEqual(session.break_hours, 0.0, places=2)

    def test_a_recorded_break_is_deducted(self):
        session = self._session(hours=8)
        start = session.check_in + timedelta(hours=4)
        self.env["hr.attendance.break"].create(
            {
                "attendance_id": session.id,
                "break_start": start,
                "break_end": start + timedelta(minutes=30),
            }
        )
        session.invalidate_recordset(["worked_hours", "break_hours"])
        self.assertAlmostEqual(session.break_hours, 0.5, places=2)
        self.assertAlmostEqual(session.worked_hours, 7.5, places=2)

    def test_two_breaks_both_count(self):
        session = self._session(hours=8)
        first = session.check_in + timedelta(hours=2)
        second = session.check_in + timedelta(hours=5)
        Break = self.env["hr.attendance.break"]
        Break.create({
            "attendance_id": session.id,
            "break_start": first,
            "break_end": first + timedelta(minutes=15),
        })
        Break.create({
            "attendance_id": session.id,
            "break_start": second,
            "break_end": second + timedelta(minutes=45),
        })
        session.invalidate_recordset(["worked_hours", "break_hours"])
        self.assertAlmostEqual(session.break_hours, 1.0, places=2)
        self.assertAlmostEqual(session.worked_hours, 7.0, places=2)

    def test_a_running_break_deducts_nothing_yet(self):
        """Otherwise worked_hours falls while somebody watches it.

        And a break nobody remembers to end would eat the whole day.
        """
        session = self._session(hours=8)
        self.env["hr.attendance.break"].create(
            {
                "attendance_id": session.id,
                "break_start": session.check_in + timedelta(hours=4),
            }
        )
        session.invalidate_recordset(["worked_hours", "break_hours"])
        self.assertAlmostEqual(session.break_hours, 0.0, places=2)
        self.assertAlmostEqual(session.worked_hours, 8.0, places=2)
        self.assertTrue(session.has_open_break)

    def test_worked_hours_never_goes_negative(self):
        """Belt to the constraints' braces: a negative feeds overtime."""
        session = self._session(hours=1)
        self.env["hr.attendance.break"].create(
            {
                "attendance_id": session.id,
                "break_start": session.check_in,
                "break_end": session.check_out,
            }
        )
        session.invalidate_recordset(["worked_hours"])
        self.assertGreaterEqual(session.worked_hours, 0.0)

    # -- THE trap --------------------------------------------------------
    def test_a_scheduled_lunch_is_not_charged_on_top_of_a_real_break(self):
        """Recorded breaks REPLACE the calendar lunch; they do not add to it.

        A non-flexible calendar makes Odoo subtract its scheduled lunch. If
        this module then also subtracted the recorded break, an employee who
        took one hour would lose two — and nothing on any screen would say so.

        The assertion is deliberately loose about the exact figure and strict
        about the thing that matters: the deduction is the break, once.
        """
        rigid = self.env["resource.calendar"].create(
            {"name": "Break Co Standard", "company_id": self.company.id}
        )
        self.employee.resource_calendar_id = rigid

        session = self._session(hours=8)
        gross = 8.0
        start = session.check_in + timedelta(hours=4)
        self.env["hr.attendance.break"].create(
            {
                "attendance_id": session.id,
                "break_start": start,
                "break_end": start + timedelta(hours=1),
            }
        )
        session.invalidate_recordset(["worked_hours", "break_hours"])

        self.assertAlmostEqual(session.break_hours, 1.0, places=2)
        self.assertAlmostEqual(
            session.worked_hours,
            gross - 1.0,
            places=2,
            msg="the scheduled lunch was deducted as well as the real break",
        )

    # -- the guards ------------------------------------------------------
    def test_a_break_cannot_end_before_it_starts(self):
        session = self._session(hours=8)
        with self.assertRaises(ValidationError):
            self.env["hr.attendance.break"].create(
                {
                    "attendance_id": session.id,
                    "break_start": session.check_in + timedelta(hours=4),
                    "break_end": session.check_in + timedelta(hours=3),
                }
            )

    def test_a_break_cannot_escape_its_session(self):
        session = self._session(hours=8)
        with self.assertRaises(ValidationError):
            self.env["hr.attendance.break"].create(
                {
                    "attendance_id": session.id,
                    "break_start": session.check_in - timedelta(hours=1),
                    "break_end": session.check_in,
                }
            )

    def test_overlapping_breaks_are_refused(self):
        """Overlaps are double-counted by the sum, which under-pays."""
        session = self._session(hours=8)
        start = session.check_in + timedelta(hours=2)
        Break = self.env["hr.attendance.break"]
        Break.create({
            "attendance_id": session.id,
            "break_start": start,
            "break_end": start + timedelta(hours=1),
        })
        with self.assertRaises(ValidationError):
            Break.create({
                "attendance_id": session.id,
                "break_start": start + timedelta(minutes=30),
                "break_end": start + timedelta(minutes=90),
            })

    # -- the helpers the endpoint uses -----------------------------------
    def test_start_and_end_through_the_helpers(self):
        session = self.env["hr.attendance"].create(
            {
                "employee_id": self.employee.id,
                "check_in": fields.Datetime.now() - timedelta(hours=2),
            }
        )
        record = session.start_break(break_type="meal", source="mobile")
        self.assertEqual(record.break_type, "meal")
        self.assertFalse(record.break_end)
        self.assertTrue(session.has_open_break)

        ended = session.end_break()
        self.assertEqual(ended, record)
        self.assertTrue(ended.break_end)
        session.invalidate_recordset(["has_open_break"])
        self.assertFalse(session.has_open_break)

    def test_two_breaks_cannot_run_at_once(self):
        session = self.env["hr.attendance"].create(
            {
                "employee_id": self.employee.id,
                "check_in": fields.Datetime.now() - timedelta(hours=2),
            }
        )
        session.start_break()
        session.invalidate_recordset(["has_open_break"])
        with self.assertRaises(ValidationError):
            session.start_break()

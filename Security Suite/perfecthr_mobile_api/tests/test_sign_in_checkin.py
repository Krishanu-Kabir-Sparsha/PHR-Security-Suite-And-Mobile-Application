# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Attendance recorded at sign-in, and the cases where it must not be.

The lunch-break case is the one this file exists for. "Check in if not checked
in" looks obviously right and is wrong: after a lunch check-out the employee is
not checked in, so glancing at the app at 14:00 would invent an afternoon
session. Deriving from "has today got anything on it" is what makes that
impossible, and the test below is what keeps it that way.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSignInCheckin(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Checkin = self.env["perfecthr.mobile.checkin"]
        self.company = self.env["res.company"].create({"name": "Checkin Co"})
        self.user = self.env["res.users"].create(
            {
                "name": "Attendance Tester",
                "login": "attendance.tester@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.company.id,
                "company_ids": [(6, 0, [self.company.id])],
            }
        )
        self.employee = self.env["hr.employee"].create(
            {
                "name": "Attendance Tester",
                "user_id": self.user.id,
                "company_id": self.company.id,
            }
        )

    def _record(self):
        return self.Checkin.record_sign_in(self.user, company=self.company)

    # -- the happy path ------------------------------------------------
    def test_first_sign_in_of_the_day_checks_in(self):
        result = self._record()
        self.assertEqual(result["status"], "recorded")
        self.assertTrue(result["check_in_at"])
        self.assertEqual(self.employee.attendance_state, "checked_in")

    def test_the_row_is_attributed_to_the_app(self):
        """Provenance is legible in the attendance list without a join."""
        self._record()
        attendance = self.env["hr.attendance"].search(
            [("employee_id", "=", self.employee.id)], limit=1
        )
        self.assertEqual(attendance.in_mode, "manual")
        self.assertEqual(attendance.in_browser, "Perfect HR mobile app")

    # -- the cases that must not record --------------------------------
    def test_second_sign_in_while_checked_in_does_nothing(self):
        self._record()
        result = self._record()
        self.assertEqual(result["status"], "already_in")
        self.assertEqual(
            self.env["hr.attendance"].search_count(
                [("employee_id", "=", self.employee.id)]
            ),
            1,
        )

    def test_reopening_the_app_after_lunch_does_not_check_in_again(self):
        """THE case. See the module docstring.

        Checked in this morning, checked out for lunch, now not checked in --
        and must stay that way until they choose to check in themselves.
        """
        self._record()
        attendance = self.env["hr.attendance"].search(
            [("employee_id", "=", self.employee.id)], limit=1
        )
        attendance.check_out = fields.Datetime.now()
        self.employee.invalidate_recordset(["attendance_state"])
        self.assertNotEqual(self.employee.attendance_state, "checked_in")

        result = self._record()
        self.assertEqual(result["status"], "already_today")
        self.assertEqual(
            self.env["hr.attendance"].search_count(
                [("employee_id", "=", self.employee.id)]
            ),
            1,
        )

    def test_a_kiosk_punch_earlier_today_suppresses_it(self):
        """The fingerprint terminal got there first; do not double-punch."""
        self.env["hr.attendance"].create(
            {
                "employee_id": self.employee.id,
                "check_in": fields.Datetime.now() - timedelta(hours=2),
                "check_out": fields.Datetime.now() - timedelta(hours=1),
                "in_mode": "kiosk",
            }
        )
        self.assertEqual(self._record()["status"], "already_today")

    def test_approved_leave_suppresses_it(self):
        """Being recorded present while on approved leave lands in payroll."""
        leave_type = self.env["hr.leave.type"].create(
            {
                "name": "Checkin Test Leave",
                "requires_allocation": "no",
                "company_id": self.company.id,
            }
        )
        today = fields.Date.context_today(self.user)
        leave = self.env["hr.leave"].create(
            {
                "name": "Out today",
                "employee_id": self.employee.id,
                "holiday_status_id": leave_type.id,
                "request_date_from": today,
                "request_date_to": today,
            }
        )
        leave.sudo().action_approve()
        if leave.state != "validate":
            leave.sudo().write({"state": "validate"})

        self.assertEqual(self._record()["status"], "on_leave")

    def test_company_can_switch_it_off(self):
        self.company.mobile_auto_checkin = False
        self.assertEqual(self._record()["status"], "disabled")
        self.assertFalse(
            self.env["hr.attendance"].search_count(
                [("employee_id", "=", self.employee.id)]
            )
        )

    def test_no_employee_record_is_reported_not_raised(self):
        """A user HR has not finished setting up must still get a session."""
        stranger = self.env["res.users"].create(
            {
                "name": "No Employee",
                "login": "no.employee@example.internal",
                "password": "correct-horse-battery-staple",
                "company_id": self.company.id,
                "company_ids": [(6, 0, [self.company.id])],
            }
        )
        result = self.Checkin.record_sign_in(stranger, company=self.company)
        self.assertEqual(result["status"], "no_employee")

    # -- multi-company employee resolution -----------------------------
    def test_employee_is_resolved_within_the_signed_in_company(self):
        """One user, two employments: the session's company decides which.

        An unscoped lookup returns whichever row the database ordered first,
        and every figure drawn from it then belongs to the other employment --
        silently, because nothing about it looks wrong.
        """
        other = self.env["res.company"].create({"name": "Second Employer"})
        self.user.company_ids = [(4, other.id)]
        second = self.env["hr.employee"].create(
            {
                "name": "Attendance Tester (Second)",
                "user_id": self.user.id,
                "company_id": other.id,
            }
        )

        self.assertEqual(
            self.Checkin.employee_for(self.user, self.company), self.employee
        )
        self.assertEqual(self.Checkin.employee_for(self.user, other), second)

    def test_employee_falls_back_when_none_exists_in_that_company(self):
        """Better the right person's data than an empty app."""
        other = self.env["res.company"].create({"name": "No Employees Here"})
        self.assertEqual(
            self.Checkin.employee_for(self.user, other), self.employee
        )

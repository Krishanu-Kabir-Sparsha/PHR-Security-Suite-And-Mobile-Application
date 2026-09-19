# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""GET /api/mobile/v1/me/home -- the E-01 Employee Home aggregate.

One endpoint rather than six, because a home screen that fans out is slow on the
target market's networks and cannot be cached coherently. The client caches the
whole response under `CachePolicy.dashboard` (2 minutes); six responses would
have six independent ages and the "Last synchronized" line would be a fiction.

The response shape is not invented here. It is the contract already encoded in
the client's `EmployeeHomeSummary.fromJson`, down to the enum wire values, so
that model and this function must be changed together. Two of its properties are
load-bearing:

* `worked_minutes` is computed server-side and never on the client. Break
  handling, shift rules and rounding are payroll-adjacent business logic, and a
  phone must not be the place that decides how long somebody worked.
* `performance` and `ai_insight` are nullable, and null is returned here rather
  than a zero. A new joiner shown "0%" would read it as a bad score rather than
  as an absence of data, and there is no performance source wired up yet.
"""

import logging

from odoo import fields, http
from odoo.http import request

from .common import authenticated, fail, ok

_logger = logging.getLogger(__name__)

# hr.leave states that mean "waiting on somebody", which is what the PENDING
# section is for. 'validate' is approved and 'refuse'/'cancel' are finished, so
# none of them belong here.
PENDING_LEAVE_STATES = ("confirm", "validate1")


class MobileMe(http.Controller):
    def _employee(self):
        """The hr.employee for the authenticated user, or an empty recordset.

        sudo() is used for the *lookup* only: a user may read their own employee
        record but not search the employee table, and this is the one join that
        establishes "me". Everything read afterwards is scoped to this employee.
        """
        return (
            request.env["hr.employee"]
            .sudo()
            .search([("user_id", "=", request.env.user.id)], limit=1)
        )

    def _attendance(self, employee):
        """Today's attendance, in the client's AttendanceState vocabulary."""
        empty = {
            "state": "not_checked_in",
            "check_in_at": None,
            "break_started_at": None,
            "check_out_at": None,
            "worked_minutes": 0,
            "shift_label": None,
            "workplace_label": None,
        }
        if not employee:
            return empty

        today = fields.Date.context_today(request.env.user)
        records = (
            request.env["hr.attendance"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", employee.id),
                    ("check_in", ">=", fields.Datetime.to_datetime(today)),
                ],
                order="check_in asc",
            )
        )

        # An approved absence outranks the attendance table: someone on leave is
        # "on leave", not "not checked in", and showing them a Check In button
        # would invite an attendance record that contradicts their own leave.
        on_leave = (
            request.env["hr.leave"]
            .sudo()
            .search_count(
                [
                    ("employee_id", "=", employee.id),
                    ("state", "=", "validate"),
                    ("request_date_from", "<=", today),
                    ("request_date_to", ">=", today),
                ]
            )
        )
        if on_leave and not records:
            return {**empty, "state": "on_leave"}

        if not records:
            return empty

        first = records[0]
        last = records[-1]
        # Summed across the day: a check-in/check-out over lunch is two rows,
        # and reporting only the last would under-report the morning.
        worked_minutes = int(round(sum(records.mapped("worked_hours")) * 60))
        checked_out = bool(last.check_out)

        return {
            "state": "checked_out" if checked_out else "checked_in",
            "check_in_at": first.check_in,
            "break_started_at": None,  # Break tracking is not modelled yet.
            "check_out_at": last.check_out or None,
            "worked_minutes": worked_minutes,
            "shift_label": employee.resource_calendar_id.name or None,
            "workplace_label": employee.work_location_id.name or None,
        }

    def _leave_balances(self, employee):
        """Remaining days per leave type, most generous first.

        Read from hr.leave.type with the employee in context, which is how Odoo
        computes `virtual_remaining_leaves` -- allocations minus taken minus
        pending. Summing allocations by hand here would quietly disagree with
        what the same employee sees in the web client.
        """
        if not employee:
            return []
        types = (
            request.env["hr.leave.type"]
            .sudo()
            .with_context(employee_id=employee.id)
            .search([])
        )
        balances = [
            {
                "label": leave_type.name,
                "remaining_days": round(leave_type.virtual_remaining_leaves, 1),
            }
            for leave_type in types
            if leave_type.virtual_remaining_leaves
        ]
        # The client shows `leave_balances.first` in the MY HR strip and calls it
        # the primary balance, so the ordering here is the ordering on screen.
        balances.sort(key=lambda b: b["remaining_days"], reverse=True)
        return balances

    def _pending_items(self, employee):
        """The employee's own requests that are still awaiting a decision."""
        if not employee:
            return []
        leaves = (
            request.env["hr.leave"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", employee.id),
                    ("state", "in", PENDING_LEAVE_STATES),
                ],
                order="request_date_from desc",
                limit=20,
            )
        )
        return [
            {
                "id": "leave-%s" % leave.id,
                "title": leave.holiday_status_id.name or "Time Off",
                "subtitle": leave.request_date_from
                and str(leave.request_date_from)
                or "",
                "kind": "leave",
            }
            for leave in leaves
        ]

    def _unread_notifications(self, employee):
        """Activities assigned to this user and still open."""
        return (
            request.env["mail.activity"]
            .sudo()
            .search_count([("user_id", "=", request.env.user.id)])
        )

    @http.route(
        "/api/mobile/v1/me/home",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def home(self, **kwargs):
        employee = self._employee()
        if not employee:
            # 404 rather than 403. The client renders 403 as a permission wall
            # ("you are not allowed to see this"), which would be wrong and
            # alarming: the user is allowed, there is simply no employee record
            # linked to their login yet, which is an HR data task.
            return fail(
                404,
                "No employee record is linked to your account yet. "
                "Please ask HR to complete your profile.",
                code="no_employee_record",
                log="no hr.employee for uid %s" % request.env.user.id,
            )

        return ok(
            {
                "attendance": self._attendance(employee),
                "leave_balances": self._leave_balances(employee),
                # Null, not zero. No performance source is wired up, and a
                # fabricated 0% reads as a bad score. See the module docstring.
                "performance": None,
                "pending_items": self._pending_items(employee),
                # Null until there is an AI backend. The client degrades a
                # missing insight gracefully; it cannot un-say a wrong one.
                "ai_insight": None,
                "unread_notifications": self._unread_notifications(employee),
            }
        )

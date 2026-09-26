# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Recording attendance when somebody signs in on their phone.

THE RULE
--------
A completed mobile sign-in checks the employee in, **once per day**, and only
when there is nothing on today's attendance already.

"Once per day" is derived rather than remembered: if the employee has any
``hr.attendance`` row whose check-in falls today, this does nothing. That one
test covers every case that matters and needs no extra state to go stale --

    a fingerprint terminal punched them in at 08:55   -> already a row, skip
    they checked in from the kiosk in reception       -> already a row, skip
    they checked out for lunch and reopen the app     -> already a row, skip
    they sign out and back in at 21:00                -> already a row, skip

The lunch case is the one worth stating plainly. After a lunch check-out the
employee is *not* checked in, so a naive "check in if not checked in" would
punch them back in the moment they glanced at the app -- inventing an afternoon
session they never started. Deriving from "has anything happened today" makes
that impossible.

WHY IT CANNOT FAIL A SIGN-IN
----------------------------
Every failure here is swallowed and reported as ``skipped``. Attendance is
important; being able to get into the product is more important. An employee
locked out of the app because their attendance record could not be written
would be a worse outcome than a missing punch, and the punch can be corrected
by HR while a failed sign-in cannot be corrected by anyone.

This is the one place in this module where an exception is deliberately not
surfaced to the caller, and the reason is stated here rather than left as a
bare ``except``. It is still logged with its traceback.

CHECK-OUT IS NEVER AUTOMATIC
----------------------------
Signing out, or a session expiring, records nothing. A phone that loses its
token at 14:00 has not told us the person went home, and writing a check-out
from that guess would silently shorten somebody's paid day.
"""

import logging

from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# What lands in hr.attendance.in_browser, so a row's provenance is legible in
# the attendance list without joining anything. in_mode stays 'manual' because
# a person really did sign in; 'technical' is for rows the system invents.
CHECKIN_SOURCE = "Perfect HR mobile app"


class MobileCheckin(models.AbstractModel):
    _name = "perfecthr.mobile.checkin"
    _description = "Attendance Recorded at Mobile Sign-in"

    # ------------------------------------------------------------------
    # Employee resolution
    # ------------------------------------------------------------------
    @api.model
    def employee_for(self, user, company=None):
        """The user's employee record, in ``company`` when one is given.

        Multi-company tenants give one user an ``hr.employee`` **per company**,
        so a bare ``search([('user_id','=',uid)], limit=1)`` returns whichever
        the database happened to order first. That is the wrong record roughly
        half the time on any two-company tenant, and it is wrong invisibly:
        attendance, leave balances and payslips all quietly belong to the other
        employment.

        Falls back to any employee when the company-scoped lookup finds none,
        because a user whose employee record sits in a company they are signing
        into for the first time should still see their own data rather than an
        empty app.
        """
        Employee = self.env["hr.employee"].sudo()
        if company:
            scoped = Employee.search(
                [("user_id", "=", user.id), ("company_id", "=", company.id)],
                limit=1,
            )
            if scoped:
                return scoped
        return Employee.search([("user_id", "=", user.id)], limit=1)

    # ------------------------------------------------------------------
    # One definition of "am I checked in"
    # ------------------------------------------------------------------
    @api.model
    def open_session(self, employee):
        """The employee's unclosed attendance row, whenever it started.

        THE ONE DEFINITION. Everything that asks "are they checked in" asks
        this, because it is the same question Odoo's own ``_check_validity``
        constraint asks before it refuses a new row.

        There were two other answers in this module, and they disagreed.
        ``_today_state`` derived the state from *today's* rows only, while
        ``toggle`` read ``employee.attendance_state``, which is global. A row
        left open overnight made the first say "checked out" and the second say
        "checked in" -- so the app drew a Check In button, the user pressed it,
        and Odoo refused with a constraint error naming a date two days earlier.
        That is exactly the failure reported on 2026-09-26.

        Not scoped to today on purpose. A night shift legitimately spans
        midnight, and a row that is open is open regardless of which calendar
        day started it.
        """
        return (
            self.env["hr.attendance"]
            .sudo()
            .search(
                [("employee_id", "=", employee.id), ("check_out", "=", False)],
                order="check_in desc",
                limit=1,
            )
        )

    @api.model
    def is_stale(self, session):
        """True when an open row started before today and should have closed.

        Distinguished from an ordinary open row because the remedy differs. A
        session opened this morning is somebody at work; one opened on Thursday
        is somebody who forgot, and until it is closed **every** future
        check-in is refused by the constraint. Telling those apart is what lets
        the app say so before the person taps a button that cannot work.

        A night shift is not stale merely for crossing midnight, so the cutoff
        is the start of *yesterday* rather than of today.
        """
        if not session or not session.check_in:
            return False
        user = session.employee_id.user_id or self.env.user
        yesterday = fields.Date.subtract(fields.Date.context_today(user), days=1)
        return session.check_in < fields.Datetime.to_datetime(yesterday)

    @api.model
    def resolve_stale(self, employee):
        """Close a forgotten session at the end of the day it belongs to.

        The remedy for ``checked_in_stale``. Returns the closed record, or an
        empty recordset when there was nothing to close.

        **Not closed at ``now``.** That is the whole point. Toggling a Thursday
        session shut on Saturday records a 48-hour shift, and worked_hours and
        overtime consume that without complaint. Instead it closes at the
        check-in plus the hours that employee was scheduled to work that
        weekday -- the same quantity Odoo's own ``_cron_auto_check_out`` uses,
        and for the same reason.

        Stamped ``out_mode='auto_check_out'`` so nobody later mistakes it for a
        real punch, and a note is posted on the record naming who triggered it.
        Eight hours is the fallback where no calendar says otherwise; a guess
        that is visibly a guess beats leaving the row open forever, because
        while it is open the constraint refuses every future check-in.
        """
        session = self.open_session(employee)
        if not session or not self.is_stale(session):
            return self.env["hr.attendance"]

        calendar = employee.resource_calendar_id
        expected = 0.0
        if calendar:
            weekday = str(session.check_in.weekday())
            expected = sum(
                calendar.attendance_ids.filtered(
                    lambda a: a.dayofweek == weekday
                ).mapped("duration_hours")
            )
        if not expected:
            expected = 8.0

        close_at = session.check_in + timedelta(hours=expected)
        # Never in the future, and never at or before the check-in: both would
        # be rejected by hr.attendance's own constraints.
        close_at = min(close_at, fields.Datetime.now())
        close_at = max(close_at, session.check_in + timedelta(seconds=1))

        session.sudo().write(
            {"check_out": close_at, "out_mode": "auto_check_out"}
        )
        session.sudo().message_post(
            body=_(
                "Closed automatically at the end of the scheduled working day "
                "because no check-out was recorded. Requested by %(user)s from "
                "the mobile app. Correct this record if the employee worked "
                "different hours.",
                user=self.env.user.name,
            )
        )
        _logger.info(
            "Resolved stale attendance %s for %s: checked out at %s",
            session.id,
            employee.name,
            close_at,
        )
        return session

    # ------------------------------------------------------------------
    # The decision
    # ------------------------------------------------------------------
    @api.model
    def _already_recorded_today(self, employee):
        """True when today already has an attendance row for this employee.

        ``context_today`` for the employee's own user, not the server's date:
        an employee in Dhaka signing in at 00:30 local is on a different
        calendar day from a server running in UTC, and getting that wrong would
        double-punch every night shift.
        """
        today = fields.Date.context_today(employee.user_id or self.env.user)
        return bool(
            self.env["hr.attendance"]
            .sudo()
            .search_count(
                [
                    ("employee_id", "=", employee.id),
                    ("check_in", ">=", fields.Datetime.to_datetime(today)),
                ]
            )
        )

    @api.model
    def serialise_session(self, attendance):
        """One attendance row, as the app's AttendanceSession expects it."""
        return {
            "id": str(attendance.id),
            "check_in": attendance.check_in,
            "check_out": attendance.check_out or None,
            "worked_hours": round(attendance.worked_hours or 0.0, 2),
            "in_city": attendance.in_city or None,
            "out_city": attendance.out_city or None,
            "in_mode": attendance.in_mode or None,
            "out_mode": attendance.out_mode or None,
        }

    @api.model
    def day_state(self, employee):
        """Today's attendance and the state derived from it.

        The single payload behind both ``/me/home`` and ``/me/attendance``.
        They each built their own before, from slightly different rules, so the
        home screen and the attendance screen could disagree about the same
        morning.

        ``state`` is one of:

            not_checked_in    nothing today, nothing open
            checked_in        an open row that started today
            checked_in_stale  an open row from before yesterday -- they forgot
            checked_out       today has rows and none is open
            on_leave          approved absence covers today and nothing is open

        ``checked_in_stale`` is the case that used to surface as a raw Odoo
        constraint error *after* the user pressed Check In. Reporting it as a
        state lets the app explain it beforehand and offer the remedy.
        """
        if not employee:
            return {
                "state": "not_checked_in",
                "check_in_at": None,
                "check_out_at": None,
                "break_started_at": None,
                "worked_minutes": 0,
                "open_since": None,
                "sessions": [],
            }

        user = employee.user_id or self.env.user
        today = fields.Date.context_today(user)
        records = (
            self.env["hr.attendance"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", employee.id),
                    ("check_in", ">=", fields.Datetime.to_datetime(today)),
                ],
                # Ascending, and it matters. The app renders a day as
                # "first check-in -> last check-out", so a descending list
                # printed the range backwards: a two-session day showed
                # "5:57 AM -> 5:53 AM".
                order="check_in asc",
            )
        )

        session = self.open_session(employee)
        stale = self.is_stale(session)

        if session:
            state = "checked_in_stale" if stale else "checked_in"
        elif records:
            state = "checked_out"
        elif self._on_approved_leave(employee):
            state = "on_leave"
        else:
            state = "not_checked_in"

        # Summed across the day. A lunch break is two rows, and reporting only
        # the last would under-report the morning.
        worked = int(round(sum(records.mapped("worked_hours")) * 60))
        closed = records.filtered("check_out")

        return {
            "state": state,
            "check_in_at": records[0].check_in if records else (
                session.check_in if session else None
            ),
            "check_out_at": closed[-1].check_out if closed else None,
            # Populated by the break feature; null while no break is running.
            "break_started_at": self._break_started_at(session),
            "worked_minutes": worked,
            # When the open row started, so a stale session can name its own
            # date rather than making the reader work it out.
            "open_since": session.check_in if session else None,
            "sessions": [self.serialise_session(r) for r in records],
        }

    @api.model
    def _break_started_at(self, session):
        """When the running break began, or None.

        Split out so the attendance payload does not have to know whether
        break tracking is installed. Returns None until it is.
        """
        if not session or "hr.attendance.break" not in self.env:
            return None
        running = (
            self.env["hr.attendance.break"]
            .sudo()
            .search(
                [("attendance_id", "=", session.id), ("break_end", "=", False)],
                order="break_start desc",
                limit=1,
            )
        )
        return running.break_start if running else None

    @api.model
    def _on_approved_leave(self, employee):
        """True when an approved absence covers today.

        Somebody on approved leave who opens the app to check their balance
        must not thereby be recorded as present. That contradiction lands in
        payroll, and it is the employee who has to argue it back.
        """
        today = fields.Date.context_today(employee.user_id or self.env.user)
        return bool(
            self.env["hr.leave"]
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

    # ------------------------------------------------------------------
    # The action
    # ------------------------------------------------------------------
    @api.model
    def record_sign_in(self, user, company=None, source_ip=None, auth_mode=None):
        """Check ``user`` in if today has nothing on it yet.

        Returns a dict the sign-in response embeds verbatim, always with a
        ``status`` the app can render:

            recorded       an attendance row was created, ``check_in_at`` set
            already_in     they were checked in already
            already_today  today has attendance from a kiosk, device or app
            on_leave       approved absence covers today
            disabled       the company has auto check-in switched off
            no_employee    no hr.employee is linked to this account
            skipped        it could not be done; the sign-in is unaffected

        Never raises. See the module docstring.
        """
        employee = self.employee_for(user, company)
        if not employee:
            return {"status": "no_employee", "check_in_at": None}

        # The employee's own company decides, not the one being signed into.
        # They are the same in every ordinary case; where they differ, the
        # employment record is the one that owns the attendance policy.
        policy_company = employee.company_id or company
        if policy_company and not policy_company.mobile_auto_checkin:
            return {"status": "disabled", "check_in_at": None}

        if employee.attendance_state == "checked_in":
            return {
                "status": "already_in",
                "check_in_at": employee.last_attendance_id.check_in,
            }

        if self._already_recorded_today(employee):
            return {"status": "already_today", "check_in_at": None}

        if self._on_approved_leave(employee):
            return {"status": "on_leave", "check_in_at": None}

        try:
            # Same entry point as the kiosk, the systray and the biometric
            # gateway. Creating the hr.attendance row directly would skip the
            # overtime recompute and the state machine that hr_attendance
            # extensions hook, and a mobile punch has to be the same kind of
            # event as a device punch or the two disagree about the same day.
            #
            # Both guards above have already established that the employee is
            # not checked in, so this method can only take its create branch.
            # It is a toggle, and calling it while checked in would check them
            # *out* -- which is why neither guard is optional.
            attendance = employee.sudo()._attendance_action_change(
                geo_information={
                    "mode": "manual",
                    "ip_address": source_ip,
                    "browser": CHECKIN_SOURCE,
                }
                if source_ip
                else {"mode": "manual", "browser": CHECKIN_SOURCE}
            )
        except Exception:  # noqa: BLE001 - a sign-in must never fail over this
            _logger.exception(
                "Automatic check-in failed for %s; the sign-in itself is "
                "unaffected and the employee can check in from the app.",
                user.login,
            )
            return {"status": "skipped", "check_in_at": None}

        _logger.info(
            "Mobile sign-in checked %s in (%s authentication)",
            user.login,
            auth_mode or "unknown",
        )
        return {
            "status": "recorded",
            "check_in_at": attendance.check_in if attendance else None,
            # Rendered on the home screen as confirmation. Written here rather
            # than on the client so one server decides the wording and a future
            # policy change does not need an app release.
            "message": _("You were checked in automatically."),
        }

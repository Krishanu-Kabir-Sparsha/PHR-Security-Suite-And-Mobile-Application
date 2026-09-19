# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Attendance: today's state, check in and out, and month history.

**Check-in and check-out go through ``_attendance_action_change``**, the same
method the web client and the kiosk call. Creating the ``hr.attendance`` record
by hand here would be shorter and wrong: that method is where overlap handling
and the ``attendance_state`` recompute live, and anything installed on top of
``hr_attendance`` -- ``hr_attendance_gateway`` on this deployment, which
reconciles biometric device punches -- extends that path rather than the model's
``create``. A mobile punch has to be the same kind of event as a device punch or
the two will disagree about the same day.

**The server decides the direction, not the client.** The request says "toggle",
not "check me in": a phone that has been offline for an hour does not know
whether a kiosk punch has happened since, and a client-chosen direction would
produce a double check-in. The response reports which way it went.

**Location is optional and never required.** It is recorded when the phone
offers it, because attendance without any location is hard to dispute after the
fact -- but refusing a check-in for a missing GPS fix would strand anyone
indoors, on an old handset, or with location denied, and attendance is how
people get paid. Policy enforcement, if it is ever wanted, belongs in Odoo where
it can be seen and appealed, not in a silent client-side refusal.
"""

import logging

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from .common import authenticated, current_ip, fail, ok, _payload

_logger = logging.getLogger(__name__)

# A month of history is what the calendar screen shows. Capped so a client
# cannot ask for a year of rows and time the request out.
MAX_HISTORY_DAYS = 62


class MobileAttendance(http.Controller):
    def _employee(self):
        return (
            request.env["hr.employee"]
            .sudo()
            .search([("user_id", "=", request.env.user.id)], limit=1)
        )

    def _no_employee(self):
        return fail(
            404,
            "No employee record is linked to your account yet. "
            "Please ask HR to complete your profile.",
            code="no_employee_record",
            log="attendance without hr.employee for uid %s" % request.env.user.id,
        )

    def _geo_information(self, data):
        """Translate the client's payload into ``_attendance_action_change``'s.

        That method prefixes every key with ``in_``/``out_`` depending on the
        direction, so the keys here are the unprefixed field names. Only the
        ones the model actually declares are passed: an unknown key would become
        an unknown field and raise, turning a stray client value into a failed
        check-in.
        """
        allowed = ("latitude", "longitude", "city", "country_name")
        geo = {}
        for key in allowed:
            value = data.get(key)
            if value in (None, ""):
                continue
            if key in ("latitude", "longitude"):
                try:
                    geo[key] = float(value)
                except (TypeError, ValueError):
                    continue
            else:
                geo[key] = str(value)[:128]

        if geo:
            geo["ip_address"] = current_ip()
            # 'manual' is the honest value. 'kiosk' is a shared unattended
            # device and 'systray' is the desktop client; labelling a phone punch
            # as either would misreport how attendance was captured in reports
            # that exist precisely to tell them apart.
            geo["mode"] = "manual"
        return geo or None

    def _serialise(self, attendance):
        return {
            "id": str(attendance.id),
            "check_in": attendance.check_in,
            "check_out": attendance.check_out or None,
            "worked_hours": round(attendance.worked_hours or 0.0, 2),
            "in_city": attendance.in_city or None,
            "out_city": attendance.out_city or None,
        }

    def _today_state(self, employee):
        """Today's rows plus the derived state the client's model expects."""
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

        if not records:
            return {
                "state": "on_leave" if on_leave else "not_checked_in",
                "check_in_at": None,
                "check_out_at": None,
                "worked_minutes": 0,
                "sessions": [],
            }

        last = records[-1]
        return {
            "state": "checked_out" if last.check_out else "checked_in",
            "check_in_at": records[0].check_in,
            "check_out_at": last.check_out or None,
            # Summed across the day. A lunch break is two rows, and reporting
            # only the last would under-report the morning.
            "worked_minutes": int(round(sum(records.mapped("worked_hours")) * 60)),
            "sessions": [self._serialise(record) for record in records],
        }

    @http.route(
        "/api/mobile/v1/me/attendance",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def attendance(self, days=None, **kwargs):
        """Today's state plus recent history, for the calendar and the list."""
        employee = self._employee()
        if not employee:
            return self._no_employee()

        try:
            window = min(int(days or 31), MAX_HISTORY_DAYS)
        except (TypeError, ValueError):
            window = 31
        window = max(window, 1)

        since = fields.Date.subtract(
            fields.Date.context_today(request.env.user), days=window
        )
        history = (
            request.env["hr.attendance"]
            .sudo()
            .search(
                [
                    ("employee_id", "=", employee.id),
                    ("check_in", ">=", fields.Datetime.to_datetime(since)),
                ],
                order="check_in desc",
            )
        )

        # Grouped by calendar day, which is what a month grid renders. Doing it
        # here rather than on the client keeps one definition of "a day's work"
        # -- the phone's timezone must not be what decides which day a late
        # evening punch belongs to.
        by_day = {}
        for record in history:
            day = str(fields.Datetime.context_timestamp(
                record, record.check_in
            ).date())
            entry = by_day.setdefault(
                day, {"date": day, "worked_minutes": 0, "sessions": []}
            )
            entry["worked_minutes"] += int(round((record.worked_hours or 0) * 60))
            entry["sessions"].append(self._serialise(record))

        return ok(
            {
                "today": self._today_state(employee),
                "shift_label": employee.resource_calendar_id.name or None,
                "workplace_label": employee.work_location_id.name or None,
                "days": sorted(by_day.values(), key=lambda d: d["date"], reverse=True),
            }
        )

    @http.route(
        "/api/mobile/v1/me/attendance/toggle",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def toggle(self, **kwargs):
        """Check in if out, check out if in. The server decides which.

        See the module docstring: a client that picks the direction will
        eventually pick the wrong one, because it cannot see punches made
        elsewhere since it last synchronised.
        """
        employee = self._employee()
        if not employee:
            return self._no_employee()

        data = _payload() or kwargs
        was_checked_in = employee.attendance_state == "checked_in"

        try:
            # Not sudo. The employee's own rights are what should permit this,
            # and hr_attendance already grants a user rights over their own
            # records. Punching in with elevated rights would also bypass the
            # suite's Record Freeze guard on a frozen period.
            employee.with_user(request.env.user)._attendance_action_change(
                geo_information=self._geo_information(data)
            )
        except AccessError:
            return fail(
                403,
                "You are not allowed to record attendance for this employee.",
                code="attendance_forbidden",
                log="attendance AccessError for uid %s" % request.env.user.id,
            )
        except (UserError, ValidationError) as error:
            # Odoo's own rule violations -- an overlapping record, or a frozen
            # period from sec_record_freeze. These messages are written for
            # people and are safe to forward; the client renders them as a
            # validation failure rather than a crash.
            return fail(
                422,
                str(error),
                code="attendance_rejected",
                log="attendance rejected for %s: %s" % (request.env.user.login, error),
            )

        employee.invalidate_recordset(["attendance_state", "last_attendance_id"])
        _logger.info(
            "Mobile attendance %s: %s",
            "check-out" if was_checked_in else "check-in",
            request.env.user.login,
        )

        return ok(
            {
                "direction": "check_out" if was_checked_in else "check_in",
                "today": self._today_state(employee),
            }
        )

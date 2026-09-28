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

from .common import (
    authenticated,
    current_ip,
    fail,
    ok,
    request_employee,
    _payload,
)

_logger = logging.getLogger(__name__)

# A month of history is what the calendar screen shows. Capped so a client
# cannot ask for a year of rows and time the request out.
MAX_HISTORY_DAYS = 62


class MobileAttendance(http.Controller):
    def _employee(self):
        """The employee record for this session, scoped to its company.

        Shared definition in common.request_employee -- a multi-company tenant
        gives one user an hr.employee per company, and an unscoped lookup
        returns whichever the database ordered first.
        """
        return request_employee()

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

    def _service(self):
        return request.env["perfecthr.mobile.checkin"].sudo()

    def _evaluate_location(self, employee, data):
        """Run the location check, unless the caller already explained itself.

        A payload carrying ``off_site_reason`` is the second attempt: the user
        has been told they look far from work and has said why. That is
        accepted and flagged rather than refused again -- refusing a reason
        that was asked for would be a dead end.
        """
        reason = (data.get("off_site_reason") or "").strip()
        result = (
            request.env["perfecthr.attendance.geofence"]
            .sudo()
            .evaluate(
                employee,
                self._as_float(data.get("latitude")),
                self._as_float(data.get("longitude")),
                accuracy_m=self._as_float(data.get("accuracy_m")),
            )
        )
        if reason and result["outcome"] == "refuse":
            return {**result, "outcome": "flag"}
        return result

    def _flag_off_site(self, employee, fence, data):
        """Mark the row just created as an off-site punch, for HR review."""
        session = self._service().open_session(employee)
        if not session:
            return
        reason = (data.get("off_site_reason") or "").strip()
        session.sudo().write(
            {
                "off_site": True,
                "off_site_reason": reason[:1000] or False,
                "off_site_distance_m": fence.get("distance_m") or 0,
            }
        )
        _logger.info(
            "Off-site check-in recorded for %s at %sm from %s",
            employee.name,
            fence.get("distance_m"),
            fence.get("location_name"),
        )

    @staticmethod
    def _as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _distance_label(metres):
        """A distance a person can picture, rather than a bare number."""
        if not metres:
            return "some distance"
        if metres < 1000:
            return "%d metres" % int(round(metres / 10.0) * 10)
        return "%.1f km" % (metres / 1000.0)

    def _serialise(self, attendance):
        return self._service().serialise_session(attendance)

    def _today_state(self, employee):
        """Today's attendance and state, from the one shared definition.

        Was computed here from today's rows alone, while ``toggle`` below read
        ``employee.attendance_state``. The two disagreed whenever a row stayed
        open overnight, which is how a Check In button came to be drawn for
        somebody Odoo considered already checked in. See
        ``perfecthr.mobile.checkin.day_state``.
        """
        return self._service().day_state(employee)

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
                # ASCENDING, and the direction is load-bearing. The app renders
                # a day as "first check-in -> last check-out", reading
                # sessions.first and sessions.last. Built from a descending
                # search, a two-session day printed its range backwards --
                # "5:57 AM -> 5:53 AM" -- which reads as corrupt data rather
                # than as a sort order.
                #
                # The DAY list is still newest-first; that is the sort at the
                # bottom of this method, and it is a different question from
                # the order of sessions within a day.
                order="check_in asc",
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
        "/api/mobile/v1/me/attendance/break",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def toggle_break(self, **kwargs):
        """Start or end a break inside the current session.

        A toggle, for the same reason the check-in is: the phone may have been
        offline while the break was ended somewhere else, and a client that
        picks the direction eventually picks the wrong one.

        A break is recorded **inside** the attendance rather than as a
        check-out and a check-back-in. Two rows would say "left and came back"
        and lose the distinction between a tea break and going home early --
        see ``models/attendance_break.py``.
        """
        employee = self._employee()
        if not employee:
            return self._no_employee()

        data = _payload() or kwargs
        session = self._service().open_session(employee)
        if not session:
            return fail(
                409,
                "You are not checked in, so there is no session to take a "
                "break from.",
                code="not_checked_in",
                log="break toggled while checked out by %s"
                % request.env.user.login,
            )

        running = session.break_ids.filtered(lambda b: not b.break_end)
        try:
            if running:
                session.sudo().end_break()
                direction = "break_end"
            else:
                session.sudo().start_break(
                    break_type=data.get("break_type") or "short",
                    source="mobile",
                )
                direction = "break_start"
        except (UserError, ValidationError) as error:
            return fail(
                422,
                str(error),
                code="break_rejected",
                log="break rejected for %s: %s" % (request.env.user.login, error),
            )

        session.invalidate_recordset(["break_hours", "has_open_break",
                                      "worked_hours"])
        _logger.info(
            "Mobile break %s: %s", direction, request.env.user.login
        )
        return ok(
            {
                "direction": direction,
                "today": self._today_state(employee),
            }
        )

    @http.route(
        "/api/mobile/v1/me/attendance/resolve-stale",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def resolve_stale(self, **kwargs):
        """Close a session left open on an earlier day.

        The way out of ``stale_session``. Closes at the end of the scheduled
        working day the session belongs to rather than at now -- see
        ``perfecthr.mobile.checkin.resolve_stale`` for why that distinction is
        the whole point.

        Idempotent: nothing open, or nothing stale, is a success with
        ``resolved: false`` rather than an error. Two taps on a slow connection
        must not produce a failure the second time.
        """
        employee = self._employee()
        if not employee:
            return self._no_employee()

        try:
            closed = self._service().resolve_stale(employee)
        except (UserError, ValidationError) as error:
            return fail(
                422,
                str(error),
                code="resolve_failed",
                log="stale resolve failed for %s: %s"
                % (request.env.user.login, error),
            )

        employee.invalidate_recordset(["attendance_state", "last_attendance_id"])
        return ok(
            {
                "resolved": bool(closed),
                "closed_at": closed.check_out if closed else None,
                "today": self._today_state(employee),
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
        service = self._service()

        # The same question the display asked, answered the same way. This read
        # `employee.attendance_state` while `_today_state` derived its own
        # answer from today's rows; the two disagreed across midnight, so the
        # screen offered Check In while the server was about to check out.
        session = service.open_session(employee)
        was_checked_in = bool(session)

        # A row left open for days is refused here rather than toggled, and the
        # reason is payroll rather than tidiness. The toggle would check them
        # out at *now*, turning a forgotten Thursday into a 48-hour shift and
        # feeding that straight into worked_hours and overtime.
        #
        # Refusing also cannot strand anybody, because the remedy is an
        # endpoint away: /me/attendance/resolve-stale closes it at the end of
        # the day it belongs to. Until it is closed the database constraint
        # refuses every new check-in anyway, so the alternative is not "carry
        # on" but "a raw constraint error naming a date from last week".
        if session and service.is_stale(session):
            return fail(
                409,
                "You are still checked in from %s. Close that session before "
                "checking in again." % session.check_in.strftime("%A %d %B"),
                code="stale_session",
                errors={"open_since": str(session.check_in)},
                log="stale open attendance %s for %s since %s"
                % (session.id, request.env.user.login, session.check_in),
            )

        # An unfinished break cannot be deducted from the session, so a
        # check-out on top of one would silently pay for the break. Refused
        # with the remedy named, rather than accepted and corrected later by
        # somebody reading a timesheet.
        if was_checked_in and session.has_open_break:
            return fail(
                409,
                "You are on a break. End the break before checking out, so "
                "your hours are recorded correctly.",
                code="break_running",
                log="check-out during break by %s" % request.env.user.login,
            )

        # Where they are, when they are starting work. Never checked on the
        # way out: somebody who has left the site has, if anything, finished
        # working, and refusing their check-out would leave a session open
        # that the constraint then blocks tomorrow's check-in with.
        fence = {"outcome": "allow", "distance_m": None}
        if not was_checked_in:
            fence = self._evaluate_location(employee, data)
            if fence["outcome"] == "refuse":
                return fail(
                    403,
                    "You seem to be about %(distance)s away from %(place)s. "
                    "If you are working away from there, send this again with "
                    "a short reason and it will be recorded."
                    % {
                        "distance": self._distance_label(fence["distance_m"]),
                        "place": fence["location_name"],
                    },
                    code="off_site",
                    errors={
                        "distance_m": fence["distance_m"],
                        "radius_m": fence["radius_m"],
                        "location_name": fence["location_name"],
                        # The client shows a reason field and resends with
                        # off_site_reason. Named here so the app does not have
                        # to hard-code the contract.
                        "requires": "off_site_reason",
                    },
                    log="off-site check-in refused for %s at %sm"
                    % (request.env.user.login, fence["distance_m"]),
                )

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

        # Stamped after the fact rather than passed into the punch, because
        # _attendance_action_change only forwards the geo keys hr.attendance
        # declares and would raise on an unknown one. The flag is the real
        # output of the location check -- see models/attendance_geofence.py --
        # so it has to land on the row whether the punch was allowed outright
        # or accepted on the strength of a reason.
        if not was_checked_in and fence["outcome"] in ("flag", "refuse"):
            self._flag_off_site(employee, fence, data)

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

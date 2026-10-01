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
        """Run the location check on the position the client sent.

        Nothing here inspects a reason any more. A reason used to turn a
        refusal into an acceptance on this very call, which meant the employee
        authorised their own exception -- see the note at the refusal in
        ``toggle``. The reason now travels to
        ``POST /me/attendance/offsite-request`` and waits for a manager.
        """
        return (
            request.env["perfecthr.attendance.geofence"]
            .sudo()
            .evaluate(
                employee,
                self._as_float(data.get("latitude")),
                self._as_float(data.get("longitude")),
                accuracy_m=self._as_float(data.get("accuracy_m")),
            )
        )

    @staticmethod
    def _refusal_message(fence):
        """The sentence the employee reads when a punch is refused.

        Delegated to the model so the app, the web dashboard and the Odoo
        backend all say the same thing. Three refusals need three different
        remedies -- turn location on, move somewhere with a clearer sky, or
        ask your manager -- and a single message would send two thirds of
        people to the wrong one.
        """
        return request.env["hr.attendance"]._geofence_refusal_message(fence)

    def _flag_off_site(self, employee, fence):
        """Mark the row just created as an off-site punch, for HR review."""
        session = self._service().open_session(employee)
        if not session:
            return
        session.sudo().write(
            {
                "off_site": True,
                # No reason under WARN: nobody was asked for one, and an empty
                # string here would read in the backend as "they declined to
                # explain" rather than "we never asked".
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
                # Refused, and that is the end of this punch.
                #
                # It used to be the start of a negotiation: the app asked for a
                # reason and resent, and the punch was accepted on the strength
                # of whatever was typed. That made the radius a prompt rather
                # than a control -- anybody willing to write a sentence was
                # through it. Now the employee asks their MANAGER, and nothing
                # is recorded until somebody other than the subject agrees.
                return fail(
                    403,
                    self._refusal_message(fence),
                    code="off_site",
                    errors={
                        "reason": fence["reason"],
                        "distance_m": fence["distance_m"],
                        "radius_m": fence["radius_m"],
                        "location_name": fence["location_name"],
                        # The contract with the client: POST the reason to
                        # /me/attendance/offsite-request, do NOT resend the
                        # punch. Named here so the app need not hard-code it.
                        "requires": "approval_request",
                    },
                    log="check-in refused for %s (%s) at %sm"
                    % (
                        request.env.user.login,
                        fence["reason"],
                        fence["distance_m"],
                    ),
                )

        try:
            # Not sudo. The employee's own rights are what should permit this,
            # and hr_attendance already grants a user rights over their own
            # records. Punching in with elevated rights would also bypass the
            # suite's Record Freeze guard on a frozen period.
            #
            # The position rides along in the context so the model-level gate
            # in attendance_geofence.py can see it. That gate is the backstop
            # for every route into attendance; this controller having already
            # evaluated the same position simply means it agrees.
            employee.with_user(request.env.user).with_context(
                perfecthr_punch_location={
                    "latitude": self._as_float(data.get("latitude")),
                    "longitude": self._as_float(data.get("longitude")),
                    "accuracy_m": self._as_float(data.get("accuracy_m")),
                }
            )._attendance_action_change(
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
            self._flag_off_site(employee, fence)

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

    # ------------------------------------------------------------------
    # Asking a manager to accept a punch made away from work
    # ------------------------------------------------------------------
    @http.route(
        "/api/mobile/v1/me/attendance/offsite-request",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def submit_offsite_request(self, **kwargs):
        """The way out of a refused check-in.

        The employee has been told they are not where they need to be. They
        say where they are and why; their manager decides. Nothing is recorded
        here -- that is the point. An approval records the check-in at the time
        of THIS call, not the time it is approved, so an afternoon decision
        does not rewrite somebody's morning.
        """
        employee = request_employee()
        if not employee:
            return fail(
                404,
                "Your login is not linked to an employee file yet, so "
                "attendance cannot be recorded for you. Ask HR to finish "
                "setting up your profile.",
                code="no_employee",
            )

        data = _payload() or kwargs
        reason = (data.get("reason") or "").strip()
        if len(reason) < 3:
            return fail(
                422,
                "Please say where you are and what you are doing.",
                code="reason_required",
                errors={"reason": "Required."},
            )

        # Re-evaluated here rather than trusted from the client. The position
        # on the request is what a manager will judge, and a client that could
        # supply its own distance could supply a flattering one.
        fence = self._evaluate_location(employee, data)

        if fence["outcome"] == "allow":
            # They are in range after all -- the fix improved while they typed,
            # which happens constantly as a phone settles. Sending this to a
            # manager would waste both their time.
            return fail(
                409,
                "You are within range of your work location now. Close this "
                "and check in as usual.",
                code="in_range_now",
                log="offsite request abandoned, now in range: %s"
                % request.env.user.login,
            )

        record = request.env["hr.attendance.offsite.request"].submit(
            employee, fence, reason
        )
        _logger.info(
            "Off-site check-in requested by %s (%s, %sm)",
            request.env.user.login, fence["reason"], fence.get("distance_m"),
        )
        return ok(
            {
                "request": record._payload(),
                "message": _manager_sentence(record),
            }
        )

    @http.route(
        "/api/mobile/v1/me/attendance/offsite-request",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def my_offsite_request(self, **kwargs):
        """The most recent request, so the app can say what became of it.

        Without this the employee sends a request into silence and has no way
        to tell a pending one from a rejected one except by trying to check in
        again and being refused a second time.
        """
        employee = request_employee()
        if not employee:
            return ok({"request": None})

        record = (
            request.env["hr.attendance.offsite.request"]
            .sudo()
            .search([("employee_id", "=", employee.id)], order="id desc", limit=1)
        )
        return ok({"request": record._payload() if record else None})


def _manager_sentence(record):
    """Who the employee should expect to hear from.

    Named rather than left as "your manager", because an employee whose record
    has no manager set would otherwise be told to wait on somebody who does
    not exist. In that case HR is the honest answer.
    """
    manager = record.manager_id.name
    if manager:
        return (
            "Sent to %s. Your check-in will be recorded from the time you "
            "asked, once it is approved." % manager
        )
    return (
        "Sent to HR. Your check-in will be recorded from the time you asked, "
        "once it is approved."
    )


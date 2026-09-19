# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Leave: balances, the user's own requests, applying, and cancelling.

**Balances come from ``hr.leave.type`` with the employee in context**, which is
how Odoo computes ``virtual_remaining_leaves`` -- allocation minus taken minus
still-pending. Summing allocations here by hand would be a second implementation
of an accrual rule that already exists, and the two would disagree the moment
anything is configured: carry-over, accrual plans, or an allocation that expires.
Someone whose phone and web client disagree about their own balance will trust
neither.

**Applying creates the record as the user, never sudo.** Odoo's leave validation
-- overlap with an existing request, exceeding the allocation, a date outside the
working calendar -- runs in ``create`` and ``_check_holidays``. Bypassing it with
sudo would let the phone book leave the web client would refuse, and the
contradiction would only surface at approval time, after the person had already
planned around it.

**Cancellation is restricted to the requester's own not-yet-approved request.**
Withdrawing something already approved has payroll and coverage consequences and
belongs in a conversation with a manager, not behind a phone button.
"""

import logging

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from .common import authenticated, fail, ok, _payload

_logger = logging.getLogger(__name__)

# States that are still waiting on somebody. 'validate' is approved, and
# 'refuse'/'cancel' are finished, so none of those belong in "pending".
PENDING_STATES = ("confirm", "validate1")

# Whether the user may still withdraw a request is NOT decided here. hr.leave
# carries a computed ``can_cancel`` -- it accounts for the validation type, the
# current state and whether the leave has already started -- and that field is
# what the web client's own Cancel button honours. Re-deriving it from a state
# list would eventually disagree with the web client about the same request.

STATE_LABELS = {
    "draft": "Draft",
    "confirm": "Waiting approval",
    "validate1": "Waiting second approval",
    "validate": "Approved",
    "refuse": "Refused",
    "cancel": "Cancelled",
}


class MobileLeave(http.Controller):
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
            log="leave without hr.employee for uid %s" % request.env.user.id,
        )

    def _balances(self, employee):
        types = (
            request.env["hr.leave.type"]
            .sudo()
            .with_context(employee_id=employee.id)
            .search([])
        )
        balances = []
        for leave_type in types:
            remaining = leave_type.virtual_remaining_leaves or 0.0
            allocated = leave_type.max_leaves or 0.0
            # A type with no allocation at all is not a balance of zero, it is
            # a type this employee does not have. Showing "0 days" invites
            # someone to apply for leave that will be refused.
            if not remaining and not allocated:
                continue
            balances.append(
                {
                    "id": str(leave_type.id),
                    "label": leave_type.name,
                    "remaining_days": round(remaining, 1),
                    "allocated_days": round(allocated, 1),
                    "taken_days": round(leave_type.leaves_taken or 0.0, 1),
                    # Whether applying needs an allocation to exist first.
                    "requires_allocation":
                        leave_type.requires_allocation == "yes"
                        if hasattr(leave_type, "requires_allocation")
                        else True,
                }
            )
        balances.sort(key=lambda b: b["remaining_days"], reverse=True)
        return balances

    def _serialise(self, leave):
        return {
            "id": str(leave.id),
            "type_id": str(leave.holiday_status_id.id),
            "type_label": leave.holiday_status_id.name or "Time Off",
            "date_from": leave.request_date_from,
            "date_to": leave.request_date_to,
            "days": leave.number_of_days,
            "state": leave.state,
            "state_label": STATE_LABELS.get(leave.state, leave.state),
            "reason": leave.name or None,
            "can_cancel": bool(leave.can_cancel),
        }

    @http.route(
        "/api/mobile/v1/me/leave",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def leave(self, **kwargs):
        employee = self._employee()
        if not employee:
            return self._no_employee()

        leaves = (
            request.env["hr.leave"]
            .sudo()
            .search(
                [("employee_id", "=", employee.id)],
                order="request_date_from desc",
                limit=50,
            )
        )

        return ok(
            {
                "balances": self._balances(employee),
                "requests": [self._serialise(leave) for leave in leaves],
                "pending_count": sum(
                    1 for leave in leaves if leave.state in PENDING_STATES
                ),
            }
        )

    @http.route(
        "/api/mobile/v1/me/leave/apply",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def apply(self, **kwargs):
        employee = self._employee()
        if not employee:
            return self._no_employee()

        data = _payload() or kwargs
        type_id = data.get("type_id")
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        reason = (data.get("reason") or "").strip()

        errors = {}
        if not type_id:
            errors["type_id"] = "Choose a leave type."
        if not date_from:
            errors["date_from"] = "Choose a start date."
        if not date_to:
            errors["date_to"] = "Choose an end date."
        if errors:
            return fail(
                422,
                "Please complete the highlighted fields.",
                code="missing_fields",
                errors=errors,
            )

        try:
            parsed_from = fields.Date.to_date(date_from)
            parsed_to = fields.Date.to_date(date_to)
        except (ValueError, TypeError):
            return fail(
                422,
                "Those dates could not be read. Please pick them again.",
                code="bad_dates",
                errors={"date_from": "Invalid date."},
            )

        if parsed_to < parsed_from:
            # Checked here rather than left to Odoo because the server's own
            # message for this is about internal field names.
            return fail(
                422,
                "The end date cannot be before the start date.",
                code="bad_range",
                errors={"date_to": "Must be on or after the start date."},
            )

        values = {
            "holiday_status_id": int(type_id),
            "request_date_from": parsed_from,
            "request_date_to": parsed_to,
            "name": reason or False,
            "employee_id": employee.id,
        }

        try:
            # As the user. See the module docstring: Odoo's own validation is
            # the point, and sudo would skip it.
            leave = request.env["hr.leave"].with_user(request.env.user).create(values)
        except AccessError:
            return fail(
                403,
                "You are not allowed to request leave for this employee.",
                code="leave_forbidden",
                log="leave AccessError for uid %s" % request.env.user.id,
            )
        except (UserError, ValidationError) as error:
            # Odoo's leave validation messages are written for employees --
            # "You do not have enough days", "overlaps with an existing" -- and
            # are exactly what the person needs to see.
            return fail(
                422,
                str(error),
                code="leave_rejected",
                log="leave rejected for %s: %s" % (request.env.user.login, error),
            )

        _logger.info("Mobile leave request %s by %s", leave.id, request.env.user.login)
        return ok({"request": self._serialise(leave.sudo())}, status=201)

    @http.route(
        "/api/mobile/v1/me/leave/<int:leave_id>/cancel",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def cancel(self, leave_id, **kwargs):
        employee = self._employee()
        if not employee:
            return self._no_employee()

        leave = request.env["hr.leave"].sudo().browse(leave_id).exists()
        # Ownership is checked before state, and answered as 404 rather than
        # 403: whether somebody else's leave request exists is not this user's
        # business, and a 403 would confirm that it does.
        if not leave or leave.employee_id.id != employee.id:
            return fail(
                404,
                "That leave request could not be found.",
                code="leave_not_found",
                log="leave %s not owned by uid %s" % (leave_id, request.env.user.id),
            )

        if not leave.can_cancel:
            return fail(
                422,
                "This request can no longer be cancelled here. "
                "Please speak to your manager.",
                code="leave_not_cancellable",
            )

        data = _payload() or kwargs
        reason = (data.get("reason") or "").strip() or "Cancelled from the mobile app"

        try:
            # ``_action_user_cancel`` is what the web client's own Cancel button
            # runs, by way of the hr.holidays.cancel.leave wizard. Using it means
            # the chatter entry, the responsible-party notification and the
            # ``can_cancel`` re-check all happen exactly as they do on the web --
            # a cancellation from a phone is not a different kind of event.
            leave.with_user(request.env.user)._action_user_cancel(reason)
        except (AccessError, UserError, ValidationError) as error:
            return fail(
                422,
                str(error),
                code="leave_cancel_rejected",
                log="leave cancel rejected: %s" % error,
            )

        leave.invalidate_recordset(["state", "can_cancel"])
        return ok({"request": self._serialise(leave.sudo())})

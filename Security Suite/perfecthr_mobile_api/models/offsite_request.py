# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Asking a manager to accept a check-in made away from work.

WHY THIS EXISTS
---------------
Under ENFORCE the location rule refuses the punch outright. That is the point
of it -- but a rule with no way out would make the first genuine site visit a
lost day's pay, and the pressure that creates lands on the employee rather than
on whoever drew the radius.

So the refusal is not the end of the conversation. The employee says where they
are and why, their manager decides, and the attendance is recorded **at the
moment they asked** rather than the moment it was approved. An approval at five
in the afternoon must not record somebody as having started work at five.

WHAT THIS IS NOT
----------------
It is not self-service. The employee cannot decide their own request, and
nothing is recorded until somebody else acts. That is the whole difference from
the earlier design, where typing a sentence was enough: a radius anybody could
talk their way past was not a control, it was a prompt.

PRIVACY
-------
A request stores where the employee was standing. They chose to send it, it is
visible only to the people who decide it, and it is what makes the decision
possible -- an approver asked to rule on "somewhere else" has nothing to go on.
It is not a trail: nothing here records position at any other moment.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrAttendanceOffsiteRequest(models.Model):
    _name = "hr.attendance.offsite.request"
    _description = "Off-Site Check-In Approval"
    _order = "requested_at desc, id desc"
    _rec_name = "employee_id"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee", required=True, ondelete="cascade",
        index=True, readonly=True,
    )
    company_id = fields.Many2one(
        "res.company", related="employee_id.company_id", store=True, index=True,
    )
    manager_id = fields.Many2one(
        "hr.employee", string="Manager", related="employee_id.parent_id",
        store=True,
        help="Who is expected to decide this. HR managers may decide it too.",
    )

    requested_at = fields.Datetime(
        string="Attempted At", required=True, readonly=True,
        help="When the employee tried to check in. This -- not the approval "
        "time -- is what gets recorded as their check-in.",
    )

    latitude = fields.Float(digits=(10, 7), readonly=True, aggregator=None)
    longitude = fields.Float(digits=(10, 7), readonly=True, aggregator=None)
    accuracy_m = fields.Integer(
        string="Fix Accuracy (m)", readonly=True, aggregator=None,
        help="How precise the device said its position was. A large number "
        "means the position is uncertain, not that the employee is far away.",
    )
    distance_m = fields.Integer(
        string="Distance From Work (m)", readonly=True, aggregator=None,
    )
    location_name = fields.Char(string="Nearest Work Location", readonly=True)
    refusal_reason = fields.Selection(
        selection=[
            ("out_of_range", "Away from every work location"),
            ("no_fix", "Device reported no position"),
            ("fix_too_vague", "Position too imprecise to judge"),
        ],
        string="Why It Was Refused", readonly=True,
        help="A device that reported nothing is a different situation from "
        "one that reported being two kilometres away, and the two deserve "
        "different judgements.",
    )

    reason = fields.Text(
        string="What They Said", required=True, readonly=True,
        help="Written by the employee at the moment of the attempt, not "
        "reconstructed afterwards.",
    )

    state = fields.Selection(
        selection=[
            ("pending", "Waiting for a decision"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending", required=True, index=True, readonly=True,
    )
    approver_id = fields.Many2one("res.users", string="Decided By", readonly=True)
    decided_at = fields.Datetime(readonly=True)
    decision_note = fields.Text(string="Note")
    attendance_id = fields.Many2one(
        "hr.attendance", string="Attendance Created", readonly=True,
        ondelete="set null",
    )

    # ------------------------------------------------------------------
    # Creating one
    # ------------------------------------------------------------------
    @api.model
    def submit(self, employee, fence, reason, requested_at=None):
        """Record an attempt that was refused, for a manager to decide.

        ``fence`` is the dict from ``perfecthr.attendance.geofence.evaluate``,
        so position, distance and the reason for refusal carry across without
        the caller re-deriving any of them.

        One pending request at a time. Somebody who taps Check In four times
        should not create four things for their manager to read, and the
        manager seeing four identical rows learns nothing from the extra three.
        """
        if not employee:
            raise ValidationError(_("There is no employee record to attach this to."))
        text = (reason or "").strip()
        if not text:
            raise ValidationError(_("Please say where you are and why."))

        existing = self.sudo().search(
            [("employee_id", "=", employee.id), ("state", "=", "pending")],
            limit=1,
        )
        if existing:
            return existing

        return self.sudo().create({
            "employee_id": employee.id,
            "requested_at": requested_at or fields.Datetime.now(),
            "latitude": fence.get("latitude") or 0.0,
            "longitude": fence.get("longitude") or 0.0,
            "accuracy_m": int(fence.get("accuracy_m") or 0),
            "distance_m": int(fence.get("distance_m") or 0),
            "location_name": fence.get("location_name") or False,
            "refusal_reason": fence.get("reason") or "out_of_range",
            "reason": text[:1000],
        })

    # ------------------------------------------------------------------
    # Deciding it
    # ------------------------------------------------------------------
    def _ensure_can_decide(self):
        """Nobody decides their own request.

        Checked here rather than left to record rules, because this is the one
        property that makes this an approval instead of a form.
        """
        for request in self:
            if request.employee_id.user_id == self.env.user:
                raise UserError(_(
                    "You cannot approve your own off-site check-in. Ask your "
                    "manager or HR to decide it."
                ))

    def action_approve(self):
        self._ensure_can_decide()
        for request in self:
            if request.state != "pending":
                raise UserError(_("This request has already been decided."))

            employee = request.employee_id
            # Refuse to create something the attendance rules would reject
            # anyway. Odoo's own _check_validity would raise a message about
            # overlapping records, which tells the approver nothing about what
            # to do about it; this says what actually happened.
            clash = self.env["hr.attendance"].sudo().search_count([
                ("employee_id", "=", employee.id),
                ("check_in", "<=", request.requested_at),
                "|",
                ("check_out", "=", False),
                ("check_out", ">=", request.requested_at),
            ])
            if clash:
                raise UserError(_(
                    "%(name)s already has attendance covering that time, so "
                    "approving this would record the same period twice. "
                    "Reject it, or correct the existing attendance first.",
                    name=employee.name,
                ))

            attendance = self.env["hr.attendance"].sudo().with_context(
                # The gate would otherwise refuse this exactly as it refused
                # the original punch. An approved request IS the authorisation,
                # and it is being written by the approver, not the employee.
                perfecthr_offsite_approved=True,
            ).create({
                "employee_id": employee.id,
                "check_in": request.requested_at,
                "off_site": True,
                "off_site_reason": request.reason,
                "off_site_distance_m": request.distance_m,
            })

            request.write({
                "state": "approved",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
                "attendance_id": attendance.id,
            })
            _logger.info(
                "Off-site check-in approved for %s by %s, recorded at %s",
                employee.name, self.env.user.login, request.requested_at,
            )
        return True

    def action_reject(self):
        self._ensure_can_decide()
        for request in self:
            if request.state != "pending":
                raise UserError(_("This request has already been decided."))
            request.write({
                "state": "rejected",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
            })
            _logger.info(
                "Off-site check-in rejected for %s by %s",
                request.employee_id.name, self.env.user.login,
            )
        return True

    # ------------------------------------------------------------------
    # For the app
    # ------------------------------------------------------------------
    def _payload(self):
        """What the phone shows about a request."""
        self.ensure_one()
        return {
            "id": str(self.id),
            "state": self.state,
            "requested_at": self.requested_at,
            "reason": self.reason,
            "distance_m": self.distance_m or None,
            "location_name": self.location_name or None,
            "decided_at": self.decided_at or None,
            "manager": self.manager_id.name or None,
        }

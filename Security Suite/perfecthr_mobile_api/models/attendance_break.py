# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Breaks recorded inside an attendance, and what they do to worked hours.

WHY NOT JUST CHECK OUT AND BACK IN
----------------------------------
That was the cheap option and it loses the one fact worth keeping. Two
attendance rows say "left the building, came back" and nothing distinguishes a
twenty-minute tea break from going home early and returning. Payroll, overtime
and any absence report then read them identically. A break recorded *as a
break* stays inside the session it belongs to and can be reported on.

THE DOUBLE-DEDUCTION TRAP
-------------------------
``hr_attendance``'s own ``_compute_worked_hours`` **already subtracts a lunch
interval** for any employee whose calendar is not flexible -- it takes the
scheduled lunch from the resource calendar and removes it from the span. So
naively subtracting recorded breaks on top of that charges an employee twice:
a one-hour break during their scheduled one-hour lunch would cost them two
hours of pay.

So recorded breaks **replace** that deduction rather than adding to it:

    no breaks recorded   -> Odoo's own computation, scheduled lunch deducted
    breaks recorded      -> gross span minus the ACTUAL breaks, and the
                            scheduled lunch is not deducted at all

That is also the more honest answer. Once somebody has told us when they
actually stopped working, a figure from the calendar is a worse estimate than
the measurement sitting next to it.

WHERE THIS LIVES
----------------
In the mobile API module because the mobile app is the only thing that starts
a break today. The ``worked_hours`` override travels with the model, so the web
dashboard's totals are correct wherever this is installed without knowing that
breaks exist.

If a break button is ever added to the web client, move this file and its
security rules into a module both depend on -- the model is self-contained and
the move is mechanical. It is not shared pre-emptively because an abstraction
with one caller is a guess about the second one.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrAttendanceBreak(models.Model):
    _name = "hr.attendance.break"
    _description = "Break Within an Attendance"
    _order = "break_start desc"

    attendance_id = fields.Many2one(
        comodel_name="hr.attendance",
        string="Attendance",
        required=True,
        index=True,
        ondelete="cascade",
        help="The working session this break happened inside.",
    )
    employee_id = fields.Many2one(
        related="attendance_id.employee_id",
        store=True,
        index=True,
        string="Employee",
    )
    break_start = fields.Datetime(required=True, default=fields.Datetime.now)
    break_end = fields.Datetime(
        help="Empty while the break is still running."
    )
    duration_hours = fields.Float(
        string="Duration",
        compute="_compute_duration_hours",
        store=True,
        aggregator="sum",
        help="Hours deducted from the session's worked time. Zero while the "
        "break is still running, so an unfinished break never reduces pay.",
    )
    break_type = fields.Selection(
        selection=[
            ("meal", "Meal"),
            ("short", "Short break"),
            ("personal", "Personal"),
            ("other", "Other"),
        ],
        default="short",
        required=True,
    )
    source = fields.Selection(
        selection=[
            ("mobile", "Mobile app"),
            ("web", "Web"),
            ("manual", "Entered by HR"),
        ],
        default="manual",
        required=True,
        help="How the break was recorded, so a figure corrected by HR is "
        "distinguishable from one the employee logged themselves.",
    )

    @api.depends("break_start", "break_end")
    def _compute_duration_hours(self):
        for record in self:
            if record.break_start and record.break_end:
                delta = record.break_end - record.break_start
                record.duration_hours = max(delta.total_seconds() / 3600.0, 0.0)
            else:
                # A running break deducts nothing. Deducting elapsed time as it
                # ran would make worked_hours fall while somebody watched it,
                # and would leave a forgotten break eating a whole day.
                record.duration_hours = 0.0

    @api.constrains("break_start", "break_end", "attendance_id")
    def _check_within_session(self):
        """A break has to fit inside the session it belongs to.

        Without this, a mistyped correction can produce a break longer than the
        attendance containing it, and worked_hours goes negative. The clamp in
        the compute would hide that at zero rather than showing anybody the
        contradiction.
        """
        for record in self:
            if record.break_end and record.break_end < record.break_start:
                raise ValidationError(
                    _("A break cannot end before it started.")
                )
            attendance = record.attendance_id
            if not attendance or not attendance.check_in:
                continue
            if record.break_start < attendance.check_in:
                raise ValidationError(
                    _("A break cannot start before the check-in it belongs to.")
                )
            if attendance.check_out and record.break_end and (
                record.break_end > attendance.check_out
            ):
                raise ValidationError(
                    _("A break cannot end after the check-out it belongs to.")
                )

    @api.constrains("break_start", "break_end")
    def _check_no_overlap(self):
        """Two breaks in one session must not overlap.

        Overlapping breaks are double-counted by the sum in
        ``_compute_worked_hours``, which silently under-pays.
        """
        for record in self:
            if not record.break_end:
                continue
            clash = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("attendance_id", "=", record.attendance_id.id),
                    ("break_start", "<", record.break_end),
                    ("break_end", ">", record.break_start),
                ]
            )
            if clash:
                raise ValidationError(
                    _("That break overlaps another break in the same session.")
                )


class HrAttendanceWithBreaks(models.Model):
    """``worked_hours`` with recorded breaks taken out of it."""

    _inherit = "hr.attendance"

    break_ids = fields.One2many(
        comodel_name="hr.attendance.break",
        inverse_name="attendance_id",
        string="Breaks",
    )
    break_hours = fields.Float(
        string="Break Time",
        compute="_compute_break_hours",
        store=True,
        aggregator="sum",
        help="Total recorded break time deducted from this session.",
    )
    has_open_break = fields.Boolean(
        compute="_compute_break_hours",
        store=True,
        help="A break is running. Checking out is refused until it ends, "
        "because a break with no end cannot be deducted.",
    )

    @api.depends("break_ids.duration_hours", "break_ids.break_end")
    def _compute_break_hours(self):
        for attendance in self:
            attendance.break_hours = sum(
                attendance.break_ids.mapped("duration_hours")
            )
            attendance.has_open_break = any(
                not b.break_end for b in attendance.break_ids
            )

    @api.depends(
        "check_in",
        "check_out",
        # Added to the inherited depends, not replacing them. Without these a
        # break ending would not recompute the hours it is supposed to deduct,
        # and the figure would only correct itself the next time check_out was
        # touched -- which is to say, never.
        "break_ids.duration_hours",
        "break_ids.break_start",
        "break_ids.break_end",
    )
    def _compute_worked_hours(self):
        """Deduct recorded breaks, **instead of** the scheduled lunch.

        See the module docstring for why "instead of" and not "as well as":
        ``hr_attendance`` already removes the calendar's lunch interval for a
        non-flexible employee, so doing both charges the same hour twice.

        Records with no recorded break fall through to Odoo's own computation
        untouched, which is what keeps every existing attendance -- and every
        deployment that never uses this feature -- behaving exactly as before.
        """
        with_breaks = self.filtered(
            lambda a: a.check_in and a.check_out and a.break_ids
        )
        remainder = self - with_breaks
        if remainder:
            super(HrAttendanceWithBreaks, remainder)._compute_worked_hours()

        for attendance in with_breaks:
            gross = (
                attendance.check_out - attendance.check_in
            ).total_seconds() / 3600.0
            deducted = sum(attendance.break_ids.mapped("duration_hours"))
            # Clamped at zero. A negative figure would flow into overtime and
            # payroll, and the constraints above already make it impossible --
            # this is the belt to their braces.
            attendance.worked_hours = max(gross - deducted, 0.0)

    # ------------------------------------------------------------------
    # Starting and ending a break
    # ------------------------------------------------------------------
    def start_break(self, break_type="short", source="mobile"):
        """Begin a break on this open session. Returns the break record."""
        self.ensure_one()
        if self.check_out:
            raise ValidationError(
                _("That working session has already ended, so a break cannot "
                  "be started inside it.")
            )
        if self.has_open_break:
            raise ValidationError(
                _("A break is already running. End it before starting another.")
            )
        record = self.env["hr.attendance.break"].create(
            {
                "attendance_id": self.id,
                "break_start": fields.Datetime.now(),
                "break_type": break_type if break_type in dict(
                    self.env["hr.attendance.break"]._fields["break_type"].selection
                ) else "short",
                "source": source,
            }
        )
        _logger.info(
            "Break started for %s on attendance %s", self.employee_id.name, self.id
        )
        return record

    def end_break(self):
        """End the running break. Returns it, or an empty recordset."""
        self.ensure_one()
        running = self.break_ids.filtered(lambda b: not b.break_end)
        if not running:
            return self.env["hr.attendance.break"]
        running = running.sorted("break_start")[-1]
        running.break_end = fields.Datetime.now()
        _logger.info(
            "Break ended for %s on attendance %s after %.2fh",
            self.employee_id.name, self.id, running.duration_hours,
        )
        return running

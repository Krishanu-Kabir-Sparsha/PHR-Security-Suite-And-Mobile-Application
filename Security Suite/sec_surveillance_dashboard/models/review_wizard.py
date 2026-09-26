# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Triage wizard, including the bulk case (P3-3).

Bulk review is provided because refusing it would be worse: a monitor facing
sixty low-severity out-of-hours alerts on a Monday morning either gets a batch
action or starts ignoring the dashboard, and an ignored dashboard is the real
failure mode.

It is deliberately made slightly awkward rather than convenient:

- every alert in the batch gets its own ``anomaly.review`` row, marked ``bulk``,
  so a batch dismissal is distinguishable from sixty considered ones in the
  monthly report;
- high and critical alerts are refused in bulk, because those are exactly the
  ones a batch action would be used to sweep away.
"""

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BULK_LIMIT = 200


class AnomalyReviewWizard(models.TransientModel):
    _name = "anomaly.review.wizard"
    _description = "Anomaly Triage Wizard"

    alert_ids = fields.Many2many(
        comodel_name="anomaly.alert", string="Alerts", required=True
    )
    alert_count = fields.Integer(
        string="Alerts Selected", compute="_compute_alert_count"
    )
    contains_severe = fields.Boolean(compute="_compute_alert_count")
    outcome = fields.Selection(
        selection=lambda self: self.env["anomaly.review"]._fields["outcome"].selection,
        string="Outcome",
        required=True,
        default="benign",
    )
    note = fields.Text(
        string="Note",
        required=True,
        help="Applied to every alert in the selection, so make it true of all "
        "of them. If it is not, review them separately.",
    )

    def _compute_alert_count(self):
        for wizard in self:
            wizard.alert_count = len(wizard.alert_ids)
            wizard.contains_severe = bool(
                wizard.alert_ids.filtered(
                    lambda a: a.severity in ("high", "critical")
                )
            )

    def action_apply(self):
        self.ensure_one()
        if not self.alert_ids:
            raise UserError(_("No alerts selected."))
        if len(self.alert_ids) > BULK_LIMIT:
            raise UserError(
                _(
                    "Select at most %(limit)s alerts at a time. A single note "
                    "covering more than that is not a review.",
                    limit=BULK_LIMIT,
                )
            )
        bulk = len(self.alert_ids) > 1
        if bulk and self.contains_severe:
            raise UserError(
                _(
                    "High and critical alerts must be reviewed individually. "
                    "A batch dismissal is exactly how a serious finding gets "
                    "swept away with routine ones."
                )
            )
        already = self.alert_ids.filtered(lambda a: a.state == "reviewed")
        if already:
            raise UserError(
                _(
                    "%s of the selected alerts have already been reviewed. "
                    "Reopen them individually if your conclusion has changed.",
                    len(already),
                )
            )
        for alert in self.alert_ids:
            alert.action_mark_reviewed(
                outcome=self.outcome, note=self.note, bulk=bulk
            )
        _logger.info(
            "%s alert(s) triaged as %s by %s (bulk=%s)",
            len(self.alert_ids),
            self.outcome,
            self.env.user.login,
            bulk,
        )
        return {"type": "ir.actions.act_window_close"}

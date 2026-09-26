# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Link each anomaly to its evidence (US-7.1, second criterion).

"Each flagged item links directly to the relevant Locker entries and, if
applicable, the override request record."

The point is triage speed. An alert that says "something happened to a sales
order" and leaves the reviewer to go and find it will be skimmed and dismissed.
The links are computed rather than stored because the relationship is derivable
and storing it would add a write to the alerting path, which must stay cheap —
alerting happens inside the transaction that was blocked.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AnomalyAlertLinks(models.Model):
    _inherit = "anomaly.alert"

    locker_entry_ids = fields.Many2many(
        comodel_name="audit.locker.entry",
        string="Related Locker Entries",
        compute="_compute_evidence_links",
        help="Audit trail entries for the same record around the same time.",
    )
    locker_entry_count = fields.Integer(
        string="Locker Entries", compute="_compute_evidence_links"
    )
    override_request_id = fields.Many2one(
        comodel_name="override.request",
        string="Override Request",
        compute="_compute_evidence_links",
        help="The override this alert arose from, where applicable.",
    )
    target_exists = fields.Boolean(
        string="Target Still Exists", compute="_compute_evidence_links"
    )

    def _parse_source_ref(self):
        """Return (model, id) from the stored 'model,id' reference."""
        self.ensure_one()
        if not self.source_ref or "," not in self.source_ref:
            return None, None
        model_name, _sep, raw_id = self.source_ref.partition(",")
        try:
            return model_name.strip(), int(raw_id)
        except ValueError:
            return None, None

    @api.depends("res_model", "res_id", "source_ref", "raised_at")
    def _compute_evidence_links(self):
        Locker = self.env["audit.locker.entry"].sudo()
        Override = self.env["override.request"].sudo()
        for alert in self:
            entries = Locker.browse()
            override = Override.browse()

            source_model, source_id = alert._parse_source_ref()
            if source_model == "audit.locker.entry" and source_id:
                entries = Locker.browse(source_id).exists()
            elif alert.res_model and alert.res_id:
                entries = Locker.search(
                    [
                        ("model_name", "=", alert.res_model),
                        ("res_id", "=", alert.res_id),
                    ],
                    order="sequence desc",
                    limit=20,
                )

            if source_model == "override.request" and source_id:
                override = Override.browse(source_id).exists()
            elif alert.res_model == "override.request" and alert.res_id:
                override = Override.browse(alert.res_id).exists()

            alert.locker_entry_ids = entries
            alert.locker_entry_count = len(entries)
            alert.override_request_id = override

            target = False
            if alert.res_model and alert.res_id:
                model = self.env.get(alert.res_model)
                if model is not None:
                    target = bool(model.sudo().browse(alert.res_id).exists())
            alert.target_exists = target

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_open_target(self):
        """Open the record the alert is about."""
        self.ensure_one()
        if not (self.res_model and self.res_id and self.target_exists):
            from odoo.exceptions import UserError

            raise UserError(
                _("This alert has no target record still in the database.")
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_locker_entries(self):
        """Open the audit trail around this alert."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Locker entries for %s", self.name),
            "res_model": "audit.locker.entry",
            "view_mode": "list,form",
            "domain": [("id", "in", self.locker_entry_ids.ids)],
        }

    def action_open_override_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "override.request",
            "res_id": self.override_request_id.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Feed summary
    # ------------------------------------------------------------------
    @api.model
    def dashboard_summary(self, hours=24):
        """Counts for the period, for the dashboard header and P3-4."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), hours=hours)
        domain = [("raised_at", ">=", cutoff)]
        alerts = self.sudo().search(domain)
        by_type = {}
        for alert in alerts:
            by_type[alert.alert_type] = by_type.get(alert.alert_type, 0) + 1
        return {
            "period_hours": hours,
            "total": len(alerts),
            "unreviewed": len(alerts.filtered(lambda a: a.state == "new")),
            "critical": len(
                alerts.filtered(lambda a: a.severity in ("high", "critical"))
            ),
            "by_type": by_type,
        }

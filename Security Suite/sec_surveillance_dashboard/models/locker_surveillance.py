# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Raise out-of-hours anomalies from Locker activity (US-7.1)."""

import logging

from odoo import _, api, models

from .business_hours import WATCHED_MODELS

_logger = logging.getLogger(__name__)


class LockerEntrySurveillance(models.Model):
    _inherit = "audit.locker.entry"

    @api.model
    def append(self, vals):
        """Evaluate each Locker entry for out-of-hours activity.

        Hooked on the Locker rather than on each business model so that one
        rule covers everything already being audited, and so a model added to
        the audit scope later is covered automatically instead of needing to be
        remembered here.
        """
        entry = super().append(vals)
        try:
            entry._evaluate_out_of_hours()
        except Exception:  # noqa: BLE001 - surveillance must not break auditing
            _logger.exception(
                "Out-of-hours evaluation failed for Locker entry %s", entry.id
            )
        return entry

    def _evaluate_out_of_hours(self):
        """Flag an edit made outside configured business hours."""
        self.ensure_one()
        hours = self.env["sec.business.hours"]
        if not hours.enabled():
            return False
        if self.model_name not in WATCHED_MODELS:
            return False
        if self.action_type == "read":
            return False
        if not hours.is_out_of_hours(self.timestamp_utc):
            return False

        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="out_of_hours_edit",
            name=_(
                "Out-of-hours %(action)s on %(model)s",
                action=self.action_type,
                model=self.model_name,
            ),
            reason=_(
                "%(user)s performed a %(action)s on %(label)s outside business "
                "hours, at %(when)s. Working late is normal; this is recorded "
                "so it can be read alongside other signals rather than treated "
                "as a finding on its own.",
                user=self.user_login,
                action=self.action_type,
                label=self.record_label or "%s,%s" % (self.model_name, self.res_id),
                when=hours.describe(self.timestamp_utc),
            ),
            # Low by design. A dashboard where routine evening work shows as
            # high severity trains its reader to ignore high severity.
            severity="low",
            user=self.user_id,
            source_ref="audit.locker.entry,%s" % self.id,
        )
        return True

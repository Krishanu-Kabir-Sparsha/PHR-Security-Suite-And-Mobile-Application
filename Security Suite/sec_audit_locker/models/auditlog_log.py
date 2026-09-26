# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Hardening of OCA auditlog, and the bridge into the Locker.

OCA `auditlog` does the hard part well: it patches the ORM per subscribed model
and captures field-level before/after values. What it does not do, and what
BRD FR-4.1/FR-4.2 require, is:

- record the **source IP** (its `auditlog.http.request` model stores path,
  root URL, user and context — no client address);
- make its own log rows **non-editable and non-deletable**;
- provide any **tamper evidence** if someone edits the tables directly.

This module adds all three rather than reimplementing capture, which is the
right division: field diffing is fiddly, well-tested upstream, and not where
our risk lies.
"""

import json
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ACTION_MAP = {
    "create": "create",
    "write": "write",
    "unlink": "unlink",
    "read": "read",
}


class AuditlogLog(models.Model):
    _inherit = "auditlog.log"

    @api.model_create_multi
    def create(self, vals_list):
        logs = super().create(vals_list)
        for log in logs:
            try:
                log._mirror_to_locker()
            except Exception:  # noqa: BLE001 - never break the audited action
                _logger.exception(
                    "Failed to mirror auditlog entry %s into the Locker", log.id
                )
        return logs

    def _mirror_to_locker(self):
        """Write a chained Locker entry for this auditlog record."""
        self.ensure_one()
        changes = {}
        for line in self.line_ids:
            changes[line.field_name or (line.field_id.name if line.field_id else "?")] = {
                "old": line.old_value_text or line.old_value,
                "new": line.new_value_text or line.new_value,
            }
        user = self.user_id or self.env.user
        self.env["audit.locker.entry"].append(
            {
                "user_id": user.id,
                "user_login": user.login,
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
                "model_name": self.model_model or (
                    self.model_id.model if self.model_id else "unknown"
                ),
                "res_id": self.res_id,
                "record_label": self.name,
                "action_type": ACTION_MAP.get(self.method, "other"),
                "field_changes": json.dumps(changes, sort_keys=True, separators=(",", ":"))
                if changes
                else "",
                "auditlog_log_id": self.id,
            }
        )

    def write(self, vals):
        raise UserError(
            _(
                "Audit log entries cannot be modified, by any role. If this "
                "block is preventing legitimate work, the work is not "
                "legitimate — raise it with Compliance."
            )
        )

    def unlink(self):
        """No deletion, including by the upstream autovacuum.

        OCA auditlog ships an `autovacuum` cron that purges logs older than N
        days. It is inactive by default upstream and this module keeps it that
        way. FR-4.2 forbids deletion outright, and the retention period is
        still an open question with Legal (PRD Section 12). An automatic
        silent purge is precisely the mechanism an insider would rely on, so
        retention, when defined, should be an explicit archival process with
        its own approval — not a cron nobody watches.
        """
        raise UserError(
            _(
                "Audit log entries cannot be deleted. Retention is a documented "
                "policy decision, not an automatic purge."
            )
        )

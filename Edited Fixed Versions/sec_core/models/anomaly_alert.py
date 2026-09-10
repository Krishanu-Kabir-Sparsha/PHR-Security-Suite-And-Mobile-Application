# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Shared anomaly alerting primitive.

Implements the PRD ``anomaly.alert`` data entity and the raising side of
BRD FR-1.4 / FR-7.2. The *consuming* side — the live dashboard, notification
delivery and threshold tuning — is Phase 3 (`sec_surveillance_dashboard`),
which extends this model rather than redefining it.

Why this lives in its own module: P1-3 requires anomaly events to be raised
during Phase 1, and P1-5 and P1-7 will need to raise them too. Defining the
model inside `sec_declaration_gateway` would force `sec_record_freeze` and
`sec_audit_locker` to depend on the declaration gateway, which is an unrelated
concern. See PROGRESS.md "Known Deviations" for the record of this departure
from the master build prompt's module map.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Alert taxonomy. Extended by later modules via selection_add.
ALERT_TYPES = [
    ("missing_documentation", "Required Documentation Missing"),
    ("out_of_hours_edit", "Edit Outside Business Hours"),
    ("high_value_edit", "High-Value Field Edit"),
    ("frozen_record_write_attempt", "Write Attempt on Frozen Record"),
    ("incomplete_override", "Override Attempted Without Full Approval"),
    ("declaration_bypass_attempt", "Dashboard Access Before Declaration"),
    ("credential_anomaly", "Authenticator Anomaly"),
    ("other", "Other"),
]

SEVERITIES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("critical", "Critical"),
]


class AnomalyAlert(models.Model):
    """A flagged suspicious or non-compliant action."""

    _name = "anomaly.alert"
    _description = "Anomaly Alert"
    _order = "raised_at desc, id desc"

    name = fields.Char(
        string="Summary",
        required=True,
        help="One-line description of what was detected.",
    )
    alert_type = fields.Selection(
        selection=ALERT_TYPES,
        string="Alert Type",
        required=True,
        index=True,
        help="Category of anomaly, used for dashboard filtering and the "
        "monthly forensic report.",
    )
    severity = fields.Selection(
        selection=SEVERITIES,
        string="Severity",
        default="medium",
        required=True,
        index=True,
        help="Triage priority. Override attempts without full approval and "
        "writes to frozen records are raised as critical.",
    )
    raised_at = fields.Datetime(
        string="Raised At (UTC)",
        required=True,
        default=fields.Datetime.now,
        index=True,
        help="When the triggering action occurred.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Acting User",
        index=True,
        help="The user whose action triggered the alert.",
    )
    source_ip = fields.Char(
        string="Source IP",
        help="Client IP recorded at the time of the action, where available.",
    )
    res_model = fields.Char(
        string="Target Model",
        index=True,
        help="Technical model of the record the action targeted.",
    )
    res_id = fields.Integer(
        string="Target Record ID",
        help="Database ID of the targeted record.",
    )
    source_ref = fields.Char(
        string="Source Reference",
        help="Free-form pointer to the originating record or Locker entry, "
        "stored as model,id. Replaces a reference field so that alerts can "
        "cite models from modules that are not yet installed.",
    )
    reason = fields.Text(
        string="Reason",
        required=True,
        help="Why this was flagged, in language a non-technical reviewer can act on.",
    )
    state = fields.Selection(
        selection=[
            ("new", "New"),
            ("reviewed", "Reviewed"),
            ("escalated", "Escalated"),
        ],
        string="Status",
        default="new",
        required=True,
        index=True,
        help="New alerts appear on the surveillance dashboard until reviewed.",
    )
    reviewed_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Reviewed By",
        readonly=True,
        help="Who triaged the alert.",
    )
    reviewed_at = fields.Datetime(
        string="Reviewed At",
        readonly=True,
        help="When the alert was triaged.",
    )
    review_note = fields.Text(
        string="Review Note",
        help="Mandatory when marking an alert reviewed (PRD US-7.1).",
    )

    # action_mark_reviewed, action_escalate and action_reopen are implemented
    # in anomaly_review.py (P3-3). The Phase 1 version required a note but
    # recorded nothing about who concluded what, which left the monitoring
    # function itself unaudited.


class AnomalyMixin(models.AbstractModel):
    """Inherit to gain a consistent way of raising anomaly alerts.

    Alerts are written with ``sudo()`` on purpose: the whole point is that the
    acting user cannot suppress the record of their own blocked action, and the
    action being flagged is frequently one the user had no right to perform.
    """

    _name = "sec.anomaly.mixin"
    _description = "Anomaly Raising Mixin"

    @api.model
    def _raise_anomaly(
        self,
        alert_type,
        name,
        reason,
        severity="medium",
        record=None,
        user=None,
        source_ref=None,
    ):
        """Create an anomaly alert and return it.

        Never raises on failure: a fault in alerting must not roll back or mask
        the security decision that triggered it. A failure to log is itself
        logged to the server log.
        """
        try:
            vals = {
                "alert_type": alert_type,
                "name": name,
                "reason": reason,
                "severity": severity,
                "user_id": (user or self.env.user).id,
                "source_ip": self._current_source_ip(),
                "source_ref": source_ref,
            }
            if record is not None and record:
                vals["res_model"] = record._name
                vals["res_id"] = record.id
            alert = self.env["anomaly.alert"].sudo().create(vals)
            _logger.warning(
                "ANOMALY [%s/%s] %s (user=%s)",
                alert_type,
                severity,
                name,
                (user or self.env.user).login,
            )
            return alert
        except Exception:  # noqa: BLE001 - alerting must never break the caller
            _logger.exception(
                "Failed to write anomaly alert (type=%s, name=%s)", alert_type, name
            )
            return self.env["anomaly.alert"]

    @api.model
    def _current_source_ip(self):
        """Best-effort client IP; returns False outside an HTTP context."""
        try:
            from odoo.http import request

            if request and request.httprequest:
                return request.httprequest.remote_addr
        except Exception:  # noqa: BLE001 - cron and shell contexts have no request
            pass
        return False

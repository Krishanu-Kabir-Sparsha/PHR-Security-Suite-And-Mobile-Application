# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Audit trail for anomaly triage (P3-3, US-7.1 third criterion).

"Dashboard supports marking an anomaly as Reviewed with a mandatory note,
itself logged."

The mandatory note existed from Phase 1. The "itself logged" half did not, and
it is the half that matters. Dismissing an alert is a security-relevant act:
the System Monitor is the one person positioned to make an inconvenient finding
disappear, and until now doing so left nothing behind but a changed status field
that could itself be edited.

So every triage decision writes an append-only ``anomaly.review`` row, and
reviews are visible in the monthly forensic report. The point is not to distrust
the monitor — it is that a monitoring function nobody audits is the same
single-point-of-trust problem the BRD set out to remove, just moved one step
sideways.

This lives in ``sec_core`` rather than in the dashboard module on purpose. If it
sat in the dashboard, an installation without the dashboard would still be able
to mark alerts reviewed, silently and untraceably. The log belongs wherever the
alerts are.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OUTCOMES = [
    ("benign", "Benign - expected activity"),
    ("explained", "Explained - checked with the actor"),
    ("action_taken", "Action taken - a change was made as a result"),
    ("escalated", "Escalated - needs a decision above me"),
    ("duplicate", "Duplicate of another alert"),
]


class AnomalyReview(models.Model):
    """One triage decision on one alert. Append-only."""

    _name = "anomaly.review"
    _description = "Anomaly Review Decision"
    _order = "reviewed_at desc, id desc"

    alert_id = fields.Many2one(
        comodel_name="anomaly.alert",
        string="Alert",
        required=True,
        ondelete="cascade",
        index=True,
    )
    reviewer_id = fields.Many2one(
        comodel_name="res.users",
        string="Reviewed By",
        required=True,
        ondelete="restrict",
        index=True,
        help="Restrict on delete: removing a user must not erase the record of "
        "what they dismissed.",
    )
    reviewed_at = fields.Datetime(
        string="Reviewed At (UTC)", required=True, default=fields.Datetime.now
    )
    outcome = fields.Selection(
        selection=OUTCOMES,
        string="Outcome",
        required=True,
        help="A bounded set, so the monthly report can answer 'how many alerts "
        "were dismissed as benign this month, and by whom?' — a question free "
        "text cannot answer.",
    )
    note = fields.Text(
        string="Note",
        required=True,
        help="Mandatory. What was checked and what was concluded, in enough "
        "detail that someone reading it in six months can tell whether the "
        "conclusion was reasonable.",
    )
    state_before = fields.Char(string="State Before", required=True)
    state_after = fields.Char(string="State After", required=True)
    source_ip = fields.Char(string="Source IP")
    bulk = fields.Boolean(
        string="Part of a Bulk Review",
        default=False,
        help="True when this alert was triaged as part of a batch. Batch "
        "dismissals get less individual attention by definition, so they are "
        "marked as such for the monthly review rather than being "
        "indistinguishable from considered ones.",
    )

    def write(self, vals):
        raise UserError(
            _(
                "Review decisions cannot be edited. If your conclusion has "
                "changed, reopen the alert and record a new review."
            )
        )

    def unlink(self):
        raise UserError(_("Review decisions cannot be deleted."))


class AnomalyAlertReview(models.Model):
    _inherit = "anomaly.alert"

    review_ids = fields.One2many(
        comodel_name="anomaly.review",
        inverse_name="alert_id",
        string="Review History",
        readonly=True,
    )
    review_count = fields.Integer(
        string="Times Reviewed", compute="_compute_review_count", store=True
    )
    reopened_count = fields.Integer(
        string="Times Reopened",
        compute="_compute_review_count",
        store=True,
        help="An alert reopened repeatedly is one where the first conclusion "
        "kept turning out to be wrong.",
    )

    @api.depends("review_ids.outcome")
    def _compute_review_count(self):
        for alert in self:
            alert.review_count = len(alert.review_ids)
            alert.reopened_count = len(
                alert.review_ids.filtered(lambda r: r.state_after == "new")
            )

    # Fields whose change is a triage decision and must go through the logged
    # actions. P4-4 finding: these were directly writable by anyone with write
    # access to the model, which made the whole review trail optional.
    TRIAGE_FIELDS = frozenset(
        {"state", "reviewed_by_id", "reviewed_at"}
    )

    def write(self, vals):
        """Force triage through the logged actions."""
        if self.env.context.get("anomaly_triage_internal"):
            return super().write(vals)
        touched = self.TRIAGE_FIELDS & set(vals)
        if touched:
            raise UserError(
                _(
                    "Use Mark Reviewed, Escalate or Reopen. Setting %(fields)s "
                    "directly would close the alert without recording who "
                    "concluded what, which is the one thing the review trail "
                    "exists to prevent.",
                    fields=", ".join(sorted(touched)),
                )
            )
        return super().write(vals)

    def unlink(self):
        raise UserError(
            _(
                "Anomaly alerts cannot be deleted. An alert that can be removed "
                "is not a record of anything."
            )
        )

    def _log_review(self, outcome, note, state_after, bulk=False):
        """Write the append-only review row and mirror it to the Locker."""
        self.ensure_one()
        review = self.env["anomaly.review"].sudo().create(
            {
                "alert_id": self.id,
                "reviewer_id": self.env.user.id,
                "reviewed_at": fields.Datetime.now(),
                "outcome": outcome,
                "note": note,
                "state_before": self.state,
                "state_after": state_after,
                "source_ip": self._current_source_ip()
                if hasattr(self, "_current_source_ip")
                else self.env["sec.anomaly.mixin"]._current_source_ip(),
                "bulk": bulk,
            }
        )
        self._mirror_review_to_locker(review)
        _logger.info(
            "Anomaly %s triaged as %s by %s: %s",
            self.id,
            outcome,
            self.env.user.login,
            (note or "")[:200],
        )
        return review

    def _mirror_review_to_locker(self, review):
        """Put the triage decision in the tamper-evident trail too.

        Guarded by a membership test rather than a module dependency, so
        sec_core still installs without the Locker.
        """
        if "audit.locker.entry" not in self.env:
            return
        import json

        try:
            self.env["audit.locker.entry"].append(
                {
                    "user_id": self.env.user.id,
                    "user_login": self.env.user.login,
                    "source_ip": review.source_ip,
                    "model_name": "anomaly.alert",
                    "res_id": self.id,
                    "record_label": self.name,
                    "action_type": "write",
                    "field_changes": json.dumps(
                        {
                            "triage": {
                                "old": review.state_before,
                                "new": review.state_after,
                            },
                            "outcome": {"old": "", "new": review.outcome},
                            "note": {"old": "", "new": review.note},
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        except Exception:  # noqa: BLE001 - the review itself already stands
            _logger.exception(
                "Review of alert %s recorded but its Locker entry failed", self.id
            )

    # ------------------------------------------------------------------
    # Triage actions
    # ------------------------------------------------------------------
    def action_mark_reviewed(self, outcome=None, note=None, bulk=False):
        """Mark reviewed. Note mandatory, decision logged.

        Replaces the Phase 1 version, which required a note but recorded
        nothing about who concluded what.
        """
        outcome = outcome or self.env.context.get("review_outcome") or "benign"
        for alert in self:
            text = (note or alert.review_note or "").strip()
            if not text:
                raise UserError(
                    _(
                        "Marking an anomaly as reviewed requires a note "
                        "explaining what was checked and what was concluded."
                    )
                )
            if alert.state == "reviewed":
                raise UserError(
                    _("That alert has already been reviewed. Reopen it first.")
                )
            alert._log_review(outcome, text, "reviewed", bulk=bulk)
            alert.with_context(anomaly_triage_internal=True).write(
                {
                    "state": "reviewed",
                    "review_note": text,
                    "reviewed_by_id": self.env.user.id,
                    "reviewed_at": fields.Datetime.now(),
                }
            )
        return True

    def action_escalate(self, note=None):
        """Escalate rather than close. Also logged."""
        for alert in self:
            text = (note or alert.review_note or "").strip()
            if not text:
                raise UserError(
                    _("Escalating requires a note saying what needs deciding.")
                )
            alert._log_review("escalated", text, "escalated")
            alert.with_context(anomaly_triage_internal=True).write(
                {"state": "escalated", "review_note": text}
            )
            alert._notify_escalation(text)
        return True

    def _notify_escalation(self, note):
        """Tell the Super Administrators an alert needs a decision."""
        self.ensure_one()
        group = self.env.ref(
            "sec_plaza_rbac.group_security_super_admin", raise_if_not_found=False
        )
        if not group:
            return
        # res.groups exposes its members as "users" on Odoo 18; "user_ids" is
        # the Odoo 19 name and raises AttributeError here.
        partners = group.sudo().users.mapped("partner_id")
        for partner in partners:
            try:
                partner.message_post(
                    subject=_("Escalated security anomaly"),
                    body=_(
                        "<p><strong>%(name)s</strong> was escalated by "
                        "%(user)s.</p><p>%(note)s</p>",
                        name=self.name,
                        user=self.env.user.name,
                        note=note,
                    ),
                )
            except Exception:  # noqa: BLE001 - notification is not the control
                _logger.exception("Could not notify %s of escalation", partner.name)

    def action_reopen(self, note=None):
        """Reopen a closed alert when new information appears."""
        for alert in self:
            text = (note or "").strip()
            if not text:
                raise UserError(
                    _("Reopening requires a note saying what changed.")
                )
            if alert.state == "new":
                raise UserError(_("That alert is already open."))
            alert._log_review("explained", text, "new")
            alert.with_context(anomaly_triage_internal=True).write(
                {"state": "new"}
            )
        return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    @api.model
    def review_activity_report(self, days=30):
        """Who dismissed what, for the monthly forensic report (P3-4)."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        reviews = self.env["anomaly.review"].sudo().search(
            [("reviewed_at", ">=", cutoff)]
        )
        by_reviewer = {}
        by_outcome = {}
        for review in reviews:
            login = review.reviewer_id.login
            by_reviewer[login] = by_reviewer.get(login, 0) + 1
            by_outcome[review.outcome] = by_outcome.get(review.outcome, 0) + 1
        unreviewed = self.sudo().search_count(
            [("state", "=", "new"), ("severity", "in", ("high", "critical"))]
        )
        return {
            "period_days": days,
            "reviews": len(reviews),
            "by_reviewer": by_reviewer,
            "by_outcome": by_outcome,
            "bulk_reviews": len(reviews.filtered("bulk")),
            "open_high_severity": unreviewed,
        }

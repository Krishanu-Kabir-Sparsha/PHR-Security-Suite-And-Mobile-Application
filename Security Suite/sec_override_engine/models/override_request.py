# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Override requests against frozen records (P2-5, US-5.1).

Built on OCA ``base_tier_validation`` rather than a bespoke workflow, per the
master build prompt and BRD Section 8.1. What the OCA mixin gives us: tier
definitions, review records, sequencing, reviewer resolution, notification and
the ``validated`` / ``rejected`` state machine. What it does not give us, and
what later tasks add:

- **P2-6:** WebAuthn gating on each approval. ``base_tier_validation`` will
  happily accept an approval backed by nothing but a session cookie.
- **P2-7:** distinct-identity enforcement across tiers. Confirmed by reading
  ``validate_tier`` in the upstream source: it filters reviews by the sequences
  the acting user may approve, so a user who happens to sit in two reviewer
  groups can satisfy two tiers. FR-5.1 forbids exactly that, and nothing
  upstream prevents it.
- **P2-8:** performing the edit, re-freezing, and closing the Locker loop.

This task builds the request itself: what is being changed, why, under which
policy category, and with what documentation.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class OverrideRequest(models.Model):
    """A request to modify one frozen record, pending three-tier approval."""

    _name = "override.request"
    _description = "Record Override Request"
    # sec.instruction.mixin carries the Written/Oral classification and its
    # documentation rules from P1-2. Inheriting rather than reimplementing is
    # the point: if the two ever diverged, one route into a frozen record would
    # start accepting undocumented oral instructions.
    _inherit = ["tier.validation", "sec.instruction.mixin", "mail.thread"]
    _order = "create_date desc"

    _state_field = "state"
    _state_from = ["draft"]
    _state_to = ["approved"]
    _cancel_state = "cancelled"

    name = fields.Char(
        string="Reference",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
        copy=False,
    )
    requester_id = fields.Many2one(
        comodel_name="res.users",
        string="Requester",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        ondelete="restrict",
        tracking=True,
    )
    res_model = fields.Char(
        string="Target Model",
        required=True,
        help="Technical model of the frozen record, e.g. sale.order. "
        "Made read-only after submission by the view, since the states= "
        "field attribute was removed in Odoo 17.",
    )
    res_id = fields.Integer(
        string="Target Record ID",
        required=True,
    )
    target_display = fields.Char(
        string="Target Record",
        compute="_compute_target_display",
        store=True,
        help="Human-readable name of the record at the time of the request.",
    )
    reason_category_id = fields.Many2one(
        comodel_name="override.reason.category",
        string="Policy Exception Category",
        required=True,
        tracking=True,
        ondelete="restrict",
        help="Which recognised policy exception this correction falls under.",
    )
    justification = fields.Text(
        string="Justification",
        required=True,
        tracking=True,
        help="What is wrong, what it should say, and why it cannot wait for a "
        "normal credit note or amendment. Approvers read this; write it for "
        "them, not for the file.",
    )
    proposed_changes = fields.Text(
        string="Proposed Changes",
        required=True,
        help="Exactly which fields change and to what. The approved edit is "
        "limited to this in P2-8; an approval is not a general licence to "
        "edit the record.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending", "Awaiting Approval"),
            ("approved", "Approved"),
            ("executed", "Executed"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
        copy=False,
    )
    submitted_at = fields.Datetime(string="Submitted At", readonly=True)
    approved_at = fields.Datetime(string="Fully Approved At", readonly=True)
    executed_at = fields.Datetime(string="Executed At", readonly=True)
    rejection_reason = fields.Text(string="Rejection Reason", readonly=True)
    high_risk = fields.Boolean(
        related="reason_category_id.high_risk", store=True, string="High Risk"
    )

    _sql_constraints = [
        ("name_uniq", "unique(name)", "That override reference already exists."),
    ]

    # ------------------------------------------------------------------
    # Naming and display
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("override.request")
                    or _("OVR/%s", fields.Datetime.now().strftime("%Y%m%d%H%M%S"))
                )
        return super().create(vals_list)

    @api.depends("res_model", "res_id")
    def _compute_target_display(self):
        for request_record in self:
            display = False
            if request_record.res_model and request_record.res_id:
                model = self.env.get(request_record.res_model)
                if model is not None:
                    record = model.browse(request_record.res_id).exists()
                    if record:
                        display = record.display_name
            request_record.target_display = display or _("(record not found)")

    def _target_record(self):
        """The record this request targets, or an empty recordset."""
        self.ensure_one()
        model = self.env.get(self.res_model)
        if model is None:
            return None
        return model.browse(self.res_id).exists()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @api.constrains("res_model", "res_id")
    def _check_target_is_in_scope(self):
        """An override only means something against a record that is frozen.

        Allowing requests against arbitrary records would turn this into a
        general-purpose approval workflow, and the approval evidence would stop
        implying what it currently implies: that a frozen record was changed.
        """
        for request_record in self:
            rule = (
                self.env["sec.freeze.rule"]
                .sudo()
                .search([("model_name", "=", request_record.res_model)], limit=1)
            )
            if not rule:
                raise ValidationError(
                    _(
                        "%(model)s is not covered by any record freeze rule, so "
                        "it cannot need an override. Edit it normally.",
                        model=request_record.res_model,
                    )
                )
            record = request_record._target_record()
            if record is None or not record:
                raise ValidationError(
                    _("The target record no longer exists.")
                )

    def _target_is_frozen(self):
        self.ensure_one()
        record = self._target_record()
        if not record:
            return False
        rule = self.env["sec.freeze.rule"].sudo().search(
            [("model_name", "=", self.res_model)], limit=1
        )
        if not rule:
            return False
        return bool(record._filter_frozen(rule))

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------
    def action_submit(self):
        """Submit for approval, enforcing every precondition server-side."""
        for request_record in self:
            if request_record.state != "draft":
                raise UserError(_("Only a draft request can be submitted."))

            if not request_record.reason_category_id.active:
                raise UserError(
                    _(
                        "'%(category)s' is no longer a recognised policy "
                        "exception category. Choose a current one.",
                        category=request_record.reason_category_id.name,
                    )
                )

            if not request_record._target_is_frozen():
                raise UserError(
                    _(
                        "That record is not currently frozen, so no override is "
                        "needed. Edit it directly."
                    )
                )

            # Written/Oral documentation, from P1-2. Raises and raises an
            # anomaly if incomplete.
            request_record._check_documentation_or_flag()

            if request_record.reason_category_id.requires_attachment and not (
                request_record.attachment_ids
            ):
                raise UserError(
                    _(
                        "The '%(category)s' category always requires supporting "
                        "documentation.",
                        category=request_record.reason_category_id.name,
                    )
                )

            request_record.write(
                {"state": "pending", "submitted_at": fields.Datetime.now()}
            )
            request_record.request_validation()
            request_record._raise_anomaly(
                alert_type="incomplete_override",
                name=_("Override requested against a frozen record"),
                reason=_(
                    "%(user)s requested an override of %(target)s under "
                    "'%(category)s'. Justification: %(justification)s",
                    user=request_record.requester_id.login,
                    target=request_record.target_display,
                    category=request_record.reason_category_id.name,
                    justification=request_record.justification,
                ),
                severity="high" if request_record.high_risk else "medium",
                record=request_record,
            )
            _logger.warning(
                "Override %s requested by %s against %s,%s",
                request_record.name,
                request_record.requester_id.login,
                request_record.res_model,
                request_record.res_id,
            )
        return True

    def action_cancel(self):
        for request_record in self:
            if request_record.state in ("executed",):
                raise UserError(
                    _("An executed override cannot be cancelled after the fact.")
                )
            request_record.write({"state": "cancelled"})
        return True

    # ------------------------------------------------------------------
    # tier.validation hooks
    # ------------------------------------------------------------------
    def _get_under_validation_exceptions(self):
        """Fields still writable while the request is under review.

        Everything material is locked: changing the justification or the
        proposed changes after Tier 1 has approved would mean the CEO/Owner
        signs off on something different from what the department head saw.
        """
        exceptions = super()._get_under_validation_exceptions()
        return exceptions + [
            "state",
            "approved_at",
            "executed_at",
            "rejection_reason",
            "message_ids",
            "message_follower_ids",
            "activity_ids",
        ]

    def _validate_tier(self, tiers=False):
        result = super()._validate_tier(tiers=tiers)
        for request_record in self:
            if request_record.validated and request_record.state == "pending":
                request_record.write(
                    {"state": "approved", "approved_at": fields.Datetime.now()}
                )
                request_record._raise_anomaly(
                    alert_type="incomplete_override",
                    name=_("Override fully approved"),
                    reason=_(
                        "Override %(ref)s against %(target)s received all "
                        "required approvals and is now executable.",
                        ref=request_record.name,
                        target=request_record.target_display,
                    ),
                    severity="critical",
                    record=request_record,
                )
        return result

    def _rejected_tier(self, tiers=False):
        result = super()._rejected_tier(tiers=tiers)
        for request_record in self:
            if request_record.rejected and request_record.state == "pending":
                request_record.write({"state": "rejected"})
                request_record._raise_anomaly(
                    alert_type="incomplete_override",
                    name=_("Override rejected"),
                    reason=_(
                        "Override %(ref)s was rejected. The frozen record was "
                        "not changed.",
                        ref=request_record.name,
                    ),
                    severity="medium",
                    record=request_record,
                )
        return result

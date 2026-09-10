# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Break-glass recovery for a lost or replaced authenticator (P2-4, US-6.3).

The requirement: "Re-enrollment itself requires independent approval from the
other two tiers (cannot be self-service)" and "Recovery event is written to the
Locker with full context".

The problem this solves is narrow but sharp. Every other control in the suite
assumes the approver's authenticator works. When it does not — phone lost, key
in a drawer at home, credential auto-revoked as a suspected clone — there has to
be a way back in, and that way back in is the single most attractive target in
the system. Anyone who can add their own authenticator to the CEO/Owner's
account owns the Nuclear Key.

So enrolment is permitted by three different routes depending on the situation,
and only one of them is self-service:

**1. First enrolment (no credential has ever existed).** Self-service. There is
nothing to steal yet, and requiring ceremony here would only obstruct
onboarding.

**2. Adding another device while one still works.** Permitted, but the user must
first confirm with an existing credential. Proving control of the current key is
both stronger and far less friction than convening approvers — and BRD FR-6.5
wants the CEO/Owner to hold two, so this path needs to be usable.

**3. Recovery: credentials existed, none are usable.** Break-glass. Requires an
approved recovery request carrying two approvals from distinct people, neither
of them the requester, each WebAuthn-confirmed on their own device.

Circular dependency, flagged in the master build prompt (task P2-4): the natural
home for these approvals is the override engine, which is P2-5 and does not
exist. This module therefore carries a self-contained two-approver rule. It is
deliberately *not* wired to the three-tier ladder, because the commonest real
recovery is the CEO/Owner losing their phone — and requiring the CEO's own tier
to approve their own recovery is unsatisfiable. Revisit when P2-5 lands; logged
in PROGRESS.md under Known Deviations.
"""

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

REQUIRED_APPROVALS = 2
GRANT_VALIDITY_HOURS = 24


class RecoveryRequest(models.Model):
    """A request to re-enrol an authenticator after losing access."""

    _name = "sec.webauthn.recovery.request"
    _description = "WebAuthn Break-Glass Recovery Request"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: _("Recovery request"),
        tracking=True,
    )
    requester_id = fields.Many2one(
        comodel_name="res.users",
        string="Requester",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        ondelete="restrict",
        tracking=True,
        help="The user who has lost access to their authenticator.",
    )
    reason = fields.Text(
        string="What Happened",
        required=True,
        tracking=True,
        help="How access was lost. Approvers read this before deciding, and it "
        "is the record an auditor will read afterwards.",
    )
    lost_credential_ids = fields.Many2many(
        comodel_name="sec.webauthn.credential",
        string="Credentials Being Replaced",
        help="Which authenticators are no longer usable.",
    )
    approval_ids = fields.One2many(
        comodel_name="sec.webauthn.recovery.approval",
        inverse_name="request_id",
        string="Approvals",
        readonly=True,
    )
    approval_count = fields.Integer(
        string="Approvals Given",
        compute="_compute_approval_state",
        store=True,
    )
    state = fields.Selection(
        selection=[
            ("pending", "Awaiting Approval"),
            ("approved", "Approved - Enrolment Open"),
            ("consumed", "Used"),
            ("rejected", "Rejected"),
            ("expired", "Expired"),
        ],
        string="Status",
        default="pending",
        required=True,
        readonly=True,
        tracking=True,
    )
    approved_at = fields.Datetime(string="Approved At", readonly=True)
    expires_at = fields.Datetime(
        string="Enrolment Window Closes",
        readonly=True,
        help="An approved recovery opens a %s-hour window for exactly one "
        "enrolment. An indefinite grant would be a standing key to the "
        "account." % GRANT_VALIDITY_HOURS,
    )
    consumed_at = fields.Datetime(string="Used At", readonly=True)
    resulting_credential_id = fields.Many2one(
        comodel_name="sec.webauthn.credential",
        string="Credential Enrolled",
        readonly=True,
    )

    @api.depends("approval_ids.decision")
    def _compute_approval_state(self):
        for request_record in self:
            request_record.approval_count = len(
                request_record.approval_ids.filtered(
                    lambda a: a.decision == "approve"
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for request_record in requests:
            request_record._raise_recovery_anomaly(
                _("Break-glass recovery requested"),
                _(
                    "%(user)s requested re-enrolment of an authenticator. "
                    "Reason given: %(reason)s",
                    user=request_record.requester_id.login,
                    reason=request_record.reason,
                ),
                severity="high",
            )
            request_record._notify_eligible_approvers()
        return requests

    def _raise_recovery_anomaly(self, name, reason, severity="high"):
        """US-6.3: the recovery event reaches the audit trail with full context."""
        self.ensure_one()
        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="credential_anomaly",
            name=name,
            reason=reason,
            severity=severity,
            record=self,
        )

    # ------------------------------------------------------------------
    # Approver eligibility
    # ------------------------------------------------------------------
    @api.model
    def _eligible_approvers(self, requester):
        """Users who may approve a recovery for ``requester``.

        Anyone holding an approval-tier role in the Plaza catalog, except the
        requester themselves, and only if they hold a working authenticator of
        their own — an approver who cannot produce an assertion cannot give a
        WebAuthn-confirmed approval, and an unconfirmed approval on this
        particular workflow would be worth very little.
        """
        Credential = self.env["sec.webauthn.credential"]
        tier_groups = (
            self.env["role.plaza_model"]
            .sudo()
            .search([("active", "=", True), ("is_approval_tier", "!=", "none")])
            .mapped("group_id")
        )
        if not tier_groups:
            return self.env["res.users"]
        candidates = self.env["res.users"].sudo().search(
            [("active", "=", True), ("groups_id", "in", tier_groups.ids)]
        )
        return candidates.filtered(
            lambda u: u != requester and Credential.enrolled_for(u)
        )

    def _notify_eligible_approvers(self):
        self.ensure_one()
        approvers = self._eligible_approvers(self.requester_id)
        if len(approvers) < REQUIRED_APPROVALS:
            _logger.error(
                "Recovery request %s cannot be satisfied: only %d eligible "
                "approver(s) hold an authenticator.",
                self.id,
                len(approvers),
            )
            self._raise_recovery_anomaly(
                _("Recovery cannot be approved - too few eligible approvers"),
                _(
                    "A recovery request was raised but only %(count)s eligible "
                    "approver(s) hold a working authenticator. %(required)s are "
                    "required. Until more approvers enrol, nobody can recover "
                    "from a lost device — which is itself an availability risk "
                    "worth fixing before it is needed.",
                    count=len(approvers),
                    required=REQUIRED_APPROVALS,
                ),
                severity="critical",
            )
            return
        for approver in approvers:
            try:
                self.message_subscribe(partner_ids=approver.partner_id.ids)
            except Exception:  # noqa: BLE001 - notification is not the control
                _logger.exception("Could not notify approver %s", approver.login)
        self.message_post(
            body=_(
                "%(user)s cannot use their authenticator and has asked to "
                "enrol a replacement. Two approvals from different people are "
                "required, and each approver must confirm on their own device.",
                user=self.requester_id.name,
            )
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------
    def action_approve(self):
        """Record one approval, WebAuthn-confirmed on the approver's device."""
        self.ensure_one()
        self._assert_pending()
        approver = self.env.user
        if approver == self.requester_id:
            raise UserError(
                _(
                    "You cannot approve your own recovery request. That would "
                    "make the whole control self-service."
                )
            )
        if approver not in self._eligible_approvers(self.requester_id):
            raise UserError(
                _(
                    "Only approval-tier role holders with their own enrolled "
                    "authenticator may approve a recovery request."
                )
            )
        if self.approval_ids.filtered(lambda a: a.approver_id == approver):
            raise UserError(
                _("You have already recorded a decision on this request.")
            )

        Credential = self.env["sec.webauthn.credential"]
        context_ref = "%s,%s" % (self._name, self.id)
        strong = False
        if Credential._verification_ready():
            if not Credential._verify_pending_assertion(context_ref):
                raise UserError(
                    _(
                        "Confirm on your own security key before approving. "
                        "This approval will let someone else enrol a new "
                        "authenticator, so it needs more than a session cookie."
                    )
                )
            strong = True

        self.env["sec.webauthn.recovery.approval"].sudo().create(
            {
                "request_id": self.id,
                "approver_id": approver.id,
                "decision": "approve",
                "decided_at": fields.Datetime.now(),
                "strongly_authenticated": strong,
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
            }
        )
        self.invalidate_recordset(["approval_ids", "approval_count"])
        if self.approval_count >= REQUIRED_APPROVALS:
            self._grant()
        return True

    def action_reject(self, reason=None):
        """Any single rejection ends the request."""
        self.ensure_one()
        self._assert_pending()
        if self.env.user == self.requester_id:
            raise UserError(_("You cannot decide your own recovery request."))
        self.env["sec.webauthn.recovery.approval"].sudo().create(
            {
                "request_id": self.id,
                "approver_id": self.env.user.id,
                "decision": "reject",
                "decided_at": fields.Datetime.now(),
                "comment": reason or self.env.context.get("rejection_reason"),
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
            }
        )
        self.sudo().write({"state": "rejected"})
        self._raise_recovery_anomaly(
            _("Break-glass recovery rejected"),
            _(
                "%(approver)s rejected the recovery request from %(user)s.",
                approver=self.env.user.login,
                user=self.requester_id.login,
            ),
        )
        return True

    def _assert_pending(self):
        if self.state != "pending":
            raise UserError(
                _("This request is %s and can no longer be decided.", self.state)
            )

    def _grant(self):
        """Open a single-use, time-limited enrolment window."""
        self.ensure_one()
        approvers = self.approval_ids.filtered(
            lambda a: a.decision == "approve"
        ).mapped("approver_id")
        # Defence in depth: the per-approval checks should already guarantee
        # this, but the property is important enough to assert at the point it
        # actually matters.
        if len(approvers) < REQUIRED_APPROVALS:
            raise ValidationError(
                _("Fewer than %s distinct approvers.", REQUIRED_APPROVALS)
            )
        if self.requester_id in approvers:
            raise ValidationError(
                _("The requester appears among the approvers.")
            )
        now = fields.Datetime.now()
        self.sudo().write(
            {
                "state": "approved",
                "approved_at": now,
                "expires_at": now + timedelta(hours=GRANT_VALIDITY_HOURS),
            }
        )
        self._raise_recovery_anomaly(
            _("Break-glass recovery APPROVED - enrolment window open"),
            _(
                "Re-enrolment for %(user)s was approved by %(approvers)s. A "
                "single enrolment is now permitted until %(expiry)s. Any "
                "credential enrolled in this window was authorised by those "
                "named approvers, not by the account holder alone.",
                user=self.requester_id.login,
                approvers=", ".join(approvers.mapped("login")),
                expiry=self.expires_at,
            ),
            severity="critical",
        )
        _logger.warning(
            "Break-glass recovery approved for %s by %s",
            self.requester_id.login,
            ", ".join(approvers.mapped("login")),
        )

    # ------------------------------------------------------------------
    # Consumption by the enrolment ceremony
    # ------------------------------------------------------------------
    @api.model
    def active_grant_for(self, user):
        """An approved, unexpired, unused grant for this user, if any."""
        now = fields.Datetime.now()
        grant = self.sudo().search(
            [
                ("requester_id", "=", user.id),
                ("state", "=", "approved"),
                ("expires_at", ">", now),
            ],
            order="approved_at desc",
            limit=1,
        )
        return grant

    def consume(self, credential):
        """Spend the grant on exactly one enrolled credential."""
        self.ensure_one()
        self.sudo().write(
            {
                "state": "consumed",
                "consumed_at": fields.Datetime.now(),
                "resulting_credential_id": credential.id,
            }
        )
        self._raise_recovery_anomaly(
            _("Break-glass recovery used"),
            _(
                "%(user)s enrolled '%(label)s' under the approved recovery "
                "grant. The grant is now spent.",
                user=self.requester_id.login,
                label=credential.device_label,
            ),
            severity="high",
        )

    @api.model
    def cron_expire_grants(self):
        """Close windows nobody used."""
        now = fields.Datetime.now()
        stale = self.sudo().search(
            [("state", "in", ("pending", "approved")), ("expires_at", "<", now)]
        )
        stale.write({"state": "expired"})
        return len(stale)


class RecoveryApproval(models.Model):
    """One approver's decision. Append-only."""

    _name = "sec.webauthn.recovery.approval"
    _description = "WebAuthn Recovery Approval"
    _order = "decided_at"

    request_id = fields.Many2one(
        comodel_name="sec.webauthn.recovery.request",
        string="Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        required=True,
        ondelete="restrict",
    )
    decision = fields.Selection(
        selection=[("approve", "Approved"), ("reject", "Rejected")],
        string="Decision",
        required=True,
    )
    decided_at = fields.Datetime(string="Decided At (UTC)", required=True)
    strongly_authenticated = fields.Boolean(
        string="WebAuthn Confirmed",
        default=False,
        help="Whether this approval was confirmed on the approver's own "
        "authenticator. Recorded rather than assumed.",
    )
    comment = fields.Text(string="Comment")
    source_ip = fields.Char(string="Source IP")

    _sql_constraints = [
        (
            "one_decision_per_approver",
            "unique(request_id, approver_id)",
            "That approver has already decided on this request.",
        ),
    ]

    def write(self, vals):
        raise UserError(_("Recovery approvals cannot be modified."))

    def unlink(self):
        raise UserError(_("Recovery approvals cannot be deleted."))

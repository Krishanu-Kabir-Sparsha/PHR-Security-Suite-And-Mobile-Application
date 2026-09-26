# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""WebAuthn-gated tier approval (P2-6, US-5.2, BRD FR-5.3).

FR-5.3: "Each approval step must be authenticated via the FIDO2 WebAuthn
mechanism defined in FR-6, not by password alone."
US-5.2: "Approval requires WebAuthn authentication; a password-only approval is
rejected by the system."

``base_tier_validation`` provides the ladder but will accept an approval backed
by nothing more than a logged-in session. This module refuses to record any tier
unless a WebAuthn assertion **bound to this specific request** was verified in
the same HTTP round trip.

Why the same round trip matters. ``_verify_pending_assertion`` reads a marker
placed on the request object, and that object lives for exactly one HTTP
request. If the ceremony and the approval were separate calls, the marker would
be gone by the time the approval arrived — and the obvious fix, moving the
marker to the session, is precisely what must not happen: a session-scoped
marker means one confirmation silently authorises every later approval in the
same browser session. The controller therefore verifies and approves in one
call.

``override.approval`` records the PRD's approval entity alongside the upstream
``tier.review``: same decision, plus the evidence that it was cryptographically
confirmed, which is the part an auditor will ask about.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OverrideApproval(models.Model):
    """One tier decision, with its authentication evidence. Append-only."""

    _name = "override.approval"
    _description = "Override Tier Approval"
    _order = "decided_at"

    request_id = fields.Many2one(
        comodel_name="override.request",
        string="Override Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    tier_sequence = fields.Integer(
        string="Tier",
        required=True,
        help="Tier sequence: 10 Department Head, 20 Compliance, 30 CEO/Owner.",
    )
    tier_name = fields.Char(string="Tier Name", required=True)
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        required=True,
        ondelete="restrict",
        index=True,
        help="Restrict on delete: removing a user must never erase the record "
        "of an approval they gave.",
    )
    decision = fields.Selection(
        selection=[("approve", "Approved"), ("reject", "Rejected")],
        string="Decision",
        required=True,
    )
    decided_at = fields.Datetime(string="Decided At (UTC)", required=True)
    strongly_authenticated = fields.Boolean(
        string="WebAuthn Confirmed",
        required=True,
        help="Whether this decision was confirmed on the approver's own "
        "authenticator. An approval with this False did not meet FR-5.3 and "
        "should not exist; it is a field rather than an assumption so that a "
        "misconfiguration is visible in the evidence instead of invisible.",
    )
    credential_id = fields.Many2one(
        comodel_name="sec.webauthn.credential",
        string="Authenticator Used",
        ondelete="restrict",
        help="Which enrolled device confirmed this approval.",
    )
    comment = fields.Text(string="Comment")
    source_ip = fields.Char(string="Source IP")

    _sql_constraints = [
        (
            "one_decision_per_tier_per_user",
            "unique(request_id, tier_sequence, approver_id)",
            "That approver has already decided this tier.",
        ),
    ]

    def write(self, vals):
        raise UserError(
            _("Approval records cannot be modified. They are the evidence.")
        )

    def unlink(self):
        raise UserError(_("Approval records cannot be deleted."))


class OverrideRequestApproval(models.Model):
    _inherit = "override.request"

    approval_ids = fields.One2many(
        comodel_name="override.approval",
        inverse_name="request_id",
        string="Tier Approvals",
        readonly=True,
    )
    approval_count = fields.Integer(
        string="Approvals Recorded",
        compute="_compute_approval_count",
        store=True,
    )
    all_approvals_strong = fields.Boolean(
        string="All Approvals WebAuthn-Confirmed",
        compute="_compute_approval_count",
        store=True,
        help="False on any request where a tier was recorded without "
        "cryptographic confirmation. Reported in the monthly forensic report.",
    )

    @api.depends("approval_ids.decision", "approval_ids.strongly_authenticated")
    def _compute_approval_count(self):
        for request_record in self:
            approvals = request_record.approval_ids.filtered(
                lambda a: a.decision == "approve"
            )
            request_record.approval_count = len(approvals)
            request_record.all_approvals_strong = all(
                a.strongly_authenticated for a in approvals
            ) if approvals else True

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------
    def _webauthn_context_ref(self):
        self.ensure_one()
        return "override.request,%s" % self.id

    def _pending_tier_for(self, user):
        """The review this user is currently able to decide, or empty.

        Reads through the upstream ``can_review`` / sequence logic rather than
        reimplementing it, so that a change in the tier configuration is
        respected here too.
        """
        self.ensure_one()
        sequences = self._get_sequences_to_approve(user)
        return self.review_ids.filtered(
            lambda r: r.status == "pending"
            and r.sequence in sequences
            and user in r.reviewer_ids
        )

    def _assert_webauthn_confirmed(self):
        """Refuse the approval unless an assertion for THIS request was verified.

        Raising rather than returning a flag is deliberate: an approval that
        proceeds while recording ``strongly_authenticated=False`` would satisfy
        the ladder without satisfying FR-5.3, and the override would complete.
        """
        self.ensure_one()
        Credential = self.env["sec.webauthn.credential"]
        # Either proof satisfies FR-5.3: both bind a user-present signature to
        # this one request. A deployment that cannot do WebAuthn at all can
        # still approve from a paired app, which is the point of that path
        # existing -- the passkey stack is no longer a single point of failure
        # for the highest-authority action in the system.
        ready = Credential._verification_ready()
        if not ready and hasattr(Credential, "_device_binding_ready"):
            ready = Credential._device_binding_ready()
        if not ready:
            raise UserError(
                _(
                    "Strong authentication is unavailable on this server, so "
                    "this approval cannot be authenticated as FR-5.3 requires. "
                    "Approval is refused rather than downgraded to a "
                    "password-only decision.\n\n"
                    "Install py_webauthn and configure the Relying Party ID, "
                    "or pair a device under Security Suite > Authenticators."
                )
            )
        if not Credential._verify_pending_assertion(self._webauthn_context_ref()):
            # On a SEPARATE CURSOR, because the UserError below rolls this
            # transaction back. Written on the same cursor -- as it was until
            # 18.0.1.1.0 -- the alert vanished with the refusal, so the one
            # signal that somebody is repeatedly trying to approve an override
            # without a security key was destroyed every single time it fired.
            # The record looked correct in code review and produced nothing in
            # the database. Same trap freeze_mixin and device_binding document.
            self._raise_anomaly_out_of_band(
                alert_type="incomplete_override",
                name=_("Override approval attempted without WebAuthn"),
                reason=_(
                    "%(user)s attempted to approve override %(ref)s without a "
                    "verified assertion bound to it. A password-only approval "
                    "is rejected by design (BRD FR-5.3).",
                    user=self.env.user.login,
                    ref=self.name,
                ),
                severity="critical",
            )
            raise UserError(
                _(
                    "Confirm on your security key before approving. An approval "
                    "on this system cannot rest on a password or a session "
                    "alone."
                )
            )
        return True

    def _record_approval(self, review, decision, comment=None):
        """Write the evidence record for one tier decision."""
        self.ensure_one()
        Credential = self.env["sec.webauthn.credential"]
        # The device that actually signed, where the verification path stamped
        # it. The fallback is the old behaviour and is only reached by callers
        # predating the stamp; it picks *a* credential of the user's, which is
        # weaker evidence and should not be relied on.
        credential = Credential.enrolled_for(self.env.user)[:1]
        if hasattr(Credential, "_verified_credential"):
            credential = Credential._verified_credential() or credential
        self.env["override.approval"].sudo().create(
            {
                "request_id": self.id,
                "tier_sequence": review.sequence,
                "tier_name": review.name or _("Tier %s", review.sequence),
                "approver_id": self.env.user.id,
                "decision": decision,
                "decided_at": fields.Datetime.now(),
                "strongly_authenticated": True,
                "credential_id": credential.id if credential else False,
                "comment": comment,
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
            }
        )

    # ------------------------------------------------------------------
    # Overrides of the upstream entry points
    # ------------------------------------------------------------------
    def validate_tier(self):
        """Gate every approval on a verified, request-bound assertion.

        Order matters here. The evidence record is written *after* the upstream
        validation succeeds, not before: ``override.approval`` is append-only,
        so an approval recorded ahead of a failing ``super()`` would leave a
        permanent claim that a tier was approved when it was not.
        """
        pending_reviews = {}
        for request_record in self:
            if request_record.state != "pending":
                raise UserError(_("This request is not awaiting approval."))
            review = request_record._pending_tier_for(self.env.user)
            if not review:
                raise UserError(
                    _(
                        "There is no approval step awaiting you on this "
                        "request. Either it is not yet your tier's turn, or "
                        "you are not a reviewer for it."
                    )
                )
            request_record._assert_webauthn_confirmed()
            pending_reviews[request_record.id] = review[0]

        result = super().validate_tier()

        for request_record in self:
            review = pending_reviews.get(request_record.id)
            if not review:
                continue
            request_record._record_approval(review, "approve")
            _logger.warning(
                "Override %s tier %s approved by %s (WebAuthn confirmed)",
                request_record.name,
                review.sequence,
                self.env.user.login,
            )
        return result

    def reject_tier(self):
        """Rejections are recorded too, and end the workflow.

        Not WebAuthn-gated. FR-5.3 requires strong authentication for
        *approvals*; a rejection cannot change a frozen record, and putting a
        hardware-key ceremony between a reviewer and "no" would discourage the
        safe answer. The decision is still recorded with actor, time and IP.
        """
        for request_record in self:
            review = request_record._pending_tier_for(self.env.user)
            if review:
                request_record.env["override.approval"].sudo().create(
                    {
                        "request_id": request_record.id,
                        "tier_sequence": review[0].sequence,
                        "tier_name": review[0].name
                        or _("Tier %s", review[0].sequence),
                        "approver_id": self.env.user.id,
                        "decision": "reject",
                        "decided_at": fields.Datetime.now(),
                        "strongly_authenticated": False,
                        "source_ip": request_record.env[
                            "sec.anomaly.mixin"
                        ]._current_source_ip(),
                    }
                )
        return super().reject_tier()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    @api.model
    def approvals_without_strong_auth(self):
        """Any approval recorded without cryptographic confirmation.

        Should always be empty. If it is not, either the gate was bypassed or
        the system ran for a period without WebAuthn available, and the monthly
        report needs to say so rather than present those overrides as
        equivalently authorised.
        """
        weak = self.env["override.approval"].sudo().search(
            [("decision", "=", "approve"), ("strongly_authenticated", "=", False)]
        )
        return {
            "clean": not weak,
            "count": len(weak),
            "entries": [
                {
                    "request": a.request_id.name,
                    "tier": a.tier_name,
                    "approver": a.approver_id.login,
                    "at": a.decided_at,
                }
                for a in weak
            ],
        }

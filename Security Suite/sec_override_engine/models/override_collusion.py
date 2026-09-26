# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Collusion and duplicate-identity prevention (P2-7, US-5.3, FR-5.1/FR-5.2).

FR-5.1: "No two of the three approvers may be the same person, and no override
may be committed on fewer than all three approvals."
FR-5.2: "The system must prevent collusion scenarios where two parties attempt
to authorize a change without independent CEO/Owner approval."
US-5.3: "The unlock action is technically incapable of executing until all three
tier approvals are present and validated in sequence."

Confirmed by reading the upstream source: ``base_tier_validation`` does none of
this. ``validate_tier`` filters reviews by the sequences the acting user may
approve, so somebody in two reviewer groups approves twice and the ladder
completes. This module is what makes the three-tier claim true.

**What is blocked versus what is merely flagged.** The distinction matters,
because a control that blocks on a weak signal gets switched off.

Blocked outright — these are provably the same identity:

- the requester approving any tier;
- one user account satisfying two tiers;
- two user accounts linked to the *same* ``res.partner``, which is what a
  deliberately paired account looks like in Odoo.

Flagged, not blocked — suspicious but with innocent explanations:

- two tiers approved from the same source IP. In a single-office company that
  is Tuesday. It is still worth a reviewer's attention when the whole point of
  the control is independence, so it raises an alert and appears in the monthly
  report.

The honest limit: no software check can tell whether two genuinely distinct
people, on distinct devices, decided together in a corridor. What this
architecture does is force that conversation to happen between three named
individuals who each cryptographically signed for it. That is a much better
evidentiary position than the phone-call model in the BRD's problem statement —
and it is what should be claimed, rather than "collusion is prevented".
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

REQUIRED_TIERS = 3


class OverrideApprovalIdentity(models.Model):
    _inherit = "override.approval"

    @api.constrains("approver_id", "decision")
    def _check_one_approval_per_person_per_request(self):
        """A person approves at most once per request, at the database level.

        Belt and braces with the check in ``validate_tier``: this one holds even
        if a future caller reaches the model directly.
        """
        for approval in self:
            if approval.decision != "approve":
                continue
            duplicates = self.sudo().search_count(
                [
                    ("request_id", "=", approval.request_id.id),
                    ("approver_id", "=", approval.approver_id.id),
                    ("decision", "=", "approve"),
                ]
            )
            if duplicates > 1:
                raise ValidationError(
                    _(
                        "%(user)s has already approved a tier on override "
                        "%(ref)s. One person cannot satisfy two tiers "
                        "(BRD FR-5.1).",
                        user=approval.approver_id.login,
                        ref=approval.request_id.name,
                    )
                )


class OverrideRequestIdentity(models.Model):
    _inherit = "override.request"

    collusion_signal = fields.Boolean(
        string="Independence Signal Raised",
        default=False,
        readonly=True,
        help="True when something about the approvals warranted a look — for "
        "example two tiers approved from the same address. Not a block, and "
        "not proof of anything.",
    )
    distinct_approver_count = fields.Integer(
        string="Distinct Approvers",
        compute="_compute_distinct_approvers",
        store=True,
        help="Number of different people who have approved. Must reach three "
        "before the override can execute.",
    )

    @api.depends("approval_ids.approver_id", "approval_ids.decision")
    def _compute_distinct_approvers(self):
        for request_record in self:
            approvers = request_record.approval_ids.filtered(
                lambda a: a.decision == "approve"
            ).mapped("approver_id")
            request_record.distinct_approver_count = len(set(approvers.ids))

    # ------------------------------------------------------------------
    # Blocking checks
    # ------------------------------------------------------------------
    def _assert_distinct_identity(self):
        """Refuse an approval that would breach three-way independence."""
        self.ensure_one()
        approver = self.env.user

        if approver == self.requester_id:
            self._raise_collusion_anomaly(
                _("Requester attempted to approve their own override"),
                _(
                    "%(user)s raised override %(ref)s and then attempted to "
                    "approve it. Blocked.",
                    user=approver.login,
                    ref=self.name,
                ),
            )
            raise UserError(
                _(
                    "You raised this request, so you cannot approve it. Three "
                    "independent approvals are required and yours would not be "
                    "one of them."
                )
            )

        prior = self.approval_ids.filtered(lambda a: a.decision == "approve")

        if approver in prior.mapped("approver_id"):
            self._raise_collusion_anomaly(
                _("Same user attempted to approve two tiers"),
                _(
                    "%(user)s has already approved a tier on override %(ref)s "
                    "and attempted a second. Blocked (BRD FR-5.1).",
                    user=approver.login,
                    ref=self.name,
                ),
            )
            raise UserError(
                _(
                    "You have already approved a tier on this request. One "
                    "person cannot stand in for two of the three approvals, "
                    "even if you hold both roles."
                )
            )

        # Two user accounts sharing one contact record is what a deliberately
        # paired account looks like in Odoo. Distinct logins, one person.
        if approver.partner_id and approver.partner_id in prior.mapped(
            "approver_id.partner_id"
        ):
            self._raise_collusion_anomaly(
                _("Paired accounts attempted to approve two tiers"),
                _(
                    "%(user)s shares a contact record with an approver who has "
                    "already signed override %(ref)s. Two logins for one person "
                    "do not make two approvers. Blocked (BRD FR-5.2).",
                    user=approver.login,
                    ref=self.name,
                ),
            )
            raise UserError(
                _(
                    "Your account is linked to the same contact as an approver "
                    "who has already signed this request. Two logins belonging "
                    "to one person cannot supply two of the three approvals."
                )
            )
        return True

    def _raise_collusion_anomaly(self, name, reason):
        self._raise_anomaly(
            alert_type="incomplete_override",
            name=name,
            reason=reason,
            severity="critical",
            record=self,
        )
        _logger.critical("%s: %s", name, reason)

    # ------------------------------------------------------------------
    # Non-blocking signals
    # ------------------------------------------------------------------
    def _flag_independence_signals(self):
        """Note things worth a reviewer's attention without blocking on them."""
        self.ensure_one()
        approvals = self.approval_ids.filtered(lambda a: a.decision == "approve")
        addresses = [a.source_ip for a in approvals if a.source_ip]
        if len(addresses) != len(set(addresses)):
            self.sudo().write({"collusion_signal": True})
            self._raise_anomaly(
                alert_type="incomplete_override",
                name=_("Two tiers approved from the same address"),
                reason=_(
                    "Override %(ref)s has approvals from different users at the "
                    "same source address. In a single-office company this is "
                    "routine; it is flagged because independence is the point "
                    "of the control, not because it is evidence of anything.",
                    ref=self.name,
                ),
                severity="medium",
                record=self,
            )

    # ------------------------------------------------------------------
    # The execution gate (US-5.3)
    # ------------------------------------------------------------------
    def _assert_executable(self):
        """Refuse to unlock unless three distinct, confirmed approvals exist.

        Called by P2-8 immediately before performing the edit. Deliberately
        re-derives everything from stored records rather than trusting
        ``state`` or the upstream ``validated`` flag: those are conclusions, and
        this is the last checkpoint before a frozen record changes.
        """
        self.ensure_one()
        problems = []

        approvals = self.approval_ids.filtered(lambda a: a.decision == "approve")
        approvers = approvals.mapped("approver_id")
        distinct = set(approvers.ids)

        if len(distinct) < REQUIRED_TIERS:
            problems.append(
                _(
                    "only %(count)s distinct approver(s); %(required)s are "
                    "required",
                    count=len(distinct),
                    required=REQUIRED_TIERS,
                )
            )
        if self.requester_id.id in distinct:
            problems.append(_("the requester is among the approvers"))
        if len(approvals) != len(distinct):
            problems.append(_("one approver signed more than one tier"))

        tiers_signed = set(approvals.mapped("tier_sequence"))
        configured = set(
            self.env["tier.definition"]
            .sudo()
            .search([("model", "=", self._name)])
            .mapped("sequence")
        )
        missing = configured - tiers_signed
        if missing:
            problems.append(
                _("no approval recorded for tier(s) %s",
                  ", ".join(str(s) for s in sorted(missing)))
            )
        weak = approvals.filtered(lambda a: not a.strongly_authenticated)
        if weak:
            problems.append(
                _("%s approval(s) were not WebAuthn-confirmed", len(weak))
            )
        if self.state != "approved":
            problems.append(_("the request is in state '%s'", self.state))
        if self.rejected:
            problems.append(_("a tier rejected the request"))

        if problems:
            self._raise_anomaly(
                alert_type="incomplete_override",
                name=_("Attempt to execute an incompletely approved override"),
                reason=_(
                    "%(user)s attempted to unlock %(target)s under override "
                    "%(ref)s, which is not fully approved: %(problems)s. "
                    "Blocked.",
                    user=self.env.user.login,
                    target=self.target_display,
                    ref=self.name,
                    problems="; ".join(problems),
                ),
                severity="critical",
                record=self,
            )
            _logger.critical(
                "Blocked unlock attempt on %s by %s: %s",
                self.name,
                self.env.user.login,
                "; ".join(problems),
            )
            raise UserError(
                _(
                    "This override cannot be executed:\n\n%(problems)s\n\n"
                    "The attempt has been recorded and reported.",
                    problems="\n".join("- %s" % p for p in problems),
                )
            )
        return True

    # ------------------------------------------------------------------
    # Wiring into the approval path
    # ------------------------------------------------------------------
    def validate_tier(self):
        for request_record in self:
            request_record._assert_distinct_identity()
        result = super().validate_tier()
        for request_record in self:
            request_record._flag_independence_signals()
        return result

    @api.model
    def independence_report(self):
        """Feeds the monthly forensic report (P3-4)."""
        executed = self.sudo().search([("state", "in", ("approved", "executed"))])
        flagged = executed.filtered("collusion_signal")
        insufficient = executed.filtered(
            lambda r: r.distinct_approver_count < REQUIRED_TIERS
        )
        return {
            "clean": not flagged and not insufficient,
            "same_address_approvals": [r.name for r in flagged],
            "insufficient_distinct_approvers": [r.name for r in insufficient],
        }

# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guard against role assignments outside the Plaza Model catalog.

Implements the third acceptance criterion of PRD US-2.1: "Assigning a role
outside the standard catalog requires a logged justification and is itself
flagged for the monthly audit."

Design: any security group that is not the backing group of an active Plaza
role, and is not on the technical allow-list, is a *non-standard grant*. Such a
grant is refused unless a matching ``plaza.grant.exception`` record exists in
the ``approved`` state. Every accepted non-standard grant is stamped with
``flagged_for_audit = True`` so it surfaces in the monthly forensic report.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Technical/base groups that every user legitimately holds and that are not
# part of the Plaza catalog. Kept deliberately short and explicit.
TECHNICAL_GROUP_XMLIDS = (
    "base.group_user",
    "base.group_portal",
    "base.group_public",
    "base.group_multi_company",
    "base.group_allow_export",
)


class GrantException(models.Model):
    """A logged, justified permission grant outside the Plaza catalog."""

    _name = "plaza.grant.exception"
    _description = "Non-Standard Permission Grant Exception"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
        help="The user receiving access outside the standard role catalog.",
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Security Group",
        required=True,
        ondelete="cascade",
        tracking=True,
        help="The non-standard group being granted.",
    )
    justification = fields.Text(
        string="Justification",
        required=True,
        tracking=True,
        help="Why standard Plaza roles are insufficient for this user. "
        "Mandatory; reviewed at the monthly forensic audit.",
    )
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        required=True,
        help="Who raised the exception request.",
    )
    approved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
        readonly=True,
        tracking=True,
        help="Who approved the exception.",
    )
    approved_on = fields.Datetime(
        string="Approved On",
        readonly=True,
        help="UTC timestamp of approval.",
    )
    expires_on = fields.Date(
        string="Expires On",
        tracking=True,
        help="Optional expiry. An expired exception no longer authorises the "
        "grant and is reported as a finding.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("revoked", "Revoked"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        help="Only an approved, unexpired exception permits the grant.",
    )
    flagged_for_audit = fields.Boolean(
        string="Flagged for Monthly Audit",
        default=True,
        readonly=True,
        help="Always true: every non-standard grant is reported, by design.",
    )

    def action_approve(self):
        """Approve the exception so the grant can be applied."""
        for exception in self:
            if exception.state != "draft":
                raise ValidationError(
                    _("Only a draft exception can be approved.")
                )
            exception.write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_on": fields.Datetime.now(),
                }
            )
            _logger.warning(
                "Non-standard permission grant approved: user=%s group=%s by=%s",
                exception.user_id.login,
                exception.group_id.full_name,
                self.env.user.login,
            )
        return True

    def action_revoke(self):
        """Revoke the exception. Does not itself remove the group."""
        self.write({"state": "revoked"})
        return True

    @api.model
    def active_exceptions_for(self, user, groups):
        """Return the subset of ``groups`` covered by a live exception for ``user``."""
        today = fields.Date.context_today(self)
        covered = self.sudo().search(
            [
                ("user_id", "=", user.id),
                ("group_id", "in", groups.ids),
                ("state", "=", "approved"),
                "|",
                ("expires_on", "=", False),
                ("expires_on", ">=", today),
            ]
        )
        return covered.mapped("group_id")


class ResUsers(models.Model):
    _inherit = "res.users"

    plaza_role_ids = fields.Many2many(
        comodel_name="role.plaza_model",
        string="Plaza Roles",
        compute="_compute_plaza_role_ids",
        help="Plaza Model roles derived from this user's security groups.",
    )
    has_nonstandard_access = fields.Boolean(
        string="Has Non-Standard Access",
        compute="_compute_plaza_role_ids",
        help="True when the user holds a group outside the Plaza catalog.",
    )

    @api.depends("groups_id")
    def _compute_plaza_role_ids(self):
        Role = self.env["role.plaza_model"].sudo()
        for user in self:
            roles = Role.search(
                [("active", "=", True), ("group_id", "in", user.groups_id.ids)]
            )
            user.plaza_role_ids = roles
            user.has_nonstandard_access = bool(
                user._plaza_nonstandard_groups(user.groups_id)
            )

    # ------------------------------------------------------------------
    # Non-standard grant detection
    # ------------------------------------------------------------------
    @api.model
    def _plaza_technical_groups(self):
        """Groups that are exempt from Plaza catalog coverage."""
        groups = self.env["res.groups"]
        for xmlid in TECHNICAL_GROUP_XMLIDS:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    def _plaza_nonstandard_groups(self, groups):
        """Return the subset of ``groups`` not covered by the Plaza catalog."""
        if not groups:
            return self.env["res.groups"]
        catalog_groups = (
            self.env["role.plaza_model"]
            .sudo()
            .search([("active", "=", True)])
            .mapped("group_id")
        )
        exempt = catalog_groups | self._plaza_technical_groups()
        # Implied groups: holding a catalog group implies its parents, which is
        # a consequence of a standard assignment, not a separate grant.
        exempt |= exempt.mapped("implied_ids")
        return groups - exempt

    def write(self, vals):
        """Refuse un-justified non-standard group grants.

        Bypassed when the environment carries ``plaza_bypass_grant_check``,
        which module installation and data loading set, since group assignment
        during install has no acting human to justify it.
        """
        if "groups_id" not in vals or self.env.context.get(
            "plaza_bypass_grant_check"
        ):
            return super().write(vals)

        before = {user.id: user.groups_id for user in self}
        result = super().write(vals)
        for user in self:
            added = user.groups_id - before.get(user.id, self.env["res.groups"])
            if not added:
                continue
            nonstandard = user._plaza_nonstandard_groups(added)
            if not nonstandard:
                continue
            justified = self.env["plaza.grant.exception"].active_exceptions_for(
                user, nonstandard
            )
            unjustified = nonstandard - justified
            if unjustified:
                raise ValidationError(
                    _(
                        "The following groups are outside the Plaza Model role "
                        "catalog and cannot be granted to %(login)s without an "
                        "approved, justified exception: %(groups)s\n\n"
                        "Raise a Non-Standard Permission Grant Exception first "
                        "(Security Suite > Plaza RBAC > Grant Exceptions).",
                        login=user.login,
                        groups=", ".join(unjustified.mapped("full_name")),
                    )
                )
            _logger.warning(
                "Non-standard groups granted under exception: user=%s groups=%s",
                user.login,
                ", ".join(justified.mapped("full_name")),
            )
        return result

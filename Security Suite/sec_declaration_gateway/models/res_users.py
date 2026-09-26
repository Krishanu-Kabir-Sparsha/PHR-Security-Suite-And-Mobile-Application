# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""User-side view of declaration status."""

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    declaration_signoff_ids = fields.One2many(
        comodel_name="declaration.signoff",
        inverse_name="user_id",
        string="Declaration Sign-offs",
        help="Every declaration version this user has accepted.",
    )
    must_accept_declaration = fields.Boolean(
        string="Declaration Outstanding",
        compute="_compute_must_accept_declaration",
        search="_search_must_accept_declaration",
        help="True when the currently published declaration has not been "
        "accepted by this user. Drives the blocking gate.",
    )
    current_declaration_accepted_on = fields.Datetime(
        string="Current Declaration Accepted On",
        compute="_compute_must_accept_declaration",
        help="When this user accepted the currently published version.",
    )

    @api.depends("declaration_signoff_ids.version_id")
    def _compute_must_accept_declaration(self):
        current = self.env["declaration.version"].sudo().get_current_version()
        for user in self:
            if not current:
                # No published declaration means nothing to accept. The gate
                # must not lock everyone out before Legal has supplied text.
                user.must_accept_declaration = False
                user.current_declaration_accepted_on = False
                continue
            signoff = user.sudo().declaration_signoff_ids.filtered(
                lambda s, c=current: s.version_id == c
            )[:1]
            user.must_accept_declaration = not signoff
            user.current_declaration_accepted_on = (
                signoff.accepted_at if signoff else False
            )

    def _search_must_accept_declaration(self, operator, value):
        current = self.env["declaration.version"].sudo().get_current_version()
        if not current:
            return [(1, "=", 1)] if not value else [(0, "=", 1)]
        accepted = (
            self.env["declaration.signoff"]
            .sudo()
            .search([("version_id", "=", current.id)])
            .mapped("user_id")
        )
        outstanding = operator in ("=", "==") and value or operator == "!=" and not value
        return [("id", "not in" if outstanding else "in", accepted.ids)]

    def _is_declaration_exempt(self):
        """Users the gate must not lock out.

        Only the base superuser (OdooBot / uid 1) is exempt, because locking it
        out would break cron jobs and module installation. Real administrators
        are NOT exempt: the BRD's threat model is an administrator acting on
        informal instruction, so exempting administrators would exempt exactly
        the population the declaration exists to bind.
        """
        self.ensure_one()
        return self.id == self.env.ref("base.user_root").id or self.share

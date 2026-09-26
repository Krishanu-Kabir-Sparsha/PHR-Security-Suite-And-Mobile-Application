# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""User-side view of authenticator enrolment."""

from odoo import _, api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    webauthn_credential_ids = fields.One2many(
        comodel_name="sec.webauthn.credential",
        inverse_name="user_id",
        string="Authenticators",
        help="Devices this user has enrolled for approval authentication.",
    )
    webauthn_credential_count = fields.Integer(
        string="Authenticators Enrolled",
        compute="_compute_webauthn_status",
    )
    webauthn_enrolment_sufficient = fields.Boolean(
        string="Enrolment Sufficient",
        compute="_compute_webauthn_status",
        help="False when this user holds an approval tier but has not enrolled "
        "enough authenticators. The CEO/Owner tier requires two (BRD FR-6.5).",
    )

    @api.depends("webauthn_credential_ids.active", "groups_id")
    def _compute_webauthn_status(self):
        Credential = self.env["sec.webauthn.credential"]
        for user in self:
            status = Credential.check_enrolment_sufficient(user)
            user.webauthn_credential_count = status["enrolled"]
            user.webauthn_enrolment_sufficient = status["sufficient"]

    def action_open_webauthn_enrolment(self):
        """Send the user to the enrolment page."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/webauthn/enroll",
            "target": "self",
        }

    @api.model
    def webauthn_enrolment_report(self):
        """Who still needs to enrol. Consumed by the monthly report (P3-4)."""
        Credential = self.env["sec.webauthn.credential"]
        findings = []
        users = self.sudo().search([("active", "=", True), ("share", "=", False)])
        for user in users:
            status = Credential.check_enrolment_sufficient(user)
            if status["required"] and not status["sufficient"]:
                findings.append(status)
        return {
            "ready": not findings,
            "outstanding": findings,
            "message": _("%s user(s) hold an approval tier without sufficient "
                         "authenticators.", len(findings)) if findings else "",
        }

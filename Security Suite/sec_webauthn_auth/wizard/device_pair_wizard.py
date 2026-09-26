# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Show a signed-in user a code that pairs the Perfect HR app on their phone.

Deliberately self-only. There is no field for choosing whose account to pair,
and the code is always minted for ``env.user``. An administrator able to
generate a pairing code for someone else would be able to bind a device they
control to that person's account and then approve as them -- with the approval
evidence naming the victim and a device that looks legitimate. Onboarding help
therefore means walking the person through generating their own code, not
generating it for them.

The code is displayed once. It is stored only as a digest, so re-opening this
wizard cannot show the previous code; it mints a fresh one and invalidates the
old, which is also the recovery path for a code typed wrongly too many times.
"""

from odoo import _, api, fields, models


class SecDevicePairWizard(models.TransientModel):
    _name = "sec.device.pair.wizard"
    _description = "Pair a Device"

    user_login = fields.Char(string="Your Username", readonly=True)
    code = fields.Char(string="Pairing Code", readonly=True)
    expires_at = fields.Datetime(string="Valid Until (UTC)", readonly=True)
    minutes = fields.Integer(string="Valid For (minutes)", readonly=True)
    existing_devices = fields.Text(string="Already Paired", readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Mint the code on open, so the menu entry is one click."""
        values = super().default_get(fields_list)
        user = self.env.user
        issued = self.env["sec.device.pairing"].issue_for(user)
        devices = self.env["sec.webauthn.credential"].bound_devices_for(user)
        values.update(
            {
                "user_login": user.login,
                "code": issued["formatted"],
                "expires_at": issued["expires_at"],
                "minutes": issued["minutes"],
                "existing_devices": "\n".join(
                    "- %s (paired %s)"
                    % (d.device_label, fields.Date.to_string(d.enrolled_at))
                    for d in devices
                )
                or _("No app is paired to your account yet."),
            }
        )
        return values

    def action_regenerate(self):
        """Mint a replacement, for a code that expired mid-typing."""
        self.ensure_one()
        issued = self.env["sec.device.pairing"].issue_for(self.env.user)
        self.write(
            {
                "code": issued["formatted"],
                "expires_at": issued["expires_at"],
                "minutes": issued["minutes"],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
